"""Practice types. Each one decides how the session starts, what the tutor receives and what to track.

A practice works in one of two ways:
- Single call (e.g. Conversation): `wrap` builds the message and the tutor answers with
  CORRECTION/NATURAL/WHY/REPLY fields in one go.
- Graded (e.g. PhrasalVerbs, RolePlay): `grade` evaluates the sentence with a separate structured
  call, then `reply_instruction` tells the tutor exactly what to say, and the whole answer is spoken.
  Smaller models are much more reliable when grading and talking are separate tasks.

Optional hooks: `setup` (interactive choices before the session), `intro` (fixed narrator text),
`announce` (text shown on screen before each turn), `prepare` + `round_pending`/`next_round` (the
practice presents new material, e.g. a text to listen to, when the student presses Enter),
`voice` (voice for the tutor's replies), `finished` (end the session), `help_context` (the "h"
command) and `debrief` (review at the end).

To add a new practice: subclass Practice, write prompts/<prompt>.md and register it in PRACTICES.
"""

import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
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

    def announce(self) -> str | None:
        """Text shown on screen (not spoken) before each student turn, e.g. a sentence to translate."""
        return None

    round_prompt = "Enter para continuar"

    def prepare(self, tutor: Tutor) -> None:
        """Called once the tutor is ready, before the intro (e.g. to start generating material)."""

    def round_pending(self) -> bool:
        """True when the practice must present new material (after the student presses Enter)."""
        return False

    def next_round(self, tutor: Tutor) -> str:
        """The new material, spoken by the narrator but not shown on screen."""
        raise NotImplementedError

    def late_feedback(self) -> list[str]:
        """Feedback prepared in the background after the reply, shown before the next round."""
        return []

    def wrap(self, sentence: str) -> str:
        """Single-call practices: message actually sent to the tutor for the student's sentence."""
        return sentence

    def grade(self, tutor: Tutor, sentence: str) -> Feedback | None:
        """Graded practices: evaluate the sentence. None means this practice uses a single call."""
        return None

    def quick_reply(self, sentence: str, fb: Feedback) -> str | None:
        """Graded practices: fixed text spoken right after grading, before (or instead of) the model's reply."""
        return None

    def reply_instruction(self, sentence: str, fb: Feedback | None) -> str | None:
        """Graded practices: what the tutor must say (called before `after`). None: nothing more to say.

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


class Progress:
    """Per-item success history saved as JSON; picks what to practice next."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def pick(self, items: list[str], exclude: set[str] = frozenset(), top: int = 5) -> str:
        """Prefer items never practiced, then the ones with the lowest success rate, oldest first."""

        def score(item: str) -> tuple:
            p = self.data.get(item)
            if not p:
                return (0, 0.0, "")
            return (1, p["correct"] / p["attempts"], p["last"])

        candidates = [i for i in items if i not in exclude] or list(items)
        random.shuffle(candidates)  # sort is stable: shuffle first so ties (e.g. all unseen) come out random
        candidates.sort(key=score)
        return random.choice(candidates[:top])  # a bit of variety among the top candidates

    def record(self, item: str, correct: bool) -> None:
        p = self.data.setdefault(item, {"attempts": 0, "correct": 0, "last": ""})
        p["attempts"] += 1
        p["correct"] += int(correct)
        p["last"] = datetime.now().isoformat(timespec="seconds")
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")


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
        self.progress = Progress(progress_path)
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
        self.progress.record(self.current, correct)
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
        return self.progress.pick(self.verbs, exclude)


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


@dataclass
class Structure:
    key: str
    name: str  # English, for the tutor and grader
    name_es: str  # Spanish, for the screen
    level: str
    hint: str  # what kind of question makes the structure necessary
    translations: list[dict]  # {"es": ..., "en": ...}


def _spoken(name: str) -> str:
    """Structure name as the voice should say it: "wish / if only (x)" -> "wish or if only"."""
    return re.sub(r"\s*\(.*?\)", "", name).replace(" / ", " or ")


def _is_ok(value: str) -> bool:
    return value.strip().strip(".").upper() in ("", "OK")


def load_structures(path: Path = ROOT / "data" / "tenses.yaml") -> list[Structure]:
    return [Structure(**item) for item in yaml.safe_load(path.read_text(encoding="utf-8"))]


@dataclass
class TenseItem:
    structure: Structure
    mode: str  # "question" (answer freely) or "translation" (from Spanish)
    es: str = ""
    en: str = ""


class Tenses(Practice):
    key = "tenses"
    title = "Tiempos verbales"
    description = "Respondes preguntas y traduces frases del español que obligan a usar tiempos complejos."
    prompt = "tenses"
    max_attempts = 2

    def __init__(
        self,
        level: Level = LEVELS["B2"],
        structures: list[Structure] | None = None,
        progress_path: Path = ROOT / "progress" / "tenses.json",
        diagnostic: bool | None = None,  # None: ask in setup()
    ):
        super().__init__(level)
        allowed = {"B1"} if level.name == "B1" else {"B1", "B2", "C1"}
        self.structures = [st for st in (structures or load_structures()) if st.level in allowed]
        self.by_key = {st.key: st for st in self.structures}
        self.progress = Progress(progress_path)
        self.diagnostic = diagnostic
        self.queue: list[TenseItem] = []  # diagnostic: one item per structure
        self.used: set[str] = set()  # translations already asked in this session
        self._next_mode = random.choice(["question", "translation"])
        self.attempt = 1
        self.last_line = ""  # the tutor's last question, for grading
        self._quick = ""  # fixed reply already spoken this turn
        self.done: list[tuple[Structure, bool]] = []
        if diagnostic is not None:
            self._start()

    def setup(self, model: str) -> None:
        if self.diagnostic is not None:
            return
        if not self.progress.data:
            print(f"\nEs tu primera vez con los tiempos verbales. El diagnóstico prueba una frase de cada "
                  f"estructura ({len(self.structures)}) para saber por dónde empezar.")
            self.diagnostic = input("¿Empezamos con el diagnóstico? [S/n] › ").strip().lower() not in ("n", "no")
        else:
            print("\n  1. Práctica (prioriza lo que más te cuesta)\n  2. Diagnóstico (una frase de cada estructura)")
            self.diagnostic = input("› ").strip() == "2"
        self._start()

    def _start(self) -> None:
        if self.diagnostic:
            order = random.sample(self.structures, len(self.structures))
            self.queue = [self._item(st) for st in order]
            self.current = self.queue.pop(0)
            self.next = self.queue[0] if self.queue else None
        else:
            self.current = self._item()
            self.next = self._item(exclude={self.current.structure.key})

    def _item(self, structure: Structure | None = None, exclude: set[str] = frozenset()) -> TenseItem:
        """Next exercise: the weakest structures first, alternating questions and translations."""
        st = structure or self.by_key[self.progress.pick(list(self.by_key), set(exclude))]
        mode, self._next_mode = self._next_mode, "question" if self._next_mode == "translation" else "translation"
        options = [t for t in st.translations if t["es"] not in self.used]
        if mode == "translation" and options:
            pick = random.choice(options)
            self.used.add(pick["es"])
            return TenseItem(st, "translation", es=pick["es"], en=pick["en"])
        return TenseItem(st, "question")

    # --- what the tutor says ------------------------------------------------
    # Everything except new questions is fixed text: it plays right after grading, and the model
    # can't drift from what the screen shows (e.g. make up a different sentence to translate).

    TRANSLATE = "Now, translate the sentence on your screen into English."

    def intro(self) -> str:
        start = ("Let's do a quick check of a few tenses, to see what to practice." if self.diagnostic
                 else "Let's practice tenses.")
        return f"{start} {self.TRANSLATE}" if self.current.mode == "translation" else start

    def opening(self) -> str | None:
        return None if self.current.mode == "translation" else f"[{self._ask(self.current)}]"

    def _ask(self, item: TenseItem) -> str:
        return (
            f"Ask the student one question that needs the {item.structure.name} in the answer. "
            f"{item.structure.hint} Use the {item.structure.name} in your question too, so the natural answer "
            f"uses it. Ask only the question, in 1-2 sentences, different from any question you asked before."
        )

    def announce(self) -> str | None:
        if self.current and self.current.mode == "translation":
            return f"🇪🇸 Traduce: {self.current.es}"
        return None

    def status(self) -> str:
        name = self.current.structure.name_es
        if self.diagnostic:
            total = len(self.structures)
            return f"Diagnóstico {total - len(self.queue)}/{total} · {name}"
        return f"{name} · intento {self.attempt}/{self.max_attempts}"

    # --- turns ----------------------------------------------------------------

    def grade(self, tutor: Tutor, sentence: str) -> Feedback:
        item = self.current
        if item.mode == "translation":
            content = f"Target: {item.structure.name} | Spanish: {item.es} | Reference: {item.en} | Student: {sentence}"
        else:
            content = f"Target: {item.structure.name} | Question: {self.last_line} | Student: {sentence}"
        d = tutor.structured(render(load_prompt("tenses_grader"), self.level), content, TENSES_GRADER_SCHEMA)
        correct = bool(d.get("target_ok")) and (item.mode == "question" or bool(d.get("meaning_ok")))
        return Feedback(
            correction=str(d.get("correction", "")).strip(),
            natural=str(d.get("natural", "")).strip(),
            why=str(d.get("why_es", "")).strip(),
            result="CORRECT" if correct else "RETRY",
            verb_words=str(d.get("verb_words", "")).strip(),
        )

    def heard(self, text: str) -> None:
        self.last_line = text

    def quick_reply(self, sentence: str, fb: Feedback) -> str:
        item, nxt = self.current, self.next
        name = _spoken(item.structure.name)
        if not self.diagnostic and fb.result != "CORRECT" and self.attempt < self.max_attempts:
            again = "translate it again" if item.mode == "translation" else "answer again"
            self._quick = f"Not quite. You need the {name} here. Try to {again}."
            return self._quick
        if self.diagnostic:
            parts = ["Okay, thanks."]
        elif fb.result == "CORRECT":
            parts = [random.choice(["Great!", "Well done!", "Exactly!", "Nice one!"])]
        else:
            answer = item.en if item.mode == "translation" else (fb.natural if not _is_ok(fb.natural) else fb.correction)
            parts = [f"Not quite. A correct version would be: {answer}" if not _is_ok(answer) else "Not quite."]
        if nxt is None:
            parts.append("That's the end of the check. Thank you!")
        elif nxt.mode == "translation":
            parts.append(self.TRANSLATE)
        self._quick = " ".join(parts)
        return self._quick

    def reply_instruction(self, sentence: str, fb: Feedback | None) -> str | None:
        """Only needed when the next exercise is a new question (called after quick_reply)."""
        staying = not self.diagnostic and fb.result != "CORRECT" and self.attempt < self.max_attempts
        if staying or self.next is None or self.next.mode == "translation":
            return None
        return f'[You have just said: "{self._quick}". Do not repeat it. {self._ask(self.next)}]'

    def after(self, fb: Feedback) -> None:
        correct = fb.result == "CORRECT"
        self.progress.record(self.current.structure.key, correct)
        if correct or self.diagnostic or self.attempt >= self.max_attempts:
            self.done.append((self.current.structure, correct))
            self.attempt = 1
            if self.diagnostic:
                self.current = self.queue.pop(0) if self.queue else None
                self.next = self.queue[0] if self.queue else None
                self.finished = self.current is None
            else:
                self.current = self.next
                self.next = self._item(exclude={self.current.structure.key})
        else:
            self.attempt += 1

    def summary(self) -> str | None:
        if not self.done:
            return None
        right = sum(ok for _, ok in self.done)
        missed = list(dict.fromkeys(st.name_es for st, ok in self.done if not ok))
        head = "Diagnóstico" if self.diagnostic else "Tiempos practicados"
        text = f"{head}: {right}/{len(self.done)} bien"
        if missed:
            text += f" · a repasar: {', '.join(missed)}"
        return text


def reuse_ratio(original: str, retelling: str, n: int = 3) -> float:
    """Share of the retelling's n-word sequences that appear word for word in the original."""

    def grams(text: str) -> set[tuple[str, ...]]:
        words = re.findall(r"[a-z0-9']+", text.lower())
        return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}

    mine = grams(retelling)
    return len(mine & grams(original)) / len(mine) if mine else 0.0


@dataclass
class ListeningText:
    title: str
    text: str
    points: list[str]


class Paraphrase(Practice):
    key = "paraphrase"
    title = "Parafraseo"
    description = "El tutor habla unos 30 segundos sobre un tema y tú lo cuentas con tus propias palabras."
    prompt = "paraphrase"
    round_prompt = "Enter para escuchar el texto"
    words = {"B1": (40, 55), "B2": (60, 75), "C1": (75, 90)}  # ~30 s at each level's voice speed
    kinds = ["a short news report", "an opinion", "a personal anecdote", "a short explanation of how something works"]
    HIGH_REUSE = 0.4

    def __init__(self, level: Level = LEVELS["B2"], topic: str | None = None,
                 topics_path: Path = ROOT / "data" / "paraphrase_topics.txt"):
        super().__init__(level)
        lines = topics_path.read_text(encoding="utf-8").splitlines()
        self.topics = [t.strip() for t in lines if t.strip() and not t.startswith("#")]
        self.topic = topic  # None: ask in setup; "": a different topic each round
        self.current: ListeningText | None = None
        self.titles: list[str] = []  # texts already used in this session, to avoid repeats
        self.results: list[tuple[int, float]] = []  # (key ideas covered, reuse) per round
        self._pending = True
        self._future = None  # next text
        self._review = None  # mistakes + model paraphrase of the last answer
        self._pool = ThreadPoolExecutor(max_workers=1)  # Ollama serves one request at a time anyway

    def setup(self, model: str) -> None:
        if self.topic is None:
            self.topic = input("\nTema (Enter = uno distinto cada vez) › ").strip()

    def intro(self) -> str:
        return ("I'll talk about something for about thirty seconds. Listen carefully, and then tell me "
                "what I said, in your own words. Try not to repeat my exact sentences.")

    # --- rounds ---------------------------------------------------------------

    def prepare(self, tutor: Tutor) -> None:
        self._prefetch(tutor)

    def round_pending(self) -> bool:
        return self._pending

    def next_round(self, tutor: Tutor) -> str:
        if self._future is None:
            self._prefetch(tutor)
        self.current = self._future.result()
        self._future = None
        self.titles.append(self.current.title)
        self._pending = False
        return self.current.text

    def _prefetch(self, tutor: Tutor) -> None:
        """Generate the next text in the background while the student reads the feedback."""
        self._future = self._pool.submit(self._generate, tutor)

    def _generate(self, tutor: Tutor) -> ListeningText:
        topic = self.topic or random.choice([t for t in self.topics if t not in self.titles] or self.topics)
        low, high = self.words.get(self.level.name, self.words["B2"])
        request = f"Topic: {topic}\nKind of text: {random.choice(self.kinds)}"
        if self.titles:
            request += f"\nIt must be different from these earlier texts: {'; '.join(self.titles)}"
        d = tutor.structured(
            render(load_prompt("paraphrase_text"), self.level, words=str(low), max_words=str(high)),
            request, TEXT_SCHEMA,
        )
        return ListeningText(d["title"], d["text"], [d[f"point_{i}"] for i in range(1, 5)])

    def announce(self) -> str | None:
        if self.current and not self._pending:
            return "🎧 Cuenta lo que escuchaste con tus propias palabras (r = volver a escuchar)"
        return None

    def status(self) -> str:
        return f"Texto {len(self.titles)}"

    # --- grading --------------------------------------------------------------

    def grade(self, tutor: Tutor, sentence: str) -> Feedback:
        # Two calls: a short one (ideas covered + spoken comment) so the student hears back quickly,
        # and a longer one (mistakes + model paraphrase) that runs in the background while they listen
        text = self.current
        reuse = reuse_ratio(text.text, sentence)
        points = "\n".join(f"{i}. {p}" for i, p in enumerate(text.points, 1))
        d = tutor.structured(
            render(load_prompt("paraphrase_grader"), self.level),
            f"Original text: {text.text}\n\nKey ideas:\n{points}\n\n"
            f"Copied word for word: {reuse:.0%}\n\nStudent's retelling: {sentence}",
            PARAPHRASE_GRADER_SCHEMA,
        )
        covered = [bool(d.get(f"covered_{i}")) for i in range(1, 5)]
        self.results.append((sum(covered), reuse))
        lines = [f"  📊 Ideas: {sum(covered)}/4 · copiado literal: {reuse:.0%}"
                 + ("  ⚠️ parafrasea más" if reuse > self.HIGH_REUSE else "")]
        lines += [f"     {'✅' if ok else '❌'} {point}" for ok, point in zip(covered, text.points)]
        if wrong := str(d.get("wrong_info", "")).strip():
            lines.append(f"  ⚠️  Dato incorrecto: {wrong}")
        self._review = self._pool.submit(self._make_review, tutor, text.text, sentence)
        self._prefetch(tutor)  # queued after the review: the next text is ready when the student presses Enter
        return Feedback(reply=str(d.get("comment", "")).strip(), lines=lines)

    def _make_review(self, tutor: Tutor, original: str, retelling: str) -> list[str]:
        d = tutor.structured(
            render(load_prompt("paraphrase_review"), self.level),
            f"Original text: {original}\n\nStudent's retelling: {retelling}",
            PARAPHRASE_REVIEW_SCHEMA,
        )
        lines = [f"  ✏️  {m['wrong']} → {m['fix']}" for m in d.get("mistakes", [])[:3]]
        lines.append(f"  💡 Versión modelo: {str(d.get('model', '')).strip()}")
        lines.append(f"  📝 Texto original: {original}")
        return lines

    def late_feedback(self) -> list[str]:
        if self._review is None:
            return []
        lines, self._review = self._review.result(), None
        return lines

    def quick_reply(self, sentence: str, fb: Feedback) -> str:
        return f"{fb.reply} Press Enter when you're ready for the next one."

    def reply_instruction(self, sentence: str, fb: Feedback | None) -> None:
        return None

    def after(self, fb: Feedback) -> None:
        self._pending = True

    def summary(self) -> str | None:
        if not self.results:
            return None
        covered = sum(c for c, _ in self.results)
        reuse = sum(r for _, r in self.results) / len(self.results)
        return (f"Parafraseo: {len(self.results)} textos · ideas cubiertas {covered}/{4 * len(self.results)} "
                f"· copiado literal medio {reuse:.0%}")


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

TENSES_GRADER_SCHEMA = {
    "type": "object",
    "properties": {
        "verb_words": {"type": "string"},
        "target_ok": {"type": "boolean"},
        "meaning_ok": {"type": "boolean"},
        "correction": {"type": "string"},
        "natural": {"type": "string"},
        "why_es": {"type": "string"},
    },
    "required": ["verb_words", "target_ok", "meaning_ok", "correction", "natural", "why_es"],
}

TEXT_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in ("title", "text", "point_1", "point_2", "point_3", "point_4")},
    "required": ["title", "text", "point_1", "point_2", "point_3", "point_4"],
}

PARAPHRASE_GRADER_SCHEMA = {
    "type": "object",
    "properties": {
        **{f"covered_{i}": {"type": "boolean"} for i in range(1, 5)},
        "wrong_info": {"type": "string"},
        "comment": {"type": "string"},
    },
    "required": [*(f"covered_{i}" for i in range(1, 5)), "wrong_info", "comment"],
}

PARAPHRASE_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "mistakes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"wrong": {"type": "string"}, "fix": {"type": "string"}},
                "required": ["wrong", "fix"],
            },
        },
        "model": {"type": "string"},
    },
    "required": ["mistakes", "model"],
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

PRACTICES: dict[str, type[Practice]] = {p.key: p for p in (Conversation, PhrasalVerbs, Tenses, Paraphrase, RolePlay)}
