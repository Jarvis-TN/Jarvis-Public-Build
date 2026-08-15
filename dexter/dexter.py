"""Dexter — a virtual Pokedex desktop app.

A tkinter/Canvas rendition of the classic Kanto Pokedex from the animated
series: red clamshell body, the big blue lens that flashes while Dexter
talks, three indicator LEDs, a dark screen that shows official artwork and
stats, a green console that types out what Dexter says, and a microphone
button so you can ask Pokemon questions out loud — including "I'm thinking
of a Pokemon" to start the guessing game.

Run via "Launch Dexter.bat" (or the desktop shortcut created by setup.bat).
All geometry/colors live in THEME below so the look can be tuned to match
reference images without touching logic.
"""

from __future__ import annotations

import json
import os
import queue
import random
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dexter_data
from dexter_brain import DexterBrain
from dexter_voice import DexterVoice

try:
    from dexter_ears import DexterEars
except Exception:
    DexterEars = None

try:
    from PIL import Image, ImageTk
except Exception:
    Image = ImageTk = None


# ------------------------------------------------------------------ theme ---
# Tune these to match reference images of the show's Pokedex.
THEME = {
    "win_w": 1010, "win_h": 640,
    "room": "#14090b",           # backdrop behind the device
    "body": "#c8102e",           # pokedex red
    "body_dark": "#8f0b20",      # shading / hinge
    "body_edge": "#5c0714",
    "lens_ring": "#e8eef5",      # white ring around the big lens
    "lens_blue_hi": "#9fd8ff",   # lens gradient, bright center
    "lens_blue": "#1d6ff2",
    "lens_blue_lo": "#0b2e8f",
    "led_red": "#ff3b30", "led_red_off": "#5a1512",
    "led_yellow": "#ffcc00", "led_yellow_off": "#5c4a08",
    "led_green": "#34c759", "led_green_off": "#11451f",
    "bezel": "#1c1f24",          # around the screen
    "bezel_edge": "#3a3f47",
    "screen": "#08120c",         # main display
    "screen_text": "#bfffd0",
    "screen_dim": "#4e8f63",
    "console_bg": "#04180a",     # green terminal strip
    "console_text": "#41ff7a",
    "dpad": "#1450c8", "dpad_hi": "#2a6ef0",
    "button_dark": "#101216",
    "grid_btn": "#1450c8",
    "type_colors": {
        "normal": "#a8a878", "fire": "#f08030", "water": "#6890f0",
        "electric": "#f8d030", "grass": "#78c850", "ice": "#98d8d8",
        "fighting": "#c03028", "poison": "#a040a0", "ground": "#e0c068",
        "flying": "#a890f0", "psychic": "#f85888", "bug": "#a8b820",
        "rock": "#b8a038", "ghost": "#705898", "dragon": "#7038f8",
        "dark": "#705848", "steel": "#b8b8d0", "fairy": "#ee99ac",
    },
}

STAT_ORDER = [("hp", "HP"), ("attack", "ATK"), ("defense", "DEF"),
              ("special-attack", "SpA"), ("special-defense", "SpD"),
              ("speed", "SPE")]


def load_config():
    example = os.path.join(HERE, "config.example.json")
    path = os.path.join(HERE, "config.json")
    if not os.path.exists(path) and os.path.exists(example):
        with open(example, encoding="utf-8") as f:
            open(path, "w", encoding="utf-8").write(f.read())
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def round_rect(canvas, x1, y1, x2, y2, r=18, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def blend(c1, c2, t):
    """Blend two #rrggbb colors, t in 0..1."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class DexterApp:
    def __init__(self):
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.title("Dexter — Pokedex")
        self.root.configure(bg=THEME["room"])
        self.root.geometry(f"{THEME['win_w']}x{THEME['win_h']}")
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(self.root, width=THEME["win_w"],
                                height=THEME["win_h"], bg=THEME["room"],
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.mono = lambda size, weight="normal": tkfont.Font(
            family="Consolas", size=size, weight=weight)

        self.level = 0.0            # live TTS loudness 0..1 (voice thread)
        self.lens_glow = 0.0        # smoothed value the lens actually shows
        self.state = "boot"         # boot | idle | listening | thinking | speaking
        self.entry = None
        self.sprite_img = None      # keep a reference or tk drops it
        self.console_full = ""
        self.console_shown = 0
        self.frame = 0

        self.brain = DexterBrain(self.cfg)
        self.voice = DexterVoice(self.cfg,
                                 on_level=self._on_level,
                                 on_state=self._on_voice_state)
        self.ears = DexterEars(self.cfg) if DexterEars else None
        self.jobs = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

        self._build_static()
        self._build_controls()
        self._bind_keys()
        self.root.after(30, self._tick)
        self.root.after(400, self._boot_sequence)

    # -------------------------------------------------------------- chrome ---

    def _build_static(self):
        c, T = self.canvas, THEME
        w, h = T["win_w"], T["win_h"]
        # device body with a darker edge, like molded red plastic
        round_rect(c, 8, 8, w - 8, h - 8, r=34, fill=T["body_edge"])
        round_rect(c, 14, 14, w - 14, h - 14, r=30, fill=T["body"])
        # the classic diagonal hinge cut across the top-right
        c.create_polygon(w - 330, 14, w - 14, 14, w - 14, 96, w - 260, 96,
                         fill=T["body_dark"], outline="")
        # --- big lens (top-left), redrawn each frame for the glow ---
        self.lens_center = (92, 92)
        self.lens_items = None
        # --- three LEDs to the right of the lens ---
        self.led_items = {}
        for i, name in enumerate(("red", "yellow", "green")):
            x = 175 + i * 44
            c.create_oval(x - 15, 45, x + 15, 75, fill=T["body_dark"], outline="")
            self.led_items[name] = c.create_oval(
                x - 11, 49, x + 11, 71, fill=T[f"led_{name}_off"], outline="")
        # --- screen bezel + screen ---
        sx1, sy1, sx2, sy2 = 60, 170, 620, 560
        round_rect(c, sx1 - 18, sy1 - 18, sx2 + 18, sy2 + 18, r=22,
                   fill=T["bezel"], outline=T["bezel_edge"], width=2)
        c.create_rectangle(sx1, sy1, sx2, sy2, fill=T["screen"], outline="")
        self.screen_box = (sx1, sy1, sx2, sy2)
        # decorative screws in the bezel corners
        for x, y in ((sx1 - 9, sy1 - 9), (sx2 + 9, sy1 - 9),
                     (sx1 - 9, sy2 + 9), (sx2 + 9, sy2 + 9)):
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#565d68", outline="")
        # --- green console strip (Dexter's words), right side ---
        cx1, cy1, cx2, cy2 = 660, 330, 950, 500
        round_rect(c, cx1 - 10, cy1 - 10, cx2 + 10, cy2 + 10, r=14,
                   fill=T["bezel"], outline=T["bezel_edge"], width=2)
        c.create_rectangle(cx1, cy1, cx2, cy2, fill=T["console_bg"], outline="")
        self.console_box = (cx1, cy1, cx2, cy2)
        self.console_item = c.create_text(
            cx1 + 10, cy1 + 8, anchor="nw", fill=T["console_text"],
            font=self.mono(11), width=cx2 - cx1 - 20, text="")
        # decorative blue button grid under the console
        for row in range(2):
            for col in range(5):
                x = 665 + col * 58
                y = 520 + row * 40
                round_rect(c, x, y, x + 48, y + 30, r=6, fill=T["grid_btn"])
        # dynamic screen items get tagged "screen_fg" and cleared per entry
        self.type_badges = []

    def _build_controls(self):
        c, T = self.canvas, THEME
        # --- D-pad (prev / next / random) ---
        dx, dy, arm, thick = 800, 180, 46, 34
        c.create_rectangle(dx - arm - thick // 2, dy - thick // 2,
                           dx + arm + thick // 2, dy + thick // 2,
                           fill=T["dpad"], outline="")
        c.create_rectangle(dx - thick // 2, dy - arm - thick // 2,
                           dx + thick // 2, dy + arm + thick // 2,
                           fill=T["dpad"], outline="")
        c.create_oval(dx - 14, dy - 14, dx + 14, dy + 14, fill=T["dpad_hi"],
                      outline="")
        for tag, box, label in (
                ("prev", (dx - arm - thick // 2, dy - thick // 2, dx - 14,
                          dy + thick // 2), "◀"),
                ("next", (dx + 14, dy - thick // 2, dx + arm + thick // 2,
                          dy + thick // 2), "▶"),
                ("rand", (dx - thick // 2, dy - arm - thick // 2,
                          dx + thick // 2, dy - 14), "?"),
                ("randb", (dx - thick // 2, dy + 14, dx + thick // 2,
                           dy + arm + thick // 2), "?")):
            item = c.create_text((box[0] + box[2]) // 2, (box[1] + box[3]) // 2,
                                 text=label, fill="white",
                                 font=self.mono(12, "bold"))
            for target in (item,):
                c.tag_bind(target, "<Button-1>",
                           lambda e, t=tag: self._on_dpad(t))
            rect = c.create_rectangle(*box, outline="", fill="")
            c.tag_bind(rect, "<Button-1>", lambda e, t=tag: self._on_dpad(t))
        # --- mic button ---
        mx, my, mr = 900, 180, 42
        self.mic_ring = c.create_oval(mx - mr - 6, my - mr - 6, mx + mr + 6,
                                      my + mr + 6, outline=T["dpad_hi"],
                                      width=3)
        self.mic_btn = c.create_oval(mx - mr, my - mr, mx + mr, my + mr,
                                     fill=T["button_dark"], outline="#2a2e35",
                                     width=2)
        self.mic_icon = c.create_text(mx, my, text="MIC", fill="#9fb4cc",
                                      font=self.mono(13, "bold"))
        for item in (self.mic_btn, self.mic_icon, self.mic_ring):
            c.tag_bind(item, "<Button-1>", lambda e: self.toggle_mic())
        c.create_text(mx, my + mr + 20, text="or hold SPACE",
                      fill=T["body_dark"], font=self.mono(9))
        # --- search box ---
        c.create_text(660, 258, anchor="w", text="SEARCH",
                      fill="#f4c8cf", font=self.mono(10, "bold"))
        self.search_var = tk.StringVar()
        entry = tk.Entry(self.root, textvariable=self.search_var,
                         bg="#2a0d13", fg="#ffe9ec",
                         insertbackground="#ffe9ec", relief="flat",
                         font=self.mono(12))
        entry.place(x=660, y=272, width=210, height=30)
        entry.bind("<Return>", lambda e: self._on_search())
        btn = round_rect(c, 880, 270, 950, 304, r=8, fill=T["dpad"])
        btn_t = c.create_text(915, 287, text="GO", fill="white",
                              font=self.mono(11, "bold"))
        for item in (btn, btn_t):
            c.tag_bind(item, "<Button-1>", lambda e: self._on_search())

    def _bind_keys(self):
        self.root.bind("<Left>", lambda e: self._on_dpad("prev"))
        self.root.bind("<Right>", lambda e: self._on_dpad("next"))
        self.root.bind("<KeyPress-space>", self._space_down)
        self.root.bind("<KeyRelease-space>", self._space_up)
        self._space_held = False

    # ------------------------------------------------------------- animate ---

    def _tick(self):
        self.frame += 1
        # lens: chase the live voice level with a little smoothing + idle pulse
        target = self.level
        if self.state == "idle":
            import math
            target = max(target, 0.06 + 0.04 * math.sin(self.frame / 22))
        self.lens_glow += (target - self.lens_glow) * 0.35
        self._draw_lens()
        self._draw_leds()
        self._advance_console()
        if self.ears and self.state == "listening" and not self.ears.recording:
            self._finish_listening()   # silence auto-stop tripped
        self.root.after(33, self._tick)

    def _draw_lens(self):
        c, T = self.canvas, THEME
        x, y = self.lens_center
        glow = max(0.0, min(1.0, self.lens_glow))
        if self.lens_items:
            for item in self.lens_items:
                c.delete(item)
        items = []
        halo_r = 58 + glow * 14
        items.append(c.create_oval(x - halo_r, y - halo_r, x + halo_r,
                                   y + halo_r,
                                   fill=blend(T["body"], "#3f79d8", glow * 0.55),
                                   outline=""))
        items.append(c.create_oval(x - 56, y - 56, x + 56, y + 56,
                                   fill=T["lens_ring"], outline="#b9c4d2",
                                   width=2))
        for radius, base, bright in ((46, T["lens_blue_lo"], T["lens_blue"]),
                                     (34, T["lens_blue"], T["lens_blue_hi"]),
                                     (20, T["lens_blue_hi"], "#eaf7ff")):
            items.append(c.create_oval(x - radius, y - radius, x + radius,
                                       y + radius,
                                       fill=blend(base, bright, glow),
                                       outline=""))
        items.append(c.create_oval(x - 30, y - 38, x - 8, y - 22,
                                   fill=blend("#cfe9ff", "#ffffff", glow),
                                   outline=""))
        self.lens_items = items

    def _draw_leds(self):
        c, T = self.canvas, THEME
        blink = (self.frame // 8) % 2 == 0
        states = {"red": False, "yellow": False, "green": False}
        if self.state == "boot":
            states[("red", "yellow", "green")[(self.frame // 6) % 3]] = True
        elif self.state == "listening":
            states["yellow"] = blink
        elif self.state == "thinking":
            states["red"] = blink
        elif self.state == "speaking":
            states["green"] = True
            states["yellow"] = self.level > 0.35
        else:
            states["green"] = True
        for name, on in states.items():
            c.itemconfigure(self.led_items[name],
                            fill=T[f"led_{name}"] if on else T[f"led_{name}_off"])

    def _advance_console(self):
        if self.console_shown < len(self.console_full):
            self.console_shown = min(len(self.console_full),
                                     self.console_shown + 2)
            cursor = "▌" if (self.frame // 6) % 2 == 0 else " "
            self.canvas.itemconfigure(
                self.console_item,
                text=self.console_full[:self.console_shown] + cursor)
        elif self.console_full and self.frame % 12 == 0:
            self.canvas.itemconfigure(self.console_item, text=self.console_full)

    def console(self, text):
        self.console_full = text
        self.console_shown = 0

    def console_append(self, text):
        self.console_full += text

    # -------------------------------------------------------------- screen ---

    def show_entry(self, entry):
        if not entry:
            return
        self.entry = entry
        c, T = self.canvas, THEME
        sx1, sy1, sx2, sy2 = self.screen_box
        c.delete("screen_fg")
        # artwork
        img_path = dexter_data.sprite_path(entry)
        self.sprite_img = None
        if img_path and Image is not None:
            try:
                img = Image.open(img_path).convert("RGBA")
                img.thumbnail((240, 240), Image.LANCZOS)
                self.sprite_img = ImageTk.PhotoImage(img)
                c.create_image(sx1 + 150, sy1 + 140, image=self.sprite_img,
                               tags="screen_fg")
            except Exception:
                pass
        if self.sprite_img is None:
            c.create_text(sx1 + 150, sy1 + 140, text="[ NO IMAGE ]",
                          fill=T["screen_dim"], font=self.mono(12),
                          tags="screen_fg")
        # header: number + name + genus
        c.create_text(sx1 + 20, sy1 + 16, anchor="nw",
                      text=f"No.{entry['id']:04d}", fill=T["screen_dim"],
                      font=self.mono(12), tags="screen_fg")
        c.create_text(sx1 + 300, sy1 + 40, anchor="nw",
                      text=entry["display_name"].upper(),
                      fill=T["screen_text"], font=self.mono(20, "bold"),
                      tags="screen_fg")
        c.create_text(sx1 + 300, sy1 + 74, anchor="nw",
                      text=entry.get("genus") or "", fill=T["screen_dim"],
                      font=self.mono(11), tags="screen_fg")
        # type badges
        for i, t in enumerate(entry.get("types") or []):
            bx = sx1 + 300 + i * 96
            by = sy1 + 100
            round_rect(c, bx, by, bx + 86, by + 24, r=10,
                       fill=T["type_colors"].get(t, "#888"), tags="screen_fg")
            c.create_text(bx + 43, by + 12, text=t.upper(), fill="white",
                          font=self.mono(10, "bold"), tags="screen_fg")
        # size line
        c.create_text(sx1 + 300, sy1 + 138, anchor="nw",
                      text=(f"HT {entry['height_m']:.1f} m    "
                            f"WT {entry['weight_kg']:.1f} kg"),
                      fill=T["screen_text"], font=self.mono(11),
                      tags="screen_fg")
        # stat bars
        stats = entry.get("stats") or {}
        bar_x, bar_y = sx1 + 300, sy1 + 170
        for i, (key, label) in enumerate(STAT_ORDER):
            val = stats.get(key, 0)
            y = bar_y + i * 26
            c.create_text(bar_x, y, anchor="nw", text=f"{label:<4}",
                          fill=T["screen_dim"], font=self.mono(10),
                          tags="screen_fg")
            c.create_rectangle(bar_x + 44, y + 2, bar_x + 214, y + 12,
                               outline=T["screen_dim"], tags="screen_fg")
            fill_w = int(170 * min(1.0, val / 200.0))
            color = ("#41ff7a" if val >= 100 else
                     "#f8d030" if val >= 60 else "#f08030")
            c.create_rectangle(bar_x + 44, y + 2, bar_x + 44 + fill_w, y + 12,
                               fill=color, outline="", tags="screen_fg")
            c.create_text(bar_x + 222, y - 1, anchor="nw", text=str(val),
                          fill=T["screen_text"], font=self.mono(10),
                          tags="screen_fg")
        # flavor text along the bottom of the screen
        flavor = ""
        if entry.get("flavor"):
            flavor = entry["flavor"][-1]["text"]
        c.create_text(sx1 + 20, sy2 - 96, anchor="nw", text=flavor,
                      fill=T["screen_text"], font=self.mono(10),
                      width=sx2 - sx1 - 40, tags="screen_fg")

    def flash_entry(self, entry):
        """Show an entry with the identification flash — a double white-green
        blink over the screen, like the show's dex locking onto a Pokemon."""
        if not entry:
            return
        self.show_entry(entry)
        for delay in (0, 170):
            self.root.after(delay, self._flash_once)

    def _flash_once(self):
        rect = self.canvas.create_rectangle(*self.screen_box,
                                            fill="#d8ffe4", outline="")
        self.canvas.after(85, lambda: self.canvas.delete(rect))

    # -------------------------------------------------------------- events ---

    def _on_dpad(self, which):
        if self.entry is None:
            entry = dexter_data.get(1) or dexter_data.random_one()
        elif which == "prev":
            entry = dexter_data.neighbor(self.entry["id"], -1)
        elif which == "next":
            entry = dexter_data.neighbor(self.entry["id"], +1)
        else:
            entry = dexter_data.random_one()
        if entry:
            self.show_entry(entry)
            self.jobs.put(("speak", DexterBrain.describe(entry)))
        else:
            self.console("Database is empty. Run: setup.bat  (or "
                         "python dexter_data.py sync)")

    def _on_search(self):
        q = self.search_var.get().strip()
        if not q:
            return
        self.search_var.set("")
        entry = dexter_data.get(q) or dexter_data.find_named_in(q)
        if entry:
            self.show_entry(entry)
            self.jobs.put(("speak", DexterBrain.describe(entry)))
        else:
            self.jobs.put(("ask", q))   # not a name — treat as a question

    def _space_down(self, _e):
        if not self._space_held:
            self._space_held = True
            if self.state != "listening":
                self.toggle_mic()

    def _space_up(self, _e):
        self._space_held = False
        if self.state == "listening":
            self.toggle_mic()

    def toggle_mic(self):
        if self.ears is None:
            self.console("Microphone support is not installed. Re-run "
                         "setup.bat to add sounddevice and faster-whisper.")
            return
        if self.state == "listening":
            self._finish_listening()
            return
        if self.state in ("thinking", "boot"):
            return
        self.voice.stop()
        try:
            self.ears.start()
        except Exception as exc:
            self.console(f"Microphone error: {exc}")
            return
        self._set_state("listening")
        self.canvas.itemconfigure(self.mic_ring, outline="#ffcc00")
        self.console("Listening... ask me anything. Weaknesses, strengths, "
                     "types, abilities, stats, evolutions, matchups — or say "
                     "\"I'm thinking of a Pokemon\" and I will identify it.")

    def _finish_listening(self):
        self.canvas.itemconfigure(self.mic_ring, outline=THEME["dpad_hi"])
        self._set_state("thinking")
        self.console("Processing...")
        self.jobs.put(("transcribe", None))

    def _set_state(self, state):
        self.state = state

    def _on_level(self, level):
        self.level = level

    def _on_voice_state(self, state):
        if state == "speaking":
            self._set_state("speaking")
        elif self.state == "speaking":
            self._set_state("idle")
            self.level = 0.0

    # -------------------------------------------------------------- worker ---

    def _speak(self, text):
        """Speak and, if ElevenLabs fell back to the Windows voice, say why
        on the console instead of failing silently."""
        self.voice.speak(text)
        if self.voice.last_error:
            self.root.after(0, self.console_append,
                            f"\n\n[voice] ElevenLabs unavailable: "
                            f"{self.voice.last_error}\n[voice] Using the "
                            "Windows voice for now.")

    def _worker(self):
        while True:
            job, arg = self.jobs.get()
            try:
                if job == "speak":
                    self.root.after(0, self.console, arg)
                    self._speak(arg)
                elif job == "speak_show":  # speak one text, display another
                    spoken, shown = arg
                    self.root.after(0, self.console, shown)
                    self._speak(spoken)
                elif job == "ask":
                    self._set_state("thinking")
                    reply, entry = self.brain.handle(arg)
                    if entry:
                        self.root.after(0, self.flash_entry, entry)
                    self.root.after(0, self.console, reply)
                    self._speak(reply)
                    self._set_state("idle")
                elif job == "transcribe":
                    heard = self.ears.stop_and_transcribe()
                    if not heard:
                        self._set_state("idle")
                        self.root.after(0, self.console,
                                        "I heard nothing but static. Try again.")
                        continue
                    self.root.after(0, self.console, f"> {heard}")
                    reply, entry = self.brain.handle(heard)
                    if entry:
                        self.root.after(0, self.flash_entry, entry)
                    self.root.after(0, self.console, reply)
                    self._speak(reply)
                    self._set_state("idle")
            except Exception as exc:
                self._set_state("idle")
                self.root.after(0, self.console, f"Error: {exc}")

    # ---------------------------------------------------------------- boot ---

    def _boot_sequence(self):
        n = dexter_data.count()
        self.console("DEXTER OS v1.0\nSYSTEM CHECK ... OK\n"
                     f"DATABASE ... {n} SPECIES\nVOICE ... READY\n")
        def finish():
            self._set_state("idle")
            if n == 0:
                self.console("Database is empty.\nRun setup.bat (it offers a "
                             "full sync),\nor: .venv\\Scripts\\python.exe "
                             "dexter_data.py sync")
                return
            entry = dexter_data.get(random.randint(1, min(151, n))) \
                or dexter_data.random_one()
            if entry:
                self.show_entry(entry)
            trainer = self.cfg.get("trainer_name", "Walker")
            hometown = self.cfg.get("hometown", "Pallet")
            greeting = (f"I'm Dexter, a Pokedex programmed by Professor Oak "
                        f"for Pokemon trainer {trainer} of the town of "
                        f"{hometown}. My function is to provide {trainer} "
                        "with information and advice regarding Pokemon and "
                        "their training. If lost or stolen, I cannot be "
                        "replaced.")
            hint = ("\n\n[ MIC or SPACE to ask about any Pokemon —\n"
                    "  or say \"I'm thinking of a Pokemon\" ]")
            self.jobs.put(("speak_show", (greeting, greeting + hint)))
        self.root.after(2200, finish)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    DexterApp().run()
