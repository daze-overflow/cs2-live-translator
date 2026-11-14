"""Small text-only accuracy comparison; reuse the running local model, pace around live work."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import time

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.catalog import MatchVocabulary
from backend.qwen import QwenTranslator

CASES = [
    ("Liquid vs TYLOO", "yeah just individually mismatched", "over some of these liquid players"),
    ("Liquid vs TYLOO", "still loses out to the mac tec", ""),
    ("Liquid vs TYLOO", "veals him and puts the ninth on the board yeah that is a lackluster attempt", ""),
    ("NAVI vs PARIVISION", "two smokes a Molly and a flash", ""),
    ("NAVI vs PARIVISION", "They still have two smokes, a molly and a flash left.", ""),
    ("NAVI vs PARIVISION", "Jame has no smoke, but FL1T has two flashes.", ""),
    ("NAVI vs PARIVISION", "b1t cannot trade Jame because the molly blocks him.", ""),
    ("NAVI vs PARIVISION", "Aleksib and iM push together while w0nderful holds the AWP.", ""),
    ("Falcons vs NAVI", "m0NESY is still alive, and NiKo is not saving.", ""),
    ("", "They need two more rounds, but this is not match point yet.", ""),
    ("", "see if the", "It is nice to have the crowd behind you."),
    ("NAVI vs PARIVISION", "Jame", ""),
]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline", help="Optional saved qwen.py implementation")
    parser.add_argument("--glossary", default="backend/glossary.json")
    args = parser.parse_args()
    cls = QwenTranslator
    if args.baseline:
        spec = importlib.util.spec_from_file_location("baseline_qwen", ROOT / args.baseline)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = module.QwenTranslator
    config = json.loads((ROOT / "local-config.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "backend/catalog.json").read_text(encoding="utf-8"))
    glossary = json.loads((ROOT / args.glossary).read_text(encoding="utf-8"))
    rows = []
    async with aiohttp.ClientSession(trust_env=False, headers={"Authorization": f"Bearer {config['token']}"}) as session:
        translator = cls(ROOT, config["token"])
        translator.session = session
        for title, source, context in CASES:
            await asyncio.sleep(2)  # Do not saturate the live model's single inference slot.
            vocabulary = MatchVocabulary(catalog, glossary, title)
            tick = time.perf_counter()
            translated = await translator.translate(source, vocabulary.glossary(), context)
            row = {"source": source, "context": context, **translated,
                   "elapsed_ms": round((time.perf_counter() - tick) * 1000, 1)}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    (ROOT / args.output).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
