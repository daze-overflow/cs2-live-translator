"""Download pinned vendor ASR artifacts into this project."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v0.3.0"
ASSET = "nemo-speech-0.3.0-windows-x86_64-cuda.zip"
RELEASE = f"https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/{VERSION}"


def read_url(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, path, sha=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (sha is None or digest(path) == sha):
        return path
    partial = path.with_suffix(path.suffix + ".part")
    print(f"Downloading {path.name}", flush=True)
    subprocess.run(["curl.exe", "-fLsS", "--retry", "2", "--connect-timeout", "20",
                    "--max-time", "1200", "-C", "-", "-o", str(partial), url], check=True)
    if sha and digest(partial) != sha:
        raise ValueError(f"Checksum mismatch: {partial}")
    partial.replace(path)
    print(f"Verified/downloaded {path.name} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)
    return path


def extract(path, target):
    target.mkdir(parents=True, exist_ok=True)
    base = target.resolve()
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            if not (base / member.filename).resolve().is_relative_to(base):
                raise ValueError("Archive contains a path outside its destination")
        archive.extractall(target)


def main():
    raw_index = read_url(f"https://raw.githubusercontent.com/NVIDIA/NeMo-Speech.cpp/{VERSION}/models/index.json")
    index = json.loads(raw_index)
    model = next(m for m in index["models"] if "nemotron-en" in m.get("aliases", []))
    artifact = model["artifacts"][0]
    asr_url = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{artifact['filename']}"
    runtime_sha = read_url(f"{RELEASE}/{ASSET}.sha256").decode().split()[0]
    downloads = ROOT / "runtime" / "downloads"
    asr_path = ROOT / "models" / "asr" / artifact["filename"]
    runtime_path = downloads / ASSET
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(download, f"{RELEASE}/{ASSET}", runtime_path, runtime_sha),
                pool.submit(download, asr_url, asr_path, artifact["sha256"])]
        for job in jobs:
            job.result()
    extract(runtime_path, ROOT / "runtime" / "nemo")
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    (evidence / "models.json").write_text(json.dumps({
        "runtime": {"version": VERSION, "sha256": runtime_sha, "url": f"{RELEASE}/{ASSET}"},
        "asr": {"repo": model["repo"], "revision": model["revision"], **artifact}
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Models and runtime are ready.", flush=True)


if __name__ == "__main__":
    main()
