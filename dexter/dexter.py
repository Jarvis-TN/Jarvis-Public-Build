"""Dexter — a virtual Pokedex desktop app.

The window mirrors the show's open clamshell dex (see dexter_skin.py for the
rendered chrome): left panel with the glossy blue lens that flashes in sync
with Dexter's speech, three LEDs, the white-bezel main screen showing
artwork/types/stats; center hinge; right panel with the black console that
types out Dexter's words, the blue button grid, search bar and controls.

Layout/colors live in THEME and _layout() so the look can be tuned against
reference frames without touching logic. Run via "Launch Dexter.bat".
"""

from __future__ import annotations

import json
import math
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
    import dexter_skin
except Exception:
    Image = ImageTk = dexter_skin = None


THEME = {
    "win_w": 1060, "win_h": 680,
    "room": "#100a0c",
    "body": "#c8102e",
    "lens_blue_hi": "#9fd8ff",
    "lens_blue": "#1d6ff2",
    "lens_blue_lo": "#0b2e8f",
    "led_red": "#ff3b30", "led_yellow": "#ffcc00", "led_green": "#34c759",
    "screen": "#08120c",
    "screen_text": "#bfffd0",
    "screen_dim": "#4e8f63",
    "console_bg": "#050f07",
    "console_text": "#41ff7a",
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


def _layout():
    """Every coordinate of the device, shared by the skin and the app."""
    L = {
        "left_panel": (30, 30, 512, 650),
        "right_panel": (550, 62, 1032, 650),
        "hinge": (506, 44, 556, 640),
        "plate_pts": [(30, 30), (512, 30), (512, 104), (312, 104),
                      (258, 150), (30, 150)],
        "lens_center": (104, 90), "lens_r": 44,
        "led_centers": [(172, 52), (202, 52), (232, 52)],
        "bezel": (68, 182, 468, 464),
        "screen": (100, 216, 436, 440),
        "mic": (100, 522, 18),
        "pills": [((150, 500, 196, 510), "#d23b2f"),
                  ((210, 500, 256, 510), "#2e6fd8")],
        "green_btn": (148, 524, 242, 568),
        "dpad": (398, 522, 42, 30),
        "console": (584, 94, 998, 192),
        "grid_buttons": [(584 + col * 84, y, 584 + col * 84 + 76, y + 44)
                         for y in (224, 276) for col in range(5)],
        "white_btns": (584, 352, 686, 392),
        "yellow": (964, 372, 15),
        "black_slots": [(584, 562, 800, 618), (836, 562, 998, 618)],
    }
    return L


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


class DexterApp:
    def __init__(self):
        if Image is None:
            raise SystemExit("Pillow is required for the Pokedex skin - "
                             "run setup.bat to install dependencies.")
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

        self.L = _layout()
        self.level = 0.0            # live TTS loudness 0..1 (voice thread)
        self.lens_glow = 0.0        # displayed glow: fast attack, slow decay
        self._lens_idx = -1
        self.state = "boot"         # boot | idle | listening | thinking | speaking
        self.entry = None
        self.sprite_img = None
        self.console_full = ""
        self.console_shown = 0
        self.frame = 0
        self._led_shown = {}

        self.brain = DexterBrain(self.cfg)
        self.voice = DexterVoice(self.cfg,
                                 on_level=self._on_level,
                                 on_state=self._on_voice_state)
        self.ears = DexterEars(self.cfg) if DexterEars else None
        self.jobs = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
        if self.ears:  # load Whisper now so the first question answers fast
            threading.Thread(target=self.ears.warm_up, daemon=True).start()

        self._build_skin()
        self._build_dynamic()
        self._bind_input()
        self.root.after(30, self._tick)
        self.root.after(400, self._boot_sequence)

    # ---------------------------------------------------------------- skin ---

    def _build_skin(self):
        w, h = THEME["win_w"], THEME["win_h"]
        body = dexter_skin.render_body(w, h, THEME, self.L)
        self.bg_img = ImageTk.PhotoImage(body)
        self.canvas.create_image(0, 0, anchor="nw", image=self.bg_img)
        self.lens_imgs = [ImageTk.PhotoImage(f) for f in
                          dexter_skin.lens_frames(THEME,
                                                  size=self.L["lens_r"] * 2 + 16,
                                                  halo=38)]
        self.led_imgs = {}
        for name, hexc in (("red", THEME["led_red"]),
                           ("yellow", THEME["led_yellow"]),
                           ("green", THEME["led_green"])):
            self.led_imgs[name] = (ImageTk.PhotoImage(dexter_skin.led(hexc, False)),
                                   ImageTk.PhotoImage(dexter_skin.led(hexc, True)))

    def _build_dynamic(self):
        c, L = self.canvas, self.L
        cx, cy = L["lens_center"]
        self.lens_item = c.create_image(cx, cy, image=self.lens_imgs[0])
        self.led_items = {}
        for (x, y), name in zip(L["led_centers"], ("red", "yellow", "green")):
            self.led_items[name] = c.create_image(x, y,
                                                  image=self.led_imgs[name][0])
        # console text (right panel black display)
        cx1, cy1, cx2, cy2 = L["console"]
        self.console_item = c.create_text(cx1 + 12, cy1 + 10, anchor="nw",
                                          fill=THEME["console_text"],
                                          font=self.mono(11),
                                          width=cx2 - cx1 - 24, text="")
        # control labels (subtle, sit on the skin's buttons)
        mx, my, mr = L["mic"]
        c.create_text(mx, my, text="MIC", fill="#8fa3bd",
                      font=self.mono(9, "bold"))
        c.create_text(mx, my + mr + 14, text="hold SPACE", fill="#6b0f1e",
                      font=self.mono(8))
        self.mic_ring = c.create_oval(mx - mr - 7, my - mr - 7, mx + mr + 7,
                                      my + mr + 7, outline="", width=3)
        g = L["green_btn"]
        c.create_text((g[0] + g[2]) // 2, (g[1] + g[3]) // 2, text="GAME",
                      fill="#0b3317", font=self.mono(10, "bold"))
        wb = L["white_btns"]
        midx = (wb[0] + wb[2]) // 2
        c.create_text((wb[0] + midx) // 2, (wb[1] + wb[3]) // 2, text="◀",
                      fill="#33363c", font=self.mono(11, "bold"))
        c.create_text((midx + wb[2]) // 2, (wb[1] + wb[3]) // 2, text="▶",
                      fill="#33363c", font=self.mono(11, "bold"))
        dx, dy, arm, thick = L["dpad"]
        c.create_text(dx - arm + 8, dy, text="◀", fill="#3d4f45",
                      font=self.mono(10, "bold"))
        c.create_text(dx + arm - 8, dy, text="▶", fill="#3d4f45",
                      font=self.mono(10, "bold"))
        c.create_text(dx, dy - arm + 8, text="?", fill="#3d4f45",
                      font=self.mono(10, "bold"))
        # search bar inside the first black slot
        s1 = L["black_slots"][0]
        c.create_text(s1[0] + 12, (s1[1] + s1[3]) // 2, anchor="w",
                      text="SEARCH>", fill=THEME["screen_dim"],
                      font=self.mono(10, "bold"))
        self.search_var = tk.StringVar()
        entry = tk.Entry(self.root, textvariable=self.search_var,
                         bg="#080a08", fg=THEME["console_text"],
                         insertbackground=THEME["console_text"],
                         relief="flat", font=self.mono(11))
        entry.place(x=s1[0] + 90, y=s1[1] + 10, width=s1[2] - s1[0] - 102,
                    height=s1[3] - s1[1] - 20)
        entry.bind("<Return>", lambda e: self._on_search())
        # status readout in the second slot
        s2 = L["black_slots"][1]
        self.status_item = c.create_text((s2[0] + s2[2]) // 2,
                                         (s2[1] + s2[3]) // 2,
                                         text="DEXTER OS",
                                         fill=THEME["screen_dim"],
                                         font=self.mono(9))

    def _bind_input(self):
        self.canvas.bind("<Button-1>", self._on_click)
        self.root.bind("<Left>", lambda e: self._on_nav("prev"))
        self.root.bind("<Right>", lambda e: self._on_nav("next"))
        self.root.bind("<KeyPress-space>", self._space_down)
        self.root.bind("<KeyRelease-space>", self._space_up)
        self._space_held = False

    def _on_click(self, event):
        x, y, L = event.x, event.y, self.L
        mx, my, mr = L["mic"]
        if (x - mx) ** 2 + (y - my) ** 2 <= (mr + 8) ** 2:
            return self.toggle_mic()
        yx, yy, yr = L["yellow"]
        if (x - yx) ** 2 + (y - yy) ** 2 <= (yr + 5) ** 2:
            return self._on_nav("random")
        dx, dy, arm, thick = L["dpad"]
        if dy - thick // 2 <= y <= dy + thick // 2:
            if dx - arm - thick // 2 <= x < dx - 8:
                return self._on_nav("prev")
            if dx + 8 < x <= dx + arm + thick // 2:
                return self._on_nav("next")
        if dx - thick // 2 <= x <= dx + thick // 2 and \
                dy - arm - thick // 2 <= y <= dy + arm + thick // 2:
            return self._on_nav("random")
        wb = L["white_btns"]
        if wb[0] <= x <= wb[2] and wb[1] <= y <= wb[3]:
            return self._on_nav("prev" if x < (wb[0] + wb[2]) // 2 else "next")
        g = L["green_btn"]
        if g[0] <= x <= g[2] and g[1] <= y <= g[3]:
            return self.jobs.put(("ask", "I'm thinking of a Pokemon"))

    # ------------------------------------------------------------- animate ---

    def _tick(self):
        self.frame += 1
        target = self.level
        if self.state == "idle":
            target = max(target, 0.05 + 0.04 * math.sin(self.frame / 20))
        # fast attack so the flash lands on the syllable, slower release
        rate = 0.75 if target > self.lens_glow else 0.22
        self.lens_glow += (target - self.lens_glow) * rate
        idx = max(0, min(len(self.lens_imgs) - 1,
                         int(round(self.lens_glow * (len(self.lens_imgs) - 1)))))
        if idx != self._lens_idx:
            self._lens_idx = idx
            self.canvas.itemconfigure(self.lens_item, image=self.lens_imgs[idx])
        self._draw_leds()
        self._advance_console()
        if self.ears and self.state == "listening" and not self.ears.recording:
            self._finish_listening()   # silence auto-stop tripped
        self.root.after(33, self._tick)

    def _draw_leds(self):
        blink = (self.frame // 7) % 2 == 0
        states = {"red": False, "yellow": False, "green": False}
        if self.state == "boot":
            states[("red", "yellow", "green")[(self.frame // 5) % 3]] = True
        elif self.state == "listening":
            states["yellow"] = blink
        elif self.state == "thinking":
            states["red"] = blink
        elif self.state == "speaking":
            states["green"] = True
            states["yellow"] = self.level > 0.45
        else:
            states["green"] = True
        for name, on in states.items():
            if self._led_shown.get(name) != on:
                self._led_shown[name] = on
                self.canvas.itemconfigure(self.led_items[name],
                                          image=self.led_imgs[name][int(on)])

    def _advance_console(self):
        if self.console_shown < len(self.console_full):
            self.console_shown = min(len(self.console_full),
                                     self.console_shown + 3)
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
        sx1, sy1, sx2, sy2 = self.L["screen"]
        c.delete("screen_fg")
        img_path = dexter_data.sprite_path(entry)
        self.sprite_img = None
        if img_path:
            try:
                img = Image.open(img_path).convert("RGBA")
                img.thumbnail((150, 150), Image.LANCZOS)
                self.sprite_img = ImageTk.PhotoImage(img)
                c.create_image(sx1 + 78, sy1 + 108, image=self.sprite_img,
                               tags="screen_fg")
            except Exception:
                pass
        if self.sprite_img is None:
            c.create_text(sx1 + 78, sy1 + 108, text="[ NO IMAGE ]",
                          fill=T["screen_dim"], font=self.mono(9),
                          tags="screen_fg")
        tx = sx1 + 158
        c.create_text(sx1 + 10, sy1 + 8, anchor="nw",
                      text=f"No.{entry['id']:04d}", fill=T["screen_dim"],
                      font=self.mono(10), tags="screen_fg")
        c.create_text(tx, sy1 + 8, anchor="nw",
                      text=entry["display_name"].upper(),
                      fill=T["screen_text"], font=self.mono(14, "bold"),
                      tags="screen_fg")
        c.create_text(tx, sy1 + 32, anchor="nw",
                      text=entry.get("genus") or "", fill=T["screen_dim"],
                      font=self.mono(9), tags="screen_fg")
        for i, t in enumerate(entry.get("types") or []):
            bx = tx + i * 88
            by = sy1 + 50
            c.create_rectangle(bx, by, bx + 80, by + 18,
                               fill=T["type_colors"].get(t, "#888"),
                               outline="", tags="screen_fg")
            c.create_text(bx + 40, by + 9, text=t.upper(), fill="white",
                          font=self.mono(9, "bold"), tags="screen_fg")
        c.create_text(tx, sy1 + 78, anchor="nw",
                      text=(f"HT {entry['height_m']:.1f}m  "
                            f"WT {entry['weight_kg']:.1f}kg"),
                      fill=T["screen_text"], font=self.mono(9),
                      tags="screen_fg")
        stats = entry.get("stats") or {}
        for i, (key, label) in enumerate(STAT_ORDER):
            val = stats.get(key, 0)
            y = sy1 + 98 + i * 20
            c.create_text(tx, y, anchor="nw", text=label,
                          fill=T["screen_dim"], font=self.mono(9),
                          tags="screen_fg")
            c.create_rectangle(tx + 32, y + 2, tx + 132, y + 11,
                               outline=T["screen_dim"], tags="screen_fg")
            fill_w = int(100 * min(1.0, val / 200.0))
            color = ("#41ff7a" if val >= 100 else
                     "#f8d030" if val >= 60 else "#f08030")
            c.create_rectangle(tx + 32, y + 2, tx + 32 + fill_w, y + 11,
                               fill=color, outline="", tags="screen_fg")
            c.create_text(tx + 138, y, anchor="nw", text=str(val),
                          fill=T["screen_text"], font=self.mono(9),
                          tags="screen_fg")

    def flash_entry(self, entry):
        """Show an entry with the identification flash — a double blink over
        the screen, like the show's dex locking onto a Pokemon."""
        if not entry:
            return
        self.show_entry(entry)
        for delay in (0, 170):
            self.root.after(delay, self._flash_once)

    def _flash_once(self):
        rect = self.canvas.create_rectangle(*self.L["screen"],
                                            fill="#d8ffe4", outline="")
        self.canvas.after(85, lambda: self.canvas.delete(rect))

    # -------------------------------------------------------------- events ---

    def _on_nav(self, which):
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
            self.console("Database is empty. Run setup.bat, or:\n"
                         ".venv\\Scripts\\python.exe dexter_data.py sync")

    def _on_search(self):
        q = self.search_var.get().strip()
        if not q:
            return
        self.search_var.set("")
        entry = dexter_data.get(q) or dexter_data.find_named_in(q)
        if entry and len(q.split()) <= 2:
            self.flash_entry(entry)
            self.jobs.put(("speak", DexterBrain.describe(entry)))
        else:
            self.jobs.put(("ask", q))

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
        self.console("Listening... weaknesses, strengths, types, powers, "
                     "stats, evolutions, matchups — anything. Or say \"I'm "
                     "thinking of a Pokemon\".")

    def _finish_listening(self):
        self.canvas.itemconfigure(self.mic_ring, outline="")
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
                     f"DATABASE ... {n} SPECIES\nVOICE ... READY")
        self.canvas.itemconfigure(self.status_item,
                                  text=f"{n} SPECIES LOADED")

        def finish():
            self._set_state("idle")
            if n == 0:
                self.console("Database is empty. Run setup.bat (say yes to "
                             "the sync), or:\n"
                             ".venv\\Scripts\\python.exe dexter_data.py sync")
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
            hint = "\n\n[ MIC or SPACE to ask · GAME to be identified ]"
            self.jobs.put(("speak_show", (greeting, greeting + hint)))
        self.root.after(2200, finish)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    DexterApp().run()
