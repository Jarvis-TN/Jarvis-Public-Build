"""Turn a video clip into still frames for visual reference.

Pulls evenly-spaced frames between two timestamps, optionally zoomed/cropped to a
region (so a hologram fills the frame), saved as full-resolution PNGs plus a
contact sheet. Hand a few of the PNGs to Claude - it reads images clearly, just
not video.

Examples (run from the Jarvis folder):
  .venv\\Scripts\\python.exe extract_frames.py "C:\\path\\clip.mp4" --start 14 --end 22 --count 12
  .venv\\Scripts\\python.exe extract_frames.py "C:\\path\\clip.mp4" --start 15 --end 20 --count 16 --zoom 0.55 --offx 0.0 --offy -0.05
  .venv\\Scripts\\python.exe extract_frames.py "C:\\path\\clip.mp4" --start 0 --end 30 --count 30 --out boot_frames
"""

import os
import argparse
import av
from PIL import Image, ImageDraw


def extract(path, start, end, count, out_dir, zoom, offx, offy, max_w):
    os.makedirs(out_dir, exist_ok=True)
    container = av.open(path)
    vs = container.streams.video[0]
    dur = float(container.duration) / 1_000_000.0
    if end <= 0 or end > dur:
        end = dur
    if start < 0:
        start = 0.0
    print(f"clip duration: {dur:.1f}s | sampling {count} frames from {start:.1f}s to {end:.1f}s")

    times = [start + (end - start) * (i / max(1, count - 1)) for i in range(count)]
    thumbs = []
    for idx, tsec in enumerate(times, 1):
        try:
            container.seek(int(tsec / vs.time_base), stream=vs)
            img = None
            for frame in container.decode(vs):
                img = frame.to_image()
                break
            if img is None:
                continue
            if zoom and zoom < 1.0:
                w, h = img.size
                cw, ch = int(w * zoom), int(h * zoom)
                cx = int(w * (0.5 + offx)) - cw // 2
                cy = int(h * (0.5 + offy)) - ch // 2
                cx = max(0, min(w - cw, cx)); cy = max(0, min(h - ch, cy))
                img = img.crop((cx, cy, cx + cw, cy + ch))
            if max_w and img.size[0] > max_w:
                img = img.resize((max_w, int(img.size[1] * max_w / img.size[0])))
            fn = os.path.join(out_dir, f"frame_{idx:02d}_{tsec:05.1f}s.png")
            img.save(fn)
            thumbs.append(img)
        except Exception as e:
            print(f"  frame at {tsec:.1f}s failed: {e}")
    container.close()

    # contact sheet
    if thumbs:
        cols = 4
        tw = 320
        th = int(tw * thumbs[0].size[1] / thumbs[0].size[0])
        rows = (len(thumbs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (tw + 6) + 6, rows * (th + 6) + 6), (10, 10, 14))
        d = ImageDraw.Draw(sheet)
        for i, im in enumerate(thumbs):
            t = im.resize((tw, th))
            x = 6 + (i % cols) * (tw + 6); y = 6 + (i // cols) * (th + 6)
            sheet.paste(t, (x, y))
            d.text((x + 4, y + 4), f"{i+1:02d}", fill=(255, 200, 90))
        sheet.save(os.path.join(out_dir, "_contact_sheet.png"))

    print(f"done: {len(thumbs)} frames + _contact_sheet.png in '{out_dir}'")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Extract reference frames from a video.")
    ap.add_argument("video", help="path to the video file")
    ap.add_argument("--start", type=float, default=0.0, help="start time (seconds)")
    ap.add_argument("--end", type=float, default=0.0, help="end time (seconds; 0 = end of clip)")
    ap.add_argument("--count", type=int, default=12, help="number of frames")
    ap.add_argument("--out", default="frames", help="output folder")
    ap.add_argument("--zoom", type=float, default=1.0,
                    help="center-crop fraction (e.g. 0.55 zooms into the middle 55%%)")
    ap.add_argument("--offx", type=float, default=0.0, help="crop center shift X (-0.5..0.5)")
    ap.add_argument("--offy", type=float, default=0.0, help="crop center shift Y (-0.5..0.5)")
    ap.add_argument("--max-w", type=int, default=900, help="max output width (px)")
    a = ap.parse_args()
    extract(a.video, a.start, a.end, a.count, a.out, a.zoom, a.offx, a.offy, a.max_w)
