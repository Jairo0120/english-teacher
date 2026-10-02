"""Speech to text with faster-whisper (CPU, int8)."""

from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

DEFAULT_STT_MODEL = "small"


class Transcriber:
    def __init__(self, model_size: str = DEFAULT_STT_MODEL, device: str = "cpu", compute_type: str = "int8"):
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray | str | Path, language: str = "en") -> str:
        # Keep Whisper as literal as possible so the tutor sees the student's real mistakes:
        # no initial_prompt and no conditioning on previous text (both push it to "clean up").
        segments, _ = self.model.transcribe(
            str(audio) if isinstance(audio, Path) else audio,
            language=language,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=None,
        )
        return " ".join(s.text.strip() for s in segments).strip()
