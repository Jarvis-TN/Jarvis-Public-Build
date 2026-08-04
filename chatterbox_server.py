"""Isolated Chatterbox TTS server.

Runs in its OWN virtual environment (.venv-chatterbox) because chatterbox-tts has
hard dependency conflicts with Jarvis's main stack (it wants transformers 5.x and
downgrades torch/numpy, which would break the XTTS/coqui voice clone). Jarvis's
main process talks to this over localhost, so the two dependency worlds never mix.

Started automatically by the engine when tts_engine="chatterbox" (or run manually:
    .venv-chatterbox\\Scripts\\python chatterbox_server.py --port 8123 --reference voices\\clone\\reference.wav

Endpoints:
    GET  /health  -> {"ready": bool}
    POST /synth   {text, exaggeration, cfg_weight} -> audio/wav bytes
"""

import io
import sys
import json
import argparse
import threading
import http.server


def build(args):
    state = {"model": None, "ready": False, "error": None}

    def load():
        try:
            if args.model == "turbo":
                from chatterbox.tts_turbo import ChatterboxTurboTTS as CB
            else:
                from chatterbox.tts import ChatterboxTTS as CB
            state["model"] = CB.from_pretrained(device=args.device)
            state["ready"] = True
            print(f"Chatterbox ({args.model}) loaded on {args.device}.", flush=True)
        except Exception as e:
            state["error"] = str(e)
            print(f"Chatterbox load failed: {e}", flush=True)

    threading.Thread(target=load, daemon=True).start()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/health"):
                body = json.dumps({"ready": state["ready"],
                                   "error": state["error"]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path.split("?")[0] != "/synth":
                return self.send_error(404)
            if not state["ready"]:
                return self.send_error(503, "model not ready")
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self.send_error(400, "bad request")
            text = (req.get("text") or "").strip()
            if not text:
                return self.send_error(400, "no text")
            try:
                import torch
                import torchaudio
                model = state["model"]
                kw = {}
                if args.reference:
                    kw["audio_prompt_path"] = args.reference
                wav = model.generate(
                    text,
                    exaggeration=float(req.get("exaggeration", 0.5)),
                    cfg_weight=float(req.get("cfg_weight", 0.5)),
                    **kw)
                wav = wav.detach().to("cpu")
                if wav.dim() == 1:
                    wav = wav.unsqueeze(0)
                buf = io.BytesIO()
                torchaudio.save(buf, wav, model.sr, format="wav")
                data = buf.getvalue()
            except Exception as e:
                return self.send_error(500, f"synth failed: {e}")
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--model", default="turbo")          # "turbo" or "standard"
    ap.add_argument("--reference", default="")
    ap.add_argument("--device", default="cpu")           # "cpu" or "cuda"
    args = ap.parse_args()
    httpd = build(args)
    print(f"Chatterbox server on http://127.0.0.1:{args.port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
