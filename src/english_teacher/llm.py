"""Tutor LLM via Ollama: sends the student's sentence and parses the structured feedback."""

import re
from dataclasses import dataclass
from pathlib import Path

import ollama

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "tutor.md"
DEFAULT_MODEL = "gemma3:12b"
FIELDS = ("CORRECTION", "NATURAL", "WHY", "REPLY")
_FIELD_RE = re.compile(rf"^\s*\**({'|'.join(FIELDS)})\**\s*:\s*\**\s*", re.MULTILINE)


@dataclass
class Feedback:
    correction: str = ""
    natural: str = ""
    why: str = ""
    reply: str = ""
    raw: str = ""

    @property
    def parsed(self) -> bool:
        return bool(self.correction and self.reply)


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def parse_feedback(text: str) -> Feedback:
    """Split the model output into its CORRECTION/NATURAL/WHY/REPLY fields."""
    fb = Feedback(raw=text)
    matches = list(_FIELD_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        setattr(fb, m.group(1).lower(), text[m.end():end].strip())
    return fb


class Tutor:
    def __init__(self, model: str = DEFAULT_MODEL, host: str | None = None, keep_history: bool = True):
        self.model = model
        self.client = ollama.Client(host=host)
        self.keep_history = keep_history
        self.messages: list[dict] = [{"role": "system", "content": load_system_prompt()}]
        self._think: bool | None = False

    def ask(self, sentence: str) -> Feedback:
        messages = [*self.messages, {"role": "user", "content": sentence}]
        text = self._chat(messages)
        if self.keep_history:
            self.messages = [*messages, {"role": "assistant", "content": text}]
        return parse_feedback(text)

    def _chat(self, messages: list[dict]) -> str:
        # Disable thinking so voice replies start fast; models without a
        # thinking mode (e.g. gemma3) reject the flag, so drop it for them.
        try:
            resp = self.client.chat(model=self.model, messages=messages, think=self._think)
        except ollama.ResponseError as e:
            if self._think is None or "think" not in str(e).lower():
                raise
            self._think = None
            resp = self.client.chat(model=self.model, messages=messages)
        return resp.message.content or ""
