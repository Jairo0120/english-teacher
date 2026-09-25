"""Tutor LLM via Ollama: sends the student's sentence and parses the structured feedback."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import ollama

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
DEFAULT_MODEL = "gemma3:12b"
FIELDS = ("CORRECTION", "NATURAL", "WHY", "REPLY")
_FIELD_RE = re.compile(rf"^\s*\**({'|'.join(FIELDS)})\**\s*:\s*\**\s*", re.MULTILINE)


@dataclass
class Feedback:
    correction: str = ""
    natural: str = ""
    why: str = ""
    result: str = ""  # only in practices that grade the answer (CORRECT / RETRY)
    verb_words: str = ""  # phrasal verbs practice: the words the student used for the target
    meaning_ok: bool = False  # phrasal verbs practice: the target was used with the right meaning
    reply: str = ""
    raw: str = ""

    @property
    def parsed(self) -> bool:
        return bool(self.correction and self.reply)


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def parse_feedback(text: str) -> Feedback:
    """Split the model output into its CORRECTION/NATURAL/WHY/REPLY fields."""
    fb = Feedback(raw=text)
    matches = list(_FIELD_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        setattr(fb, m.group(1).lower(), text[m.end():end].strip())
    return fb


_SENTENCE_END = re.compile(r"[.!?]+[\"')]*\s+")


def reply_sentences(pieces: Iterator[str], out: list[str], field: bool = True) -> Iterator[str]:
    """Consume streamed model output and yield REPLY sentences as soon as each one is complete.

    With field=False the whole output is the reply (plain spoken text, no fields).
    The whole raw text is accumulated into `out[0]` so the caller can parse the feedback afterwards.
    """
    text, sent = "", 0  # sent: offset inside the reply already yielded
    out[:] = [""]
    for piece in pieces:
        text += piece
        out[0] = text
        reply = _reply_part(text) if field else text
        if reply is None:
            continue
        while m := _SENTENCE_END.search(reply, sent):
            yield reply[sent:m.end()].strip()
            sent = m.end()
    reply = _reply_part(text) if field else text
    if reply is not None and reply[sent:].strip():
        yield reply[sent:].strip()


def _reply_part(text: str) -> str | None:
    marker = next((m for m in _FIELD_RE.finditer(text) if m.group(1) == "REPLY"), None)
    return text[marker.end():] if marker else None


class Tutor:
    def __init__(
        self,
        system_prompt: str,
        model: str = DEFAULT_MODEL,
        host: str | None = None,
        keep_history: bool = True,
        max_turns: int = 10,
        keep_alive: str = "30m",
    ):
        self.model = model
        self.client = ollama.Client(host=host)
        self.keep_history = keep_history
        self.max_turns = max_turns
        self.keep_alive = keep_alive  # keep the model in VRAM while the student thinks
        self.system = {"role": "system", "content": system_prompt}
        self.history: list[dict] = []
        self._think: bool | None = False

    def ask(self, sentence: str) -> Feedback:
        return parse_feedback("".join(self.stream(sentence)))

    def stream(self, sentence: str) -> Iterator[str]:
        """Yield the model output piece by piece and record the turn in the history."""
        user = {"role": "user", "content": sentence}
        parts = []
        for piece in self._chat([self.system, *self.history, user]):
            parts.append(piece)
            yield piece
        if self.keep_history:
            # Only the last max_turns exchanges, so the context (and latency) doesn't grow forever
            self.history = [*self.history, user, {"role": "assistant", "content": "".join(parts)}]
            self.history = self.history[-2 * self.max_turns:]

    def structured(self, system: str, content: str, schema: dict) -> dict:
        """One-off call (no history) whose answer is forced to match a JSON schema."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        kwargs = {"think": self._think} if self._think is not None else {}
        try:
            resp = self.client.chat(
                model=self.model, messages=messages, format=schema,
                options={"temperature": 0}, keep_alive=self.keep_alive, **kwargs,
            )
        except ollama.ResponseError as e:
            if self._think is None or "think" not in str(e).lower():
                raise
            self._think = None
            return self.structured(system, content, schema)
        return json.loads(resp.message.content or "{}")

    def warm_up(self) -> None:
        """Load the model into VRAM so the first real answer is fast."""
        self.client.generate(model=self.model, prompt="", keep_alive=self.keep_alive)

    def _chat(self, messages: list[dict]) -> Iterator[str]:
        # Disable thinking so voice replies start fast; models without a
        # thinking mode (e.g. gemma3) reject the flag, so drop it for them.
        # With stream=True the error only shows up when reading the first chunk.
        try:
            first, chunks = self._open_stream(messages)
        except ollama.ResponseError as e:
            if self._think is None or "think" not in str(e).lower():
                raise
            self._think = None
            first, chunks = self._open_stream(messages)
        yield first
        for chunk in chunks:
            yield chunk.message.content or ""

    def _open_stream(self, messages: list[dict]) -> tuple[str, Iterator]:
        kwargs = {"think": self._think} if self._think is not None else {}
        chunks = self.client.chat(
            model=self.model, messages=messages, stream=True, keep_alive=self.keep_alive, **kwargs
        )
        first = next(chunks, None)
        return (first.message.content or "") if first else "", chunks
