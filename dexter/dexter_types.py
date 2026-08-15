"""Type effectiveness engine: the full 18x18 chart (Gen 6+ rules) plus
spoken-sentence builders for weaknesses, resistances, offensive strengths,
and head-to-head matchups. Fully offline — no API involved."""

from __future__ import annotations

TYPES = ["normal", "fire", "water", "electric", "grass", "ice", "fighting",
         "poison", "ground", "flying", "psychic", "bug", "rock", "ghost",
         "dragon", "dark", "steel", "fairy"]

# CHART[attacker][defender] = multiplier (missing = 1.0)
CHART = {
    "normal":   {"rock": .5, "ghost": 0, "steel": .5},
    "fire":     {"fire": .5, "water": .5, "grass": 2, "ice": 2, "bug": 2,
                 "rock": .5, "dragon": .5, "steel": 2},
    "water":    {"fire": 2, "water": .5, "grass": .5, "ground": 2, "rock": 2,
                 "dragon": .5},
    "electric": {"water": 2, "electric": .5, "grass": .5, "ground": 0,
                 "flying": 2, "dragon": .5},
    "grass":    {"fire": .5, "water": 2, "grass": .5, "poison": .5,
                 "ground": 2, "flying": .5, "bug": .5, "rock": 2,
                 "dragon": .5, "steel": .5},
    "ice":      {"fire": .5, "water": .5, "grass": 2, "ice": .5, "ground": 2,
                 "flying": 2, "dragon": 2, "steel": .5},
    "fighting": {"normal": 2, "ice": 2, "poison": .5, "flying": .5,
                 "psychic": .5, "bug": .5, "rock": 2, "ghost": 0, "dark": 2,
                 "steel": 2, "fairy": .5},
    "poison":   {"grass": 2, "poison": .5, "ground": .5, "rock": .5,
                 "ghost": .5, "steel": 0, "fairy": 2},
    "ground":   {"fire": 2, "electric": 2, "grass": .5, "poison": 2,
                 "flying": 0, "bug": .5, "rock": 2, "steel": 2},
    "flying":   {"electric": .5, "grass": 2, "fighting": 2, "bug": 2,
                 "rock": .5, "steel": .5},
    "psychic":  {"fighting": 2, "poison": 2, "psychic": .5, "dark": 0,
                 "steel": .5},
    "bug":      {"fire": .5, "grass": 2, "fighting": .5, "poison": .5,
                 "flying": .5, "psychic": 2, "ghost": .5, "dark": 2,
                 "steel": .5, "fairy": .5},
    "rock":     {"fire": 2, "ice": 2, "fighting": .5, "ground": .5,
                 "flying": 2, "bug": 2, "steel": .5},
    "ghost":    {"normal": 0, "psychic": 2, "ghost": 2, "dark": .5},
    "dragon":   {"dragon": 2, "steel": .5, "fairy": 0},
    "dark":     {"fighting": .5, "psychic": 2, "ghost": 2, "dark": .5,
                 "fairy": .5},
    "steel":    {"fire": .5, "water": .5, "electric": .5, "ice": 2, "rock": 2,
                 "steel": .5, "fairy": 2},
    "fairy":    {"fire": .5, "fighting": 2, "poison": .5, "dragon": 2,
                 "dark": 2, "steel": .5},
}


def matchup(attacker, defender_types):
    """Damage multiplier for one attacking type vs a (possibly dual) defender."""
    mult = 1.0
    for d in defender_types:
        mult *= CHART.get(attacker, {}).get(d, 1.0)
    return mult


def best_matchup(attacker_types, defender_types):
    """Best multiplier the attacker's own types can achieve, and which type."""
    best_t, best_m = None, -1.0
    for a in attacker_types:
        m = matchup(a, defender_types)
        if m > best_m:
            best_t, best_m = a, m
    return best_t, best_m


def defense_profile(defender_types):
    """{multiplier: [attacking types]} for 4, 2, 0.5, 0.25, 0."""
    prof = {4.0: [], 2.0: [], 0.5: [], 0.25: [], 0.0: []}
    for a in TYPES:
        m = matchup(a, defender_types)
        if m in prof:
            prof[m].append(a)
    return prof


def offense_targets(attacker_types):
    """{own type: [defender single-types it hits super effectively]}."""
    return {a: [d for d in TYPES if CHART.get(a, {}).get(d, 1.0) > 1.0]
            for a in attacker_types}


# ------------------------------------------------------- spoken sentences ---

def _join(names):
    names = [n.title() for n in names]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def type_phrase(types):
    joined = " and ".join(t.title() for t in types)
    article = "an" if joined[:1].lower() in "aeiou" else "a"
    return f"{article} {joined} type"


def weakness_sentence(entry):
    types = entry.get("types") or []
    prof = defense_profile(types)
    parts = [f"{entry['display_name']} is {type_phrase(types)}."]
    if prof[4.0]:
        parts.append(f"It takes four times damage from {_join(prof[4.0])}.")
    if prof[2.0]:
        parts.append(f"It is weak to {_join(prof[2.0])}.")
    if not prof[4.0] and not prof[2.0]:
        parts.append("Remarkably, it has no type weaknesses.")
    resists = prof[0.5] + prof[0.25]
    if resists:
        parts.append(f"It resists {_join(resists)}.")
    if prof[0.0]:
        parts.append(f"It is immune to {_join(prof[0.0])} attacks.")
    return " ".join(parts)


def strength_sentence(entry):
    types = entry.get("types") or []
    parts = [f"{entry['display_name']} is {type_phrase(types)}."]
    for own, targets in offense_targets(types).items():
        if targets:
            parts.append(f"Its {own.title()} attacks are super effective "
                         f"against {_join(targets)}.")
        else:
            parts.append(f"Its {own.title()} attacks hit nothing for extra "
                         "damage.")
    return " ".join(parts)


def _mult_words(m):
    return {4.0: "four times damage", 2.0: "double damage",
            1.0: "normal damage", 0.5: "half damage",
            0.25: "one quarter damage", 0.0: "no damage at all"}.get(
                m, f"{m:g} times damage")


def type_vs_type_sentence(att, def_):
    m = CHART.get(att, {}).get(def_, 1.0)
    verdict = ("Yes." if m > 1 else "No." if m < 1 else "It is an even match.")
    return (f"{verdict} {att.title()} attacks deal {_mult_words(m)} to "
            f"{def_.title()} types.")


def head_to_head_sentence(a, b):
    """Which of two Pokemon has the type edge, plus stat totals."""
    at, am = best_matchup(a.get("types") or [], b.get("types") or [])
    bt, bm = best_matchup(b.get("types") or [], a.get("types") or [])
    bst_a = sum((a.get("stats") or {}).values())
    bst_b = sum((b.get("stats") or {}).values())
    parts = []
    if at:
        parts.append(f"{a['display_name']}'s {at.title()} attacks deal "
                     f"{_mult_words(am)} to {b['display_name']}.")
    if bt:
        parts.append(f"{b['display_name']}'s {bt.title()} attacks deal "
                     f"{_mult_words(bm)} back.")
    parts.append(f"Base stat totals, {a['display_name']} {bst_a}, "
                 f"{b['display_name']} {bst_b}.")
    score_a = (am - bm) + (bst_a - bst_b) / 150.0
    if abs(score_a) < 0.3:
        parts.append("My analysis calls this one too close to declare.")
    else:
        winner = a if score_a > 0 else b
        parts.append(f"The advantage goes to {winner['display_name']}.")
    return " ".join(parts)
