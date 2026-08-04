"""Jarvis real-time gesture sidecar - runs in the isolated .venv-vision.

Owns the webcam, runs MediaPipe's on-device Gesture Recognizer at ~camera rate,
and prints ONE JSON event per line to stdout for the engine to act on:

    {"type":"ready"}
    {"type":"gesture","action":"screenshot","gesture":"Victory","conf":0.94}
    {"type":"error","msg":"..."}          # then a non-zero exit

Gestures (palm-swipe mapping):
    open-palm swipe left / right  -> move_left / move_right
    victory (peace sign)          -> screenshot
    closed fist (held)            -> close_window

Nothing here imports the Jarvis engine (different venv); it shares only the pure
debounce/swipe logic in jarvis_vision.py. Never touches the network except a
one-time model download. Stdout is the wire; keep stray prints off it.
"""

import os
import sys
import json
import time
import base64
import argparse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jarvis_vision as jv


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def log(msg):
    # diagnostics go to stderr so they never pollute the stdout event stream
    sys.stderr.write(f"[vision] {msg}\n")
    sys.stderr.flush()


def ensure_model(path):
    if os.path.isfile(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log(f"downloading gesture model -> {path}")
    tmp = path + ".part"
    urllib.request.urlretrieve(jv.GESTURE_MODEL_URL, tmp)
    os.replace(tmp, path)


def open_camera(cv2, index):
    """Open the requested index (CAP_DSHOW first), else probe 0..2."""
    order = [index] + [i for i in range(3) if i != index]
    for i in order:
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap, i
        cap.release()
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            return cap, i
        cap.release()
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera-index", type=int, default=0)
    ap.add_argument("--model", default=jv.GESTURE_MODEL)
    ap.add_argument("--fps", type=float, default=18.0)
    ap.add_argument("--hold-frames", type=int, default=8)      # static-gesture hold (fist/victory)
    ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--swipe-dx", type=float, default=0.20)
    ap.add_argument("--frame-interval", type=float, default=1.5)  # secs between shared frames (0=off)
    ap.add_argument("--swipe-cooldown", type=float, default=1.2)
    ap.add_argument("--swipe-invert", action="store_true")
    args = ap.parse_args()

    try:
        import cv2
        import numpy as np
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
    except Exception as e:
        emit({"type": "error", "msg": f"vision deps unavailable: {e}"})
        return 2

    try:
        ensure_model(args.model)
    except Exception as e:
        emit({"type": "error", "msg": f"couldn't get the gesture model: {e}"})
        return 2

    try:
        opts = mp_vision.GestureRecognizerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=args.model),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=1)
        recognizer = mp_vision.GestureRecognizer.create_from_options(opts)
    except Exception as e:
        emit({"type": "error", "msg": f"couldn't load the gesture recognizer: {e}"})
        return 2

    cap, idx = open_camera(cv2, args.camera_index)
    if cap is None:
        emit({"type": "error", "msg": "couldn't open any webcam (index tried 0-2)"})
        return 2
    log(f"camera {idx} open; recognizer ready")

    hold = jv.HoldDebouncer(hold_frames=args.hold_frames,
                            cooldown_s=1.8, min_conf=args.min_conf)
    swipe = jv.SwipeTracker(min_dx=args.swipe_dx, cooldown_s=args.swipe_cooldown,
                            invert=args.swipe_invert)

    emit({"type": "ready"})
    period = 1.0 / max(1.0, args.fps)
    ts_ms = 0
    last_frame_emit = 0.0
    try:
        while True:
            t0 = time.monotonic()
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            mirror = cv2.flip(frame, 1)                    # mirror -> natural swipes
            rgb = cv2.cvtColor(mirror, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms += max(1, int(period * 1000))
            try:
                res = recognizer.recognize_for_video(mp_image, ts_ms)
            except Exception:
                continue

            name, conf = None, 0.0
            if res.gestures and res.gestures[0]:
                top = res.gestures[0][0]
                name, conf = top.category_name, float(top.score)
            hand_present = bool(res.hand_landmarks and res.hand_landmarks[0])
            palm_x = float(res.hand_landmarks[0][9].x) if hand_present else None
            now = time.monotonic()

            # horizontal swipe -> move window. Track whenever a hand is present
            # (except a fist/victory, which are the close/screenshot poses) so the
            # motion isn't lost when the recognizer stops labelling it "Open_Palm".
            swipe_open = hand_present and name not in ("Closed_Fist", "Victory")
            swipe_action = swipe.update(palm_x, palm_open=swipe_open, now=now)
            if swipe_action:
                emit({"type": "gesture", "action": swipe_action,
                      "gesture": "swipe", "conf": round(conf, 3)})

            # held static pose -> closed fist = close window, victory = screenshot
            fired = hold.update(name, conf, now)
            action = jv.STATIC_GESTURE_ACTIONS.get(fired) if fired else None
            if action:
                emit({"type": "gesture", "action": action,
                      "gesture": fired, "conf": round(conf, 3)})

            # share a periodic frame so Jarvis's vision tool / face-auth can still
            # "see" while we hold the camera. Send the UNMIRRORED frame (true
            # orientation) downscaled + JPEG-compressed to keep the stream light.
            if args.frame_interval > 0 and (now - last_frame_emit) >= args.frame_interval:
                last_frame_emit = now
                try:
                    h, w = frame.shape[:2]
                    small = frame if w <= 640 else cv2.resize(
                        frame, (640, max(1, int(h * 640.0 / w))))
                    ok2, buf = cv2.imencode(".jpg", small,
                                            [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                    if ok2:
                        emit({"type": "frame",
                              "jpeg_b64": base64.b64encode(buf.tobytes()).decode("ascii")})
                except Exception:
                    pass

            dt = time.monotonic() - t0
            if dt < period:
                time.sleep(period - dt)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        emit({"type": "error", "msg": f"vision loop crashed: {e}"})
        return 1
    finally:
        try:
            cap.release()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
