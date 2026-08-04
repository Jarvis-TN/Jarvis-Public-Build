"""Jarvis face-print authentication - recognise the owner by face, fully offline.

A "Windows Hello"-style face gate. Uses OpenCV's bundled YuNet detector (finds
+ 5-point-aligns the face) and SFace recognizer (128-d embedding) - both run
locally through onnxruntime, no internet after the one-time model download.
Faces are matched by cosine similarity against enrolled profiles.

Personalization/convenience-grade, NOT a hardened biometric lock - a photo on a
phone can fool single-frame face ID (no liveness detection). Pair with the voice
print (jarvis_voiceid) for a stronger two-factor "it's really you" signal.
"""

import os
import sqlite3
import threading

import numpy as np

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
DB_PATH = os.path.join(MEMORY_DIR, "faceprints.db")
MODEL_DIR = os.path.join(APP_DIR, "voices", "face")
DETECTOR = os.path.join(MODEL_DIR, "face_detection_yunet_2023mar.onnx")
RECOGNIZER = os.path.join(MODEL_DIR, "face_recognition_sface_2021dec.onnx")
DETECTOR_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
                "face_detection_yunet/face_detection_yunet_2023mar.onnx")
RECOGNIZER_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
                  "face_recognition_sface/face_recognition_sface_2021dec.onnx")

# SFace cosine similarity: ~>=0.363 == same person (OpenCV's recommended default).
DEFAULT_THRESHOLD = 0.363

_models = None        # None=untried, False=unavailable, else (detector, recognizer)
_models_lock = threading.Lock()


def _download(url, path):
    import urllib.request
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, path)


def _get_models():
    """Lazily load YuNet + SFace, downloading them once on first use. Returns
    (detector, recognizer) or None if unavailable."""
    global _models
    if _models is None:
        with _models_lock:
            if _models is None:
                try:
                    import cv2
                    if not os.path.exists(DETECTOR):
                        _download(DETECTOR_URL, DETECTOR)
                    if not os.path.exists(RECOGNIZER):
                        _download(RECOGNIZER_URL, RECOGNIZER)
                    det = cv2.FaceDetectorYN.create(DETECTOR, "", (320, 320),
                                                    score_threshold=0.7)
                    rec = cv2.FaceRecognizerSF.create(RECOGNIZER, "")
                    _models = (det, rec)
                except Exception:
                    _models = False
    return _models or None


def embed_face(frame_bgr):
    """Detect the largest face in a BGR frame and return its L2-normalized
    embedding, or None if no face is found / models unavailable."""
    try:
        models = _get_models()
        if models is None or frame_bgr is None:
            return None
        det, rec = models
        h, w = frame_bgr.shape[:2]
        det.setInputSize((w, h))
        n, faces = det.detect(frame_bgr)
        if faces is None or len(faces) == 0:
            return None
        # largest face by bounding-box area (the person closest to the camera)
        faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        aligned = rec.alignCrop(frame_bgr, faces[0])
        feat = rec.feature(aligned).flatten().astype(np.float32)
        norm = float(np.linalg.norm(feat)) or 1.0
        return feat / norm
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Face profile store (mirrors jarvis_voiceid.VoiceProfiles)
# --------------------------------------------------------------------------- #
def _blob(vec):
    return vec.astype(np.float32).tobytes() if vec is not None else None


def _vec(blob):
    return np.frombuffer(blob, dtype=np.float32) if blob else None


class FaceProfiles:
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
                CREATE TABLE IF NOT EXISTS faces (
                    name TEXT PRIMARY KEY,
                    samples INTEGER DEFAULT 0,
                    embedding BLOB,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            self._conn.commit()

    def enroll(self, name, vec):
        """Add/refine a face print for `name` via a running mean (re-normalized),
        so more samples (different angles/lighting) = more robust."""
        name = (name or "").strip()
        if not name or vec is None:
            return None
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            row = self._conn.execute("SELECT samples, embedding FROM faces WHERE name=?",
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
                    "UPDATE faces SET samples=?, embedding=?, updated_at=? WHERE name=?",
                    (n + 1, _blob(merged), now, name))
            else:
                self._conn.execute(
                    "INSERT OR REPLACE INTO faces(name, samples, embedding, created_at, updated_at) "
                    "VALUES (?,?,?,?,?)", (name, 1, _blob(vec), now, now))
            self._conn.commit()
        return self.profile(name)

    def identify(self, vec, threshold=DEFAULT_THRESHOLD, margin=0.04):
        """Best-matching enrolled face for `vec`.
        Returns (name|None, best_score, ranked). A match needs best>=threshold
        AND beating the runner-up by `margin`."""
        if vec is None:
            return None, 0.0, []
        rows = self._conn.execute("SELECT name, embedding FROM faces").fetchall()
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
            "SELECT name, samples, created_at, updated_at FROM faces WHERE name=?",
            (name,)).fetchone()
        return dict(r) if r else None

    def list_faces(self):
        return [dict(r) for r in self._conn.execute(
            "SELECT name, samples, created_at, updated_at FROM faces ORDER BY name").fetchall()]

    def remove(self, name):
        with self._lock:
            cur = self._conn.execute("DELETE FROM faces WHERE name=?", (name.strip(),))
            self._conn.commit()
            return cur.rowcount > 0

    def wipe(self):
        with self._lock:
            self._conn.execute("DELETE FROM faces")
            self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
