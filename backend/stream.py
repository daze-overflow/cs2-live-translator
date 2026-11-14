"""Refresh immutable ASR options at endpoints and replay only undecoded lookahead."""


class EndpointStream:
    def __init__(self, recognizer, hints):
        self.recognizer, self.hints = recognizer, hints
        self.stream = recognizer.stream(hints)
        self.samples = self.base = 0
        self.tail = bytearray()
        self.boundary = None
        self.refreshes = 0

    def _offset(self, events):
        self.boundary = None
        for event in events:
            event["audio_processed"] += self.base / 16000
            for word in event["words"]:
                word["start_ms"] += self.base / 16
                word["end_ms"] += self.base / 16
        if events and events[-1]["final"]:
            self.boundary = round(events[-1]["audio_processed"] * 16000)
        return events

    def push(self, pcm):
        self.samples += len(pcm) // 2
        self.tail.extend(pcm)
        self.tail = self.tail[-64000:]
        return self._offset(self.stream.push(pcm))

    def refresh(self, hints):
        if hints == self.hints or self.boundary is None:
            return []
        tail_start = self.samples - len(self.tail) // 2
        if not tail_start <= self.boundary <= self.samples:
            return []
        replay = bytes(self.tail[(self.boundary - tail_start) * 2:])
        self.stream.close()
        self.stream = self.recognizer.stream(hints)
        self.hints, self.base = hints, self.boundary
        self.refreshes += 1
        self.boundary = None
        return self._offset(self.stream.push(replay)) if replay else []

    def finish(self):
        return self._offset(self.stream.finish())

    def close(self):
        self.stream.close()
