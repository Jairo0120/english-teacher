"""Conversation loop: record -> transcribe -> tutor -> speak."""

import argparse
import time
from datetime import datetime
from pathlib import Path

from english_teacher.audio import SAMPLE_RATE, record_until_enter
from english_teacher.llm import DEFAULT_MODEL, Feedback, Tutor, parse_feedback, reply_sentences
from english_teacher.speech import SpeechPlayer
from english_teacher.stt import DEFAULT_STT_MODEL, Transcriber
from english_teacher.tts import DEFAULT_VOICE, Speaker

ROOT = Path(__file__).resolve().parents[2]
GREETING = "Hi! I'm your English tutor. What would you like to talk about today?"
HELP = "Enter = hablar · escribe una frase = enviarla como texto · r = repetir · q = salir"

DIM, BOLD, RED, GREEN, YELLOW, CYAN, RESET = "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"


def is_ok(value: str) -> bool:
    return value.strip().strip(".").upper() in ("", "OK")


def show_feedback(fb: Feedback) -> None:
    if not fb.parsed:
        print(f"{YELLOW}(el modelo no respetó el formato){RESET}\n{fb.raw}")
        return
    if is_ok(fb.correction) and is_ok(fb.natural):
        print(f"  {GREEN}✅ ¡Perfecto!{RESET}")
    if not is_ok(fb.correction):
        print(f"  {RED}✏️  Corrección:{RESET} {fb.correction}")
    if not is_ok(fb.natural):
        print(f"  {CYAN}💬 Más natural:{RESET} {fb.natural}")
    if fb.why and not is_ok(fb.why):
        print(f"  {DIM}💡 {fb.why}{RESET}")


class Session:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        print(f"{DIM}Cargando Whisper '{args.stt_model}', {args.model} y Kokoro '{args.voice}'...{RESET}")
        start = time.perf_counter()
        self.stt = Transcriber(args.stt_model)
        self.tutor = Tutor(args.model)
        self.tutor.warm_up()
        self.player = SpeechPlayer(Speaker(args.voice, args.speed), args.output)
        print(f"{DIM}Listo en {time.perf_counter() - start:.1f}s. {HELP}{RESET}\n")
        self.log_path = ROOT / "sessions" / f"{datetime.now():%Y-%m-%d_%H%M}.md"
        self.log_path.parent.mkdir(exist_ok=True)
        self.log_path.write_text(f"# Sesión {datetime.now():%Y-%m-%d %H:%M} ({args.model})\n", encoding="utf-8")

    def run(self) -> None:
        self.speak_line(GREETING)
        while True:
            cmd = input(f"{BOLD}🎙  Enter para hablar › {RESET}").strip()
            if cmd.lower() == "q":
                break
            if cmd.lower() == "r":
                self.player.repeat()
                self.player.wait()
                continue
            sentence = cmd or self.listen()
            if sentence:
                self.turn(sentence)

    def listen(self) -> str:
        audio = record_until_enter(self.args.input)
        if len(audio) < 0.3 * SAMPLE_RATE:
            print(f"{DIM}(grabación demasiado corta){RESET}")
            return ""
        text = self.stt.transcribe(audio)
        if not text:
            print(f"{DIM}(no se detectó voz){RESET}")
        return text

    def turn(self, sentence: str) -> None:
        print(f"\n{BOLD}Tú:{RESET} {sentence}")
        self.player.new_utterance()
        raw: list[str] = []
        spoken = []
        # REPLY is the last field: sentences start playing while the model is still writing them
        for s in reply_sentences(self.tutor.stream(sentence), raw):
            if not spoken and self.args.say_natural:
                self.say_natural(parse_feedback(raw[0]))
            spoken.append(s)
            self.player.say(s)
        fb = parse_feedback(raw[0])
        if not spoken:  # broken format: at least say something
            self.player.say(fb.raw)
        show_feedback(fb)
        print(f"{BOLD}{GREEN}🗣  Tutor:{RESET} {fb.reply or fb.raw}\n")
        self.log(sentence, fb)
        self.player.wait()

    def say_natural(self, fb: Feedback) -> None:
        better = fb.natural if not is_ok(fb.natural) else fb.correction
        if not is_ok(better):
            self.player.say(f"You could say: {better}")

    def speak_line(self, text: str) -> None:
        print(f"{BOLD}{GREEN}🗣  Tutor:{RESET} {text}\n")
        self.player.new_utterance()
        self.player.say(text)
        self.player.wait()

    def log(self, sentence: str, fb: Feedback) -> None:
        lines = ["", f"**Tú:** {sentence}"]
        if not is_ok(fb.correction):
            lines.append(f"- ✏️ {fb.correction}")
        if not is_ok(fb.natural):
            lines.append(f"- 💬 {fb.natural}")
        if fb.why and not is_ok(fb.why):
            lines.append(f"- 💡 {fb.why}")
        lines.append(f"\n**Tutor:** {fb.reply or fb.raw}")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def device_arg(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def main() -> None:
    parser = argparse.ArgumentParser(description="Tutor de inglés local por voz.")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help=f"modelo de Ollama (por defecto {DEFAULT_MODEL})")
    parser.add_argument("-w", "--stt-model", default=DEFAULT_STT_MODEL, help="tamaño de Whisper")
    parser.add_argument("-v", "--voice", default=DEFAULT_VOICE, help="voz de Kokoro")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="velocidad de la voz")
    parser.add_argument("-i", "--input", type=device_arg, help="dispositivo de entrada")
    parser.add_argument("-o", "--output", type=device_arg, help="dispositivo de salida")
    parser.add_argument("--say-natural", action="store_true", help="decir en voz alta la versión corregida antes de responder")
    args = parser.parse_args()

    session = Session(args)
    try:
        session.run()
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        session.player.close()
        print(f"{DIM}Sesión guardada en {session.log_path.relative_to(ROOT)}{RESET}")


if __name__ == "__main__":
    main()
