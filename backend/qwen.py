"""Project-local Qwen translation through an owned, loopback-only llama.cpp process."""
import asyncio
import json
import re
import socket
import subprocess
import time

import aiohttp

SYSTEM = ("Faithfully translate English CS2 commentary into Simplified Chinese subtitles. "
          "Output only the translation. Preserve player IDs, team names, map names and weapon names verbatim. "
          "Preserve negation, numbers, and who is together or against whom. Translate all other English; "
          "Keep every listed utility and its quantity; equipment counts are not player counts. "
          "do not repeat the source. Translate incomplete phrases as they are, without guessing missing words. "
          "Previous speech is context only: translate ONLY the current English, never repeat or complete the previous sentence.")
EXAMPLES = [
    {"role": "user", "content": "英文：apEX and ZywOo push A together."},
    {"role": "assistant", "content": "apEX和ZywOo一起进攻A点。"},
    {"role": "user", "content": "英文：Falcons cannot retake B without a kit."},
    {"role": "assistant", "content": "Falcons没有拆包器，无法回防B点。"},
    {"role": "user", "content": "英文：two smokes a molly and a flash"},
    {"role": "assistant", "content": "两颗烟雾弹、一颗燃烧弹和一颗闪光弹。"},
]


def untranslated_english(output, glossary):
    names = list(glossary.names) if glossary else []
    names += ["A", "B", "CT", "T", "CS2", "HP"]
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
        hints = []
        corrections = []
        if glossary:
            text, corrections = glossary.canonicalize(text)
            hints = [f"{source}={target}" for source, target in glossary.hints(text)]
            text = glossary.normalize_names(text)
            if text in glossary.names:
                return {"zh": text, "en": text, "name_corrections": corrections,
                        "name_fallbacks": [], "term_fallbacks": [], "truncated": False, "timings": {},
                        "quality_retries": 0, "untranslated": False}
        if len(text.split()) < 4:
            context = ""
        content = (("前文（仅作参考，不翻译）：" + context + "\n") if context else "")
        content += ("参考词表（按整句语境选义）：" + "；".join(dict.fromkeys(hints)) + "\n" if hints else "") + "英文：" + text
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
            untranslated = untranslated_english(output, glossary)
            if not untranslated or attempt or not repair:
                break
            retries = 1
            payload["messages"] = [{"role": "system", "content":
                "你是CS2赛事解说字幕翻译。将用户的英文翻译成简体中文，只输出译文。保留人名，不要重复英文原文。"},
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
