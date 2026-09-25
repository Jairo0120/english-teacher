"""Text to speech with Kokoro (CPU)."""

import warnings
from collections.abc import Iterator

import numpy as np

# torch/kokoro emit harmless deprecation warnings on every load
warnings.filterwarnings("ignore", category=UserWarning, module="torch")
warnings.filterwarnings("ignore", category=FutureWarning, module="torch")

from kokoro import KPipeline  # noqa: E402

SAMPLE_RATE = 24_000
DEFAULT_VOICE = "af_heart"
# First letter of a Kokoro voice is its language: a = American English, b = British English
VOICES = {
    "a": ["af_heart", "af_bella", "af_nicole", "af_sarah", "am_michael", "am_fenrir", "am_puck"],
    "b": ["bf_emma", "bf_isabella", "bm_george", "bm_fable"],
}


class Speaker:
    """Kokoro TTS. Can speak with different voices (narrator, role-play characters) sharing one model."""

    def __init__(self, voice: str = DEFAULT_VOICE, speed: float = 1.0):
        self.voice = voice
        self.speed = speed
        self.pipelines: dict[str, KPipeline] = {}
        self._pipeline(voice)  # load the model now, not on the first sentence

    def stream(self, text: str, voice: str | None = None) -> Iterator[np.ndarray]:
        """Yield audio chunk by chunk so playback can start before the whole text is synthesized."""
        voice = voice or self.voice
        for result in self._pipeline(voice)(text, voice=voice, speed=self.speed):
            if result.audio is not None:
                yield result.audio.numpy()

    def synthesize(self, text: str, voice: str | None = None) -> np.ndarray:
        chunks = list(self.stream(text, voice))
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)

    def _pipeline(self, voice: str) -> KPipeline:
        # One pipeline per language (a = American, b = British); the model weights are shared
        lang = voice[0]
        if lang not in self.pipelines:
            shared = next(iter(self.pipelines.values())).model if self.pipelines else True
            self.pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", model=shared)
        return self.pipelines[lang]
