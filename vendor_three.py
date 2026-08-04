"""Vendor Three.js locally so the WebGL HUD works with NO internet.

The HUD's <script type=importmap> pulls three + its addons from the unpkg CDN.
Offline, those module imports fail and the whole HUD script dies (blank HUD, dead
buttons). This downloads three.module.js and every addon the HUD needs - following
the import graph so transitive deps aren't missed - into web/vendor/three/, after
which the importmap can point at local files.

    python vendor_three.py
"""

import os
import re
import sys
import urllib.request

VERSION = "0.160.0"
BASE = f"https://unpkg.com/three@{VERSION}"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(APP_DIR, "web", "vendor", "three")

# entry points the HUD imports (addons are under examples/jsm == "three/addons/")
ENTRY_ADDONS = [
    "examples/jsm/postprocessing/EffectComposer.js",
    "examples/jsm/postprocessing/RenderPass.js",
    "examples/jsm/postprocessing/UnrealBloomPass.js",
    "examples/jsm/postprocessing/OutputPass.js",
]

IMPORT_RE = re.compile(r"""(?:from|import)\s+['"]([^'"]+)['"]""")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "JarvisVendor"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def local_path_for(remote_rel):
    """Map a remote path under three@VER to a local file under VENDOR."""
    if remote_rel.startswith("build/three.module.js"):
        return os.path.join(VENDOR, "three.module.js")
    if remote_rel.startswith("examples/jsm/"):
        return os.path.join(VENDOR, "jsm", remote_rel[len("examples/jsm/"):])
    return os.path.join(VENDOR, remote_rel)


def resolve(spec, current_remote):
    """Resolve an import specifier to a remote path under three@VER, or None to
    skip (bare 'three')."""
    if spec == "three":
        return "build/three.module.js"
    if spec.startswith("three/addons/"):
        return "examples/jsm/" + spec[len("three/addons/"):]
    if spec.startswith("./") or spec.startswith("../"):
        base = os.path.dirname(current_remote)
        return os.path.normpath(os.path.join(base, spec)).replace("\\", "/")
    return None   # other bare specifier - shouldn't happen for three addons


def main():
    os.makedirs(VENDOR, exist_ok=True)
    queue = ["build/three.module.js"] + ENTRY_ADDONS
    seen = set()
    while queue:
        remote = queue.pop()
        if remote in seen:
            continue
        seen.add(remote)
        try:
            src = fetch(f"{BASE}/{remote}")
        except Exception as e:
            print(f"  FAILED {remote}: {e}")
            return 1
        dest = local_path_for(remote)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"  {remote} -> {os.path.relpath(dest, APP_DIR)}")
        for spec in IMPORT_RE.findall(src):
            nxt = resolve(spec, remote)
            if nxt and nxt not in seen:
                queue.append(nxt)
    print(f"\nVendored {len(seen)} files into {os.path.relpath(VENDOR, APP_DIR)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
