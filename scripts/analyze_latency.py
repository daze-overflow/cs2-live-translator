"""Controlled-input phrase timing; explicitly excludes Chrome capture/display and real-caster accuracy."""
import json
import argparse
import statistics
from pathlib import Path
import wave

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--captions", default="evidence/qwen-synthetic-replay.json")
parser.add_argument("--output", default="evidence/synthetic-phrase-latency.json")
args = parser.parse_args()
caption_path = ROOT / args.captions
captions = json.loads(caption_path.read_text(encoding="utf-8"))
references = json.loads((ROOT / "evidence/synthetic/reference-timings.json").read_text(encoding="utf-8-sig"))
TARGETS = [(0, "Niko", "niko", "NiKo"), (0, "kill", "opening kill", "首杀"),
           (1, "Navi", "navi", "NAVI"), (1, "site", "bombsite", "A点"),
           (2, "bomb", "defuse the bomb", "拆包"), (3, "weapons", "save their weapons", "保枪"),
           (4, "Monesy", "monesy", "m0NESY"), (4, "three", "one versus three", "一打三"),
           (5, "retake", "retake", "回防"), (5, "Inferno", "inferno", "Inferno")]
offsets = []
seconds = 0
for reference in references:
    offsets.append(seconds)
    with wave.open(str(ROOT / "evidence/synthetic" / reference["file"]), "rb") as source:
        seconds += source.getnframes() / source.getframerate() + .7

# source_progress is a synthetic replay clock, independently mapped to TTS phoneme times below.
rows = []
# Replay writes the exact clock origin in a sidecar; never infer it from ASR's own timestamps.
clock = json.loads(caption_path.with_name(caption_path.stem + "-clock.json").read_text())
epoch = clock["epoch_ms"]
for utterance, source_word, source_phrase, target in TARGETS:
    word = next(word for word in references[utterance]["words"] if word["word"].casefold().rstrip(".") == source_word.casefold())
    source_end = epoch + offsets[utterance] * 1000 + word["end_ms"]
    matches = [caption for caption in captions if caption.get("asr_utterance", caption["utterance"]) == utterance
               and (source_phrase.casefold() in caption["full_text"].casefold()
                    or target.isascii() and target.casefold() in caption.get("en", "").casefold())
               and target.casefold() in caption["zh"].casefold()]
    rows.append({"utterance": utterance, "source_phrase": source_phrase, "target": target,
                 "status": "matched" if matches else "missing",
                 "normalized_entity": bool(matches and source_phrase.casefold() not in matches[0]["full_text"].casefold()),
                 "source_word_end_ms": word["end_ms"],
                 "delay_ms": round(matches[0]["client_received_ms"] - source_end, 1) if matches else None})
delays = sorted(row["delay_ms"] for row in rows if row["delay_ms"] is not None)
report = {"scope": "Synthetic English voice; 20ms real-time replay -> ASR -> Qwen -> loopback receive. Chrome display not included.",
          "timing_reference": "Independent Windows TTS word/phoneme event schedule; terminal silence excluded.",
          "accuracy_limit": "Entity matches include scoped alias normalization. This generated corpus has influenced glossary tuning and is not an independent caster-accuracy evaluation.",
          "targets": rows, "matched": len(delays), "total": len(rows),
          "median_ms": round(statistics.median(delays), 1) if delays else None,
          "max_ms": max(delays) if delays else None,
          "all_targets_within_1000ms": len(delays) == len(rows) and max(delays) <= 1000}
text = json.dumps(report, ensure_ascii=False, indent=2)
(ROOT / args.output).write_text(text, encoding="utf-8")
print(text)
