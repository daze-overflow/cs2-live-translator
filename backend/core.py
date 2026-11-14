"""Terminology-preserving translation and bounded partial-hypothesis scheduling."""
import asyncio
from difflib import SequenceMatcher
import re
import time


def caption_window(text, limit=16):
    words = text.split()
    start = max(0, len(words) - limit)
    if start:
        for index in range(start, len(words) - 3):
            if words[index - 1].endswith((".", "!", "?", ";", ",")):
                start = index
                break
    return " ".join(words[start:]), " ".join(words[max(0, start - 16):start])


class Glossary:
    def __init__(self, names, terms, context_terms=None):
        self.names = dict(names)
        self.terms = dict(terms)
        self.context_terms = {key.casefold(): value for key, value in (context_terms or {}).items()}
        self._compile()

    def _compile(self):
        self.replacements = {key.casefold(): value for key, value in {**self.context_terms, **self.terms}.items()}
        for canonical, aliases in self.names.items():
            for alias in [canonical, *aliases]:
                self.replacements[alias.casefold()] = canonical
        variants = sorted(self.replacements, key=len, reverse=True)
        self.pattern = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, variants)) + r")(?!\w)", re.I)

    def add_names(self, names):
        self.names.update({name.strip(): [] for name in names if name.strip()})
        self._compile()

    @staticmethod
    def _ordinary(match, text):
        word = match.group().casefold()
        before, after = text[:match.start()], text[match.end():]
        if word == "bit" and re.search(r"\b(?:a|little|every)\s+$", before, re.I):
            return True
        following = {"wonderful": "shot|round|play|game|performance|job|day|time",
                     "simple": "plan|setup|mistake|question|way",
                     "zero": "chance|chances|kills|seconds|utility|health|damage|money",
                     "rain": "delay|delayed|weather", "device": "failure|issue|broken|malfunction"}
        return word in following and re.match(r"\s+(?:" + following[word] + r")(?!\w)", after, re.I) is not None

    def normalize_names(self, text):
        return self.pattern.sub(lambda match: self.replacements[match.group().casefold()]
                                if self.replacements[match.group().casefold()] in self.names
                                and not self._ordinary(match, text) else match.group(), text)

    def canonicalize(self, text):
        changes = []
        candidates = {alias.casefold(): name for name, aliases in self.names.items()
                      for alias in [name, *aliases] if " " not in alias}

        def replace(match):
            token = match.group()
            if self._ordinary(match, text):
                return token
            if token.casefold() in candidates:
                return candidates[token.casefold()]
            if len(token) < 6:
                return token
            scores = {}
            for alias, canonical in candidates.items():
                score = SequenceMatcher(None, token.casefold(), alias).ratio()
                scores[canonical] = max(scores.get(canonical, 0), score)
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            if ranked and ranked[0][1] >= .92 and (len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= .04):
                changes.append({"source": token, "canonical": ranked[0][0], "score": round(ranked[0][1], 3)})
                return ranked[0][0]
            return token

        return re.sub(r"\b[A-Za-z0-9]+\b", replace, text), changes

    def hints(self, text):
        return [(match.group(), self.replacements[match.group().casefold()])
                for match in self.pattern.finditer(text) if not self._ordinary(match, text)]

    def preserve(self, source, output):
        required = list(dict.fromkeys(target for term, target in self.hints(source)
                                     if term.casefold() not in self.context_terms))
        names = [target for target in required if target in self.names and target.casefold() not in output.casefold()]
        terms = [target for target in required if target not in self.names and target not in output]
        if names or terms:
            output += "（" + "、".join([*names, *terms]) + "）"
        return {"zh": output, "name_fallbacks": names, "term_fallbacks": terms}


class LatestTranslator:
    """One active job, a replaceable draft, and one protected final."""
    def __init__(self, translate, emit, interval=0.45, min_draft_words=0):
        self.translate, self.emit, self.interval = translate, emit, interval
        self.min_draft_words = min_draft_words
        self.pending = None
        self.final_pending = None
        self.version = 0
        self.wake = asyncio.Event()
        self.settled = asyncio.Event()
        self.settled.set()
        self.closed = False
        self.missed_finals = 0
        self.generation = 0
        self.translating = False

    def clear(self):
        self.pending = self.final_pending = None
        self.version += 1
        self.generation += 1
        self.wake.clear()
        if not self.translating:
            self.settled.set()

    def submit(self, job):
        if not job.get("final") and len(job["text"].split()) < self.min_draft_words:
            return
        if self.pending and self.pending[1].get("final") and self.pending[1]["utterance"] != job["utterance"]:
            if self.final_pending:
                self.missed_finals += 1
            self.final_pending = self.pending
        self.version += 1
        self.pending = (self.version, job)
        self.settled.clear()
        self.wake.set()

    async def run(self):
        previous = 0.0
        try:
            while not self.closed:
                await self.wake.wait()
                self.wake.clear()
                if self.closed:
                    break
                remaining = self.interval - (time.perf_counter() - previous)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                if self.pending is None and self.final_pending is None:
                    self.settled.set()
                    continue
                if self.final_pending:
                    version, job = self.final_pending
                    self.final_pending = None
                else:
                    version, job = self.pending
                    self.pending = None
                generation = self.generation
                self.translating = True
                result = await self.translate(job)
                self.translating = False
                # An older final still belongs in history when a new utterance has begun.
                older_final = job.get("final") and self.pending and job["utterance"] < self.pending[1]["utterance"]
                continuing = (self.pending and job["utterance"] == self.pending[1]["utterance"]
                              and self.pending[1].get("full_text", self.pending[1]["text"]).startswith(
                                  job.get("full_text", job["text"])))
                if generation == self.generation and (version == self.version or older_final or continuing):
                    outcome = self.emit(result)
                    if asyncio.iscoroutine(outcome):
                        await outcome
                    previous = time.perf_counter()
                if self.pending is None and self.final_pending is None:
                    self.settled.set()
                    self.wake.clear()
                else:
                    self.wake.set()
        finally:
            self.settled.set()

    async def idle(self):
        await self.settled.wait()

    def close(self):
        self.closed = True
        self.wake.set()
