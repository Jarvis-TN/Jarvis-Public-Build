"""Jarvis affect sensor - read the user's emotional/energetic state from the
prosody of the utterance they just spoke, so Jarvis can match their tone and
pacing (be brief when they're rushed, gentler when they're flat).

Fully local, numpy-only, no model or network. Works off the SAME captured audio
array that voice-ID already receives, plus the transcript for a speech-rate
estimate. Deliberately conservative: absolute pitch varies per person, so the
label leans on energy + speaking rate + pause structure (robust across speakers)
and uses pitch only as a light tie-breaker. Returns a dict the engine injects
into the system prompt and uses to nudge the TTS voice, or None if unusable.

  analyze(audio_f32_mono, text, sr=16000) -> {
     label, prompt, verbosity, busy, tts:{stability_delta,style_delta,speed_mult},
     features:{energy, rate_wps, pause_frac, f0}
  }
"""

import numpy as np

SR = 16000
_FRAME = 512          # ~32ms at 16k
_SIL = 0.02           # per-frame RMS below this ~ silence


def _frame_rms(audio):
    n = len(audio) // _FRAME
    if n <= 0:
        return np.array([float(np.sqrt(np.mean(audio ** 2)))]) if len(audio) else np.array([0.0])
    trimmed = audio[:n * _FRAME].reshape(n, _FRAME)
    return np.sqrt(np.mean(trimmed ** 2, axis=1) + 1e-12)


def _estimate_f0(audio, sr):
    """Rough fundamental frequency (Hz) via autocorrelation over the loudest
    ~0.5s voiced window. Returns 0.0 if it can't find a confident pitch."""
    if len(audio) < sr // 4:
        return 0.0
    rms = _frame_rms(audio)
    if not len(rms):
        return 0.0
    peak = int(np.argmax(rms)) * _FRAME
    win = audio[max(0, peak - sr // 8): peak + int(sr * 0.375)]
    if len(win) < sr // 20:
        return 0.0
    win = win - float(np.mean(win))
    ac = np.correlate(win, win, mode="full")[len(win) - 1:]
    if ac[0] <= 0:
        return 0.0
    lo, hi = sr // 320, sr // 80          # 80-320 Hz search band
    seg = ac[lo:hi]
    if not len(seg):
        return 0.0
    lag = lo + int(np.argmax(seg))
    if ac[lag] < 0.3 * ac[0]:             # weak periodicity -> unvoiced/noise
        return 0.0
    return float(sr) / lag


def analyze(audio, text, sr=SR):
    try:
        audio = np.asarray(audio, dtype=np.float32).ravel()
        if len(audio) < sr // 5:          # under ~0.2s: nothing reliable
            return None
        total_dur = len(audio) / float(sr)
        rms = _frame_rms(audio)
        if not len(rms):
            return None
        peak = float(np.max(rms))
        if peak < 1e-3:                   # essentially silent
            return None
        # ADAPTIVE voiced detection - relative to THIS clip's own levels, so a
        # quiet recording (low mic gain) isn't misread as one long pause. The old
        # absolute 0.02 threshold inflated the speaking rate on soft audio.
        noise = float(np.percentile(rms, 20))
        thr = noise + 0.15 * (peak - noise)
        voiced = rms > thr
        idx = np.where(voiced)[0]
        if not len(idx):
            return None
        first, last = int(idx[0]), int(idx[-1])
        frame_dur = _FRAME / float(sr)
        speech_span = max(0.3, (last - first + 1) * frame_dur)   # trimmed spoken span
        inner = voiced[first:last + 1]
        pause_frac = float(np.mean(~inner)) if len(inner) else 0.0
        words = len([w for w in (text or "").split() if any(c.isalpha() for c in w)])
        rate_wps = (words / speech_span) if words else 0.0
        energy = float(np.mean(rms[voiced]))   # kept for the features log (level-dependent)
        f0 = _estimate_f0(audio, sr)

        # --- classify on the LEVEL-INVARIANT cue: speaking rate over the spoken
        # span. Absolute loudness/pitch vary too much with mic gain to gate on from
        # a single utterance, so they're logged but not used to decide. ---
        label, prompt, verbosity, busy = "neutral", "", "normal", False
        tts = {"stability_delta": 0.0, "style_delta": 0.0, "speed_mult": 1.0}

        if words >= 3 and rate_wps >= 4.5:
            label = "rushed/urgent"
            prompt = ("The user sounds rushed or urgent. Lead with the answer, be brief, and "
                      "offer detail only if they ask.")
            verbosity, busy = "terse", True
            tts = {"stability_delta": +0.10, "style_delta": -0.05, "speed_mult": 1.03}
        elif words >= 3 and rate_wps >= 3.7:
            label = "brisk"
            prompt = "The user is speaking briskly. Keep the reply concise and to the point."
            verbosity = "terse"          # concise, but not busy enough to suppress proactivity
            tts = {"stability_delta": +0.05, "style_delta": 0.0, "speed_mult": 1.02}
        elif words >= 4 and rate_wps <= 1.9:
            label = "measured"
            prompt = ("The user is speaking slowly and deliberately. Match their calm, unhurried "
                      "pace; don't rush or overload them.")
            tts = {"stability_delta": +0.05, "style_delta": +0.03, "speed_mult": 0.98}

        return {"label": label, "prompt": prompt, "verbosity": verbosity, "busy": busy,
                "tts": tts,
                "features": {"energy": round(energy, 4), "rate_wps": round(rate_wps, 2),
                             "pause_frac": round(pause_frac, 3), "speech_span": round(speech_span, 2),
                             "f0": round(f0, 1)}}
    except Exception:
        return None
