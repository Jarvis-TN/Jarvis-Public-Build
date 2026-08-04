"""Jarvis offline brain - a deterministic command handler for when there's no
internet (so the cloud Claude brain is unreachable).

It can't hold a free-form conversation (that needs the model), but it covers the
practical things you'd still want hands-free with no connection:
  * simple maths ("what's 12.5 percent of 80", "3 to the power of 4")
  * the time and date
  * battery / CPU / memory status
  * finding, reading, and opening local files
  * opening apps and known sites
  * timers
  * taking and listing notes (local memory DB)

Everything here is local and dependency-light. The engine routes a transcript
here whenever it detects it's offline; anything this can't handle returns None so
the engine can give an honest "I'm offline, here's what I can still do" reply.

For a true offline CONVERSATIONAL brain, a local LLM (e.g. Ollama) would plug in
alongside this - this handles the deterministic commands cheaply either way.
"""

import os
import re
import ast
import glob
import operator

import jarvis_tools as tools

# ---- safe arithmetic ----------------------------------------------------- #
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_WORD_OPS = [
    (r"\bplus\b|\band\b(?=\s*\d)", "+"), (r"\bminus\b|\bless\b", "-"),
    (r"\btimes\b|\bmultiplied by\b|\bx\b", "*"),
    (r"\bdivided by\b|\bover\b", "/"),
    (r"\bto the power of\b|\bpower\b|\^", "**"),
    (r"\bsquared\b", "**2"), (r"\bcubed\b", "**3"),
]


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("non-numeric")
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


def try_math(text):
    """Return a spoken answer if `text` is a maths question, else None."""
    t = text.lower().strip().rstrip("?.! ")
    t = re.sub(r"^(hey |ok |okay )?(jarvis[,: ]+)?", "", t)
    t = re.sub(r"^(what(')?s|what is|whats|calculate|compute|work out|how much is|tell me)\s+",
               "", t)

    # percent: "X percent of Y"
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:percent|%)\s*of\s*(-?\d+(?:\.\d+)?)", t)
    if m:
        val = float(m.group(1)) / 100.0 * float(m.group(2))
        return _say_number(val)

    for pat, rep in _WORD_OPS:
        t = re.sub(pat, rep, t)
    t = t.replace("÷", "/").replace("×", "*")
    # must look like arithmetic (digits + an operator) to avoid false positives
    if not re.search(r"\d", t) or not re.search(r"[-+*/^]", t.replace("**", "^")):
        return None
    expr = re.sub(r"[^0-9.+\-*/%()\s]", "", t)
    if not expr.strip():
        return None
    try:
        result = _safe_eval(ast.parse(expr, mode="eval"))
    except Exception:
        return None
    return _say_number(result)


def _say_number(n):
    if isinstance(n, float):
        n = round(n, 6)
        if n == int(n):
            n = int(n)
    return f"That's {n}."


# ---- local file helpers -------------------------------------------------- #
def _user_dirs():
    home = os.path.expanduser("~")
    cands = [os.path.join(home, d) for d in
             ("Desktop", "Documents", "Downloads",
              os.path.join("OneDrive", "Desktop"),
              os.path.join("OneDrive", "Documents"))]
    return [d for d in cands if os.path.isdir(d)]


_TEXT_EXTS = (".txt", ".md", ".csv", ".log", ".json", ".py", ".ini", ".cfg",
              ".yml", ".yaml", ".html", ".xml")


def find_files(query, limit=8):
    """Find files under the user's common folders whose name matches `query`."""
    terms = [w for w in re.findall(r"[\w.]+", query.lower()) if len(w) > 1]
    if not terms:
        return []
    hits = []
    seen = set()
    for base in _user_dirs():
        for root, dirs, files in os.walk(base):
            # don't descend into huge/system dirs
            depth = root[len(base):].count(os.sep)
            if depth > 4:
                dirs[:] = []
                continue
            for fn in files:
                low = fn.lower()
                if all(term in low for term in terms):
                    p = os.path.join(root, fn)
                    if p not in seen:
                        seen.add(p)
                        hits.append(p)
                        if len(hits) >= limit:
                            return hits
    return hits


def _read_text_file(path, max_chars=4000):
    try:
        if os.path.getsize(path) > 2_000_000:
            return "(that file is rather large; I'll only read text files under a couple of megabytes offline.)"
    except Exception:
        pass
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read(max_chars + 1)
    except Exception as e:
        return f"(I couldn't read that file: {e})"
    if len(data) > max_chars:
        return data[:max_chars] + "\n... (truncated)"
    return data


# ---- intent handlers ----------------------------------------------------- #
def _h_time(text, engine):
    if re.search(r"\b(time|date|day|today|what day)\b", text.lower()):
        return tools._get_datetime()
    return None


def _h_system(text, engine):
    if re.search(r"\b(battery|charge|cpu|processor|memory|ram|system status|"
                 r"how('?s| is) my (pc|computer|system))\b", text.lower()):
        return tools._get_system_status()
    return None


def _h_timer(text, engine):
    m = re.search(r"(?:set|start)\s+a?\s*timer\s+for\s+(\d+)\s*(second|sec|minute|min|hour)",
                  text.lower())
    if not m or engine is None:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    secs = n * (3600 if unit.startswith("hour") else 60 if unit.startswith("min") else 1)
    try:
        engine.schedule_timer(secs, "")
    except Exception:
        return None
    human = f"{n} {unit}{'s' if n != 1 else ''}"
    return f"Timer set for {human}, sir."


def _h_notes(text, engine):
    low = text.lower()
    m = re.match(r"\s*(?:remember|note|make a note|take a note)\s*(?:that|:)?\s+(.*)", low)
    if m and m.group(1).strip():
        note = text[text.lower().index(m.group(1)):].strip()
        return tools._remember_note(note, engine)
    if re.search(r"\b(list|what are|read)\s+my\s+notes\b", low) or low.strip() in ("notes", "my notes"):
        return tools._list_notes(engine)
    return None


def _h_files(text, engine):
    low = text.lower()
    # open a file or app
    m = re.search(r"\bopen\s+(.+)", low)
    if m:
        target = text[text.lower().index(m.group(1)):].strip().rstrip("?.! ")
        # if it names a file we can find, open that exact path; else hand to the launcher
        files = find_files(target, limit=1)
        chosen = files[0] if files else target
        try:
            tools._open_single(chosen) if hasattr(tools, "_open_single") else tools._open_target(chosen)
        except Exception as e:
            return f"I couldn't open that, sir: {e}"
        name = os.path.basename(chosen) if files else target
        return f"Opening {name}, sir."

    # read a file
    m = re.search(r"\b(?:read|open and read|what(?:'s| is) in|show me|contents of)\s+"
                  r"(?:the\s+)?(?:file\s+)?(.+)", low)
    if m and ("file" in low or re.search(r"\.\w{1,4}\b", low) or "read" in low):
        q = text[text.lower().index(m.group(1)):].strip().rstrip("?.! ")
        files = find_files(q, limit=1)
        if not files:
            return f"I couldn't find a file matching '{q}', sir."
        body = _read_text_file(files[0])
        return f"From {os.path.basename(files[0])}:\n{body}"

    # find/search files
    m = re.search(r"\b(?:find|search for|locate|look for)\s+(?:a\s+)?(?:file|files|document)?\s*"
                  r"(?:called|named|about|for)?\s*(.+)", low)
    if m and re.search(r"\b(file|files|document)\b", low):
        q = text[text.lower().index(m.group(1)):].strip().rstrip("?.! ")
        files = find_files(q)
        if not files:
            return f"I found no files matching '{q}', sir."
        names = [os.path.basename(p) for p in files]
        head = f"I found {len(files)} file{'s' if len(files) != 1 else ''}: "
        return head + ", ".join(names[:6]) + ("..." if len(files) > 6 else ".")
    return None


def _h_greeting(text, engine):
    low = text.lower().strip().rstrip("?.! ")
    if low in ("hello", "hi", "hey", "hey jarvis", "jarvis", "you there",
               "are you there", "good morning", "good evening"):
        return "At your service, sir - though I'm currently offline, so my full intelligence is unavailable."
    if re.search(r"what can you do|help|capabilities|offline", low):
        return ("While offline I can do maths, tell the time, check your battery and "
                "system, find read and open local files, open apps, set timers, and take "
                "notes. For anything that needs me to think or reach the internet, I'll "
                "need a connection.")
    return None


def handle(text, engine=None):
    """Route an offline transcript to a deterministic handler. Returns a spoken
    reply string, or None if nothing matched (caller gives the fallback)."""
    if not text or not text.strip():
        return None
    # maths is checked first (very specific), then intent handlers
    ans = try_math(text)
    if ans:
        return ans
    for fn in (_h_timer, _h_notes, _h_files, _h_system, _h_time, _h_greeting):
        try:
            r = fn(text, engine)
        except Exception:
            r = None
        if r:
            return r
    return None
