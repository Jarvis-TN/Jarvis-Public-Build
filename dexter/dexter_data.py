"""Dexter's Pokemon database.

One local SQLite file built from PokeAPI (https://pokeapi.co) — the canonical
open aggregation of every mainline game's data: stats, types, species info,
flavor text from EVERY game version, colors, habitats, evolution links,
legendary flags, official artwork. That single source already contains what
fan wikis republish, so we sync it once into `data/dexter.db` and Dexter then
answers instantly and offline.

CLI:
    python dexter_data.py sync            # full national dex (~1000+ species)
    python dexter_data.py sync --limit 151  # just Kanto, for a quick test
    python dexter_data.py show pikachu    # print one entry
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

API = "https://pokeapi.co/api/v2"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
DB_PATH = os.path.join(DATA_DIR, "dexter.db")
SPRITE_DIR = os.path.join(DATA_DIR, "sprites")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pokemon (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,          -- api slug, e.g. "mr-mime"
    display_name  TEXT NOT NULL,          -- "Mr. Mime"
    genus         TEXT,                   -- "Barrier Pokemon"
    types         TEXT,                   -- json list, e.g. ["psychic","fairy"]
    stats         TEXT,                   -- json {"hp":35,"attack":55,...}
    height_m      REAL,
    weight_kg     REAL,
    color         TEXT,
    habitat       TEXT,
    shape         TEXT,
    is_legendary  INTEGER DEFAULT 0,
    is_mythical   INTEGER DEFAULT 0,
    generation    INTEGER,
    evolves_from  TEXT,
    capture_rate  INTEGER,
    flavor        TEXT,                   -- json list of {"version":..,"text":..}
    artwork_url   TEXT,
    sprite_url    TEXT,
    synced_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_pokemon_name ON pokemon(name);
"""

_lock = threading.Lock()


def _connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def _get_json(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def _english(entries, key="name"):
    for e in entries:
        if e.get("language", {}).get("name") == "en":
            return e.get(key) or e.get("genus") or e.get("flavor_text")
    return None


def _clean_flavor(text):
    return re.sub(r"\s+", " ", (text or "").replace("\x0c", " ")).strip()


def _fetch_one(species_url):
    """Fetch one species + its default pokemon form; return a row dict."""
    sp = _get_json(species_url)
    default = next((v for v in sp["varieties"] if v["is_default"]), sp["varieties"][0])
    pk = _get_json(default["pokemon"]["url"])

    flavor, seen = [], set()
    for ft in sp.get("flavor_text_entries", []):
        if ft["language"]["name"] != "en":
            continue
        text = _clean_flavor(ft["flavor_text"])
        if text and text not in seen:
            seen.add(text)
            flavor.append({"version": ft["version"]["name"], "text": text})

    gen_slug = (sp.get("generation") or {}).get("name", "generation-i")
    gen_map = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6,
               "vii": 7, "viii": 8, "ix": 9, "x": 10}
    generation = gen_map.get(gen_slug.split("-")[-1], 0)

    art = (pk["sprites"].get("other", {}).get("official-artwork", {})
           .get("front_default"))
    return {
        "id": sp["id"],
        "name": sp["name"],
        "display_name": _english(sp.get("names", []), "name") or sp["name"].title(),
        "genus": _english(sp.get("genera", []), "genus"),
        "types": json.dumps([t["type"]["name"] for t in pk["types"]]),
        "stats": json.dumps({s["stat"]["name"]: s["base_stat"] for s in pk["stats"]}),
        "height_m": pk["height"] / 10.0,
        "weight_kg": pk["weight"] / 10.0,
        "color": (sp.get("color") or {}).get("name"),
        "habitat": (sp.get("habitat") or {}).get("name"),
        "shape": (sp.get("shape") or {}).get("name"),
        "is_legendary": int(sp.get("is_legendary", False)),
        "is_mythical": int(sp.get("is_mythical", False)),
        "generation": generation,
        "evolves_from": (sp.get("evolves_from_species") or {}).get("name"),
        "capture_rate": sp.get("capture_rate"),
        "flavor": json.dumps(flavor),
        "artwork_url": art,
        "sprite_url": pk["sprites"].get("front_default"),
        "synced_at": time.time(),
    }


def sync(limit=None, workers=8, progress=None):
    """Pull the national dex into SQLite. Safe to re-run (upserts)."""
    listing = _get_json(f"{API}/pokemon-species?limit=20000")["results"]
    if limit:
        listing = listing[:limit]
    con = _connect()
    done, errors = 0, []

    def store(row):
        nonlocal done
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with _lock:
            con.execute(
                f"INSERT OR REPLACE INTO pokemon ({cols}) VALUES ({marks})",
                list(row.values()))
            done += 1
            if done % 25 == 0:
                con.commit()
        if progress:
            progress(done, len(listing))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, e["url"]): e["name"] for e in listing}
        for fut in as_completed(futures):
            try:
                store(fut.result())
            except Exception as exc:
                errors.append((futures[fut], str(exc)))
    con.commit()
    con.close()
    return done, errors


# ---------------------------------------------------------------- queries ---

def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for key in ("types", "stats", "flavor"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                pass
    return d


def count():
    con = _connect()
    n = con.execute("SELECT COUNT(*) FROM pokemon").fetchone()[0]
    con.close()
    return n


def get(id_or_name):
    """Look up by dex number, slug, or display name (case-insensitive)."""
    con = _connect()
    key = str(id_or_name).strip().lstrip("#")
    if key.isdigit():
        row = con.execute("SELECT * FROM pokemon WHERE id=?", (int(key),)).fetchone()
    else:
        slug = key.lower().replace(" ", "-").replace(".", "").replace("'", "")
        row = con.execute(
            "SELECT * FROM pokemon WHERE name=? OR lower(display_name)=lower(?)",
            (slug, key)).fetchone()
    con.close()
    return _row_to_dict(row)


def neighbor(current_id, step):
    con = _connect()
    if step > 0:
        row = con.execute("SELECT * FROM pokemon WHERE id>? ORDER BY id LIMIT 1",
                          (current_id,)).fetchone()
        row = row or con.execute("SELECT * FROM pokemon ORDER BY id LIMIT 1").fetchone()
    else:
        row = con.execute("SELECT * FROM pokemon WHERE id<? ORDER BY id DESC LIMIT 1",
                          (current_id,)).fetchone()
        row = row or con.execute("SELECT * FROM pokemon ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    return _row_to_dict(row)


def random_one():
    con = _connect()
    row = con.execute("SELECT * FROM pokemon ORDER BY RANDOM() LIMIT 1").fetchone()
    con.close()
    return _row_to_dict(row)


def all_rows():
    con = _connect()
    rows = [_row_to_dict(r) for r in con.execute("SELECT * FROM pokemon ORDER BY id")]
    con.close()
    return rows


def find_named_in(text):
    """Return the first Pokemon whose name appears in free-form text."""
    words = re.findall(r"[a-zA-Z][a-zA-Z\-'.]+", text.lower())
    if not words:
        return None
    con = _connect()
    names = {r["name"]: r["id"] for r in con.execute("SELECT name, id FROM pokemon")}
    con.close()
    for i in range(len(words)):
        for j in (2, 1):  # try two-word names ("mr mime") before one-word
            cand = "-".join(words[i:i + j]).replace(".", "").replace("'", "")
            if cand in names:
                return get(names[cand])
    return None


def sprite_path(entry, fetch=True):
    """Local path of the official artwork PNG, downloading it if needed."""
    os.makedirs(SPRITE_DIR, exist_ok=True)
    path = os.path.join(SPRITE_DIR, f"{entry['id']}.png")
    if os.path.exists(path):
        return path
    url = entry.get("artwork_url") or entry.get("sprite_url")
    if not (fetch and url):
        return None
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except Exception:
        return None


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "sync":
        limit = None
        if "--limit" in args:
            limit = int(args[args.index("--limit") + 1])
        print(f"Syncing national dex from PokeAPI (limit={limit or 'all'}) ...")
        t0 = time.time()
        done, errors = sync(limit=limit,
                            progress=lambda d, t: print(f"\r  {d}/{t}", end=""))
        print(f"\nDone: {done} species in {time.time()-t0:.0f}s, "
              f"{len(errors)} errors. DB: {DB_PATH}")
        for name, err in errors[:10]:
            print(f"  ! {name}: {err}")
    elif args and args[0] == "show":
        e = get(" ".join(args[1:]))
        print(json.dumps(e, indent=2) if e else "not found (run sync first?)")
    else:
        print(__doc__)
        print(f"Database currently holds {count()} species.")
