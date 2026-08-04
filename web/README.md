# JARVIS WebGL Neural HUD

A Three.js / WebGL voice-assistant visualization: a 3D cloud of glowing cyan→white
particle "neurons" connected by distance-faded filaments, drifting on noise-based
motion with a gentle global rotation, finished with a bloom glow. It exposes a tiny
external API so you can drive it from your real assistant state later.

## Run it

ES modules don't load over `file://`, so serve the folder over HTTP:

```
cd web
..\.venv\Scripts\python.exe -m http.server 8777
```

Then open <http://localhost:8777/>. (Three.js loads from a CDN, so the first load
needs internet; after that the browser caches it.)

The demo panel (bottom-left) lets you switch state and drag an amplitude slider.
It's optional — delete the `#panel` HTML and its wiring and the API still works.

## External JavaScript API

A global `window.jarvisHUD` is exposed:

```js
jarvisHUD.setState('idle' | 'listening' | 'speaking');
jarvisHUD.setAmplitude(0.0 .. 1.0);   // live voice loudness; used in 'speaking'
jarvisHUD.getState();                 // -> current state string
```

- **idle** — slow, dim drift.
- **listening** — nodes brighten and pull slightly inward.
- **speaking** — connections brighten/pulse and the web tightens in sync with the
  amplitude you feed in. Send `setAmplitude` ~30–60×/sec for a live reaction.

### Wiring to a real mic (browser)

```js
const ctx = new AudioContext();
const src = ctx.createMediaStreamSource(await navigator.mediaDevices.getUserMedia({audio:true}));
const analyser = ctx.createAnalyser(); analyser.fftSize = 512;
src.connect(analyser);
const buf = new Uint8Array(analyser.fftSize);
(function loop(){
  analyser.getByteTimeDomainData(buf);
  let s = 0; for (const v of buf) { const x = (v-128)/128; s += x*x; }
  jarvisHUD.setAmplitude(Math.min(1, Math.sqrt(s/buf.length) * 3));
  requestAnimationFrame(loop);
})();
jarvisHUD.setState('speaking');
```

### Live bridge to the Python Jarvis (built in)

This is now wired up. When the desktop Jarvis runs, it starts a WebSocket server on
`localhost:8765` (config `hud_bridge` / `hud_bridge_port`) and streams `{state, level}`
~30×/sec. This page automatically connects to `ws://localhost:8765`, and the panel
shows **● live** when connected (and **○ local** otherwise, where the demo buttons work).

So to see the HUD react to the real assistant:

1. Launch the desktop Jarvis (it starts the bridge automatically).
2. Open this page (`http://localhost:8777/`). It connects on its own.
3. Talk to Jarvis — the sphere brightens/drifts while it listens and processes, and
   fires/pulses in sync with his voice while speaking.

State mapping: engine `listening`/`thinking` → HUD `listening`; `speaking` → `speaking`;
everything else → `idle`. `engine.level` (0..1) drives the amplitude.

## Tuning (top of the `<script>` in index.html)

- `NODE_COUNT` / `MAX_SEGMENTS` — density vs. performance.
- `RADIUS`, `CONNECT_DIST` — cloud size and how readily nodes link.
- `STATES` — per-state brightness, drift, radius, connection scale, rotation.
- Bloom `strength` / `radius` / `threshold` — glow intensity (lower threshold = more
  blooms; raise it if the cores blow out to white).
