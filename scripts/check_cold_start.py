"""Exercise the installed native launcher with no backend, including owned-tree cleanup."""
import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from native.host import read_message, write_message


def listening(port):
    with socket.socket() as probe:
        probe.settimeout(.3)
        return probe.connect_ex(('127.0.0.1', port)) == 0


async def wait_stopped():
    for _ in range(40):
        if not listening(8765) and not listening(8766):
            return
        await asyncio.sleep(.2)
    raise AssertionError('Owned model ports remain after host exit')


async def launch(origin, direct=False):
    command = [str(ROOT / '.venv/Scripts/python.exe'), '-X', 'utf8', str(ROOT / 'native/host.py'), origin] if direct else [str(ROOT / 'native/host.cmd'), origin]
    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    write_message(process.stdin, {'type': 'start'})
    started = time.perf_counter()
    try:
        while True:
            message = await asyncio.wait_for(asyncio.to_thread(read_message, process.stdout), 45)
            if message is None:
                raise RuntimeError(process.stderr.read().decode('utf-8', errors='replace'))
            if message['type'] == 'error':
                raise RuntimeError(message['message'])
            if message['type'] == 'ready':
                return process, message, round((time.perf_counter() - started) * 1000, 1)
            print(json.dumps(message, ensure_ascii=False), flush=True)
    except BaseException:
        process.stdin.close()
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        raise


async def main():
    if listening(8765) or listening(8766):
        raise RuntimeError('Cold-start check requires no existing backend; do not stop an unowned service.')
    manifest = json.loads((ROOT / 'native/com.cs2.live_translator.json').read_text(encoding='utf-8'))
    origin = manifest['allowed_origins'][0]
    config = json.loads((ROOT / 'local-config.json').read_text(encoding='utf-8'))
    process, ready, cold_ms = await launch(origin)
    try:
        assert ready['started'] is True and ready['version'] == '0.6.0', ready
        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.get('http://127.0.0.1:8765/health') as response:
                health = await response.json()
                assert health['app_id'] == 'cs2-live-translator' and health['ready'], health
            async with session.ws_connect('http://127.0.0.1:8765/audio', params={'token': config['token']}) as ws:
                await ws.send_json({'type': 'hello', 'title': 'MOUZ vs PARIVISION', 'names': []})
                fixture = await ws.receive_json()
                assert fixture['type'] == 'ready' and set(fixture['teams']) == {'MOUZ', 'PARIVISION'}, fixture
                await ws.send_json({'type': 'finish'})
                assert (await ws.receive_json())['type'] == 'finished'
        second, reused, warm_ms = await launch(origin)
        assert reused['started'] is False, reused
        second.stdin.close()
        await asyncio.to_thread(second.wait, 5)
        assert listening(8765) and listening(8766), 'Reused host must leave the existing service alive'
    finally:
        process.stdin.close()
        await asyncio.to_thread(process.wait, 10)
    await wait_stopped()
    print(json.dumps({'cold_ms': cold_ms, 'warm_ms': warm_ms, 'normal_exit_cleanup': True}), flush=True)
    hard, ready, second_cold_ms = await launch(origin, direct=True)
    subprocess.run(['taskkill', '/PID', str(ready['host_pid']), '/F'], check=True, capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    await asyncio.to_thread(hard.wait, 10)
    hard.stdin.close()
    await wait_stopped()
    report = {'cold_start_ms': cold_ms, 'warm_reuse_ms': warm_ms, 'second_cold_start_ms': second_cold_ms,
              'bridge_fixture': fixture['teams'], 'normal_exit_cleanup': True, 'hard_exit_cleanup': True,
              'scope': 'Actual installed host.cmd, local CUDA models, framed protocol and loopback bridge; Chrome connection/capture still requires extension reload.'}
    (ROOT / 'evidence/cold-start-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
