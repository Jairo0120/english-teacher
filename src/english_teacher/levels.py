"""Difficulty levels. Prompts use {{placeholders}} that are filled with the texts of the chosen level."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    name: str
    speech: str  # how the tutor talks
    reply_shape: str  # what a conversation reply looks like
    coaching: str  # extra conversation behavior (fluency push, richer suggestions)
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
        phrasal_meaning="Prefer a less obvious or idiomatic meaning if it has several.",
        phrasal_lists=("phrasal_verbs_advanced.txt",),
        strict_grading=True,
        speed=1.1,
    ),
}
DEFAULT_LEVEL = "B2"


def render(template: str, level: Level) -> str:
    """Fill {{speech}}, {{reply_shape}}... with the level's texts (JSON braces in prompts stay untouched)."""
    for field in ("name", "speech", "reply_shape", "coaching", "phrasal_meaning"):
        template = template.replace("{{" + field + "}}", getattr(level, field))
    return template
