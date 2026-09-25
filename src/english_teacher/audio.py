"""Microphone capture (push-to-talk) and playback with sounddevice."""

import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000  # what Whisper expects


def record_push_to_talk(device: int | str | None = None, samplerate: int = SAMPLE_RATE) -> np.ndarray:
    """Record mono float32 audio between two Enter presses."""
    input("🎙  Enter para hablar...")
    return record_until_enter(device, samplerate)


def record_until_enter(device: int | str | None = None, samplerate: int = SAMPLE_RATE) -> np.ndarray:
    """Start recording right away and stop on Enter."""
    chunks: list[np.ndarray] = []

    def callback(indata, frames, time, status):
        chunks.append(indata[:, 0].copy())

    with sd.InputStream(samplerate=samplerate, channels=1, dtype="float32", device=device, callback=callback):
        input("🔴 Grabando... Enter para terminar")
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def play(audio: np.ndarray, samplerate: int, device: int | str | None = None) -> None:
    sd.play(audio, samplerate, device=device)
    sd.wait()


def save_wav(path: Path, audio: np.ndarray, samplerate: int = SAMPLE_RATE) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(samplerate)
        f.writeframes(pcm.tobytes())
