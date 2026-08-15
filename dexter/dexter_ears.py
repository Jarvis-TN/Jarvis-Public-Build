"""Dexter's ears: microphone capture + local Whisper transcription.

Push-to-talk from the UI: start() begins recording, stop_and_transcribe()
ends it and returns text. Recording also auto-stops after a stretch of
silence or a hard cap, so a stuck button can't record forever.

Uses faster-whisper (CPU, int8) like Jarvis — fully local, no audio leaves
the machine. First use downloads the model to the user cache.
"""

from __future__ import annotations

import threading


class DexterEars:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sample_rate = 16000
        self._model = None
        self._stream = None
        self._chunks = []
        self._lock = threading.Lock()
        self._recording = False
        self._silent_blocks = 0
        self._max_blocks = int(cfg.get("mic_max_seconds", 15) * 10)
        self._silence_limit = int(cfg.get("mic_silence_seconds", 1.0) * 10)
        self._threshold = float(cfg.get("mic_silence_threshold", 0.012))

    @property
    def recording(self):
        return self._recording

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.cfg.get("stt_model", "base.en"),
                                       device="cpu", compute_type="int8")
        return self._model

    def warm_up(self):
        """Load the Whisper model ahead of the first question (optional)."""
        try:
            self._ensure_model()
        except Exception:
            pass

    def start(self):
        import numpy as np
        import sounddevice as sd

        with self._lock:
            if self._recording:
                return
            self._chunks = []
            self._silent_blocks = 0
            self._recording = True

        def callback(indata, frames, t, status):
            if not self._recording:
                return
            block = np.copy(indata[:, 0])
            self._chunks.append(block)
            rms = float(np.sqrt(np.mean(block ** 2)))
            self._silent_blocks = 0 if rms > self._threshold else self._silent_blocks + 1
            warmed_up = len(self._chunks) > 8  # don't cut off in the first second
            if (len(self._chunks) >= self._max_blocks
                    or (warmed_up and self._silent_blocks >= self._silence_limit)):
                self._recording = False  # UI polls .recording and finishes up

        self._stream = sd.InputStream(samplerate=self.sample_rate, channels=1,
                                      dtype="float32",
                                      blocksize=self.sample_rate // 10,
                                      callback=callback)
        self._stream.start()

    def stop_and_transcribe(self):
        """Stop recording and return the transcript ('' if nothing heard)."""
        import numpy as np

        with self._lock:
            self._recording = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            chunks, self._chunks = self._chunks, []

        if not chunks:
            return ""
        audio = np.concatenate(chunks)
        if float(np.sqrt(np.mean(audio ** 2))) < self._threshold / 2:
            return ""  # just room noise
        model = self._ensure_model()
        segments, _info = model.transcribe(audio, language="en", beam_size=1,
                                           vad_filter=True,
                                           condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()


if __name__ == "__main__":
    import time
    ears = DexterEars({})
    print("Recording 5 seconds... speak now.")
    ears.start()
    time.sleep(5)
    print("Heard:", repr(ears.stop_and_transcribe()))
