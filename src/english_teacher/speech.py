"""Background speech: synthesize and play sentences while the LLM is still writing."""

import queue
import threading

import numpy as np
import sounddevice as sd

from english_teacher.tts import SAMPLE_RATE, Speaker


class SpeechPlayer:
    """Two-stage pipeline: text -> Kokoro (synth thread) -> audio -> speakers (play thread).

    Synthesis of the next sentence overlaps with playback of the current one, so there
    are no gaps between sentences.
    """

    def __init__(self, speaker: Speaker, device: int | str | None = None):
        self.speaker = speaker
        self.last: list[np.ndarray] = []  # audio of the last utterance, for "repeat"
        self._texts: queue.Queue[str] = queue.Queue()
        self._audio: queue.Queue[np.ndarray] = queue.Queue()
        self._out = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=device)
        self._out.start()
        threading.Thread(target=self._synth_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    def say(self, text: str) -> None:
        self._texts.put(text)

    def repeat(self) -> None:
        for chunk in self.last:
            self._audio.put(chunk)

    def new_utterance(self) -> None:
        self.last = []

    def wait(self) -> None:
        """Block until everything queued has been spoken."""
        self._texts.join()
        self._audio.join()

    def close(self) -> None:
        self._out.stop()
        self._out.close()

    def _synth_loop(self) -> None:
        while True:
            text = self._texts.get()
            try:
                for chunk in self.speaker.stream(text):
                    self.last.append(chunk)
                    self._audio.put(chunk)
            finally:
                self._texts.task_done()

    def _play_loop(self) -> None:
        while True:
            chunk = self._audio.get()
            try:
                self._out.write(chunk.astype(np.float32).reshape(-1, 1))
            finally:
                self._audio.task_done()
