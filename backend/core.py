"""Terminology-preserving translation and bounded partial-hypothesis scheduling."""
import asyncio
from collections import deque
from difflib import SequenceMatcher
import re
import time


class CaptionPacer:
    """Accept a stable prefix once, then commit a clause or the ASR endpoint."""
    joiners = {"but", "whereas", "because", "then"}
    unfinished = {"a", "an", "the", "to", "of", "for", "in", "on", "with", "at", "and",
                  "or", "but", "if", "that", "is", "are", "was", "were", "could", "would",
                  "should", "can", "will", "their", "his", "her", "our", "behind", "like"}

    def __init__(self):
        self.cue = 0
        self.drafted = False
        self.reset()

    def reset(self):
        if self.drafted:
            self.cue += 1
        self.committed = []
        self.previous = []
        self.drafted = False

    @classmethod
    def boundary(cls, words, keys, stable, final):
        # Leave a few words for the next cue when splitting without punctuation.
        for end in range(4, min(stable, 16) + 1):
            if (final or end < len(words)) and words[end - 1].endswith((".", "!", "?", ";")):
                return end
            if end >= 7 and stable - end >= 2 and len(words) - end >= 4 and (
                words[end - 1].endswith(",") or keys[end] in cls.joiners
            ):
                return end
        if stable >= 16 and len(words) >= 19:
            return next((end for end in range(16, 10, -1)
                         if keys[end - 1] not in cls.unfinished), 16)
        return len(words) if final else 0

    def push(self, text, final):
        words = text.split()
        keys = [word.casefold().rstrip(".,!?;:") for word in words]
        start = len(self.committed)
        if keys[:start] != self.committed:
            # ASR can insert or remove words before a committed cue. Align to its
            # last recognized word so a late correction doesn't shift the next cue.
            blocks = SequenceMatcher(None, self.committed, keys, autojunk=False).get_matching_blocks()
            last = blocks[-2] if len(blocks) > 1 else None
            if last:
                start = min(len(keys), last.b + start - last.a)

        stable = len(keys) if final else next(
            (i for i, (old, new) in enumerate(zip(self.previous, keys)) if old != new),
            min(len(self.previous), len(keys)))
        self.previous = keys
        cues = []

        def emit(end, committed):
            cues.append({"utterance": self.cue, "text": " ".join(words[start:end]),
                         "prefix": " ".join(words[max(0, start - 24):start]), "final": committed})

        while start < stable:
            length = self.boundary(words[start:], keys[start:], stable - start, final)
            if not length:
                break
            end = start + length
            emit(end, True)
            self.committed = keys[:end]
            self.cue += 1
            self.drafted = False
            start = end

        if final:
            self.reset()
        elif not self.drafted:
            # The last word may still be a partial token even when repeated.
            end = min(stable, len(keys) - 1, start + 12)
            while end > start and keys[end - 1] in self.unfinished:
                end -= 1
            if end - start >= 5:
                emit(end, False)
                self.drafted = True
        return cues


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
    """One active job, a replaceable draft, and a few protected finals."""
    def __init__(self, translate, emit, interval=0.45, min_draft_words=0):
        self.translate, self.emit, self.interval = translate, emit, interval
        self.min_draft_words = min_draft_words
        self.pending = None
        self.finals = deque(maxlen=3)
        self.version = 0
        self.wake = asyncio.Event()
        self.settled = asyncio.Event()
        self.settled.set()
        self.closed = False
        self.missed_finals = 0
        self.generation = 0
        self.translating = False

    def clear(self):
        self.pending = None
        self.finals.clear()
        self.version += 1
        self.generation += 1
        self.wake.clear()
        if not self.translating:
            self.settled.set()

    def submit(self, job):
        if not job.get("final") and len(job["text"].split()) < self.min_draft_words:
            return
        self.version += 1
        if job.get("final"):
            self.missed_finals += len(self.finals) == self.finals.maxlen
            self.finals.append((self.version, job))
            self.pending = None
        else:
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
                if self.pending is None and not self.finals:
                    self.settled.set()
                    continue
                if self.finals:
                    version, job = self.finals.popleft()
                else:
                    version, job = self.pending
                    self.pending = None
                generation = self.generation
                self.translating = True
                result = await self.translate(job)
                self.translating = False
                continuing = (self.pending and job["utterance"] == self.pending[1]["utterance"]
                              and self.pending[1].get("full_text", self.pending[1]["text"]).startswith(
                                  job.get("full_text", job["text"])))
                if generation == self.generation and (version == self.version or job.get("final") or continuing):
                    outcome = self.emit(result)
                    if asyncio.iscoroutine(outcome):
                        await outcome
                    previous = time.perf_counter()
                if self.pending is None and not self.finals:
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
