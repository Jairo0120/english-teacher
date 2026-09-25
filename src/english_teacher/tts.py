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
    def __init__(self, voice: str = DEFAULT_VOICE, speed: float = 1.0):
        self.voice = voice
        self.speed = speed
        self.pipeline = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M")

    def stream(self, text: str) -> Iterator[np.ndarray]:
        """Yield audio chunk by chunk so playback can start before the whole text is synthesized."""
        for result in self.pipeline(text, voice=self.voice, speed=self.speed):
            if result.audio is not None:
                yield result.audio.numpy()

    def synthesize(self, text: str) -> np.ndarray:
        chunks = list(self.stream(text))
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
