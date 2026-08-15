"""Dexter's brain.

Two layers:
  1. GuessGame — a deterministic 20-questions engine over the local database.
     "I'm thinking of a Pokemon" -> Dexter asks yes/no questions chosen to
     split the remaining candidates as close to 50/50 as possible, then names
     the Pokemon. Works fully offline.
  2. Claude — free-form Pokemon Q&A in Dexter's flat encyclopedic persona,
     grounded with the matching database entry so facts come from the dex,
     not from model memory.

Everything returns plain spoken text (no markdown — it goes to TTS).
"""

from __future__ import annotations

import json
import re

import dexter_data
import dexter_types
from dexter_types import TYPES

GEN_REGIONS = {1: "Kanto", 2: "Johto", 3: "Hoenn", 4: "Sinnoh", 5: "Unova",
               6: "Kalos", 7: "Alola", 8: "Galar", 9: "Paldea"}

YES_WORDS = {"yes", "yeah", "yep", "yup", "correct", "right", "true", "it is",
             "sure", "affirmative", "definitely", "i think so"}
NO_WORDS = {"no", "nope", "nah", "not", "incorrect", "wrong", "false",
            "it isn't", "it is not", "negative", "don't think so"}
SKIP_WORDS = {"skip", "unsure", "not sure", "maybe", "don't know", "dont know",
              "no idea", "pass", "unknown"}
QUIT_WORDS = {"stop", "quit", "cancel", "never mind", "nevermind", "forget it",
              "exit", "give up", "end the game"}


def _a(word):
    return "an" if word[:1].lower() in "aeiou" else "a"


def parse_yes_no(text):
    """-> 'yes' | 'no' | 'skip' | None (couldn't tell)."""
    t = (text or "").lower().strip()
    if not t:
        return None
    if any(w in t for w in SKIP_WORDS):
        return "skip"
    # check "no" before "yes": "no it isn't" contains neither yes-word
    if any(re.search(rf"\b{re.escape(w)}\b", t) for w in NO_WORDS):
        return "no"
    if any(re.search(rf"\b{re.escape(w)}\b", t) for w in YES_WORDS):
        return "yes"
    return None


class GuessGame:
    """Akinator-style guesser over the synced database."""

    MAX_QUESTIONS = 20

    def __init__(self, rows=None):
        self.candidates = rows if rows is not None else dexter_data.all_rows()
        self.asked_keys = set()
        self.questions_asked = 0
        self.pending = None       # (key, label, predicate) awaiting an answer
        self.last_guess = None

    # Each entry: (key, spoken question, predicate(row) -> bool)
    def _question_bank(self):
        bank = []
        for t in TYPES:
            bank.append((f"type:{t}", f"Is it {_a(t)} {t} type?",
                         lambda r, t=t: t in (r.get("types") or [])))
        bank.append(("legendary", "Is it a legendary or mythical Pokemon?",
                     lambda r: bool(r.get("is_legendary") or r.get("is_mythical"))))
        bank.append(("evolved", "Did it evolve from another Pokemon?",
                     lambda r: bool(r.get("evolves_from"))))
        bank.append(("tall", "Is it taller than one meter?",
                     lambda r: (r.get("height_m") or 0) > 1.0))
        bank.append(("heavy", "Does it weigh more than fifty kilograms?",
                     lambda r: (r.get("weight_kg") or 0) > 50.0))
        for gen, region in GEN_REGIONS.items():
            bank.append((f"gen:{gen}",
                         f"Was it first discovered in the {region} region?",
                         lambda r, g=gen: r.get("generation") == g))
        for color in ("red", "blue", "green", "yellow", "brown", "purple",
                      "pink", "gray", "white", "black"):
            bank.append((f"color:{color}", f"Is its body mostly {color}?",
                         lambda r, c=color: r.get("color") == c))
        return bank

    def _pick_question(self):
        best, best_balance = None, None
        n = len(self.candidates)
        for key, label, pred in self._question_bank():
            if key in self.asked_keys:
                continue
            yes = sum(1 for r in self.candidates if pred(r))
            if yes == 0 or yes == n:
                continue  # question doesn't discriminate anymore
            balance = abs(yes - (n - yes))
            if best_balance is None or balance < best_balance:
                best, best_balance = (key, label, pred), balance
        return best

    def start(self):
        if not self.candidates:
            return ("My database is empty. Run the sync first, then challenge "
                    "me again.")
        return ("Excellent. Think of a Pokemon and I will identify it. "
                "Answer yes, no, or skip. " + self.next_question())

    def next_question(self):
        if (len(self.candidates) <= 2
                or self.questions_asked >= self.MAX_QUESTIONS
                or (q := self._pick_question()) is None):
            return self._make_guess()
        self.pending = q
        self.asked_keys.add(q[0])
        self.questions_asked += 1
        return f"Question {self.questions_asked}. {q[1]}"

    def _make_guess(self):
        if not self.candidates:
            return ("I am stumped. No Pokemon in my database matches all of "
                    "your answers. Either it is beyond my records, or one "
                    "answer led me astray.")
        self.candidates.sort(key=lambda r: r["id"])
        guess = self.candidates.pop(0)
        self.last_guess = guess
        self.pending = ("guess", None, None)
        return (f"I have it. You are thinking of {guess['display_name']}, "
                f"the {guess.get('genus') or 'Pokemon'}. Am I correct?")

    def answer(self, text):
        """Feed the user's spoken reply; returns Dexter's next line.
        Returns (line, done, revealed_entry)."""
        verdict = parse_yes_no(text)
        if self.pending and self.pending[0] == "guess":
            if verdict == "yes":
                return ("Naturally. My analysis is never wrong for long.",
                        True, self.last_guess)
            if verdict == "no":
                if self.candidates:
                    return (self._make_guess(), False, None)
                return ("Then I concede. Your Pokemon has eluded my "
                        "database.", True, None)
            return ("Was my identification correct? Yes or no.", False, None)

        if self.pending is None:
            return (self.start(), False, None)
        if verdict is None:
            return ("Please answer yes, no, or skip. "
                    + f"Again: {self.pending[1]}", False, None)
        key, _label, pred = self.pending
        if verdict == "yes":
            self.candidates = [r for r in self.candidates if pred(r)]
        elif verdict == "no":
            self.candidates = [r for r in self.candidates if not pred(r)]
        # 'skip' keeps the candidate list; the key is already marked asked
        return (self.next_question(), False, None)


class DexterBrain:
    """Routes each utterance: game control, dex lookup, or Claude Q&A."""

    START_GAME = re.compile(
        r"(thinking of|guess (the |my |which )?pok|20 questions|"
        r"twenty questions|guessing game|identify (the|my|which)|who am i thinking)",
        re.I)

    def __init__(self, cfg):
        self.cfg = cfg
        self.game = None
        self._client = None
        self._history = []

    # ------------------------------------------------------------- routes ---

    def handle(self, text):
        """-> (spoken_reply, entry_to_show_or_None).

        Priority: active game -> game start -> local knowledge engine
        (instant, offline: types, weaknesses, strengths, abilities, stats,
        evolution, matchups, comparisons) -> Claude for everything else.
        """
        text = (text or "").strip()
        if not text:
            return "I did not catch that. Speak clearly into my sensor.", None

        if self.game is not None:
            if any(w in text.lower() for w in QUIT_WORDS):
                self.game = None
                return "Very well. The game is abandoned. Ask me anything.", None
            line, done, revealed = self.game.answer(text)
            entry = revealed
            if (entry is None and self.game.pending
                    and self.game.pending[0] == "guess"):
                entry = self.game.last_guess  # flash the face of each guess
            if done:
                self.game = None
            return line, entry

        if self.START_GAME.search(text):
            self.game = GuessGame()
            return self.game.start(), None

        local = self._try_local(text)
        if local is not None:
            return local

        entry = dexter_data.find_named_in(text)
        return self._ask_claude(text, entry), entry

    # ---------------------------------------------- local knowledge engine ---

    TYPE_RE = "|".join(TYPES)

    def _try_local(self, text):
        """Answer common question shapes straight from the database.
        Returns (reply, entry) or None to fall through to Claude."""
        t = text.lower()
        entries = dexter_data.find_all_named_in(text)
        entry = entries[0] if entries else None

        # pure type vs type: "does fire beat grass", "is water good against fire"
        m = re.search(rf"\b({self.TYPE_RE})\b.{{0,20}}?\b(?:beat|good against|"
                      rf"strong against|effective against|work against|"
                      rf"counter)s?\b.{{0,20}}?\b({self.TYPE_RE})\b", t)
        if m and not entries:
            return dexter_types.type_vs_type_sentence(m.group(1), m.group(2)), None

        # two Pokemon named: matchup / comparison questions
        if len(entries) >= 2:
            a, b = entries[0], entries[1]
            if re.search(r"\bfaster|quicker|speed\b", t):
                fast = a if (a["stats"].get("speed", 0)
                             >= b["stats"].get("speed", 0)) else b
                slow = b if fast is a else a
                return (f"{fast['display_name']} is faster, with base speed "
                        f"{fast['stats'].get('speed', 0)} against "
                        f"{slow['stats'].get('speed', 0)}.", fast)
            if re.search(r"\bwin|beat|stronger|better|versus|\bvs\b|against|"
                         r"fight|battle|match", t):
                reply = dexter_types.head_to_head_sentence(a, b)
                shown = a
                if "advantage goes to" in reply:
                    name = reply.rsplit("advantage goes to ", 1)[1].rstrip(".")
                    shown = a if a["display_name"] == name else b
                return reply, shown

        if entry is None:
            return None

        # single Pokemon: intent by keyword
        if re.search(r"\bweak|vulnerab|counter|what beats|how do i beat|"
                     r"take.{0,8}down|resist|immune", t):
            return dexter_types.weakness_sentence(entry), entry
        if re.search(r"\bstrong against|good against|advantage|"
                     r"super effective\b", t):
            return dexter_types.strength_sentence(entry), entry
        if re.search(r"\bwhat type|which type|\btypes?\b.{0,12}\bis\b|"
                     r"\bis\b.{0,20}\btype\b", t):
            return (f"{entry['display_name']} is "
                    f"{dexter_types.type_phrase(entry.get('types') or [])}.",
                    entry)
        if re.search(r"\babilit|power|special skill|hidden abilit", t):
            return self._abilities_sentence(entry), entry
        if re.search(r"\bevolv", t):
            return self._evolution_sentence(entry), entry
        if re.search(r"\bstats?\b|base stat|how fast|how strong|attack stat|"
                     r"defen[cs]e|\bspeed\b|hit points|\bhp\b", t):
            return self._stats_sentence(entry, t), entry
        if re.search(r"\bhow (tall|big|heavy|much)|height|weigh|size\b", t):
            return (f"{entry['display_name']} stands "
                    f"{entry['height_m']:.1f} meters tall and weighs "
                    f"{entry['weight_kg']:.1f} kilograms.", entry)
        if re.search(r"\blegendary|mythical\b", t):
            kind = ("a mythical Pokemon" if entry.get("is_mythical")
                    else "a legendary Pokemon" if entry.get("is_legendary")
                    else "not legendary or mythical")
            return f"{entry['display_name']} is {kind}.", entry
        if re.search(r"\btell me about|who is|describe|what is\b", t):
            return self.describe(entry), entry
        # bare name ("pikachu") with no question words: recite the entry
        if not re.search(r"\b(what|who|why|how|when|where|which|does|can|"
                         r"should|compare|explain)\b", t):
            return self.describe(entry), entry
        return None  # a real question we can't parse -> Claude, with context

    def _abilities_sentence(self, entry):
        abilities = entry.get("abilities") or []
        if not abilities:
            return (f"My ability records for {entry['display_name']} are "
                    "missing. Run the database sync again to add them.")
        parts = []
        for ab in abilities:
            info = dexter_data.get_ability(ab["name"]) or {}
            name = info.get("display_name") or ab["name"].replace("-", " ").title()
            label = "Its hidden ability is" if ab.get("hidden") else \
                ("Its ability is" if not parts else "It can also have")
            line = f"{label} {name}."
            if info.get("effect"):
                line += f" {info['effect']}"
            parts.append(line)
        return f"{entry['display_name']}. " + " ".join(parts)

    def _evolution_sentence(self, entry):
        parts = []
        if entry.get("evolves_from"):
            parent = dexter_data.get(entry["evolves_from"])
            parent_name = (parent["display_name"] if parent
                           else entry["evolves_from"].title())
            parts.append(f"{entry['display_name']} evolves from {parent_name}.")
        nexts = dexter_data.evolves_into(entry)
        if nexts:
            joined = " or ".join(nexts)
            parts.append(f"It evolves into {joined}.")
        if not parts:
            return f"{entry['display_name']} does not evolve."
        if not nexts:
            parts.append("It is the final form of its line.")
        return " ".join(parts)

    STAT_WORDS = {"speed": "speed", "fast": "speed", "attack": "attack",
                  "defense": "defense", "defence": "defense", "hp": "hp",
                  "health": "hp", "hit points": "hp"}

    def _stats_sentence(self, entry, t):
        stats = entry.get("stats") or {}
        if "special attack" in t or "sp atk" in t or "special-attack" in t:
            return (f"{entry['display_name']}'s base special attack is "
                    f"{stats.get('special-attack', 0)}.")
        if "special defense" in t or "sp def" in t:
            return (f"{entry['display_name']}'s base special defense is "
                    f"{stats.get('special-defense', 0)}.")
        for word, key in self.STAT_WORDS.items():
            if word in t:
                return (f"{entry['display_name']}'s base {key} is "
                        f"{stats.get(key, 0)}.")
        total = sum(stats.values())
        listing = ", ".join(
            f"{label} {stats.get(key, 0)}"
            for key, label in (("hp", "HP"), ("attack", "attack"),
                               ("defense", "defense"),
                               ("special-attack", "special attack"),
                               ("special-defense", "special defense"),
                               ("speed", "speed")))
        return f"{entry['display_name']}'s base stats. {listing}. Total, {total}."

    # -------------------------------------------------------- dex entries ---

    @staticmethod
    def describe(entry):
        """A spoken dex entry in the show's cadence."""
        types = " and ".join(t.title() for t in (entry.get("types") or []))
        flavor = ""
        if entry.get("flavor"):
            flavor = entry["flavor"][-1]["text"]
        parts = [f"{entry['display_name']}.",
                 f"The {entry.get('genus') or 'Pokemon'}."]
        if types:
            parts.append(f"{_a(types).capitalize()} {types} type.")
        parts.append(f"Height, {entry['height_m']:.1f} meters. "
                     f"Weight, {entry['weight_kg']:.1f} kilograms.")
        if flavor:
            parts.append(flavor)
        return " ".join(parts)

    # ------------------------------------------------------------- claude ---

    def _ensure_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.cfg["anthropic_api_key"])
        return self._client

    SYSTEM = (
        "You are Dexter, the Pokedex from the Pokemon animated series. Speak "
        "in short, flat, encyclopedic sentences with dry confidence, exactly "
        "like a handheld device reciting an entry. Your replies are spoken "
        "aloud: plain text only, no markdown, no symbols, no lists, two to "
        "five sentences. You know Pokemon deeply. When database context is "
        "provided, treat it as ground truth. If asked about anything other "
        "than Pokemon, note dryly that you are a Pokedex, not a general "
        "encyclopedia, but answer briefly if you can.")

    def _ask_claude(self, text, entry=None):
        if not self.cfg.get("anthropic_api_key"):
            if entry:
                return self.describe(entry)
            return ("That question is beyond my local circuits, and I have "
                    "no Anthropic API key configured for deeper analysis. "
                    "Ask me about a Pokemon's type, weaknesses, strengths, "
                    "abilities, stats, or evolution, and I will answer from "
                    "my own database.")
        try:
            client = self._ensure_client()
            content = text
            if entry:
                slim = {k: entry.get(k) for k in
                        ("id", "display_name", "genus", "types", "stats",
                         "height_m", "weight_kg", "color", "habitat",
                         "is_legendary", "is_mythical", "generation",
                         "evolves_from")}
                slim["flavor"] = [f["text"] for f in (entry.get("flavor") or [])[-3:]]
                slim["abilities"] = entry.get("abilities")
                slim["evolves_into"] = dexter_data.evolves_into(entry)
                prof = dexter_types.defense_profile(entry.get("types") or [])
                slim["takes_4x_from"] = prof[4.0]
                slim["weak_to"] = prof[2.0]
                slim["resists"] = prof[0.5] + prof[0.25]
                slim["immune_to"] = prof[0.0]
                content = (f"Database context: {json.dumps(slim)}\n\n"
                           f"Trainer asks: {text}")
            self._history.append({"role": "user", "content": content})
            self._history = self._history[-12:]
            resp = client.messages.create(
                model=self.cfg.get("claude_model", "claude-sonnet-5"),
                max_tokens=400,
                system=self.SYSTEM,
                messages=self._history)
            reply = "".join(b.text for b in resp.content if b.type == "text").strip()
            self._history.append({"role": "assistant", "content": reply})
            return reply or "My processor returned nothing. Curious."
        except Exception as exc:
            self._history = []
            if entry:
                return self.describe(entry)
            return f"My uplink failed. {type(exc).__name__}. Try again shortly."
