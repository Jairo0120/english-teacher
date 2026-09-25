"""Practice types. Each one decides how the session starts, what the tutor receives and what to track.

A practice works in one of two ways:
- Single call (e.g. Conversation): `wrap` builds the message and the tutor answers with
  CORRECTION/NATURAL/WHY/REPLY fields in one go.
- Graded (e.g. PhrasalVerbs): `grade` evaluates the sentence with a separate structured call,
  then `reply_instruction` tells the tutor exactly what to say, and the whole answer is spoken.
  Smaller models are much more reliable when grading and talking are separate tasks.

To add a new practice: subclass Practice, write prompts/<prompt>.md and register it in PRACTICES.
"""

import json
import random
from datetime import datetime
from pathlib import Path

from english_teacher.llm import Feedback, Tutor, load_prompt

ROOT = Path(__file__).resolve().parents[2]


class Practice:
    key = ""
    title = ""
    description = ""
    prompt = ""
    greeting = ""  # fixed first line, when the tutor doesn't generate the opening

    def system_prompt(self) -> str:
        return load_prompt(self.prompt)

    def opening(self) -> str | None:
        """Hidden instruction that makes the tutor open the session, or None to use `greeting`."""
        return None

    def wrap(self, sentence: str) -> str:
        """Single-call practices: message actually sent to the tutor for the student's sentence."""
        return sentence

    def grade(self, tutor: Tutor, sentence: str) -> Feedback | None:
        """Graded practices: evaluate the sentence. None means this practice uses a single call."""
        return None

    def reply_instruction(self, sentence: str, fb: Feedback) -> str:
        """Graded practices: what the tutor must say after grading (called before `after`)."""
        raise NotImplementedError

    def status(self) -> str | None:
        """Short text shown next to the prompt (e.g. the current target)."""
        return None

    def after(self, fb: Feedback) -> None:
        """Update the practice state once the tutor has answered the student."""

    def follow_up(self, fb: Feedback) -> str | None:
        """Hidden instruction for an extra tutor turn after `after`, e.g. to resync the exercise."""
        return None

    def summary(self) -> str | None:
        return None


class Conversation(Practice):
    key = "conversation"
    title = "Conversación libre"
    description = "Charla sobre cualquier tema; corrige gramática y naturalidad."
    prompt = "conversation"
    greeting = "Hi! I'm your English tutor. What would you like to talk about today?"


class PhrasalVerbs(Practice):
    key = "phrasal-verbs"
    title = "Phrasal verbs"
    description = "El tutor explica un phrasal verb en inglés y tú creas una frase con él."
    prompt = "phrasal_verbs"
    max_attempts = 2

    def __init__(
        self,
        verbs_path: Path = ROOT / "data" / "phrasal_verbs.txt",
        progress_path: Path = ROOT / "progress" / "phrasal_verbs.json",
    ):
        lines = verbs_path.read_text(encoding="utf-8").splitlines()
        self.verbs = [v.strip() for v in lines if v.strip() and not v.startswith("#")]
        self.progress_path = progress_path
        self.progress: dict[str, dict] = (
            json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
        )
        self.current = self._pick(exclude=set())
        self.next = self._pick(exclude={self.current})
        self.attempt = 1
        self.advanced = False  # whether the last answer moved the exercise to a new verb
        self.done: list[tuple[str, bool]] = []  # (verb, got it right) in this session

    def opening(self) -> str:
        return f"[Introduce the phrasal verb: {self.current}]"

    def grade(self, tutor: Tutor, sentence: str) -> Feedback:
        d = tutor.structured(
            load_prompt("phrasal_verbs_grader"),
            f"Target: {self.current} | Student: {sentence}",
            GRADER_SCHEMA,
        )
        words = str(d.get("verb_words", "")).strip()
        correct = bool(words) and bool(d.get("meaning_ok"))
        return Feedback(
            correction=str(d.get("correction", "")).strip(),
            natural=str(d.get("natural", "")).strip(),
            why=str(d.get("why", "")).strip(),
            result="CORRECT" if correct else "RETRY",
            verb_words=words,
        )

    def reply_instruction(self, sentence: str, fb: Feedback) -> str:
        cur, nxt = self.current, self.next
        said = f'The student said: "{sentence}".'
        if fb.result == "CORRECT":
            return (
                f"[{said} They used {cur} correctly. Praise them in one short sentence, "
                f"then introduce the next phrasal verb: {nxt}.]"
            )
        problem = (
            f"they used {fb.verb_words} with the wrong meaning" if fb.verb_words
            else f"they did not use {cur}"
        )
        if self.attempt < self.max_attempts:
            return (
                f"[{said} It is not right yet: {problem}. Give a short hint without saying a full correct "
                f"sentence, and ask them to try again with {cur}.]"
            )
        return (
            f"[{said} It is not right yet: {problem}. That was the last attempt: say one correct example "
            f"sentence with {cur}, then introduce the next phrasal verb: {nxt}.]"
        )

    def follow_up(self, fb: Feedback) -> str | None:
        """If the tutor didn't introduce the verb the app moved on to, ask it to do so now."""
        if self.advanced and self.current.lower() not in fb.reply.lower():
            return self.opening()
        return None

    def status(self) -> str:
        return f"{self.current} · intento {self.attempt}/{self.max_attempts}"

    def after(self, fb: Feedback) -> None:
        correct = fb.result == "CORRECT"
        self._record(self.current, correct)
        self.advanced = correct or self.attempt >= self.max_attempts
        if self.advanced:
            # The tutor has already introduced self.next in its reply
            self.done.append((self.current, correct))
            self.current, self.attempt = self.next, 1
            self.next = self._pick(exclude={self.current})
        else:
            self.attempt += 1

    def summary(self) -> str | None:
        if not self.done:
            return None
        right = [v for v, ok in self.done if ok]
        missed = [v for v, ok in self.done if not ok]
        text = f"Phrasal verbs practicados: {len(self.done)} · bien: {len(right)}"
        if missed:
            text += f" · a repasar: {', '.join(missed)}"
        return text

    def _pick(self, exclude: set[str]) -> str:
        """Prefer verbs never practiced, then the ones with the lowest success rate, oldest first."""

        def score(verb: str) -> tuple:
            p = self.progress.get(verb)
            if not p:
                return (0, 0.0, "")
            return (1, p["correct"] / p["attempts"], p["last"])

        candidates = [v for v in self.verbs if v not in exclude]
        random.shuffle(candidates)  # sort is stable: shuffle first so ties (e.g. all unseen) come out random
        candidates.sort(key=score)
        return random.choice(candidates[:5])  # a bit of variety among the top candidates

    def _record(self, verb: str, correct: bool) -> None:
        p = self.progress.setdefault(verb, {"attempts": 0, "correct": 0, "last": ""})
        p["attempts"] += 1
        p["correct"] += int(correct)
        p["last"] = datetime.now().isoformat(timespec="seconds")
        self.progress_path.parent.mkdir(exist_ok=True)
        self.progress_path.write_text(json.dumps(self.progress, indent=2, ensure_ascii=False), encoding="utf-8")


GRADER_SCHEMA = {
    "type": "object",
    "properties": {
        "verb_words": {"type": "string"},
        "meaning_ok": {"type": "boolean"},
        "correction": {"type": "string"},
        "natural": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["verb_words", "meaning_ok", "correction", "natural", "why"],
}

PRACTICES: dict[str, type[Practice]] = {p.key: p for p in (Conversation, PhrasalVerbs)}
