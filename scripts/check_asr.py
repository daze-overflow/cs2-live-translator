from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.asr import NativeASR

root = Path(__file__).resolve().parents[1]
started = time.perf_counter()
asr = NativeASR(root)
print(f"ASR loaded in {time.perf_counter() - started:.2f}s", flush=True)
stream = asr.stream(["NiKo", "m0NESY", "NAVI", "Falcons"])
started = time.perf_counter()
durations = []
for i in range(150):
    tick = time.perf_counter()
    events = stream.push(bytes(640))
    durations.append(round((time.perf_counter() - tick) * 1000, 2))
    if events:
        print(events, flush=True)
print(f"Warm-up 3s of silence: {time.perf_counter() - started:.3f}s", flush=True)
print("Decode call times >1ms:", [v for v in durations if v > 1], flush=True)
print(stream.finish(), flush=True)
stream.close()
asr.close()
