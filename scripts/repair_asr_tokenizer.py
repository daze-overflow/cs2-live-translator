"""Add the matching original SentencePiece metadata; leave every model tensor unchanged."""
import base64
import hashlib
import io
import json
import mmap
from pathlib import Path
import shutil
import struct
import tarfile
import urllib.request

import sentencepiece

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b/resolve/ebe59e5a817142986528bbbee5dba8db7b38ed50"
SOURCE = ROOT / "models/asr/nemotron-speech-streaming-en-0.6b.q8_0.gguf"
OUTPUT = SOURCE.with_name("nemotron-en-with-tokenizer.gguf")


def string(value):
    raw = value.encode()
    return struct.pack("<Q", len(raw)) + raw


def entry(key, value):
    return string(key) + struct.pack("<I", 8) + string(value)


def metadata_end(data, count):
    sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}

    def skip(position, kind):
        if kind in sizes:
            return position + sizes[kind]
        if kind == 8:
            length = struct.unpack_from("<Q", data, position)[0]
            return position + 8 + length
        if kind == 9:
            subtype, length = struct.unpack_from("<IQ", data, position)
            position += 12
            for _ in range(length):
                position = skip(position, subtype)
            return position
        raise ValueError(f"Unknown GGUF metadata type {kind}")

    position = 24
    for _ in range(count):
        position = skip(position, 8)
        kind = struct.unpack_from("<I", data, position)[0]
        position = skip(position + 4, kind)
    return position


def main():
    if OUTPUT.exists():
        print("Tokenizer-enhanced ASR model already exists.")
        return
    request = urllib.request.Request(REPO + "/nemotron-speech-streaming-en-0.6b.nemo",
                                     headers={"Range": "bytes=0-1048575"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 206:
            raise ValueError("Expected a partial archive download")
        prefix = response.read(1048576)
    with tarfile.open(fileobj=io.BytesIO(prefix), mode="r:") as archive:
        for member in archive:
            if member.name.endswith("tokenizer.model"):
                proto = archive.extractfile(member).read()
                break
        else:
            raise ValueError("Tokenizer absent from archive prefix")
    with urllib.request.urlopen(REPO + "/tokenizer.json", timeout=30) as response:
        vocab = json.load(response)["model"]["vocab"]
    tokenizer = sentencepiece.SentencePieceProcessor(model_proto=proto)
    assert len(vocab) == tokenizer.get_piece_size()
    assert all(tokenizer.id_to_piece(index) == piece for piece, index in vocab.items())
    model_sha = hashlib.sha256(proto).hexdigest()
    added = entry("asr.tokenizer.spm_model", base64.b64encode(proto).decode())
    provenance = f"Original pinned NeMo tokenizer SHA256 {model_sha}"
    provenance += " " * (-(len(added) + len(entry("cs2.tokenizer_source", provenance))) % 32)
    added += entry("cs2.tokenizer_source", provenance)
    assert len(added) % 32 == 0  # Original tensor-info, padding and tensor-relative offsets stay valid.
    temporary = OUTPUT.with_suffix(".part")
    with SOURCE.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
        magic, version, tensors, metadata = struct.unpack_from("<4sIQQ", data)
        assert magic == b"GGUF" and version == 3
        end = metadata_end(data, metadata)
        with temporary.open("wb") as target:
            target.write(struct.pack("<4sIQQ", magic, version, tensors, metadata + 2))
            target.write(data[24:end])
            target.write(added)
            source.seek(end)
            shutil.copyfileobj(source, target, length=4 * 1024 * 1024)
    temporary.replace(OUTPUT)
    (ROOT / "evidence/tokenizer-repair.json").write_text(json.dumps({
        "source": REPO, "tokenizer_sha256": model_sha, "vocabulary_ids_verified": len(vocab),
        "tensor_bytes_unchanged": True, "metadata_bytes_added": len(added),
        "output": str(OUTPUT), "source_sha256": "d9a01898d2a611c8764e23a1c2f45e70bbd5a425dc4de93692ac951dd603812d"
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Added original tokenizer, verified all {len(vocab)} vocabulary IDs. Tensor data unchanged.")


if __name__ == "__main__":
    main()
