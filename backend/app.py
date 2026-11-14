import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import secrets
import socket
import struct
import time

from aiohttp import WSMsgType, web

from .asr import NativeASR
from .catalog import MatchVocabulary
from .core import CaptionPacer, LatestTranslator
from .qwen import QwenTranslator
from .stream import EndpointStream
from .timing import AudioClock

ROOT = Path(__file__).resolve().parents[1]


def local_config():
    path = ROOT / "local-config.json"
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
    else:
        config = {"token": secrets.token_urlsafe(32), "port": 8765}
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    (ROOT / "extension").mkdir(exist_ok=True)
    (ROOT / "extension/local-config.json").write_text(json.dumps(config), encoding="utf-8")
    return config


async def serve_socket(request):
    state = request.app["state"]
    if not secrets.compare_digest(request.query.get("token", ""), state["config"]["token"]):
        raise web.HTTPUnauthorized()
    origin = request.headers.get("Origin", "")
    if origin and not origin.startswith("chrome-extension://"):
        raise web.HTTPForbidden(text="Only the Chrome extension may connect")
    if state["active"]:
        raise web.HTTPConflict(text="Another capture is active")
    state["active"] = True
    ws = web.WebSocketResponse(max_msg_size=65536, heartbeat=15)
    stream = scheduler = worker = None
    loop = asyncio.get_running_loop()
    try:
        await ws.prepare(request)
        hello = await asyncio.wait_for(ws.receive_json(), 5)
        if hello.get("type") != "hello":
            raise ValueError("The first message must be hello")
        data = state["glossary_data"]
        vocabulary = MatchVocabulary(state["catalog"], data, str(hello.get("title", ""))[:500],
                                     hello.get("names", [])[:50])
        stream = await loop.run_in_executor(state["asr_pool"], EndpointStream, state["asr"], vocabulary.hints())
        clock = AudioClock()
        epoch = 0
        session_started = time.monotonic()
        packet_received_ms = asr_ms = 0
        pacer = CaptionPacer()
        asr_utterance = 0
        sequence = 0
        previous_text, previous_at = "", -100

        async def translate(job):
            tick = time.perf_counter()
            glossary = job.pop("glossary")
            translated = await state["translator"].translate(job["text"], glossary, job["context"], repair=job["final"])
            return {**job, **translated, "translation_ms": round((time.perf_counter() - tick) * 1000, 1)}

        async def emit(result):
            if result["epoch"] != epoch:
                return
            result.update(type="caption", server_sent_ms=time.time() * 1000,
                          missed_finals=scheduler.missed_finals, asr_hint_count=len(stream.hints),
                          vocabulary_refreshes=stream.refreshes)
            result["progress_age_ms"] = round(result["server_sent_ms"] - result["source_progress_ms"], 1)
            result["late"] = result["progress_age_ms"] > 1500
            if not ws.closed:
                await ws.send_json(result)
            with (ROOT / "evidence/captions.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(result, ensure_ascii=False) + "\n")

        def process(events):
            nonlocal sequence, asr_utterance, previous_text, previous_at
            for event in events:
                text = event["text"].strip()
                if text and event["final"]:
                    vocabulary.observe(text, time.monotonic() - session_started)
                for cue in pacer.push(text, event["final"]):
                    sequence += 1
                    prefix = cue.pop("prefix")
                    scheduler.submit({**cue, "seq": sequence, "full_text": text, "epoch": epoch,
                                      "asr_utterance": asr_utterance, "words": event["words"],
                                      "teams": list(vocabulary.active),
                                      "team_source": vocabulary.source,
                                      "context": prefix or (previous_text if event["audio_processed"] - previous_at < 8 else ""),
                                      "glossary": vocabulary.glossary(),
                                      "source_progress_ms": clock.started_ms + event["audio_processed"] * 1000,
                                      "packet_received_ms": packet_received_ms,
                                      "ingest_age_ms": round(clock.ingest_age_ms, 1), "asr_ms": round(asr_ms, 1),
                                      "asr_received_ms": time.time() * 1000})
                if event["final"]:
                    asr_utterance += 1
                    if text:
                        previous_text = " ".join(text.split()[-24:])
                        previous_at = event["audio_processed"]

        scheduler = LatestTranslator(translate, emit)
        worker = asyncio.create_task(scheduler.run())

        async def reset(title=None, reset_clock=True):
            nonlocal stream, clock, epoch, asr_utterance, previous_text, previous_at, vocabulary
            epoch += 1
            scheduler.clear()
            pacer.reset()
            asr_utterance += 1
            previous_text, previous_at = "", -100
            if title is not None:
                vocabulary = MatchVocabulary(state["catalog"], data, title[:500], hello.get("names", [])[:50])
            await loop.run_in_executor(state["asr_pool"], stream.close)
            stream = await loop.run_in_executor(state["asr_pool"], EndpointStream, state["asr"], vocabulary.hints())
            if reset_clock:
                clock = AudioClock()
            await ws.send_json({"type": "clear", "epoch": epoch, "teams": list(vocabulary.active),
                                "team_source": vocabulary.source})

        await ws.send_json({"type": "ready", "model": "Nemotron EN + Qwen3-4B (local CUDA)",
                            "teams": list(vocabulary.active), "team_source": vocabulary.source})
        async for message in ws:
            if message.type == WSMsgType.BINARY:
                packet = message.data
                if len(packet) < 10 or len(packet) % 2:
                    raise ValueError("Expected timestamp plus PCM16 samples")
                captured_end = struct.unpack_from("<d", packet)[0]
                if not math.isfinite(captured_end):
                    raise ValueError("Invalid capture timestamp")
                pcm = packet[8:]
                packet_received_ms = time.time() * 1000
                if clock.observe(captured_end, len(pcm), packet_received_ms):
                    await reset(reset_clock=False)
                tick = time.perf_counter()
                events = await loop.run_in_executor(state["asr_pool"], stream.push, pcm)
                asr_ms = (time.perf_counter() - tick) * 1000
                process(events)
                process(await loop.run_in_executor(state["asr_pool"], stream.refresh, vocabulary.hints()))
                if worker.done():
                    await worker  # Surface inference failures instead of silently losing subtitles.
            elif message.type == WSMsgType.TEXT:
                command = json.loads(message.data)
                if command.get("type") == "reset":
                    await reset(str(command.get("title", hello.get("title", ""))))
                if command.get("type") == "displayed":
                    record = {key: command.get(key) for key in ("seq", "displayed_ms", "source_progress_ms", "server_sent_ms")}
                    record["type"] = "displayed"
                    with (ROOT / "evidence/displayed.jsonl").open("a", encoding="utf-8") as log:
                        log.write(json.dumps(record) + "\n")
                if command.get("type") == "finish":
                    if clock.started_ms is not None:
                        process(await loop.run_in_executor(state["asr_pool"], stream.finish))
                        await scheduler.idle()
                    await ws.send_json({"type": "finished"})
                    break
            elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    except Exception as error:
        if not ws.closed and ws.prepared:
            await ws.send_json({"type": "error", "message": str(error)})
        print(f"Capture error: {error}", flush=True)
    finally:
        if scheduler:
            scheduler.close()
        if worker:
            await asyncio.gather(worker, return_exceptions=True)
        if stream:
            await loop.run_in_executor(state["asr_pool"], stream.close)
        await ws.close()
        state["active"] = False
    return ws


def bind_caption_socket(preferred):
    for port in dict.fromkeys((preferred, 18765)):
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            listener.close()
        else:
            return listener
    raise RuntimeError(f"字幕端口 {preferred} 和 18765 均无法绑定。")


async def run_backend(config, listener):
    print("Loading local models and warming up...", flush=True)
    loop = asyncio.get_running_loop()
    asr_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")
    asr = await loop.run_in_executor(asr_pool, NativeASR, ROOT)
    translator = QwenTranslator(ROOT, config["token"])
    runner = None
    try:
        def warm_up():
            warm = asr.stream()
            try:
                for _ in range(150):
                    warm.push(bytes(640))
                warm.finish()
            finally:
                warm.close()
        await loop.run_in_executor(asr_pool, warm_up)
        await translator.start()
        state = {"config": config, "asr": asr, "translator": translator, "active": False,
                 "asr_pool": asr_pool,
                 "glossary_data": json.loads((ROOT / "backend/glossary.json").read_text(encoding="utf-8")),
                 "catalog": json.loads((ROOT / "backend/catalog.json").read_text(encoding="utf-8"))}
        app = web.Application()
        app["state"] = state

        async def health(request):
            return web.json_response({"app_id": "cs2-live-translator", "ready": True,
                                      "active": state["active"], "model": "Qwen3-4B",
                                      "version": "0.6.2", "roster_as_of": state["catalog"]["as_of"]})

        app.router.add_get("/health", health)
        app.router.add_get("/audio", serve_socket)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        print(f"READY http://127.0.0.1:{listener.getsockname()[1]} (fully local)", flush=True)
        await asyncio.Event().wait()
    finally:
        if runner:
            await runner.cleanup()
        await translator.close()
        await loop.run_in_executor(asr_pool, asr.close)
        asr_pool.shutdown(wait=True)


async def main():
    config = local_config()
    with bind_caption_socket(config["port"]) as listener:
        await run_backend(config, listener)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
