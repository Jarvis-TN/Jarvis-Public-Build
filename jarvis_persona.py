"""Jarvis self-improvement store - the substrate for Jarvis refining his own
persona over time.

Jarvis periodically critiques his own recent performance against the J.A.R.V.I.S.
ideal and proposes concrete refinements. Crucially these are SUGGESTIONS, not
self-applied changes: a proposed persona tweak only takes effect once the USER
approves it, at which point its guidance line is appended to a persona
"addendum" that rides on top of the (fixed, in-code) base system prompt. This
human-in-the-loop boundary is deliberate - it prevents persona drift and stops
untrusted ingested content (RAG/web/email) from talking Jarvis into rewriting
himself.

Backed by a small JSON file (memory/persona.json); no model, no network.
"""

import os
import json
import threading
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(APP_DIR, "memory")
PERSONA_PATH = os.path.join(MEMORY_DIR, "persona.json")

VALID_TYPES = ("persona", "capability", "config")


def _now():
    return datetime.now().isoformat(timespec="seconds")


class PersonaStore:
    def __init__(self, path=PERSONA_PATH):
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
        d.setdefault("addendum", [])     # approved persona-refinement lines
        d.setdefault("pending", [])      # [{id,type,summary,change,rationale,created}]
        d.setdefault("history", [])      # applied/dismissed suggestions
        d.setdefault("state", {})        # last_introspect_at, last_turns, announced, next_id
        d["state"].setdefault("next_id", 1)
        return d

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---- persona addendum (injected into the system prompt) ------------- #
    def addendum_lines(self):
        return list(self._data.get("addendum", []))

    def addendum_text(self):
        lines = self.addendum_lines()
        if not lines:
            return ""
        return ("\n\nRefinements to your manner that you have adopted over time "
                "(honor these):\n" + "\n".join("- " + ln for ln in lines))

    # ---- suggestions ---------------------------------------------------- #
    def pending(self):
        return list(self._data.get("pending", []))

    def add_suggestions(self, items):
        """Add proposed improvements. `items` = list of dicts with at least
        'summary'; optional 'type'/'change'/'rationale'. De-duplicates against
        existing pending + already-adopted addendum lines. Returns count added."""
        added = 0
        with self._lock:
            existing_sum = {s["summary"].strip().lower() for s in self._data["pending"]}
            existing_change = {c.strip().lower() for c in self._data["addendum"]}
            for it in items or []:
                if not isinstance(it, dict):
                    continue
                summary = (it.get("summary") or "").strip()
                if not summary or summary.lower() in existing_sum:
                    continue
                change = (it.get("change") or "").strip()
                if change and change.lower() in existing_change:
                    continue  # already adopted
                typ = it.get("type", "persona")
                if typ not in VALID_TYPES:
                    typ = "persona"
                sid = self._data["state"]["next_id"]
                self._data["state"]["next_id"] = sid + 1
                self._data["pending"].append({
                    "id": sid, "type": typ, "summary": summary,
                    "change": change, "rationale": (it.get("rationale") or "").strip(),
                    "created": _now(),
                })
                existing_sum.add(summary.lower())
                added += 1
            if added:
                self._data["state"]["announced"] = False
                self._save()
        return added

    def _take(self, sid):
        for i, s in enumerate(self._data["pending"]):
            if s["id"] == sid:
                return self._data["pending"].pop(i)
        return None

    def apply(self, sid):
        """Approve a suggestion. For type='persona' its guidance line is appended
        to the live addendum. Returns (ok, suggestion|message)."""
        with self._lock:
            s = self._take(sid)
            if s is None:
                return False, f"No pending suggestion with id {sid}."
            if s["type"] == "persona" and s.get("change"):
                if s["change"].strip().lower() not in (c.lower() for c in self._data["addendum"]):
                    self._data["addendum"].append(s["change"].strip())
                s["_effect"] = "added to persona"
            else:
                # capability/config: can't self-build, but keep a record (a wishlist)
                s["_effect"] = "logged for the developer"
            s["action"] = "applied"
            s["resolved_at"] = _now()
            self._data["history"].append(s)
            self._save()
            return True, s

    def dismiss(self, sid):
        with self._lock:
            s = self._take(sid)
            if s is None:
                return False, f"No pending suggestion with id {sid}."
            s["action"] = "dismissed"
            s["resolved_at"] = _now()
            self._data["history"].append(s)
            self._save()
            return True, s

    def revert(self, line_substr):
        """Remove an adopted addendum line (undo a persona refinement)."""
        with self._lock:
            sub = line_substr.strip().lower()
            before = len(self._data["addendum"])
            self._data["addendum"] = [c for c in self._data["addendum"]
                                      if sub not in c.lower()]
            removed = before - len(self._data["addendum"])
            if removed:
                self._save()
            return removed

    # ---- introspection bookkeeping -------------------------------------- #
    def get_state(self, key, default=None):
        return self._data.get("state", {}).get(key, default)

    def set_state(self, **kw):
        with self._lock:
            self._data["state"].update(kw)
            self._save()

    def has_unannounced(self):
        return bool(self._data["pending"]) and not self._data["state"].get("announced", False)
