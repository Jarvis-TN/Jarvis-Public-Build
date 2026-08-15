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

TYPES = ["normal", "fire", "water", "electric", "grass", "ice", "fighting",
         "poison", "ground", "flying", "psychic", "bug", "rock", "ghost",
         "dragon", "dark", "steel", "fairy"]

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
        """-> (spoken_reply, entry_to_show_or_None)."""
        text = (text or "").strip()
        if not text:
            return "I did not catch that. Speak clearly into my sensor.", None

        if self.game is not None:
            if any(w in text.lower() for w in QUIT_WORDS):
                self.game = None
                return "Very well. The game is abandoned. Ask me anything.", None
            line, done, revealed = self.game.answer(text)
            if done:
                self.game = None
            return line, revealed

        if self.START_GAME.search(text):
            self.game = GuessGame()
            return self.game.start(), None

        entry = dexter_data.find_named_in(text)
        wants_more = re.search(r"\b(what|who|why|how|tell|explain|compare|"
                               r"strong|weak|against|evolve|best|better)\b",
                               text, re.I)
        if entry and not wants_more:
            return self.describe(entry), entry
        return self._ask_claude(text, entry), entry

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
            return ("I need an Anthropic API key in my configuration for "
                    "open questions. Name a Pokemon and I will recite its "
                    "entry from my database.")
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
