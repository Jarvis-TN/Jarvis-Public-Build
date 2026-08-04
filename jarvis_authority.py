"""Jarvis authority layer - guarded self-editing of the app's own code and
guarded execution of commands on the PC.

Two capability surfaces, each with its own guardrail philosophy:

  * SELF-EDIT (code authority) - sandboxed to the Jarvis project directory. Every
    write BACKS UP the previous version first; Python files are compile-checked
    and AUTO-REVERTED if the edit would break them. This protects the app from a
    bad edit so Jarvis can safely change his own code hands-free.

  * PC COMMANDS (pc authority) - arbitrary shell commands on the machine. These
    run hands-free by design (the user asked not to have to lift a finger),
    EXCEPT a short hard-stop list of irreversibly catastrophic commands (drive
    formatting, disk wiping, mass deletion of system folders, registry-hive
    deletion) which are refused here so the tool layer can route them through the
    spoken approval gate instead.

Everything is best-effort and returns plain dicts; the tool layer turns them into
spoken strings and audit-log entries. Nothing here speaks, prompts, or imports the
engine - it's cold-testable in isolation.
"""

import os
import re
import shutil
import py_compile
import subprocess
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(APP_DIR, "backups")

# Directories inside the project that self-edit writes must NOT touch: the
# virtualenv (baked absolute paths), backups (our safety net), the SQLite
# memory stores, downloaded model weights, binaries, and VCS metadata. Reads are
# still allowed everywhere; this only blocks writes/edits.
_PROTECTED_DIRS = {".venv", ".venv-chatterbox", "backups", "memory", "voices",
                   "bin", ".git", "__pycache__"}

# Heavy dirs skipped when listing the project tree.
_SKIP_LIST = _PROTECTED_DIRS | {"web"}

# Irreversibly catastrophic commands - refused here, routed through the approval
# gate by the tool layer. Deliberately narrow: only things that destroy a disk,
# the OS, or user data wholesale. Ordinary destructive-but-scoped commands (a
# single file delete, uninstalling an app) are allowed to run hands-free.
_CATASTROPHIC = [
    re.compile(r"\bformat\b\s+[a-z]:", re.I),               # format c:
    re.compile(r"\bFormat-Volume\b", re.I),
    re.compile(r"\bClear-Disk\b", re.I),
    re.compile(r"\bdiskpart\b", re.I),
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r"\bcipher\s+/w", re.I),                      # secure-wipe free space
    re.compile(r"\bsdelete\b", re.I),
    # recursive delete of a drive root or a core system folder
    re.compile(r"(del|rmdir|rd)\b.*/s.*\b[a-z]:\\?(\s|$|windows|users|program)", re.I),
    re.compile(r"Remove-Item\b(?=.*-Recurse).*\b[a-z]:\\(\s|$|windows|users|program|\")", re.I),
    re.compile(r"\brm\s+-rf?\s+(/|~|\.|[a-z]:)", re.I),
    # wholesale registry-hive deletion
    re.compile(r"reg\s+delete\s+HK(LM|CU|CR)\b(?!.* /v )", re.I),
    re.compile(r"Remove-Item\b.*HK(LM|CU|CR):\\", re.I),
    re.compile(r":\(\)\s*\{.*\};", re.S),                    # classic fork bomb
]


# --------------------------------------------------------------------------- #
#  Path sandboxing
# --------------------------------------------------------------------------- #
def _resolve_in_project(relpath):
    """Resolve a path (relative to the project, or an absolute path inside it) to
    an absolute path, guaranteeing it stays within APP_DIR. Returns (abspath,
    None) or (None, error)."""
    if not relpath or not str(relpath).strip():
        return None, "no path given"
    p = os.path.normpath(os.path.join(APP_DIR, str(relpath).strip())
                          if not os.path.isabs(str(relpath)) else str(relpath))
    root = os.path.normcase(os.path.abspath(APP_DIR))
    ap = os.path.normcase(os.path.abspath(p))
    if ap != root and not ap.startswith(root + os.sep):
        return None, "that path is outside the Jarvis project folder"
    return p, None


def _is_protected(abspath):
    rel = os.path.relpath(abspath, APP_DIR)
    first = rel.split(os.sep, 1)[0]
    return first in _PROTECTED_DIRS


# --------------------------------------------------------------------------- #
#  Reads
# --------------------------------------------------------------------------- #
def list_files(subdir="", max_entries=500):
    """List source files in the project (skipping venvs, models, backups, web)."""
    base, err = _resolve_in_project(subdir or ".")
    if err:
        return {"ok": False, "error": err}
    if not os.path.isdir(base):
        return {"ok": False, "error": "not a folder"}
    out = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_LIST and not d.startswith(".")]
        for fn in files:
            rel = os.path.relpath(os.path.join(dirpath, fn), APP_DIR)
            out.append(rel.replace(os.sep, "/"))
            if len(out) >= max_entries:
                return {"ok": True, "files": sorted(out), "truncated": True}
    return {"ok": True, "files": sorted(out), "truncated": False}


def read_file(relpath, max_bytes=200_000):
    abspath, err = _resolve_in_project(relpath)
    if err:
        return {"ok": False, "error": err}
    if not os.path.isfile(abspath):
        return {"ok": False, "error": "no such file"}
    try:
        with open(abspath, "r", encoding="utf-8", errors="replace") as f:
            data = f.read(max_bytes + 1)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    truncated = len(data) > max_bytes
    return {"ok": True, "path": relpath, "content": data[:max_bytes],
            "truncated": truncated}


# --------------------------------------------------------------------------- #
#  Writes (backed up + compile-checked)
# --------------------------------------------------------------------------- #
def _backup(abspath):
    """Copy an existing file into backups/ with a timestamp; return its path."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = os.path.basename(abspath)
    dst = os.path.join(BACKUP_DIR, f"{name}.{stamp}.bak")
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(BACKUP_DIR, f"{name}.{stamp}_{n}.bak")
        n += 1
    shutil.copy2(abspath, dst)
    return dst


def write_file(relpath, content):
    """Write `content` to a project file. Backs up any existing version first;
    if it's a .py file that would no longer compile, the change is rolled back
    and reported. Returns a structured result including the backup path (used as
    the undo handle)."""
    abspath, err = _resolve_in_project(relpath)
    if err:
        return {"ok": False, "error": err}
    if _is_protected(abspath):
        return {"ok": False, "error": "that location is protected (venv/backups/"
                                      "memory/models) and I won't edit it"}
    if content is None:
        return {"ok": False, "error": "no content given"}
    content = str(content)
    existed = os.path.isfile(abspath)
    backup = _backup(abspath) if existed else None
    try:
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        return {"ok": False, "error": f"write failed: {e}", "backup": backup}

    compiled = None
    if abspath.lower().endswith(".py"):
        try:
            py_compile.compile(abspath, doraise=True)
            compiled = True
        except py_compile.PyCompileError as e:
            # bad edit - restore the previous version (or remove a new file)
            compiled = False
            if backup:
                shutil.copy2(backup, abspath)
            else:
                try:
                    os.remove(abspath)
                except OSError:
                    pass
            return {"ok": False, "compiled": False, "path": relpath, "backup": backup,
                    "error": f"the edit would break {os.path.basename(abspath)} so I "
                             f"reverted it: {e.msg if hasattr(e, 'msg') else e}"}
    return {"ok": True, "path": relpath, "backup": backup, "compiled": compiled,
            "bytes": len(content), "created": not existed,
            "undo": (f"restore-file::{backup}::{abspath}" if backup else
                     f"delete-file::{abspath}")}


def edit_file(relpath, find, replace):
    """Replace one exact occurrence of `find` with `replace` in a project file.
    Requires `find` to appear exactly once (so the edit is unambiguous). Goes
    through write_file, so it's backed up + compile-checked + revertible."""
    r = read_file(relpath)
    if not r.get("ok"):
        return r
    if r.get("truncated"):
        return {"ok": False, "error": "file too large to edit safely; rewrite it whole instead"}
    body = r["content"]
    if find is None or find == "":
        return {"ok": False, "error": "nothing to find"}
    count = body.count(find)
    if count == 0:
        return {"ok": False, "error": "I couldn't find that text to change"}
    if count > 1:
        return {"ok": False, "error": f"that text appears {count} times; give me more "
                                      "surrounding context so the edit is unambiguous"}
    return write_file(relpath, body.replace(find, replace, 1))


def restore_backup(backup_path, target_path):
    """Put a backup file back in place (the undo for a self-edit)."""
    try:
        if not os.path.isfile(backup_path):
            return {"ok": False, "error": "the backup is no longer available"}
        shutil.copy2(backup_path, target_path)
        return {"ok": True, "restored": target_path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------- #
#  PC commands
# --------------------------------------------------------------------------- #
def is_catastrophic(command):
    c = command or ""
    return any(rx.search(c) for rx in _CATASTROPHIC)


def run_command(command, cwd=None, timeout=120, shell="powershell"):
    """Run a shell command on the PC and capture its output. Refuses the
    catastrophic hard-stop list. `shell` is 'powershell' or 'cmd'. This is the
    explicit, user-authorized PC-control path - it deliberately executes what
    it's given (it is NOT the injection-hardened surface; the tool layer only
    lets the user drive it)."""
    command = (command or "").strip()
    if not command:
        return {"ok": False, "error": "no command given"}
    if is_catastrophic(command):
        return {"ok": False, "blocked": True,
                "error": "that looks irreversibly destructive (formatting/wiping a "
                         "disk or deleting system folders); refused"}
    work = cwd or APP_DIR
    if not os.path.isdir(work):
        work = APP_DIR
    if shell == "cmd":
        argv = ["cmd", "/c", command]
    else:
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    try:
        p = subprocess.run(argv, cwd=work, capture_output=True, text=True,
                           timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (p.stdout or "").strip()
        errtxt = (p.stderr or "").strip()
        return {"ok": p.returncode == 0, "code": p.returncode,
                "stdout": out[:6000], "stderr": errtxt[:2000]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"the command didn't finish within {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def schedule_restart(frontend="glass", delay_ms=800):
    """Spawn a detached watcher that waits for THIS process to exit, then relaunches
    Jarvis via the matching launcher. The caller exits shortly after so the app
    comes back up on the new code. Returns True if the relaunch was scheduled."""
    bat = "Launch Jarvis HUD.bat" if frontend == "glass" else "Launch Jarvis.bat"
    batpath = os.path.join(APP_DIR, bat)
    if not os.path.isfile(batpath):     # fall back to the other launcher if missing
        alt = "Launch Jarvis.bat" if frontend == "glass" else "Launch Jarvis HUD.bat"
        batpath = os.path.join(APP_DIR, alt)
    if not os.path.isfile(batpath):
        return False
    pid = os.getpid()
    ps = (f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue; "
          f"Start-Sleep -Milliseconds {int(delay_ms)}; "
          f"Start-Process -FilePath '{batpath}' -WorkingDirectory '{APP_DIR}'")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | \
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                          "-Command", ps], creationflags=flags,
                         close_fds=True)
        return True
    except Exception:
        return False
