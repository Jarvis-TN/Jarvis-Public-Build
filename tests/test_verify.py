"""Tests for Phase 1 verification: classifying every tool result as ok/failed/
unknown, annotating failures for same-turn self-correction, and the per-tool
reliability record. Run: .venv\\Scripts\\python.exe tests\\test_verify.py"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jarvis_verify as V

_passed = _failed = 0


def check(name, fn):
    global _passed, _failed
    try:
        fn()
        print(f"  PASS  {name}")
        _passed += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        _failed += 1


def test_failure_phrases():
    for msg in ("I couldn't read that page just now, sir.",
                "(tool error) the server refused",
                "I'm afraid the document didn't get written, sir.",
                "The controlled browser isn't connected, sir.",
                "I couldn't find a file called 'resume.docx', sir."):
        st, _ = V.classify("some_tool", msg)
        assert st == V.FAILED, (msg, st)


def test_success_phrases():
    st, _ = V.classify("create_document", "I've created something and opened it for you, sir.")
    assert st == V.OK
    st, _ = V.classify("media_control", "Done, sir - paused.")
    assert st == V.OK


def test_empty_and_nonstring():
    assert V.classify("t", "")[0] == V.FAILED
    assert V.classify("t", None)[0] == V.FAILED
    assert V.classify("t", [{"type": "image"}])[0] == V.UNKNOWN   # vision blocks


def test_long_content_not_misread_as_failure():
    """A page whose BODY contains 'failed'/'not found' must not be called a failure -
    only the head of a result is treated as a status message."""
    page = ("TITLE: Build log\n\n" + "All systems nominal. " * 30
            + "Step 7 failed and the record was not found. " + "More text. " * 30)
    st, _ = V.classify("read_browser_page", page)
    assert st != V.FAILED, st


def test_file_verification_is_strongest_evidence():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "Deck.pptx")
    with open(p, "w", encoding="utf-8") as f:
        f.write("content")
    msg = f"I've put together 'Deck.pptx' - 3 slides plus a title - in {d} and opened it for you, sir."
    st, detail = V.classify("create_presentation", msg)
    assert st == V.OK and "Deck.pptx exists" in detail, (st, detail)
    # a claimed file that does NOT exist gets no positive verification
    msg2 = f"I've created 'Ghost.docx' in {d} and opened it for you, sir."
    st2, detail2 = V.classify("create_document", msg2)
    assert detail2 == ""            # nothing confirmed on disk


def test_annotate_only_on_failure_or_confirmed():
    assert "did NOT succeed" in V.annotate("nope", V.FAILED, "couldn't")
    assert V.annotate("body", V.UNKNOWN, "") == "body"          # silent
    assert V.annotate("body", V.OK, "") == "body"               # silent
    assert "confirmed" in V.annotate("body", V.OK, "X.docx exists (5 bytes)")


def test_toolstats_reliability():
    s = V.ToolStats(path=os.path.join(tempfile.mkdtemp(), "tool_stats.json"))
    for _ in range(3):
        s.record("create_document", V.OK)
    s.record("create_document", V.FAILED)
    s.record("read_browser_page", V.UNKNOWN)
    decided, ok, failed, rate = s.reliability("create_document")
    assert (decided, ok, failed) == (4, 3, 1) and abs(rate - 0.75) < 1e-9
    # 'unknown' outcomes don't count toward the decided track record
    assert s.reliability("read_browser_page")[0] == 0
    assert "create_document" in s.summary()


def test_engine_records_and_annotates():
    import jarvis
    e = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    e.toolstats = V.ToolStats(path=os.path.join(tempfile.mkdtemp(), "s.json"))
    notes = []
    e.transcript_cb = lambda kind, msg: notes.append(msg)
    status, detail = e._verify_tool_outcome("read_browser_page",
                                            "I couldn't read the page just now, sir.")
    assert status == V.FAILED
    assert any("did not succeed" in n for n in notes)          # surfaced to the transcript
    assert e.toolstats.reliability("read_browser_page")[2] == 1  # recorded as failed
    out = e._annotate_result_quality("read_browser_page", "orig", None, status, detail)
    assert "did NOT succeed" in out                             # model can self-correct


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    total = _passed + _failed
    print(f"\n{_passed} passed, {_failed} failed, {total} total")
    sys.exit(1 if _failed else 0)
