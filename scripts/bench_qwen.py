import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core import Glossary
from backend.qwen import QwenTranslator

ROOT = Path(__file__).resolve().parents[1]
TEXTS = ["niko gets the opening kill", "navi are going back to the a bombsite",
         "there is no time left to defuse the bomb", "falcons are trying to save their weapons",
         "monesy wins the one versus three", "they have to go for the retake on inferno",
         "what an incredible round from niko", "niko and monesy against natus vincere"]


async def main():
    config = json.loads((ROOT / "local-config.json").read_text())
    data = json.loads((ROOT / "backend/glossary.json").read_text(encoding="utf-8"))
    glossary = Glossary(data["names"], data["terms"])
    translator = QwenTranslator(ROOT, config["token"])
    try:
        await translator.start()
        rows = []
        for text in TEXTS:
            started = time.perf_counter()
            result = await translator.translate(text, glossary)
            rows.append({"en": text, **result, "ms": round((time.perf_counter() - started) * 1000, 1)})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        (ROOT / "evidence/qwen-translation.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await translator.close()


if __name__ == "__main__":
    asyncio.run(main())
