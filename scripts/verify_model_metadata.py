import hashlib
import json
import mmap
import struct

from repair_asr_tokenizer import ROOT, SOURCE, OUTPUT, metadata_end

hashes = []
for path in (SOURCE, OUTPUT):
    with path.open("rb") as stream:
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            count = struct.unpack_from("<Q", data, 16)[0]
            end = metadata_end(data, count)
        stream.seek(end)
        hashes.append(hashlib.file_digest(stream, "sha256").hexdigest())
assert hashes[0] == hashes[1], "Tensor information/padding/data changed"
path = ROOT / "evidence/tokenizer-repair.json"
evidence = json.loads(path.read_text(encoding="utf-8"))
evidence.update(unchanged_tail_sha256=hashes[0], tensor_region_hash_verified=True)
path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
print("MODEL_TENSOR_REGION_IDENTICAL", True)
