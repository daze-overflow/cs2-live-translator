"""ctypes binding to the pinned NVIDIA ASR C ABI (include/nemo_speech/asr.h)."""
import ctypes as C
import os
from pathlib import Path

import numpy as np


class Backend(C.Structure):
    _fields_ = [("size", C.c_size_t), ("gpu", C.c_int32)]


class Model(C.Structure):
    _fields_ = [("size", C.c_size_t), ("path", C.c_char_p), ("name", C.c_char_p)]


class Streaming(C.Structure):
    _fields_ = [("size", C.c_size_t), ("chunk", C.c_float), ("left", C.c_float),
                ("right", C.c_float), ("rnnt_right_context", C.c_int32)]


class Endpoint(C.Structure):
    _fields_ = [("size", C.c_size_t), ("enable", C.c_bool), ("vad", C.c_bool),
                ("silence_ms", C.c_int32)]


class Config(C.Structure):
    # ABI structs explicitly permit a shorter size: omitted tail fields retain defaults.
    _fields_ = [("size", C.c_size_t), ("backend", C.POINTER(Backend)),
                ("model", C.POINTER(Model)), ("streaming", C.POINTER(Streaming)),
                ("decoder", C.c_void_p), ("vad", C.c_void_p), ("endpoint", C.POINTER(Endpoint))]


class SpeechContext(C.Structure):
    _fields_ = [("size", C.c_size_t), ("phrases", C.POINTER(C.c_char_p)),
                ("count", C.c_size_t), ("boost", C.c_float)]


class Options(C.Structure):
    _fields_ = [("size", C.c_size_t), ("request_id", C.c_char_p), ("language", C.c_char_p),
                ("interim", C.c_bool), ("word_times", C.c_bool), ("punctuation", C.c_bool),
                ("verbatim", C.c_bool), ("profanity", C.c_bool), ("silence_ms", C.c_int32),
                ("contexts", C.POINTER(SpeechContext)), ("context_count", C.c_size_t),
                ("max_alternatives", C.c_int32), ("diarization", C.c_bool),
                ("max_speakers", C.c_int32)]


class NativeASR:
    def __init__(self, root, right_context=1):
        binary = root / "runtime/nemo/nemo-speech-0.3.0-windows-x86_64-cuda/bin"
        self.dll_directory = os.add_dll_directory(str(binary))
        self.lib = C.CDLL(str(binary / "nemo_speech_asr_c.dll"))
        self._signatures()
        backend = Backend(C.sizeof(Backend), 0)
        model = Model(C.sizeof(Model), str(root / "models/asr/nemotron-en-with-tokenizer.gguf").encode(), None)
        streaming = Streaming(C.sizeof(Streaming), 0.16, 1.92, 1.92, right_context)
        endpoint = Endpoint(C.sizeof(Endpoint), True, False, 550)
        config = Config(C.sizeof(Config), C.pointer(backend), C.pointer(model),
                        C.pointer(streaming), None, None, C.pointer(endpoint))
        self.handle = C.c_void_p()
        self.check(self.lib.nemo_speech_asr_create(C.byref(config), C.byref(self.handle)))

    def _signatures(self):
        handle, pointer = C.c_void_p, C.POINTER(C.c_void_p)
        functions = {
            "create": ([C.POINTER(Config), pointer], C.c_int),
            "destroy": ([handle], None),
            "streaming_recognize": ([handle, C.POINTER(Options), pointer], C.c_int),
            "stream_push_f32": ([handle, C.POINTER(C.c_float), C.c_size_t, C.c_int32], C.c_int),
            "stream_next": ([handle, pointer], C.c_int),
            "stream_finish": ([handle], C.c_int),
            "stream_force_endpoint": ([handle], C.c_int),
            "stream_close": ([handle], None),
            "result_is_final": ([handle], C.c_bool),
            "result_audio_processed": ([handle], C.c_float),
            "result_transcript": ([handle, C.c_size_t], C.c_char_p),
            "result_word_count": ([handle, C.c_size_t], C.c_size_t),
            "result_word_text": ([handle, C.c_size_t, C.c_size_t], C.c_char_p),
            "result_word_start_time": ([handle, C.c_size_t, C.c_size_t], C.c_int32),
            "result_word_end_time": ([handle, C.c_size_t, C.c_size_t], C.c_int32),
            "result_destroy": ([handle], None),
            "last_error": ([], C.c_char_p),
        }
        for name, (arguments, result) in functions.items():
            function = getattr(self.lib, "nemo_speech_asr_" + name)
            function.argtypes, function.restype = arguments, result

    def check(self, status):
        if status:
            raise RuntimeError(self.lib.nemo_speech_asr_last_error().decode("utf-8", "replace"))

    def stream(self, phrases=()):
        return RecognitionStream(self, phrases)

    def close(self):
        if self.handle:
            self.lib.nemo_speech_asr_destroy(self.handle)
            self.handle = None


class RecognitionStream:
    def __init__(self, recognizer, phrases):
        self.recognizer = recognizer
        self.lib = recognizer.lib
        self.phrases = (C.c_char_p * len(phrases))(*(p.encode() for p in phrases))
        self.context = SpeechContext(C.sizeof(SpeechContext), self.phrases, len(phrases), 2.5)
        self.options = Options(C.sizeof(Options), None, b"en-US", True, True, False, True,
                               False, 550, C.pointer(self.context), 1 if phrases else 0, 1, False, 0)
        self.handle = C.c_void_p()
        recognizer.check(self.lib.nemo_speech_asr_streaming_recognize(
            recognizer.handle, C.byref(self.options), C.byref(self.handle)))

    def push(self, pcm):
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        self.recognizer.check(self.lib.nemo_speech_asr_stream_push_f32(
            self.handle, samples.ctypes.data_as(C.POINTER(C.c_float)), len(samples), 16000))
        return self._drain()

    def finish(self):
        self.recognizer.check(self.lib.nemo_speech_asr_stream_finish(self.handle))
        return self._drain()

    def _drain(self):
        events = []
        while True:
            result = C.c_void_p()
            self.recognizer.check(self.lib.nemo_speech_asr_stream_next(self.handle, C.byref(result)))
            if not result:
                return events
            try:
                words = []
                for i in range(self.lib.nemo_speech_asr_result_word_count(result, 0)):
                    words.append({"text": self.lib.nemo_speech_asr_result_word_text(result, 0, i).decode(),
                                  "start_ms": self.lib.nemo_speech_asr_result_word_start_time(result, 0, i),
                                  "end_ms": self.lib.nemo_speech_asr_result_word_end_time(result, 0, i)})
                events.append({"text": self.lib.nemo_speech_asr_result_transcript(result, 0).decode(),
                               "final": self.lib.nemo_speech_asr_result_is_final(result),
                               "audio_processed": self.lib.nemo_speech_asr_result_audio_processed(result),
                               "words": words})
            finally:
                self.lib.nemo_speech_asr_result_destroy(result)

    def close(self):
        if self.handle:
            self.lib.nemo_speech_asr_stream_close(self.handle)
            self.handle = None
