"""Practice types. Each one decides how the session starts, what the tutor receives and what to track.

A practice works in one of two ways:
- Single call (e.g. Conversation): `wrap` builds the message and the tutor answers with
  CORRECTION/NATURAL/WHY/REPLY fields in one go.
- Graded (e.g. PhrasalVerbs, RolePlay): `grade` evaluates the sentence with a separate structured
  call, then `reply_instruction` tells the tutor exactly what to say, and the whole answer is spoken.
  Smaller models are much more reliable when grading and talking are separate tasks.

Optional hooks: `setup` (interactive choices before the session), `intro` (fixed narrator text),
`voice` (voice for the tutor's replies), `finished` (end the session), `help_context` (the "h"
command) and `debrief` (review at the end).

To add a new practice: subclass Practice, write prompts/<prompt>.md and register it in PRACTICES.
"""

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from english_teacher.levels import LEVELS, Level, render
from english_teacher.llm import Feedback, Tutor, load_prompt

ROOT = Path(__file__).resolve().parents[2]


class Practice:
    key = ""
    title = ""
    description = ""
    prompt = ""
    voice: str | None = None  # voice for the tutor's replies; None = the narrator's
    finished = False  # set to True to end the session
    grade_after_reply = False  # the reply doesn't depend on the grade: speak first, grade while it plays

    def __init__(self, level: Level = LEVELS["B2"]):
        self.level = level

    def setup(self, model: str) -> None:
        """Interactive choices before the session starts (e.g. pick a scene)."""

    def system_prompt(self) -> str:
        return render(load_prompt(self.prompt), self.level)

    def intro(self) -> str | None:
        """Fixed text the narrator says first."""
        return None

    def opening(self) -> str | None:
        """Hidden instruction that makes the tutor open the session (after `intro`)."""
        return None

    def heard(self, text: str) -> None:
        """Called with everything the tutor says out loud."""

    def wrap(self, sentence: str) -> str:
        """Single-call practices: message actually sent to the tutor for the student's sentence."""
        return sentence

    def grade(self, tutor: Tutor, sentence: str) -> Feedback | None:
        """Graded practices: evaluate the sentence. None means this practice uses a single call."""
        return None

    def reply_instruction(self, sentence: str, fb: Feedback | None) -> str:
        """Graded practices: what the tutor must say (called before `after`).

        fb is None when `grade_after_reply` is set, since grading happens after the reply.
        """
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

    def help_context(self, last_line: str) -> str | None:
        """Situation described to the model for the "h" command; None disables it."""
        return None

    def help(self, tutor: Tutor, last_line: str) -> list[str] | None:
        """Three things the student could say next."""
        context = self.help_context(last_line)
        if context is None:
            return None
        prompt = render(load_prompt("help"), self.level, context=context)
        d = tutor.structured(prompt, "Suggestions, please.", HELP_SCHEMA)
        return [str(d[k]).strip() for k in ("option_1", "option_2", "option_3") if str(d.get(k, "")).strip()]

    def debrief(self, tutor: Tutor) -> "Debrief | None":
        """Review shown and spoken at the end of the session."""
        return None


@dataclass
class Debrief:
    spoken: str  # said aloud by the narrator
    lines: list[str]  # printed and logged


class Conversation(Practice):
    key = "conversation"
    title = "Conversación libre"
    description = "Charla sobre cualquier tema; corrige gramática y naturalidad."
    prompt = "conversation"

    def intro(self) -> str:
        return "Hi! I'm your English tutor. What would you like to talk about today?"

    def help_context(self, last_line: str) -> str:
        return f"A casual conversation with an English tutor. The tutor just said: {last_line}"


class PhrasalVerbs(Practice):
    key = "phrasal-verbs"
    title = "Phrasal verbs"
    description = "El tutor explica un phrasal verb en inglés y tú creas una frase con él."
    prompt = "phrasal_verbs"
    max_attempts = 2

    def __init__(
        self,
        level: Level = LEVELS["B2"],
        verbs_paths: list[Path] | None = None,
        progress_path: Path = ROOT / "progress" / "phrasal_verbs.json",
    ):
        super().__init__(level)
        paths = verbs_paths or [ROOT / "data" / name for name in level.phrasal_lists]
        lines = [line for path in paths for line in path.read_text(encoding="utf-8").splitlines()]
        self.verbs = list(dict.fromkeys(v.strip() for v in lines if v.strip() and not v.startswith("#")))
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
        if self.level.strict_grading:
            correct = correct and bool(d.get("natural_use"))
        return Feedback(
            correction=str(d.get("correction", "")).strip(),
            natural=str(d.get("natural", "")).strip(),
            why=str(d.get("why", "")).strip(),
            result="CORRECT" if correct else "RETRY",
            verb_words=words,
            meaning_ok=bool(d.get("meaning_ok")),
        )

    def reply_instruction(self, sentence: str, fb: Feedback) -> str:
        cur, nxt = self.current, self.next
        said = f'The student said: "{sentence}".'
        if fb.result == "CORRECT":
            return (
                f"[{said} They used {cur} correctly. Praise them in one short sentence, "
                f"then introduce the next phrasal verb: {nxt}.]"
            )
        if not fb.verb_words:
            problem = f"they did not use {cur}"
        elif fb.meaning_ok:
            problem = f"the meaning of {fb.verb_words} is right, but a native speaker wouldn't use it like that"
        else:
            problem = f"they used {fb.verb_words} with the wrong meaning"
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


@dataclass
class Scenario:
    title: str  # Spanish, for the menu
    name: str  # the character's role, e.g. Receptionist
    character: str
    voice: str
    student_role: str
    setting: str
    goal: str
    twists: list[str]

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(**{field: data[field] for field in cls.__dataclass_fields__})


def load_scenarios(directory: Path = ROOT / "data" / "scenarios") -> list[Scenario]:
    return sorted((Scenario.load(p) for p in directory.glob("*.yaml")), key=lambda s: s.title)


# Character voices for invented scenes (af_heart is the narrator)
CHARACTER_VOICES = {
    "female": ["af_bella", "af_nicole", "af_sarah", "bf_emma", "bf_isabella"],
    "male": ["am_michael", "am_fenrir", "am_puck", "bm_george", "bm_fable"],
}


class RolePlay(Practice):
    key = "roleplay"
    title = "Roleplay"
    description = "El tutor plantea una escena y hablas con un personaje para conseguir un objetivo."
    prompt = "roleplay"
    grade_after_reply = True
    max_turns = 12
    twist_turns = (3, 6)  # student turns after which the character brings in each twist

    def __init__(self, level: Level = LEVELS["B2"], scenario: Scenario | None = None):
        super().__init__(level)
        self.scenario = scenario
        self.last_line = ""
        self.pending = ""  # sentence being graded, stored in `after`
        self.turns: list[tuple[str, Feedback]] = []
        self.goal_met = False

    # --- setup -------------------------------------------------------------

    def setup(self, model: str) -> None:
        if self.scenario:
            return
        scenarios = load_scenarios()
        print("\n¿Qué escena quieres?")
        for i, sc in enumerate(scenarios, 1):
            print(f"  {i:2}. {sc.title}")
        print("   i. Inventar una escena nueva")
        while True:
            choice = input("› ").strip().lower()
            if choice.isdigit() and 1 <= int(choice) <= len(scenarios):
                self.scenario = scenarios[int(choice) - 1]
                return
            if choice == "i":
                topic = input("Tema (opcional, Enter para cualquiera) › ").strip()
                print("Inventando la escena...")
                self.scenario = self.invent(Tutor("", model), topic)
                return

    def invent(self, tutor: Tutor, topic: str = "") -> Scenario:
        request = f"Create a scene about: {topic}" if topic else "Create an original everyday scene."
        d = tutor.structured(render(load_prompt("roleplay_invent"), self.level), request, INVENT_SCHEMA)
        return Scenario(
            title=d["title"], name=d["name"], character=d["character"],
            voice=random.choice(CHARACTER_VOICES.get(d.get("gender"), CHARACTER_VOICES["female"])),
            student_role=d["student_role"], setting=d["setting"], goal=d["goal"], twists=list(d["twists"])[:2],
        )

    # --- scene -------------------------------------------------------------

    @property
    def voice(self) -> str | None:
        return self.scenario.voice if self.scenario else None

    def system_prompt(self) -> str:
        sc = self.scenario
        return render(
            load_prompt(self.prompt), self.level,
            character_desc=sc.character, student_role=sc.student_role, setting=sc.setting, goal=sc.goal,
        )

    def intro(self) -> str:
        sc = self.scenario
        return (
            f"Here's the scene. {sc.setting} Your role: {sc.student_role} "
            f"Your goal: {sc.goal} The {sc.name.lower()} will start."
        )

    def opening(self) -> str:
        return "[Director: start the scene now. Speak first, in character, in 1-2 sentences.]"

    def heard(self, text: str) -> None:
        self.last_line = text

    def status(self) -> str:
        return f"{self.scenario.name} · turno {len(self.turns) + 1}/{self.max_turns}"

    # --- turns -------------------------------------------------------------

    def grade(self, tutor: Tutor, sentence: str) -> Feedback:
        sc = self.scenario
        self.pending = sentence
        d = tutor.structured(
            render(load_prompt("roleplay_grader"), self.level),
            f"Scene: {sc.setting}\nStudent's goal: {sc.goal}\n{sc.name} said: {self.last_line}\nStudent: {sentence}",
            ROLEPLAY_GRADER_SCHEMA,
        )
        return Feedback(
            correction=str(d.get("correction", "")).strip(),
            natural=str(d.get("natural", "")).strip(),
            why=str(d.get("why_es", "")).strip(),
            goal_met=bool(d.get("goal_met")),
        )

    def reply_instruction(self, sentence: str, fb: Feedback | None = None) -> str:
        # When the grade says the goal was met, the scene simply ends after this reply (see `after`)
        turn = len(self.turns) + 1
        if turn >= self.max_turns:
            note = "[Director: time is up. Answer them, then bring the scene to a natural end in 1-2 sentences.]"
        elif turn in self.twist_turns[: len(self.scenario.twists)]:
            twist = self.scenario.twists[self.twist_turns.index(turn)]
            note = f"[Director: answer them, and bring in this complication naturally: {twist}]"
        else:
            return sentence
        return f"{sentence}\n\n{note}"

    def after(self, fb: Feedback) -> None:
        self.turns.append((self.pending, fb))
        self.goal_met = self.goal_met or fb.goal_met
        self.finished = fb.goal_met or len(self.turns) >= self.max_turns

    def summary(self) -> str | None:
        if not self.turns:
            return None
        result = "conseguido ✅" if self.goal_met else "no conseguido"
        return f"Escena: {self.scenario.title} · objetivo {result} · {len(self.turns)} turnos"

    def help_context(self, last_line: str) -> str:
        sc = self.scenario
        return (
            f"A role-play. {sc.setting} The student plays: {sc.student_role} Their goal: {sc.goal} "
            f"The {sc.name.lower()} just said: {last_line}"
        )

    def debrief(self, tutor: Tutor) -> Debrief | None:
        if not self.turns:
            return None
        sc = self.scenario
        transcript = "\n".join(
            f"- Student: {sentence} | correction: {fb.correction or 'OK'} | natural: {fb.natural or 'OK'}"
            for sentence, fb in self.turns
        )
        d = tutor.structured(
            render(load_prompt("roleplay_debrief"), self.level),
            f"Scene: {sc.setting}\nStudent's goal: {sc.goal}\n"
            f"Goal achieved: {'yes' if self.goal_met else 'no'}\n\nWhat the student said:\n{transcript}",
            DEBRIEF_SCHEMA,
        )
        lines = []
        if d.get("mistakes"):
            lines.append("Errores a repasar:")
            lines += [f"  • {m['pattern']}: {m['example']} → {m['fix']}" for m in d["mistakes"][:3]]
        if d.get("phrases"):
            lines.append("Expresiones útiles para esta situación:")
            lines += [f"  • {ph['phrase']} — {ph['meaning']}" for ph in d["phrases"][:5]]
        return Debrief(spoken=str(d.get("spoken", "")).strip(), lines=lines)


# Three separate fields: with an array, Gemma sometimes returns a single long suggestion
HELP_SCHEMA = {
    "type": "object",
    "properties": {"option_1": {"type": "string"}, "option_2": {"type": "string"}, "option_3": {"type": "string"}},
    "required": ["option_1", "option_2", "option_3"],
}

ROLEPLAY_GRADER_SCHEMA = {
    "type": "object",
    "properties": {
        "correction": {"type": "string"},
        "natural": {"type": "string"},
        "why_es": {"type": "string"},
        "goal_met": {"type": "boolean"},
    },
    "required": ["correction", "natural", "why_es", "goal_met"],
}

DEBRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "spoken": {"type": "string"},
        "mistakes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}, "example": {"type": "string"}, "fix": {"type": "string"}},
                "required": ["pattern", "example", "fix"],
            },
        },
        "phrases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"phrase": {"type": "string"}, "meaning": {"type": "string"}},
                "required": ["phrase", "meaning"],
            },
        },
    },
    "required": ["spoken", "mistakes", "phrases"],
}

INVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "name": {"type": "string"},
        "character": {"type": "string"},
        "gender": {"type": "string", "enum": ["female", "male"]},
        "student_role": {"type": "string"},
        "setting": {"type": "string"},
        "goal": {"type": "string"},
        "twists": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "name", "character", "gender", "student_role", "setting", "goal", "twists"],
}

GRADER_SCHEMA = {
    "type": "object",
    "properties": {
        "verb_words": {"type": "string"},
        "meaning_ok": {"type": "boolean"},
        "natural_use": {"type": "boolean"},
        "correction": {"type": "string"},
        "natural": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["verb_words", "meaning_ok", "natural_use", "correction", "natural", "why"],
}

PRACTICES: dict[str, type[Practice]] = {p.key: p for p in (Conversation, PhrasalVerbs, RolePlay)}
