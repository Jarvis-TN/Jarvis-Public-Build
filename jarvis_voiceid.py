"""Jarvis voice-print speaker ID - recognise WHO is talking, fully offline.

Uses a real pretrained speaker-embedding network (WeSpeaker CAM++ trained on
VoxCeleb, 512-dim x-vectors) running locally through sherpa-onnx/onnxruntime -
no internet needed after the one-time model download to voices/speaker/.
Each utterance becomes an L2-normalized embedding; speakers are matched by
cosine similarity against enrolled profiles (running-mean refined).

This is personalization-grade recognition (greet the owner by name, tell
household members apart), not a hardened biometric lock - a good recording
of someone's voice could fool it, as with all consumer voice ID.
"""

import os
import sqlite3
import threading

import numpy as np

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
DB_PATH = os.path.join(MEMORY_DIR, "voiceprints.db")
SPEAKER_MODEL_DIR = os.path.join(APP_DIR, "voices", "speaker")
SPEAKER_MODEL = os.path.join(SPEAKER_MODEL_DIR, "wespeaker_en_voxceleb_CAM++.onnx")
SPEAKER_MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                     "speaker-recongition-models/wespeaker_en_voxceleb_CAM%2B%2B.onnx")

SR = 16000
MIN_SECONDS = 1.0      # need at least this much audio for a stable print

_extractor = None      # None=untried, False=unavailable, else loaded model
_extractor_lock = threading.Lock()


def _download_model():
    import urllib.request
    os.makedirs(SPEAKER_MODEL_DIR, exist_ok=True)
    tmp = SPEAKER_MODEL + ".part"
    urllib.request.urlretrieve(SPEAKER_MODEL_URL, tmp)
    os.replace(tmp, SPEAKER_MODEL)


def get_extractor():
    """Lazily load the speaker-embedding model (downloading it on first ever
    use - the only step that needs internet). Returns None if unavailable."""
    global _extractor
    if _extractor is None:
        with _extractor_lock:
            if _extractor is None:
                try:
                    import sherpa_onnx
                    if not os.path.exists(SPEAKER_MODEL):
                        _download_model()
                    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                        model=SPEAKER_MODEL, num_threads=2)
                    _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
                except Exception:
                    _extractor = False
    return _extractor or None


def embed_voice(samples, sr=SR):
    """Return an L2-normalized 512-dim speaker embedding for `samples` (mono
    float32 in [-1,1] at 16 kHz), or None if too short or model unavailable."""
    try:
        x = np.asarray(samples, dtype=np.float32).flatten()
        if x.size < int(MIN_SECONDS * sr):
            return None
        ex = get_extractor()
        if ex is None:
            return None
        stream = ex.create_stream()
        stream.accept_waveform(sample_rate=sr, waveform=x)
        stream.input_finished()
        vec = np.asarray(ex.compute(stream), dtype=np.float32)
        norm = float(np.linalg.norm(vec)) or 1.0
        return vec / norm
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Speaker profile store
# --------------------------------------------------------------------------- #
def _blob(vec):
    return vec.astype(np.float32).tobytes() if vec is not None else None


def _vec(blob):
    return np.frombuffer(blob, dtype=np.float32) if blob else None


class VoiceProfiles:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS speakers (
                    name TEXT PRIMARY KEY,
                    samples INTEGER DEFAULT 0,
                    embedding BLOB,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            self._conn.commit()

    def enroll(self, name, vec):
        """Add a voice sample for `name`. Repeated enrollments refine the profile
        via a running mean (then re-normalized), so more samples = more robust."""
        name = (name or "").strip()
        if not name or vec is None:
            return None
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            row = self._conn.execute("SELECT samples, embedding FROM speakers WHERE name=?",
                                     (name,)).fetchone()
            if row and row["embedding"] is not None:
                prev = _vec(row["embedding"])
                n = int(row["samples"])
                if prev is not None and prev.shape == vec.shape:
                    merged = (prev * n + vec) / (n + 1)
                    merged = merged / (float(np.linalg.norm(merged)) or 1.0)
                else:
                    merged, n = vec, 0
                self._conn.execute(
                    "UPDATE speakers SET samples=?, embedding=?, updated_at=? WHERE name=?",
                    (n + 1, _blob(merged), now, name))
            else:
                self._conn.execute(
                    "INSERT OR REPLACE INTO speakers(name, samples, embedding, created_at, updated_at) "
                    "VALUES (?,?,?,?,?)", (name, 1, _blob(vec), now, now))
            self._conn.commit()
        return self.profile(name)

    def identify(self, vec, threshold=0.55, margin=0.05):
        """Best-matching enrolled speaker for `vec`.
        Returns (name|None, best_score, ranked[list of (name, score)]). A match
        requires best_score >= threshold AND beating the runner-up by `margin`
        (so two similar profiles don't flip-flop). Typical CAM++ cosine scores:
        same speaker 0.55-0.85, different speakers 0.0-0.25."""
        if vec is None:
            return None, 0.0, []
        rows = self._conn.execute("SELECT name, embedding FROM speakers").fetchall()
        scored = []
        for r in rows:
            ev = _vec(r["embedding"])
            if ev is not None and ev.shape == vec.shape:
                scored.append((r["name"], float(np.dot(vec, ev))))
        scored.sort(key=lambda x: -x[1])
        if not scored:
            return None, 0.0, []
        best_name, best = scored[0]
        runner = scored[1][1] if len(scored) > 1 else -1.0
        if best >= threshold and (best - runner) >= margin:
            return best_name, best, scored
        return None, best, scored

    def profile(self, name):
        r = self._conn.execute(
            "SELECT name, samples, created_at, updated_at FROM speakers WHERE name=?",
            (name,)).fetchone()
        return dict(r) if r else None

    def list_speakers(self):
        return [dict(r) for r in self._conn.execute(
            "SELECT name, samples, created_at, updated_at FROM speakers ORDER BY name").fetchall()]

    def remove(self, name):
        with self._lock:
            cur = self._conn.execute("DELETE FROM speakers WHERE name=?", (name.strip(),))
            self._conn.commit()
            return cur.rowcount > 0

    def wipe(self):
        with self._lock:
            self._conn.execute("DELETE FROM speakers")
            self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
