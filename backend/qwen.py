"""Project-local Qwen translation through an owned, loopback-only llama.cpp process."""
import asyncio
import json
import re
import socket
import subprocess
import time

import aiohttp

SYSTEM = (
    "你是CS2英文赛事解说的实时中文字幕译者。将当前英文准确、自然地译为简体中文，只输出译文。\n"
    "规则：\n"
    "1. 选手ID、战队名、地图名、武器名及赛事专称（如Major、BLAST、IEM、ESL、PGL）必须保留英文原词，不得意译或音译"
    "（例如Spirit不要译成精神，Falcons不要译成猎鹰，the Major保留Major不要译成大赛）。\n"
    "2. 严格保留否定词、数字与道具数量（道具数量不等于人数）。\n"
    "3. 除保留原词和Major等赛事专称外，所有普通英文动词、形容词和名词都必须译为中文，不要夹杂英文单词，也不要照抄原文。\n"
    "4. 遇到口语断句或不完整短语时，按已有内容直接翻译，不要猜词补全，更不要输出括号说明或注释。\n"
    "5. 若提供了“前文”，仅作理解语境之用，只翻译当前“英文”行，不要重复翻译前文。"
)
EXAMPLES = [
    {"role": "user", "content": "保留原词：apEX、ZywOo、Vitality\n英文：apEX and ZywOo push A together to win the major."},
    {"role": "assistant", "content": "apEX和ZywOo一起进攻A点，去赢下Major。"},
    {"role": "user", "content": "保留原词：Falcons\n术语参考：retake=回防；defuse kit=拆包器\n英文：Falcons cannot retake B without a kit."},
    {"role": "assistant", "content": "Falcons没有拆包器，无法回防B点。"},
    {"role": "user", "content": "术语参考：smoke=烟雾弹/封烟；molly=燃烧弹；flash=闪光弹\n英文：They still have two smokes, a molly and a flash left."},
    {"role": "assistant", "content": "他们还剩两颗烟雾弹、一颗燃烧弹和一颗闪光弹。"},
]
PRESERVED_TOKENS = ["A", "B", "CT", "T", "CS2", "HP", "Major", "BLAST", "IEM", "ESL", "PGL", "MVP", "HLTV", "BO1", "BO3", "BO5"]


def untranslated_english(output, glossary):
    names = list(glossary.names) if glossary else []
    names += PRESERVED_TOKENS
    pattern = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    residual = re.sub(r"(?<![A-Za-z0-9_])(?:" + pattern + r")(?![A-Za-z0-9_])", "", output, flags=re.I)
    words = len(re.findall(r"[A-Za-z]{2,}", residual))
    return words >= (3 if re.search(r"[\u3400-\u9fff]", output) else 2)


class QwenTranslator:
    def __init__(self, root, token):
        self.root, self.token = root, token
        self.process = self.session = self.log = None

    async def start(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 8766))
        key_file = self.root / "runtime/qwen-api-key.txt"
        key_file.write_text(self.token, encoding="utf-8")
        self.log = (self.root / "evidence/qwen.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen([
            str(self.root / "runtime/llama/llama-server.exe"),
            "--model", "models/translation/Qwen3-4B-Q4_K_M.gguf",
            "--host", "127.0.0.1", "--port", "8766", "--api-key-file", "runtime/qwen-api-key.txt",
            "--ctx-size", "2048", "--parallel", "1", "--gpu-layers", "all",
            "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
            "--reasoning", "off", "--threads", "4", "--no-webui"
        ], stdout=self.log, stderr=subprocess.STDOUT, cwd=self.root,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.session = aiohttp.ClientSession(trust_env=False, headers={"Authorization": f"Bearer {self.token}"},
                                             timeout=aiohttp.ClientTimeout(total=15))
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.log.flush()
                raise RuntimeError("Qwen process exited; inspect evidence/qwen.log")
            try:
                async with self.session.get("http://127.0.0.1:8766/health") as response:
                    if response.status == 200:
                        await self.translate("The match is starting.", None)
                        return
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(0.25)
        raise TimeoutError("Qwen model did not become ready within 90 seconds")

    async def translate(self, text, glossary, context="", repair=True):
        keep_names = []
        term_hints = []
        corrections = []
        if glossary:
            text, corrections = glossary.canonicalize(text)
            for source, target in glossary.hints(text):
                if target in glossary.names:
                    keep_names.append(target)
                else:
                    term_hints.append(f"{source}={target}")
            text = glossary.normalize_names(text)
            if text in glossary.names:
                return {"zh": text, "en": text, "name_corrections": corrections,
                        "name_fallbacks": [], "term_fallbacks": [], "truncated": False, "timings": {},
                        "quality_retries": 0, "untranslated": False}
        if len(text.split()) < 4:
            context = ""
        parts = []
        if context:
            parts.append("前文（仅作参考，不翻译）：" + context)
        if keep_names:
            parts.append("保留原词：" + "、".join(dict.fromkeys(keep_names)))
        if term_hints:
            parts.append("术语参考：" + "；".join(dict.fromkeys(term_hints)))
        parts.append("英文：" + text)
        content = "\n".join(parts)
        payload = {"messages": [{"role": "system", "content": SYSTEM}, *EXAMPLES, {"role": "user", "content": content}],
                   "temperature": 0, "max_tokens": 72, "stream": False,
                   "chat_template_kwargs": {"enable_thinking": False}, "cache_prompt": True}
        retries = 0
        for attempt in range(2 if repair else 1):
            async with self.session.post("http://127.0.0.1:8766/v1/chat/completions", json=payload) as response:
                if response.status != 200:
                    raise RuntimeError(f"Local translation failed ({response.status}): {(await response.text())[:300]}")
                data = await response.json()
            output = data["choices"][0]["message"]["content"].strip()
            output = re.sub(r"^(?:译文|中文(?:译文)?|英文)[：:]\s*", "", output)
            output = re.sub(r"（(?:这句|原文|可能(?:指|原意)|注[：:])[^）]*）\s*$", "", output).strip()
            untranslated = untranslated_english(output, glossary)
            if not untranslated or attempt or not repair:
                break
            retries = 1
            payload["messages"] = [{"role": "system", "content":
                "你是CS2赛事解说字幕翻译。将以下英文完整译为简体中文，只输出译文。保留选手ID、战队名、地图名和Major等赛事专称，不要夹杂普通英文单词，不要输出括号说明。"},
                {"role": "user", "content": text}]
        preserved = glossary.preserve(text, output) if glossary else {"zh": output, "name_fallbacks": [], "term_fallbacks": []}
        return {**preserved, "en": text, "name_corrections": corrections,
                "truncated": data["choices"][0].get("finish_reason") == "length",
                "quality_retries": retries, "untranslated": untranslated,
                "timings": data.get("timings", {})}

    async def close(self):
        if self.session:
            await self.session.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait)
        if self.log:
            self.log.close()
