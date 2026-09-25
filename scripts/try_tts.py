"""Try Kokoro voices and speeds.

Usage:
    uv run scripts/try_tts.py                                  # default voice and sample text
    uv run scripts/try_tts.py "Any text you want to hear"
    uv run scripts/try_tts.py -v af_heart -v bf_emma -v am_michael   # compare voices
    uv run scripts/try_tts.py -s 0.85                          # slower, handy for practice
    uv run scripts/try_tts.py --voices                         # list voices
"""

import argparse
import time

from english_teacher.audio import play
from english_teacher.tts import DEFAULT_VOICE, SAMPLE_RATE, VOICES, Speaker

SAMPLE_TEXT = (
    "Nice! So you went to the cinema yesterday. "
    "What movie did you watch, and would you recommend it?"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="?", default=SAMPLE_TEXT)
    parser.add_argument("-v", "--voice", action="append", dest="voices", help="voz de Kokoro (repetible)")
    parser.add_argument("-s", "--speed", type=float, default=1.0)
    parser.add_argument("-d", "--device", help="dispositivo de salida (índice o nombre)")
    parser.add_argument("--voices", action="store_true", dest="list_voices", help="listar voces y salir")
    args = parser.parse_args()

    if args.list_voices:
        for lang, names in VOICES.items():
            print({"a": "Americano", "b": "Británico"}[lang] + ": " + ", ".join(names))
        return

    device = int(args.device) if args.device and args.device.isdigit() else args.device
    for voice in args.voices or [DEFAULT_VOICE]:
        speaker = Speaker(voice, args.speed)
        start = time.perf_counter()
        audio = speaker.synthesize(args.text)
        secs = time.perf_counter() - start
        duration = len(audio) / SAMPLE_RATE
        print(f"🔊 {voice}: audio {duration:.1f}s · síntesis {secs:.1f}s ({duration / secs:.1f}x tiempo real)")
        play(audio, SAMPLE_RATE, device)


if __name__ == "__main__":
    main()
