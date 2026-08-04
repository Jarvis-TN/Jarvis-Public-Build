/* JARVIS CGI Glass Hologram — WebGL2 particle engine, locked 30fps.
   <jarvis-hologram state="idle|listening|speaking|thinking" density="1" speed="1" tint="#ffffff">
   Global API: window.jarvis.setState(s), window.jarvis.toggleMic(), window.jarvis.state
   Events on window: 'jarvis-mic' {detail:{enabled}}, 'jarvis-state' {detail:{state}}
*/
(function () {
  'use strict';

  const VS = `#version 300 es
precision highp float;
layout(location=0) in vec3 aPos;
layout(location=1) in vec4 aData; // type, seed, size, phase
layout(location=2) in vec3 aAux;
uniform float uTime;
uniform float uRot;
uniform vec2  uTilt;
uniform float uBreath;
uniform float uAudio;
uniform float uFire;
uniform vec4  uState; // bright, jitter, packet, swirl
uniform vec2  uMouse;
uniform float uMouseOn;
uniform float uAspect;
uniform float uPx;
out float vAlpha;
out float vHeat;
mat3 rotY(float a){float c=cos(a),s=sin(a);return mat3(c,0.,-s,0.,1.,0.,s,0.,c);}
mat3 rotX(float a){float c=cos(a),s=sin(a);return mat3(1.,0.,0.,0.,c,s,0.,-s,c);}
void main(){
  int type = int(aData.x+0.5);
  float seed = aData.y;
  float phase = aData.w;
  float size = aData.z;
  float t = uTime;
  vec3 p = aPos;
  float heat = 0.22 + 0.3*fract(seed*13.7);
  float alpha = 1.0;

  if(type==0){ // shell circuit traces
    float fl = 0.5+0.5*sin(t*(1.2+fract(seed*5.3)*2.6)+phase*6.2831);
    alpha = 0.22+0.78*fl;
    p += p*(sin(t*0.7+seed*40.0)*0.014*uState.y);
  } else if(type==1){ // tilted rings, dashed circuit look
    p = rotY(t*0.12*(0.4+aAux.x)) * p;
    float dash = 0.5+0.5*sin(phase*47.0+t*0.55);
    alpha = 0.25+0.75*dash;
    heat += 0.12;
  } else if(type==2){ // dust
    p += 0.14*vec3(sin(t*0.31+seed*17.0), sin(t*0.23+seed*29.0), sin(t*0.27+seed*23.0));
    alpha = 0.3+0.4*sin(t*0.9+seed*31.0);
    heat = 0.18;
  } else if(type==3){ // packet firing along spoke
    vec3 dir = normalize(aPos);
    float sp = 0.16+0.3*fract(seed*7.1);
    float prog = fract(t*sp*uState.z + phase);
    p = dir*(0.06+prog*1.14);
    alpha = smoothstep(0.0,0.12,prog)*smoothstep(1.0,0.72,prog)*1.7;
    heat = 0.88;
    size *= 1.0+0.6*(1.0-prog);
  } else if(type==6){ // neuron firing quark (speaking only)
    vec3 b = aAux;
    float sp = 0.35+0.55*fract(sin(dot(aPos,b)*12.9898)*43758.5453);
    float prog = fract(t*sp + phase);
    p = mix(aPos, b, prog);
    p += normalize(p)*0.06*sin(prog*3.14159);
    float win = smoothstep(0.0,0.08,prog)*smoothstep(1.0,0.85,prog);
    alpha = win * uFire * 2.0;
    heat = 0.95;
    size *= (0.8+0.6*(1.0-prog));
  } else if(type==4){ // core
    p = aPos*(1.0+0.38*uAudio+0.08*sin(t*2.3+seed*20.0));
    alpha = 0.45+0.55*sin(t*1.7+seed*25.0);
    heat = 0.92;
  } else { // 5: spoke lines (neural streams, faint)
    alpha = 0.10+0.13*sin(t*2.2 - length(aPos)*9.0 + phase*6.2831);
    heat = 0.5;
  }

  float sw = uState.w*0.25*sin(t*0.35 + p.y*2.5 + seed);
  p = rotY(sw)*p;
  float r0 = length(p);
  if(type==0||type==1||type==5) p *= 1.0 + uAudio*0.07*sin(r0*10.0 - t*4.0);
  p *= uBreath;
  p = rotX(uTilt.y)*rotY(uRot+uTilt.x)*p;

  float zc = 2.7 - p.z;
  vec2 ndc = p.xy*1.95/zc;
  ndc.x /= uAspect;

  vec2 d2 = vec2((ndc.x-uMouse.x)*uAspect, ndc.y-uMouse.y);
  float md = length(d2);
  float inf = uMouseOn*smoothstep(0.42,0.0,md);
  if(md>0.0001){ vec2 push = (d2/md)*inf*0.06; push.x/=uAspect; ndc += push; }
  alpha *= 1.0+inf*1.5;
  heat = min(1.0, heat+inf*0.45);

  gl_Position = vec4(ndc, p.z*0.1, 1.0);
  gl_PointSize = max(1.0, size*uPx*2.3/zc*(1.0+uAudio*0.25));
  vAlpha = alpha*uState.x;
  vHeat = heat;
}`;

  const FS = `#version 300 es
precision highp float;
in float vAlpha;
in float vHeat;
uniform vec3 uTint;
out vec4 o;
void main(){
  vec2 q = gl_PointCoord-0.5;
  float d = length(q)*2.0;
  if(d>1.0) discard;
  float a = smoothstep(1.0,0.0,d);
  a *= a;
  vec3 deep  = vec3(1.0,0.42,0.06);
  vec3 light = vec3(1.0,0.82,0.40);
  vec3 wht   = vec3(1.0,0.96,0.88);
  vec3 col = mix(deep, light, vHeat);
  col += wht * pow(a,3.0) * (0.35+vHeat);
  o = vec4(col*uTint*a*vAlpha, 1.0);
}`;

  const STATES = {
    idle:      { bright: 0.85, jitter: 0.30, packet: 0.45, swirl: 0.15, rot: 0.020, ag: 0.25, fire: 0 },
    listening: { bright: 1.15, jitter: 0.15, packet: 0.30, swirl: 0.08, rot: 0.012, ag: 1.25, fire: 0 },
    speaking:  { bright: 1.25, jitter: 0.40, packet: 0.45, swirl: 0.15, rot: 0.020, ag: 1.10, fire: 1 },
    thinking:  { bright: 1.05, jitter: 0.85, packet: 1.80, swirl: 0.55, rot: 0.070, ag: 0.35, fire: 0 },
  };

  function mulberry(seed) {
    let s = seed >>> 0;
    return function () {
      s |= 0; s = (s + 0x6D2B79F5) | 0;
      let z = Math.imul(s ^ (s >>> 15), 1 | s);
      z = (z + Math.imul(z ^ (z >>> 7), 61 | z)) ^ z;
      return ((z ^ (z >>> 14)) >>> 0) / 4294967296;
    };
  }

  function buildGeometry(density) {
    const rnd = mulberry(1337);
    const pts = []; // 10 floats: pos3, data4(type,seed,size,phase), aux3
    const push = (x, y, z, type, size, phase, ax, ay, az) => {
      pts.push(x, y, z, type, rnd(), size, phase, ax || 0, ay || 0, az || 0);
    };
    const randUnit = () => {
      const u = rnd() * 2 - 1, th = rnd() * Math.PI * 2, s = Math.sqrt(1 - u * u);
      return [s * Math.cos(th), s * Math.sin(th), u];
    };
    const norm = (v) => { const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; };
    const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

    // 1) Shell circuit traces (walks on sphere with 90° turns)
    const nTraces = Math.round(150 * density);
    for (let i = 0; i < nTraces; i++) {
      let p = randUnit();
      let t = norm(cross(p, randUnit()));
      const steps = 30 + Math.floor(rnd() * 60);
      const stepA = 0.010 + rnd() * 0.010;
      for (let s = 0; s < steps; s++) {
        const c = Math.cos(stepA), sn = Math.sin(stepA);
        p = norm([p[0] * c + t[0] * sn, p[1] * c + t[1] * sn, p[2] * c + t[2] * sn]);
        // re-orthogonalize t
        const d = p[0] * t[0] + p[1] * t[1] + p[2] * t[2];
        t = norm([t[0] - p[0] * d, t[1] - p[1] * d, t[2] - p[2] * d]);
        if (rnd() < 0.05) { // 90° circuit turn -> bright node
          const b = cross(p, t);
          t = rnd() < 0.5 ? b : [-b[0], -b[1], -b[2]];
          push(p[0], p[1], p[2], 0, 2.6 + rnd() * 1.6, rnd());
        }
        push(p[0], p[1], p[2], 0, 0.9 + rnd() * 1.1, rnd());
      }
    }
    // 2) Latitude arcs
    for (let i = 0; i < Math.round(22 * density); i++) {
      const lat = (rnd() * 2 - 1) * 0.85;
      const rl = Math.sqrt(1 - lat * lat);
      const a0 = rnd() * Math.PI * 2, span = 0.5 + rnd() * 2.2;
      const n = Math.floor(span * 60);
      for (let k = 0; k < n; k++) {
        const a = a0 + (k / n) * span;
        push(Math.cos(a) * rl, lat, Math.sin(a) * rl, 0, 0.8 + rnd(), k / n);
      }
    }
    // 3) Dust clusters on shell
    for (let i = 0; i < Math.round(38 * density); i++) {
      const c = randUnit();
      for (let k = 0; k < 45; k++) {
        const g = () => (rnd() + rnd() + rnd() - 1.5) * 0.075;
        const p = norm([c[0] + g(), c[1] + g(), c[2] + g()]);
        const rr = 0.96 + rnd() * 0.1;
        push(p[0] * rr, p[1] * rr, p[2] * rr, 0, 0.7 + rnd() * 1.8, rnd());
      }
    }
    // 3b) Circuit blocks — PCB-like tangent grids at layered radii (traces, stubs, node pads)
    const layers = [1.0, 0.86, 0.72];
    const nBlocks = Math.round(55 * density);
    for (let i = 0; i < nBlocks; i++) {
      const c = randUnit();
      const R = layers[Math.floor(rnd() * layers.length)];
      let u = norm(cross(c, Math.abs(c[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]));
      let v = cross(c, u);
      const rotA = rnd() * Math.PI * 2, ca = Math.cos(rotA), sa = Math.sin(rotA);
      const u2 = [u[0] * ca + v[0] * sa, u[1] * ca + v[1] * sa, u[2] * ca + v[2] * sa];
      const v2 = [v[0] * ca - u[0] * sa, v[1] * ca - u[1] * sa, v[2] * ca - u[2] * sa];
      const at = (du, dv) => [
        (c[0] + u2[0] * du + v2[0] * dv) * R,
        (c[1] + u2[1] * du + v2[1] * dv) * R,
        (c[2] + u2[2] * du + v2[2] * dv) * R,
      ];
      const nLines = 3 + Math.floor(rnd() * 5);
      const len = 0.10 + rnd() * 0.16;
      const pitch = 0.014 + rnd() * 0.012;
      for (let li = 0; li < nLines; li++) {
        const dv = (li - nLines / 2) * pitch;
        const l2 = len * (0.55 + rnd() * 0.45);
        const steps = Math.max(4, Math.round(l2 * 130));
        for (let k = 0; k <= steps; k++) {
          const p = at(-l2 / 2 + (k / steps) * l2, dv);
          push(p[0], p[1], p[2], 0, 0.8 + rnd() * 0.9, li / nLines + k * 0.01);
        }
        const e0 = at(-l2 / 2, dv), e1 = at(l2 / 2, dv);
        push(e0[0], e0[1], e0[2], 0, 2.4 + rnd() * 1.4, rnd());
        push(e1[0], e1[1], e1[2], 0, 2.4 + rnd() * 1.4, rnd());
        if (rnd() < 0.55) { // perpendicular stub
          const sl = 0.02 + rnd() * 0.045;
          const sgn = rnd() < 0.5 ? 1 : -1;
          const base = rnd() < 0.5 ? -l2 / 2 : l2 / 2;
          const ss = Math.max(3, Math.round(sl * 130));
          for (let k = 0; k <= ss; k++) {
            const p = at(base, dv + sgn * (k / ss) * sl);
            push(p[0], p[1], p[2], 0, 0.7 + rnd() * 0.8, rnd());
          }
        }
      }
      if (rnd() < 0.45) { // rectangle outline (IC package)
        const w = 0.035 + rnd() * 0.05, h = 0.025 + rnd() * 0.04;
        const ox = (rnd() - 0.5) * len, oy = (rnd() - 0.5) * nLines * pitch * 1.6;
        const per = Math.round((w + h) * 2 * 150);
        for (let k = 0; k < per; k++) {
          const tt = (k / per) * (2 * w + 2 * h);
          let du, dv;
          if (tt < w) { du = tt - w / 2; dv = -h / 2; }
          else if (tt < w + h) { du = w / 2; dv = tt - w - h / 2; }
          else if (tt < 2 * w + h) { du = w / 2 - (tt - w - h); dv = h / 2; }
          else { du = -w / 2; dv = h / 2 - (tt - 2 * w - h); }
          const p = at(ox + du, oy + dv);
          push(p[0], p[1], p[2], 0, 0.9 + rnd() * 0.8, k / per);
        }
      }
    }
    // 4) Fragmented rings — broken arc segments at varied tilts/radii
    const rings = [
      { r: 1.16, tx: 0.45, tz: 0.10, sp: 0.9 },
      { r: 1.32, tx: -0.30, tz: 0.35, sp: 0.4 },
      { r: 0.84, tx: 0.15, tz: -0.50, sp: 1.4 },
      { r: 1.46, tx: 0.70, tz: -0.15, sp: 0.25 },
      { r: 1.05, tx: -0.60, tz: -0.30, sp: 0.6 },
    ];
    for (const rg of rings) {
      const cx = Math.cos(rg.tx), sx = Math.sin(rg.tx);
      const cz = Math.cos(rg.tz), sz = Math.sin(rg.tz);
      let a0 = rnd() * Math.PI * 2;
      const nSeg = 5 + Math.floor(rnd() * 6);
      for (let sgi = 0; sgi < nSeg; sgi++) {
        const span = 0.15 + rnd() * 0.9;   // fragment arc length
        const gap = 0.12 + rnd() * 0.75;   // gap after fragment
        const rOff = rg.r * (1 + (rnd() - 0.5) * 0.10); // each fragment at its own radius
        const yOff = (rnd() - 0.5) * 0.07;
        const n = Math.max(4, Math.round(span * 210 * density));
        for (let k = 0; k < n; k++) {
          const a = a0 + (k / n) * span;
          let x = Math.cos(a) * rOff * (1 + (rnd() - 0.5) * 0.02);
          let y = yOff + (rnd() - 0.5) * 0.02;
          let z = Math.sin(a) * rOff * (1 + (rnd() - 0.5) * 0.02);
          // tilt X then Z
          let y2 = y * cx - z * sx, z2 = y * sx + z * cx;
          let x3 = x * cz - y2 * sz, y3 = x * sz + y2 * cz;
          push(x3, y3, z2, 1, 0.8 + rnd() * 1.4, k / n, rg.sp, 0, 0);
        }
        a0 += span + gap;
      }
    }
    // 5) Spokes: faint lines + packets
    const nSpokes = Math.round(34 * density);
    for (let i = 0; i < nSpokes; i++) {
      const d = randUnit();
      for (let k = 0; k < 22; k++) { // static faint line
        const rr = 0.12 + (k / 21) * 0.92;
        push(d[0] * rr, d[1] * rr, d[2] * rr, 5, 0.8 + rnd() * 0.8, rnd());
      }
      const nP = 2 + Math.floor(rnd() * 3);
      for (let k = 0; k < nP; k++) {
        push(d[0], d[1], d[2], 3, 1.8 + rnd() * 2.2, rnd());
      }
    }
    // 6) Free dust inside/outside
    for (let i = 0; i < Math.round(2400 * density); i++) {
      const d = randUnit();
      const rr = 0.2 + rnd() * 1.45;
      push(d[0] * rr, d[1] * rr, d[2] * rr, 2, 0.6 + rnd() * 1.4, rnd());
    }
    // 7b) Neuron firings (type 6): quarks shooting arc-to-arc or from inside the orb
    const nFire = Math.round(150 * density);
    for (let i = 0; i < nFire; i++) {
      let a, b;
      if (rnd() < 0.6) { // arc to arc on the shell
        const u = randUnit(), v = randUnit();
        a = [u[0] * 0.99, u[1] * 0.99, u[2] * 0.99];
        b = [v[0] * 0.99, v[1] * 0.99, v[2] * 0.99];
      } else { // from a random interior spot outward
        const u = randUnit(), v = randUnit();
        const r0 = 0.15 + rnd() * 0.4;
        a = [u[0] * r0, u[1] * r0, u[2] * r0];
        b = [v[0], v[1], v[2]];
      }
      const trail = 4 + Math.floor(rnd() * 4);
      const ph = rnd();
      for (let k = 0; k < trail; k++) {
        const sz = k === 0 ? 2.2 + rnd() * 1.6 : Math.max(0.6, 1.5 - k * 0.22);
        push(a[0], a[1], a[2], 6, sz, ph - k * 0.016 + 1, b[0], b[1], b[2]);
      }
    }
    // 7) Core glow
    for (let i = 0; i < Math.round(380 * density); i++) {
      const g = () => (rnd() + rnd() + rnd() - 1.5) * 0.12;
      push(g(), g(), g(), 4, 5 + rnd() * 16, rnd());
    }
    return new Float32Array(pts);
  }

  function hexToTint(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return [1, 1, 1];
    const v = parseInt(m[1], 16);
    return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
  }

  class JarvisHologram extends HTMLElement {
    static get observedAttributes() { return ['state', 'density', 'speed', 'tint']; }

    constructor() {
      super();
      this._state = 'idle';
      this._density = 1;
      this._speed = 1;
      this._tint = [1, 1, 1];
      this._cur = Object.assign({}, STATES.idle);
      this._time = 0; this._rot = 0;
      this._audio = 0; this._micLevel = 0;
      this._extLevel = null; // external amplitude from the live bridge (null = fall back to mic/synthetic)
      this._mouse = { x: 0, y: -2, on: 0, tx: 0, ty: -2, ton: 0 };
      this._tilt = { x: 0, y: 0 };
      this._mic = null;
      this._raf = 0; this._last = 0;
      this._count = 0;
    }

    attributeChangedCallback(name, _o, v) {
      if (name === 'state' && v && STATES[v]) {
        if (this._state !== v) { this._state = v; window.dispatchEvent(new CustomEvent('jarvis-state', { detail: { state: v } })); }
      }
      if (name === 'speed') this._speed = Math.max(0.05, parseFloat(v) || 1);
      if (name === 'tint') this._tint = hexToTint(v);
      if (name === 'density') {
        const d = Math.min(2.5, Math.max(0.3, parseFloat(v) || 1));
        if (d !== this._density) { this._density = d; if (this._gl) this._upload(); }
      }
    }

    connectedCallback() {
      if (this._canvas) return;
      this.style.display = 'block';
      const c = this._canvas = document.createElement('canvas');
      c.style.cssText = 'width:100%;height:100%;display:block;';
      this.appendChild(c);
      const gl = this._gl = c.getContext('webgl2', { alpha: false, antialias: false, powerPreference: 'high-performance' });
      if (!gl) { this.textContent = 'WebGL2 not available'; return; }

      // GPU context-loss recovery. Without this, a driver TDR reset or GPU-process
      // recycle leaves the WebGL context permanently lost -> the HUD goes blank and
      // the rAF loop spins forever, which reads as "Jarvis crashed". preventDefault()
      // is what lets WebView2 fire 'webglcontextrestored' so we can rebuild.
      this._lost = false;
      c.addEventListener('webglcontextlost', (e) => {
        e.preventDefault();
        this._lost = true;
        try { console.error('[jarvis-hologram] WebGL context lost'); } catch (_) {}
      }, false);
      c.addEventListener('webglcontextrestored', () => {
        try {
          this._initGL();
          this._resize();
          this._lost = false;
          console.warn('[jarvis-hologram] WebGL context restored');
        } catch (err) {
          try { console.error('[jarvis-hologram] restore failed', err); } catch (_) {}
        }
      }, false);

      this._initGL();

      // pointer proximity
      this._onMove = (e) => {
        const r = this.getBoundingClientRect();
        this._mouse.tx = ((e.clientX - r.left) / r.width) * 2 - 1;
        this._mouse.ty = -(((e.clientY - r.top) / r.height) * 2 - 1);
        this._mouse.ton = 1;
      };
      this._onLeave = () => { this._mouse.ton = 0; };
      this.addEventListener('pointermove', this._onMove);
      this.addEventListener('pointerleave', this._onLeave);

      this._ro = new ResizeObserver(() => this._resize());
      this._ro.observe(this);
      this._resize();

      // global API
      const self = this;
      window.jarvis = window.jarvis || {};
      window.jarvis.setState = (s) => { if (STATES[s]) self.setAttribute('state', s); };
      window.jarvis.toggleMic = () => self.toggleMic();
      window.jarvis.setLevel = (v) => { self._extLevel = (v == null ? null : Math.max(0, Math.min(1, +v || 0))); };
      Object.defineProperty(window.jarvis, 'state', { get: () => self._state, configurable: true });
      Object.defineProperty(window.jarvis, 'micEnabled', { get: () => !!self._mic, configurable: true });

      this._last = performance.now();
      const loop = (now) => {
        this._raf = requestAnimationFrame(loop);
        if (this._lost) return;                             // GPU context lost -> wait for 'restored'
        if (document.hidden) { this._last = now; return; }  // minimised/hidden -> idle the GPU
        const dt = now - this._last;
        const FRAME = 1000 / 30;
        if (dt < FRAME) return; // lock ~30fps
        this._last += FRAME * Math.floor(dt / FRAME); // advance whole frames (no baseline snap-back)
        this._step(Math.min(dt, 100) / 1000);
        this._draw();
      };
      this._raf = requestAnimationFrame(loop);
    }

    disconnectedCallback() {
      cancelAnimationFrame(this._raf);
      if (this._ro) this._ro.disconnect();
      this.disableMic();
    }

    // (Re)build all GL objects (program, uniforms, VAO/VBO). Called on first init
    // and again after 'webglcontextrestored', when every GL handle is invalidated.
    _initGL() {
      const gl = this._gl;
      const mk = (type, src) => {
        const s = gl.createShader(type);
        gl.shaderSource(s, src); gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
        return s;
      };
      const prog = this._prog = gl.createProgram();
      gl.attachShader(prog, mk(gl.VERTEX_SHADER, VS));
      gl.attachShader(prog, mk(gl.FRAGMENT_SHADER, FS));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
      gl.useProgram(prog);
      this._u = {};
      for (const n of ['uTime', 'uRot', 'uTilt', 'uBreath', 'uAudio', 'uFire', 'uState', 'uMouse', 'uMouseOn', 'uAspect', 'uPx', 'uTint'])
        this._u[n] = gl.getUniformLocation(prog, n);

      this._vao = gl.createVertexArray();
      this._vbo = gl.createBuffer();
      this._upload();

      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE);
      gl.disable(gl.DEPTH_TEST);
    }

    _upload() {
      const gl = this._gl;
      const data = buildGeometry(this._density);
      this._count = data.length / 10;
      gl.bindVertexArray(this._vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, this._vbo);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      const S = 40;
      gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, S, 0);
      gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, S, 12);
      gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 3, gl.FLOAT, false, S, 28);
    }

    _resize() {
      const dpr = Math.min(1.5, window.devicePixelRatio || 1);   // cap fill/overdraw cost (was 2) to shorten GPU frames
      const w = Math.max(2, Math.round(this.clientWidth * dpr));
      const h = Math.max(2, Math.round(this.clientHeight * dpr));
      const c = this._canvas;
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    }

    async toggleMic() {
      if (this._mic) { this.disableMic(); return false; }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const src = ctx.createMediaStreamSource(stream);
        const an = ctx.createAnalyser();
        an.fftSize = 512;
        src.connect(an);
        this._mic = { stream, ctx, an, buf: new Float32Array(an.fftSize) };
        window.dispatchEvent(new CustomEvent('jarvis-mic', { detail: { enabled: true } }));
        return true;
      } catch (e) {
        window.dispatchEvent(new CustomEvent('jarvis-mic', { detail: { enabled: false, error: String(e) } }));
        return false;
      }
    }

    disableMic() {
      if (!this._mic) return;
      try { this._mic.stream.getTracks().forEach(t => t.stop()); this._mic.ctx.close(); } catch (e) {}
      this._mic = null;
      window.dispatchEvent(new CustomEvent('jarvis-mic', { detail: { enabled: false } }));
    }

    _step(dt) {
      const tgt = STATES[this._state] || STATES.idle;
      const k = 1 - Math.pow(0.92, dt * 30);
      const c = this._cur;
      for (const key of ['bright', 'jitter', 'packet', 'swirl', 'rot', 'ag', 'fire'])
        c[key] += (tgt[key] - c[key]) * k;

      this._time += dt * this._speed;
      this._rot += dt * c.rot * this._speed * Math.PI * 2 * 0.5;

      // audio level: live bridge amplitude wins, else mic RMS, else synthetic speech envelope
      let lvl = 0;
      if (this._extLevel != null) {
        lvl = this._extLevel;
      } else if (this._mic) {
        this._mic.an.getFloatTimeDomainData(this._mic.buf);
        let sum = 0;
        const b = this._mic.buf;
        for (let i = 0; i < b.length; i += 4) sum += b[i] * b[i];
        lvl = Math.min(1, Math.sqrt(sum / (b.length / 4)) * 5);
      } else if (this._state === 'speaking') {
        // synthetic speech envelope
        const t = this._time;
        lvl = Math.max(0, Math.sin(t * 2.1) * Math.sin(t * 3.7)) * 0.6 + Math.max(0, Math.sin(t * 9.3 + Math.sin(t * 1.3) * 4)) * 0.35;
      }
      this._micLevel += (lvl - this._micLevel) * 0.35;
      this._audio = this._micLevel * c.ag;

      // mouse smoothing + parallax tilt
      const m = this._mouse;
      m.x += (m.tx - m.x) * 0.2;
      m.y += (m.ty - m.y) * 0.2;
      m.on += (m.ton - m.on) * 0.12;
      this._tilt.x += (m.x * 0.22 * m.on - this._tilt.x) * 0.06;
      this._tilt.y += (-m.y * 0.18 * m.on - this._tilt.y) * 0.06;
    }

    _draw() {
      const gl = this._gl;
      if (!gl || gl.isContextLost()) return;
      this._resize();
      const c = this._canvas;
      gl.viewport(0, 0, c.width, c.height);
      gl.clearColor(0.012, 0.008, 0.005, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(this._prog);
      gl.bindVertexArray(this._vao);
      const u = this._u, cur = this._cur;
      const breath = 1 + 0.028 * Math.sin(this._time * 0.55) + this._audio * 0.07;
      gl.uniform1f(u.uTime, this._time);
      gl.uniform1f(u.uRot, this._rot);
      gl.uniform2f(u.uTilt, this._tilt.x, this._tilt.y);
      gl.uniform1f(u.uBreath, breath);
      gl.uniform1f(u.uAudio, this._audio);
      gl.uniform1f(u.uFire, cur.fire || 0);
      gl.uniform4f(u.uState, cur.bright, cur.jitter, cur.packet, cur.swirl);
      gl.uniform2f(u.uMouse, this._mouse.x, this._mouse.y);
      gl.uniform1f(u.uMouseOn, this._mouse.on);
      gl.uniform1f(u.uAspect, c.width / c.height);
      gl.uniform1f(u.uPx, c.height / 760);
      gl.uniform3f(u.uTint, this._tint[0], this._tint[1], this._tint[2]);
      gl.drawArrays(gl.POINTS, 0, this._count);
    }
  }

  if (!customElements.get('jarvis-hologram')) customElements.define('jarvis-hologram', JarvisHologram);
})();
