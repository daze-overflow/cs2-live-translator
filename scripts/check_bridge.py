"""Exercise the running local bridge's reset and backlog failure paths."""
import asyncio
import json
from pathlib import Path
import struct
import sys
import time

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from native.host import ready_service


async def main():
    config = json.loads((ROOT / "local-config.json").read_text())
    service = ready_service(config["port"])
    if not service:
        raise RuntimeError("Start the caption service before checking the bridge.")
    base_url = f"http://127.0.0.1:{service['port']}"
    url = f"{base_url}/audio"
    params = {"token": config["token"]}
    async with aiohttp.ClientSession(trust_env=False) as session:
        async with session.ws_connect(url, params=params) as ws:
            await ws.send_json({"type": "hello", "title": "PVISION vs. Natus Vincere - Quarterfinal", "names": ["Liquid", "G2"]})
            ready = await ws.receive_json()
            assert ready["type"] == "ready" and ready["teams"] == ["PARIVISION", "NAVI"], ready
            assert ready["team_source"] == "title", ready
            for _ in range(5):
                await asyncio.sleep(.02)
                await ws.send_bytes(struct.pack("<d", time.time() * 1000) + bytes(640))
            await ws.send_json({"type": "reset", "title": "Falcons vs NAVI"})
            clear = await ws.receive_json()
            assert clear == {"type": "clear", "epoch": 1, "teams": ["Falcons", "NAVI"], "team_source": "title"}, clear
            await ws.send_bytes(struct.pack("<d", time.time() * 1000) + bytes(640))
            await ws.send_json({"type": "finish"})
            assert (await ws.receive_json())["type"] == "finished"
        for _ in range(20):
            async with session.get(f"{base_url}/health") as response:
                if not (await response.json())["active"]:
                    break
            await asyncio.sleep(.05)
        async with session.ws_connect(url, params=params) as ws:
            await ws.send_json({"type": "hello", "title": "Liquid vs TYLOO", "names": []})
            assert (await ws.receive_json())["type"] == "ready"
            await ws.send_bytes(struct.pack("<d", time.time() * 1000 - 4000) + bytes(640))
            error = await ws.receive_json()
            assert error["type"] == "error" and "3 秒" in error["message"], error
    report = {"reset_epoch": 1, "initial_fixture": ready["teams"], "fixture_source": ready["team_source"],
              "fresh_stream_finishes": True, "stale_audio_fails_explicitly": True,
              "scope": "Real local bridge/model path, silence input; not browser or speech accuracy acceptance."}
    (ROOT / "evidence/bridge-v05-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
