"""Feed WAV audio at wall-clock speed; record captions without treating ASR progress as ground truth."""
import argparse
import asyncio
import json
from pathlib import Path
import struct
import sys
import time
import wave

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from native.host import ready_service


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evidence/replay-results.json")
    parser.add_argument("--title", default="")
    parser.add_argument("--names", default="", help="Comma-separated manual name overrides")
    parser.add_argument("wav", nargs="*")
    args = parser.parse_args()
    files = [Path(p) for p in args.wav] or sorted((ROOT / "evidence/synthetic").glob("*.wav"))
    if not files:
        raise ValueError("Provide mono PCM16 16kHz WAV files")
    audio = bytearray()
    for path in files:
        with wave.open(str(path), "rb") as source:
            assert (source.getnchannels(), source.getsampwidth(), source.getframerate()) == (1, 2, 16000)
            audio.extend(source.readframes(source.getnframes()))
        audio.extend(bytes(22400))  # 700ms gap for endpoint behavior.
    config = json.loads((ROOT / "local-config.json").read_text())
    service = ready_service(config["port"])
    if not service:
        raise RuntimeError("Start the caption service before replaying audio.")
    results = []
    async with aiohttp.ClientSession(trust_env=False) as session:
        async with session.ws_connect(f"http://127.0.0.1:{service['port']}/audio", params={"token": config["token"]}) as ws:
            await ws.send_json({"type": "hello", "title": args.title,
                                "names": [name.strip() for name in args.names.split(",") if name.strip()]})
            ready = await ws.receive_json()
            print(ready, flush=True)
            epoch = time.time() * 1000
            clock = time.perf_counter()
            clock_file = (ROOT / args.output).with_name((ROOT / args.output).stem + "-clock.json")
            clock_file.write_text(json.dumps({"epoch_ms": epoch, "audio_bytes": len(audio),
                                              "files": [str(path) for path in files]}), encoding="utf-8")

            async def send():
                for offset in range(0, len(audio), 640):
                    chunk = audio[offset:offset + 640]
                    end = (offset + len(chunk)) / 32000
                    await asyncio.sleep(max(0, clock + end - time.perf_counter()))
                    await ws.send_bytes(struct.pack("<d", epoch + end * 1000) + chunk)
                await ws.send_json({"type": "finish"})

            sender = asyncio.create_task(send())
            async for message in ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    break
                data = json.loads(message.data)
                if data["type"] == "caption":
                    data["client_received_ms"] = time.time() * 1000
                    results.append(data)
                    if data["final"]:
                        print(json.dumps({key: data[key] for key in ["text", "zh", "translation_ms", "progress_age_ms"]}, ensure_ascii=False), flush=True)
                elif data["type"] == "error":
                    raise RuntimeError(data["message"])
                elif data["type"] == "finished":
                    break
            await sender
    target = ROOT / args.output
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ages = sorted(row["progress_age_ms"] for row in results)
    print(json.dumps({"captions": len(results), "progress_age_ms": {
        "median": ages[len(ages) // 2] if ages else None,
        "p95": ages[min(len(ages) - 1, int(len(ages) * .95))] if ages else None,
        "max": max(ages) if ages else None}, "output": str(target),
        "scope": "ASR progress freshness, NOT independently aligned speech-to-Chinese latency"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
