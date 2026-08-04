"""Jarvis autonomy layer - the substrate for proactive, guard-railed action.

This module is the cold, testable core of Jarvis's autonomy. It deliberately
holds NO voice, network, or model code: just data models, a pure decision rule,
two small JSON-backed stores, and the approval-gate helpers. The engine
(jarvis.py) wires these into the live attention broker, voice, and turn flow.

Pieces:
  * CandidateAction  - a proactive idea a source proposes ("warn low battery",
                       "surface the 9am brief", "follow up on the visa loop").
  * decide()         - the PRIME DIRECTIVE as a pure function: do the useful,
                       low-impact, reversible thing automatically; ASK first for
                       anything consequential, irreversible, money-related, or
                       low-confidence. Default to the safe choice on ambiguity.
  * OpenLoopStore    - standing goals & multi-step "open loops" that persist
                       across days/sessions, with follow-up scheduling.
  * ActionLog        - an audit trail of every autonomous action (timestamp,
                       trigger, confidence, outcome) plus an undo path.
  * ApprovalGate helpers - requires_approval() / interpret_confirmation():
                       classify what must be confirmed, and read a spoken
                       "yes"/"no" safely (ambiguous -> treated as neither).

Everything here is local, deterministic, and import-light so the test-suite can
exercise the decision rule and the gate without touching the live assistant.
"""

import os
import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Optional, Callable, List, Dict, Any

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
OPEN_LOOPS_PATH = os.path.join(MEMORY_DIR, "open_loops.json")
ACTION_LOG_PATH = os.path.join(MEMORY_DIR, "action_log.json")


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
#  Candidate actions + the decision rule
# --------------------------------------------------------------------------- #
IMPACTS = ("low", "medium", "high")


@dataclass
class CandidateAction:
    """A proactive idea proposed by a signal source, scored so the decision rule
    can choose to act, ask, or skip.

    confidence  0..1   how sure we are this is wanted right now.
    impact      low|medium|high   how big the consequence is if we're wrong.
    reversible  bool   can it be undone, or is it merely read-only/informational?
    consequential bool sends/deletes/posts/spends money/affects other people.
                       ALWAYS routed through the approval gate, regardless of
                       confidence - this is a hard guardrail, not a score.
    speak       text spoken if this is a simple announcement.
    fulfill     callable that performs the action (used instead of/after speak).
    The remaining fields hand the action to the engine's attention broker.
    """
    kind: str
    summary: str
    confidence: float = 0.0
    impact: str = "low"
    reversible: bool = True
    consequential: bool = False
    speak: Optional[str] = None
    fulfill: Optional[Callable[[], Any]] = None
    category: str = ""
    priority: int = 40
    key: Optional[str] = None
    ttl: float = 180.0
    # an optional human description of how to undo the action, recorded to the
    # action log so the user can later say "undo that".
    undo: Optional[str] = None

    def __post_init__(self):
        self.confidence = _clamp01(self.confidence)
        if self.impact not in IMPACTS:
            self.impact = "high"          # unknown severity -> treat as worst case
        if not self.category:
            self.category = self.kind
        if self.key is None:
            self.key = self.kind


def _clamp01(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if x < 0 else 1.0 if x > 1 else x


@dataclass
class Decision:
    action: str                # "act" | "ask" | "skip"
    reason: str = ""
    candidate: Optional[CandidateAction] = None

    @property
    def act(self):
        return self.action == "act"

    @property
    def ask(self):
        return self.action == "ask"

    @property
    def skip(self):
        return self.action == "skip"


def decide(cand: CandidateAction, confidence_threshold: float = 0.7,
           auto_impacts=("low",)) -> Decision:
    """The core act/ask/skip rule. Pure and side-effect free.

    PRIME DIRECTIVE, encoded:
      1. Consequential / irreversible / money actions ALWAYS ask first. This is a
         hard gate that confidence can never override.
      2. Below the confidence threshold -> ask (when in doubt, ask, don't act).
      3. High confidence AND low-impact AND reversible -> just do it and report.
      4. Anything else (e.g. confident but medium/high impact) -> ask.

    `auto_impacts` is the set of impact levels eligible for autonomous action;
    defaults to low-impact only. Widening it is how a power user opts into more
    aggressive autonomy.
    """
    if cand.consequential or not cand.reversible:
        return Decision("ask", "consequential or irreversible - requires confirmation", cand)
    if cand.confidence < confidence_threshold:
        return Decision("ask", f"confidence {cand.confidence:.2f} below threshold "
                               f"{confidence_threshold:.2f}", cand)
    if cand.impact in auto_impacts:
        return Decision("act", "high-confidence, low-impact, reversible - acting", cand)
    return Decision("ask", f"impact '{cand.impact}' not auto-eligible - confirming first", cand)


# --------------------------------------------------------------------------- #
#  Approval gate helpers
# --------------------------------------------------------------------------- #
# Words that read as a clear yes / no when the user replies to a confirmation
# prompt. Anything not clearly affirmative is treated as NOT confirmed - the
# safe default - so an ambiguous reply never triggers a consequential action.
_AFFIRM = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "do it", "go ahead",
           "go for it", "please do", "affirmative", "confirm", "confirmed", "proceed",
           "do that", "yes please", "absolutely", "definitely", "make it so"}
_DENY = {"no", "nope", "nah", "don't", "do not", "cancel", "stop", "negative",
         "abort", "never mind", "nevermind", "leave it", "not now", "skip it",
         "forget it", "no thanks", "no thank you"}


def interpret_confirmation(text: str) -> str:
    """Read a spoken reply to a yes/no confirmation prompt.

    Returns "confirm", "cancel", or "unclear". Conservative on purpose: the
    phrase must clearly affirm to count as a confirmation; ANY clear denial, or
    a reply that's neither, yields cancel/unclear so we never act on a vague
    "...maybe". The caller treats unclear as "do not proceed".
    """
    t = (text or "").strip().lower()
    if not t:
        return "unclear"
    # normalize punctuation to spaces (keep apostrophes for "don't") so word/
    # phrase matching is on clean token boundaries, then pad for boundary tests.
    t_clean = "".join(ch if (ch.isalnum() or ch == "'") else " " for ch in t)
    padded = " " + " ".join(t_clean.split()) + " "
    # explicit denials win over affirmations ("no, go ahead" is contradictory ->
    # treat as cancel, the safe choice).
    for d in _DENY:
        if (" " + d + " ") in padded:
            return "cancel"
    for a in _AFFIRM:
        if (" " + a + " ") in padded:
            return "confirm"
    return "unclear"


def requires_approval(cand: CandidateAction) -> bool:
    """A candidate must pass the approval gate iff it is consequential or
    irreversible. (Low-confidence is handled by decide()->ask, not here.)"""
    return bool(cand.consequential) or not bool(cand.reversible)


# --------------------------------------------------------------------------- #
#  Standing goals & open loops
# --------------------------------------------------------------------------- #
LOOP_STATUSES = ("open", "waiting", "done", "dropped")


class OpenLoopStore:
    """Persistent store of the user's standing goals and multi-step tasks.

    Each "loop" tracks a concrete next step, who owns it, an optional due/check-in
    date, a status, and a running history. Jarvis uses due_for_followup() to
    decide which loops to proactively nudge, advances/closes them as they move,
    and injects the open ones into the system prompt so he stays loop-aware.

    JSON-backed (memory/open_loops.json); no model, no network.
    """

    def __init__(self, path=OPEN_LOOPS_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                d = {}
        else:
            d = {}
        d.setdefault("loops", [])
        d.setdefault("next_id", 1)
        return d

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---- writes --------------------------------------------------------- #
    def add(self, title, next_step="", owner="user", due="", note=""):
        """Open a new loop. owner is 'user' or 'jarvis'; due is 'YYYY-MM-DD' or
        '' for no scheduled check-in. Returns the created loop dict."""
        title = (title or "").strip()
        if not title:
            raise ValueError("an open loop needs a title")
        owner = owner if owner in ("user", "jarvis") else "user"
        with self._lock:
            lid = self._data["next_id"]
            self._data["next_id"] = lid + 1
            loop = {
                "id": lid,
                "title": title,
                "next_step": (next_step or "").strip(),
                "owner": owner,
                "status": "open",
                "due": _norm_due(due),
                "created": _now_iso(),
                "updated": _now_iso(),
                "last_nudged": "",
                "history": [],
            }
            if note:
                loop["history"].append({"ts": _now_iso(), "note": note.strip()})
            self._data["loops"].append(loop)
            self._save()
            return dict(loop)

    def get(self, lid):
        for lp in self._data["loops"]:
            if lp["id"] == int(lid):
                return lp
        return None

    def update(self, lid, **fields):
        """Patch arbitrary fields on a loop (status/next_step/due/owner/title).
        Returns the updated loop or None. Appends nothing to history - use
        advance()/close() for that."""
        allowed = {"title", "next_step", "owner", "due", "status"}
        with self._lock:
            lp = self.get(lid)
            if lp is None:
                return None
            for k, v in fields.items():
                if k not in allowed:
                    continue
                if k == "status" and v not in LOOP_STATUSES:
                    continue
                if k == "due":
                    v = _norm_due(v)
                if k == "owner" and v not in ("user", "jarvis"):
                    continue
                lp[k] = v.strip() if isinstance(v, str) else v
            lp["updated"] = _now_iso()
            self._save()
            return dict(lp)

    def advance(self, lid, note, next_step=None):
        """Record progress on a loop: append a history note and optionally set the
        new next step. Keeps the loop open."""
        with self._lock:
            lp = self.get(lid)
            if lp is None:
                return None
            if note:
                lp["history"].append({"ts": _now_iso(), "note": note.strip()})
            if next_step is not None:
                lp["next_step"] = next_step.strip()
            if lp["status"] == "waiting":
                lp["status"] = "open"
            lp["updated"] = _now_iso()
            self._save()
            return dict(lp)

    def mark_nudged(self, lid, when=None):
        with self._lock:
            lp = self.get(lid)
            if lp is None:
                return None
            lp["last_nudged"] = when or _now_iso()
            lp["updated"] = _now_iso()
            self._save()
            return dict(lp)

    def close(self, lid, note="", status="done"):
        """Close a loop as satisfied ('done') or abandoned ('dropped')."""
        status = status if status in ("done", "dropped") else "done"
        with self._lock:
            lp = self.get(lid)
            if lp is None:
                return None
            lp["status"] = status
            if note:
                lp["history"].append({"ts": _now_iso(), "note": note.strip()})
            lp["updated"] = _now_iso()
            self._save()
            return dict(lp)

    # ---- reads ---------------------------------------------------------- #
    def all(self):
        return [dict(lp) for lp in self._data["loops"]]

    def list_open(self):
        return [dict(lp) for lp in self._data["loops"]
                if lp["status"] in ("open", "waiting")]

    def due_for_followup(self, now=None, min_nudge_hours=20.0):
        """Open loops worth proactively following up on right now.

        A loop qualifies if it is open/waiting AND either its due date is today
        or past, OR it has no due date but has gone untouched (used for gentle
        "this seems stalled" nudges only when it has a next step). Throttled:
        never nudge the same loop more often than `min_nudge_hours`. Returns
        most-overdue first.
        """
        now = now or datetime.now()
        today = now.date()
        out = []
        for lp in self._data["loops"]:
            if lp["status"] not in ("open", "waiting"):
                continue
            # throttle repeat nudges
            if lp.get("last_nudged"):
                try:
                    last = datetime.fromisoformat(lp["last_nudged"])
                    if (now - last).total_seconds() / 3600.0 < min_nudge_hours:
                        continue
                except Exception:
                    pass
            due = lp.get("due") or ""
            overdue_by = None
            if due:
                try:
                    d = datetime.fromisoformat(due).date()
                    if d <= today:
                        overdue_by = (today - d).days
                except Exception:
                    pass
            if overdue_by is not None:
                out.append((overdue_by, dict(lp)))
        out.sort(key=lambda t: -t[0])
        return [lp for _, lp in out]

    def wipe(self):
        with self._lock:
            self._data = {"loops": [], "next_id": 1}
            self._save()


def _norm_due(due):
    """Normalize a due value to 'YYYY-MM-DD' or '' (best-effort, never raises)."""
    if not due:
        return ""
    s = str(due).strip()
    if not s:
        return ""
    try:
        # accept full ISO datetimes too, keep just the date
        return datetime.fromisoformat(s).date().isoformat()
    except Exception:
        pass
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except Exception:
        return ""   # unparseable -> treat as "no scheduled check-in"


# --------------------------------------------------------------------------- #
#  Action log (audit trail + undo)
# --------------------------------------------------------------------------- #
class ActionLog:
    """Append-only-ish audit trail of autonomous actions.

    Every action Jarvis takes on his own initiative is recorded with a timestamp,
    what triggered it, the confidence behind it, whether it was auto-done or
    user-approved, and the outcome. Reversible actions carry an `undo` hint so
    the user can say "undo that". JSON-backed (memory/action_log.json).
    """

    def __init__(self, path=ACTION_LOG_PATH, cap=500):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.cap = cap
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                d = {}
        else:
            d = {}
        d.setdefault("entries", [])
        d.setdefault("next_id", 1)
        return d

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def record(self, action, trigger="", confidence=None, decision="act",
               impact="low", reversible=True, outcome="done", undo=None):
        """Append an action record. Returns the stored entry dict."""
        with self._lock:
            eid = self._data["next_id"]
            self._data["next_id"] = eid + 1
            entry = {
                "id": eid,
                "ts": _now_iso(),
                "action": (action or "").strip(),
                "trigger": (trigger or "").strip(),
                "confidence": (None if confidence is None else round(_clamp01(confidence), 3)),
                "decision": decision,
                "impact": impact if impact in IMPACTS else "high",
                "reversible": bool(reversible),
                "outcome": (outcome or "").strip(),
                "undo": (undo or None),
                "undone": False,
            }
            self._data["entries"].append(entry)
            # keep the log bounded
            if len(self._data["entries"]) > self.cap:
                self._data["entries"] = self._data["entries"][-self.cap:]
            self._save()
            return dict(entry)

    def set_outcome(self, eid, outcome):
        with self._lock:
            for e in self._data["entries"]:
                if e["id"] == int(eid):
                    e["outcome"] = (outcome or "").strip()
                    self._save()
                    return dict(e)
        return None

    def recent(self, n=10):
        return [dict(e) for e in self._data["entries"][-n:]][::-1]

    def last_undoable(self):
        """The most recent reversible, not-yet-undone, successful action - the
        target of a bare 'undo that'."""
        for e in reversed(self._data["entries"]):
            if e["reversible"] and not e["undone"] and e.get("undo") \
                    and str(e.get("outcome", "")).lower().startswith("done"):
                return dict(e)
        return None

    def mark_undone(self, eid):
        with self._lock:
            for e in self._data["entries"]:
                if e["id"] == int(eid):
                    e["undone"] = True
                    self._save()
                    return dict(e)
        return None

    def wipe(self):
        with self._lock:
            self._data = {"entries": [], "next_id": 1}
            self._save()
