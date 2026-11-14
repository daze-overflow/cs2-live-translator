import concurrent.futures
import json

from prepare_models import download, extract, ROOT

TAG = "b11960"
MODEL_REVISION = "bc640142c66e1fdd12af0bd68f40445458f3869b"
MODEL_SHA = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
ASSETS = {
    "llama-b11960-bin-win-cuda-13.4-x64.zip": "31c75ea62b80f0816c855ea783ef68757bc2d48028edaa57d904e4982bddea4a",
    "cudart-llama-bin-win-cuda-13.4-x64.zip": "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668",
}

if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(download, f"https://github.com/ggml-org/llama.cpp/releases/download/{TAG}/{name}",
                            ROOT / "runtime/downloads" / name, sha) for name, sha in ASSETS.items()]
        model_job = pool.submit(download,
            f"https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/{MODEL_REVISION}/Qwen3-4B-Q4_K_M.gguf",
            ROOT / "models/translation/Qwen3-4B-Q4_K_M.gguf", MODEL_SHA)
        files = [job.result() for job in jobs]
        model_job.result()
    for file in files:
        extract(file, ROOT / "runtime/llama")
    (ROOT / "evidence/qwen-runtime.json").write_text(json.dumps({"tag": TAG, "assets_sha256": ASSETS,
        "model_repo": "Qwen/Qwen3-4B-GGUF", "revision": MODEL_REVISION,
        "model_sha256": MODEL_SHA}, indent=2), encoding="utf-8")
    print("Qwen inference runtime ready.", flush=True)
