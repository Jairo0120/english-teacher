"""Download the Whisper and Kokoro models so the tutor can run fully offline.

This is the only part of the project that talks to the Hugging Face Hub.

Usage:
    uv run scripts/download_models.py                  # Whisper "small" + Kokoro with all voices
    uv run scripts/download_models.py -w small -w medium
"""

import argparse
import os

os.environ["HF_HUB_OFFLINE"] = "0"  # before english_teacher sets offline mode

from faster_whisper import download_model  # noqa: E402
from huggingface_hub import snapshot_download  # noqa: E402

from english_teacher.stt import DEFAULT_STT_MODEL  # noqa: E402
from english_teacher.tts import VOICES  # noqa: E402

KOKORO_REPO = "hexgrad/Kokoro-82M"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-w", "--whisper", action="append", help="tamaño de Whisper (repetible)")
    args = parser.parse_args()

    for size in args.whisper or [DEFAULT_STT_MODEL]:
        print(f"Whisper {size}...")
        download_model(size)

    voices = [f"voices/{v}.pt" for names in VOICES.values() for v in names]
    print(f"Kokoro + {len(voices)} voces...")
    snapshot_download(KOKORO_REPO, allow_patterns=["config.json", "kokoro-v1_0.pth", *voices])
    print("Listo. El tutor ya puede funcionar sin conexión.")


if __name__ == "__main__":
    main()
