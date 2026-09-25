"""Difficulty levels. Prompts use {{placeholders}} that are filled with the texts of the chosen level."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    name: str
    speech: str  # how the tutor talks
    reply_shape: str  # what a conversation reply looks like
    coaching: str  # extra conversation behavior (fluency push, richer suggestions)
    character: str  # how role-play characters behave
    phrasal_meaning: str  # which meaning of a phrasal verb to teach
    phrasal_lists: tuple[str, ...]  # files in data/ the phrasal verbs are picked from
    strict_grading: bool  # phrasal verbs: also require the use to sound natural
    speed: float  # default Kokoro speed


LEVELS = {
    "B1": Level(
        name="B1",
        speech="Use simple, clear English (B1 level): short sentences, common vocabulary, no idioms.",
        reply_shape="1-2 short sentences, ending with a simple question.",
        coaching="",
        character=(
            "You are cooperative and patient. Speak clearly with simple, common English and short sentences. "
            "If the student struggles, make it easy for them to continue."
        ),
        phrasal_meaning="Explain only its most common meaning.",
        phrasal_lists=("phrasal_verbs_common.txt",),
        strict_grading=False,
        speed=0.9,
    ),
    "B2": Level(
        name="B2",
        speech=(
            "Use natural English at a B2-C1 level: native-like phrasing, common idioms and collocations, "
            "varied vocabulary and complex sentences. Do not simplify your English."
        ),
        reply_shape=(
            "2-3 sentences, ending with an open question that needs a developed answer: opinions, reasons, "
            "comparisons, hypotheticals (what would you do if...) or past experiences. Never a yes/no question."
        ),
        coaching=(
            "- If the student's answer is very short (one simple sentence), ask them to expand on it: why, how, an example.\n"
            "- In NATURAL, when a sentence is correct but basic, suggest a richer version a fluent speaker would use: "
            "better connectors, collocations, phrasal verbs or more precise vocabulary."
        ),
        character=(
            "Speak at a natural pace with everyday idioms and phrasal verbs, like a real person in this situation. "
            "Don't make things too easy: raise reasonable objections and ask for details, so the student has to "
            "explain, insist or negotiate."
        ),
        phrasal_meaning="If it has several common meanings, you may teach one that is less obvious.",
        phrasal_lists=("phrasal_verbs_common.txt", "phrasal_verbs_advanced.txt"),
        strict_grading=True,
        speed=1.0,
    ),
    "C1": Level(
        name="C1",
        speech=(
            "Speak like an educated native speaker: idioms, phrasal verbs, nuanced vocabulary and "
            "a natural rhythm. Do not simplify your English at all."
        ),
        reply_shape=(
            "2-4 sentences. Challenge the student's ideas, play devil's advocate or ask for nuance, "
            "and end with an open question that needs a developed, argued answer."
        ),
        coaching=(
            "- If the student's answer is short or vague, push them to expand and give concrete examples.\n"
            "- In NATURAL, suggest richer, more idiomatic versions even of correct sentences, and point out "
            "repetitive vocabulary or the wrong register (too formal or too informal)."
        ),
        character=(
            "You are hard to deal with: you don't give in easily, you use idioms, slang and fast, natural "
            "phrasing, you sometimes misunderstand or change the subject, and you only agree when the student "
            "argues convincingly and politely."
        ),
        phrasal_meaning="Prefer a less obvious or idiomatic meaning if it has several.",
        phrasal_lists=("phrasal_verbs_advanced.txt",),
        strict_grading=True,
        speed=1.1,
    ),
}
DEFAULT_LEVEL = "B2"


def render(template: str, level: Level, **extra: str) -> str:
    """Fill {{speech}}, {{reply_shape}}... with the level's texts, plus any `extra` values.

    Simple {{name}} replacement instead of str.format, so JSON braces in prompts stay untouched.
    """
    fields = ("name", "speech", "reply_shape", "coaching", "character", "phrasal_meaning")
    values = {f: getattr(level, f) for f in fields} | extra
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template
