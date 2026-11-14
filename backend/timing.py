"""Keep capture gaps separate from network/inference backlog."""


class AudioClock:
    def __init__(self):
        self.started_ms = self.previous_end = None
        self.ingest_age_ms = 0

    def observe(self, captured_end, pcm_bytes, received_ms):
        duration_ms = pcm_bytes / 32
        self.ingest_age_ms = received_ms - captured_end
        if self.ingest_age_ms > 3000:
            raise RuntimeError("音频处理已积压超过 3 秒，已停止字幕；请确认插电和电脑负载后重新开始。")
        gap = self.previous_end is not None and abs(captured_end - self.previous_end - duration_ms) > 100
        if self.started_ms is None or gap:
            self.started_ms = captured_end - duration_ms
        self.previous_end = captured_end
        return gap
