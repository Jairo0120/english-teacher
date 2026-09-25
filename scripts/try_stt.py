"""Try Whisper on your own voice.

Usage:
    uv run scripts/try_stt.py                        # record with push-to-talk, model "small"
    uv run scripts/try_stt.py -m medium              # other Whisper size
    uv run scripts/try_stt.py --devices              # list audio devices
    uv run scripts/try_stt.py -d 9                   # record from a specific device
    uv run scripts/try_stt.py -m small -m medium recordings/*.wav   # compare models on saved audio

Every recording is saved to recordings/ so you can compare models on exactly the same audio later.
"""

import argparse
import time
from datetime import datetime
from pathlib import Path

import sounddevice as sd

from english_teacher.audio import SAMPLE_RATE, record_push_to_talk, save_wav
from english_teacher.stt import DEFAULT_STT_MODEL, Transcriber

ROOT = Path(__file__).resolve().parents[1]


def load(model: str) -> Transcriber:
    start = time.perf_counter()
    t = Transcriber(model)
    print(f"Whisper '{model}' cargado en {time.perf_counter() - start:.1f}s")
    return t


def timed(t: Transcriber, audio) -> tuple[str, float]:
    start = time.perf_counter()
    text = t.transcribe(audio)
    return text, time.perf_counter() - start


def interactive(model: str, device: int | str | None) -> None:
    t = load(model)
    out_dir = ROOT / "recordings"
    out_dir.mkdir(exist_ok=True)
    print("Ctrl+C para salir.\n")
    while True:
        audio = record_push_to_talk(device)
        duration = len(audio) / SAMPLE_RATE
        if duration < 0.3:
            print("(grabación demasiado corta)\n")
            continue
        path = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}.wav"
        save_wav(path, audio)
        text, secs = timed(t, audio)
        print(f"📝 {text or '(nada detectado)'}")
        print(f"   audio {duration:.1f}s · transcripción {secs:.1f}s · {path.relative_to(ROOT)}\n")


def compare(models: list[str], files: list[Path]) -> None:
    transcribers = {m: load(m) for m in models}
    for f in files:
        print(f"\n{f.name}")
        for m, t in transcribers.items():
            text, secs = timed(t, f)
            print(f"  {m:>16} ({secs:4.1f}s): {text}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, help="WAVs a transcribir en vez de grabar")
    parser.add_argument("-m", "--model", action="append", dest="models", help="tamaño de Whisper (repetible)")
    parser.add_argument("-d", "--device", help="dispositivo de entrada (índice o nombre)")
    parser.add_argument("--devices", action="store_true", help="listar dispositivos de audio y salir")
    args = parser.parse_args()

    if args.devices:
        print(sd.query_devices())
        return
    models = args.models or [DEFAULT_STT_MODEL]
    try:
        if args.files:
            compare(models, args.files)
        else:
            device = int(args.device) if args.device and args.device.isdigit() else args.device
            interactive(models[0], device)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
