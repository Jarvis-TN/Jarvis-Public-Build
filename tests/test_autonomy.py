"""Tests for the Jarvis autonomy layer.

Covers the two things that most need to be provably correct:
  * the DECISION RULE - act vs ask vs skip, including the hard guardrails that
    force consequential / irreversible / low-confidence actions to ask first;
  * the APPROVAL GATE - both the pure spoken-yes/no parsing and the live engine
    wiring (a pending approval consumes the next turn; a clear 'yes' fires the
    action and logs it; ambiguity never acts; a stale approval lapses).

Plus the open-loop store's follow-up scheduling and the action log.

Runs standalone (`python tests/test_autonomy.py`) or under pytest. The engine
tests build a JarvisEngine via __new__ so we exercise the real methods without
booting audio/models.
"""

import os
import sys
import time
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis_autonomy as A


# --------------------------------------------------------------------------- #
#  Decision rule
# --------------------------------------------------------------------------- #
def test_decision_rule_acts_on_confident_low_impact_reversible():
    c = A.CandidateAction("brief", "morning briefing", confidence=0.9,
                          impact="low", reversible=True)
    d = A.decide(c, confidence_threshold=0.7)
    assert d.act, d.reason


def test_decision_rule_asks_below_threshold():
    c = A.CandidateAction("x", "maybe useful", confidence=0.4, impact="low")
    assert A.decide(c, 0.7).ask


def test_decision_rule_consequential_always_asks_even_at_full_confidence():
    c = A.CandidateAction("buy", "order more beans", confidence=1.0, impact="low",
                          reversible=True, consequential=True)
    d = A.decide(c, 0.7)
    assert d.ask and "consequential" in d.reason


def test_decision_rule_irreversible_always_asks():
    c = A.CandidateAction("del", "delete the file", confidence=1.0, impact="low",
                          reversible=False)
    assert A.decide(c, 0.7).ask


def test_decision_rule_medium_impact_asks_by_default():
    c = A.CandidateAction("restart", "restart the service", confidence=0.99,
                          impact="medium", reversible=True)
    assert A.decide(c, 0.7).ask


def test_decision_rule_medium_impact_acts_when_opted_in():
    c = A.CandidateAction("restart", "restart the service", confidence=0.99,
                          impact="medium", reversible=True)
    assert A.decide(c, 0.7, auto_impacts=("low", "medium")).act


def test_unknown_impact_is_treated_as_worst_case():
    c = A.CandidateAction("weird", "???", confidence=1.0, impact="catastrophic")
    assert c.impact == "high"
    assert A.decide(c, 0.7).ask


def test_confidence_is_clamped():
    assert A.CandidateAction("a", "a", confidence=5).confidence == 1.0
    assert A.CandidateAction("a", "a", confidence=-3).confidence == 0.0


# --------------------------------------------------------------------------- #
#  Approval-gate parsing
# --------------------------------------------------------------------------- #
def test_confirmation_parsing():
    confirm = ["yes", "yes please", "go ahead", "sure, do it", "okay", "make it so"]
    cancel = ["no", "no thanks", "cancel that", "stop", "never mind", "don't"]
    unclear = ["what time is it", "hmm maybe later", "", "tell me more"]
    for t in confirm:
        assert A.interpret_confirmation(t) == "confirm", t
    for t in cancel:
        assert A.interpret_confirmation(t) == "cancel", t
    for t in unclear:
        assert A.interpret_confirmation(t) == "unclear", t


def test_contradictory_reply_defaults_to_cancel():
    # "no, go ahead" is contradictory -> safe choice is cancel
    assert A.interpret_confirmation("no, go ahead") == "cancel"


def test_requires_approval():
    assert A.requires_approval(A.CandidateAction("a", "a", consequential=True))
    assert A.requires_approval(A.CandidateAction("a", "a", reversible=False))
    assert not A.requires_approval(A.CandidateAction("a", "a", reversible=True))


# --------------------------------------------------------------------------- #
#  Open-loop store
# --------------------------------------------------------------------------- #
def _tmp_loops():
    d = tempfile.mkdtemp()
    return A.OpenLoopStore(os.path.join(d, "loops.json"))


def test_open_loop_lifecycle():
    ol = _tmp_loops()
    lp = ol.add("Renew passport", next_step="book appointment", due="2026-06-10")
    assert lp["status"] == "open" and lp["due"] == "2026-06-10"
    ol.advance(lp["id"], "called consulate", next_step="gather documents")
    assert ol.get(lp["id"])["next_step"] == "gather documents"
    ol.close(lp["id"], "received it")
    assert ol.get(lp["id"])["status"] == "done"
    assert ol.list_open() == []


def test_open_loop_followup_due_and_throttle():
    ol = _tmp_loops()
    overdue = ol.add("Overdue thing", due="2026-06-01")
    ol.add("Future thing", due="2030-01-01")
    ol.add("No-date thing")
    now = datetime(2026, 6, 13)
    due = ol.due_for_followup(now=now)
    assert [d["title"] for d in due] == ["Overdue thing"]   # only the past-due one
    # once nudged, it's throttled out of the due list
    ol.mark_nudged(overdue["id"], when=now.isoformat())
    assert ol.due_for_followup(now=now, min_nudge_hours=20) == []
    # ...but eligible again after the throttle window
    later = (now + timedelta(hours=21)).isoformat()
    ol.get(overdue["id"])["last_nudged"] = ol.get(overdue["id"])["last_nudged"]
    assert any(d["title"] == "Overdue thing"
               for d in ol.due_for_followup(now=now + timedelta(hours=21)))


def test_bad_due_date_is_neutralized():
    ol = _tmp_loops()
    lp = ol.add("Loose goal", due="whenever")
    assert lp["due"] == ""   # unparseable -> no scheduled check-in, not a crash


# --------------------------------------------------------------------------- #
#  Action log
# --------------------------------------------------------------------------- #
def test_action_log_records_and_undo():
    d = tempfile.mkdtemp()
    al = A.ActionLog(os.path.join(d, "log.json"))
    al.record("Surfaced morning brief", trigger="routine", confidence=0.9)
    e = al.record("Created note foo.txt", trigger="user", confidence=0.8,
                  undo="delete C:/tmp/foo.txt")
    assert al.last_undoable()["action"] == "Created note foo.txt"
    al.mark_undone(e["id"])
    assert al.last_undoable() is None          # nothing left to undo
    assert len(al.recent()) == 2
    # an announcement with no undo path is never the undo target
    al.record("Said hello", undo=None)
    assert al.last_undoable() is None


# --------------------------------------------------------------------------- #
#  Engine wiring (real methods, no audio/model boot)
# --------------------------------------------------------------------------- #
def _fake_engine():
    """A JarvisEngine with only the attributes the autonomy methods touch,
    plus an immediate-fire stub for the attention broker so we can observe the
    act/ask effects synchronously."""
    import jarvis
    eng = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    eng.cfg = dict(jarvis.DEFAULT_CONFIG)
    d = tempfile.mkdtemp()
    eng.actionlog = A.ActionLog(os.path.join(d, "log.json"))
    eng.loops = A.OpenLoopStore(os.path.join(d, "loops.json"))
    eng._pending_approval = None
    eng.spoken = []
    eng.transcript_cb = lambda *a, **k: None
    eng.announce = lambda text: eng.spoken.append(text)
    # fire proposed interruptions immediately so tests are synchronous
    eng._propose_interruption = lambda **kw: (kw.get("fulfill") and kw["fulfill"]())
    return eng


def test_engine_acts_on_low_impact_candidate():
    eng = _fake_engine()
    fired = {"n": 0}
    cand = A.CandidateAction("brief", "give the morning brief", confidence=0.9,
                             impact="low", reversible=True, speak="Good morning, sir.",
                             fulfill=lambda: fired.__setitem__("n", fired["n"] + 1))
    d = eng._submit_candidate(cand)
    assert d.act
    assert "Good morning, sir." in eng.spoken     # it spoke
    assert fired["n"] == 1                          # it ran the action
    assert eng.actionlog.recent()[0]["decision"] == "act"   # and logged it


def test_engine_gates_consequential_then_confirm_fires_and_logs():
    eng = _fake_engine()
    sent = {"n": 0}
    cand = A.CandidateAction("email", "send the follow-up email", confidence=1.0,
                             impact="high", reversible=False, consequential=True,
                             speak="Shall I send the follow-up email?",
                             fulfill=lambda: sent.__setitem__("n", sent["n"] + 1))
    d = eng._submit_candidate(cand)
    assert d.ask
    assert eng._pending_approval is not None        # armed, waiting for yes/no
    assert sent["n"] == 0                            # NOT sent yet
    # user says yes on the next turn
    consumed = eng._resolve_pending_approval("yes, go ahead")
    assert consumed                                  # the turn was the answer
    assert sent["n"] == 1                            # now it fired
    assert eng._pending_approval is None
    assert eng.actionlog.recent()[0]["decision"] == "ask-approved"


def test_engine_gate_cancel_does_not_fire():
    eng = _fake_engine()
    sent = {"n": 0}
    cand = A.CandidateAction("email", "send it", confidence=1.0, impact="high",
                             consequential=True,
                             fulfill=lambda: sent.__setitem__("n", sent["n"] + 1))
    eng._submit_candidate(cand)
    assert eng._resolve_pending_approval("no, cancel that")
    assert sent["n"] == 0                            # never fired
    assert eng.actionlog.recent()[0]["decision"] == "ask-denied"


def test_engine_gate_ambiguous_reply_passes_through_and_keeps_pending():
    eng = _fake_engine()
    cand = A.CandidateAction("email", "send it", confidence=1.0, impact="high",
                             consequential=True, fulfill=lambda: None)
    eng._submit_candidate(cand)
    # an unrelated/ambiguous utterance is NOT consumed and leaves the gate armed
    assert eng._resolve_pending_approval("what's the weather like") is False
    assert eng._pending_approval is not None


def test_engine_gate_lapses_when_unanswered():
    eng = _fake_engine()
    eng.cfg["approval_timeout_seconds"] = 0.01
    cand = A.CandidateAction("email", "send it", confidence=1.0, impact="high",
                             consequential=True, fulfill=lambda: None)
    eng._submit_candidate(cand)
    time.sleep(0.02)
    # next turn after the timeout: approval lapses (cleared, logged) and the
    # utterance is NOT consumed as a yes/no
    assert eng._resolve_pending_approval("yes") is False
    assert eng._pending_approval is None
    assert eng.actionlog.recent()[0]["decision"] == "ask-lapsed"


def test_engine_only_one_approval_in_flight():
    eng = _fake_engine()
    eng._submit_candidate(A.CandidateAction("a", "first", consequential=True,
                                            fulfill=lambda: None))
    first = eng._pending_approval
    eng._submit_candidate(A.CandidateAction("b", "second", consequential=True,
                                            fulfill=lambda: None))
    assert eng._pending_approval is first           # second didn't clobber the first


# --------------------------------------------------------------------------- #
#  Standalone runner
# --------------------------------------------------------------------------- #
def _run():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
