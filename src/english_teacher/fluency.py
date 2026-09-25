"""Fluency metrics from a spoken answer: speech rate, long pauses and how much of the time you were talking.

Pauses come from Silero VAD on the raw audio instead of Whisper's word timestamps, because Whisper
stretches words over silences and hides most hesitations.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean

import numpy as np
from faster_whisper.vad import VadOptions, get_speech_timestamps

from english_teacher.audio import SAMPLE_RATE

ROOT = Path(__file__).resolve().parents[2]
LONG_PAUSE = 0.7  # seconds of silence inside an answer that count as a hesitation
_VAD = VadOptions(min_silence_duration_ms=250, speech_pad_ms=100)


@dataclass
class Fluency:
    words: int
    span: float  # seconds from the first to the last spoken sound
    speech: float  # seconds actually speaking
    pauses: list[float]  # every silence between speech chunks

    @property
    def wpm(self) -> float:
        return self.words / self.span * 60

    @property
    def long_pauses(self) -> list[float]:
        return [p for p in self.pauses if p >= LONG_PAUSE]

    @property
    def speech_ratio(self) -> float:
        return self.speech / self.span

    def describe(self) -> str:
        n = len(self.long_pauses)
        longest = f" (máx {max(self.long_pauses):.1f}s)" if n else ""
        return (
            f"{self.wpm:.0f} ppm · {n} {'pausa larga' if n == 1 else 'pausas largas'}{longest} · "
            f"{self.speech_ratio:.0%} del tiempo hablando"
        )


def measure(audio: np.ndarray, text: str, samplerate: int = SAMPLE_RATE) -> Fluency | None:
    """None when the answer is too short to say anything meaningful."""
    words = len(text.split())
    chunks = get_speech_timestamps(audio, _VAD, sampling_rate=samplerate)
    if words < 3 or not chunks:
        return None
    spans = [(c["start"] / samplerate, c["end"] / samplerate) for c in chunks]
    span = spans[-1][1] - spans[0][0]
    if span < 1.5:
        return None
    return Fluency(
        words=words,
        span=span,
        speech=sum(end - start for start, end in spans),
        pauses=[b[0] - a[1] for a, b in zip(spans, spans[1:])],
    )


class FluencyLog:
    """Keeps every measured answer in a CSV to follow progress across sessions."""

    FIELDS = ["session", "practice", "level", "words", "span", "speech", "long_pauses", "longest_pause", "wpm"]

    def __init__(self, practice: str, level: str, path: Path = ROOT / "progress" / "fluency.csv"):
        self.path = path
        self.practice, self.level = practice, level
        self.session = datetime.now().isoformat(timespec="seconds")
        self.current: list[Fluency] = []

    def add(self, f: Fluency) -> None:
        self.current.append(f)
        new_file = not self.path.exists()
        self.path.parent.mkdir(exist_ok=True)
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow({
                "session": self.session, "practice": self.practice, "level": self.level,
                "words": f.words, "span": round(f.span, 2), "speech": round(f.speech, 2),
                "long_pauses": len(f.long_pauses), "longest_pause": round(max(f.long_pauses, default=0), 2),
                "wpm": round(f.wpm, 1),
            })

    def summary(self, previous_sessions: int = 5) -> str | None:
        if not self.current:
            return None
        wpm = _rate(self.current)
        pauses_per_min = sum(len(f.long_pauses) for f in self.current) / sum(f.span for f in self.current) * 60
        text = f"Fluidez: {wpm:.0f} ppm · {pauses_per_min:.1f} pausas largas por minuto"
        past = self._previous(previous_sessions)
        if past:
            prev = "tu sesión anterior" if len(past) == 1 else f"tus {len(past)} sesiones anteriores"
            text += f" ({prev}: {mean(past):.0f} ppm)"
        return text + " · referencia nativa en conversación: ~150 ppm"

    def _previous(self, n: int) -> list[float]:
        """Speech rate of the last n sessions before this one."""
        if not self.path.exists():
            return []
        by_session: dict[str, list[dict]] = {}
        with self.path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["session"] != self.session:
                    by_session.setdefault(row["session"], []).append(row)
        recent = sorted(by_session)[-n:]
        return [
            sum(int(r["words"]) for r in by_session[s]) / sum(float(r["span"]) for r in by_session[s]) * 60
            for s in recent
        ]


def _rate(items: list[Fluency]) -> float:
    """Overall words per minute, weighting each answer by its length."""
    return sum(f.words for f in items) / sum(f.span for f in items) * 60

