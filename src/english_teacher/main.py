"""Conversation loop: record -> transcribe -> tutor -> speak."""

import argparse
import time
from datetime import datetime
from pathlib import Path

from english_teacher import settings
from english_teacher.audio import SAMPLE_RATE, record_until_enter
from english_teacher.fluency import Fluency, FluencyLog, measure
from english_teacher.levels import DEFAULT_LEVEL, LEVELS
from english_teacher.llm import DEFAULT_MODEL, Feedback, Tutor, parse_feedback, reply_sentences
from english_teacher.practices import PRACTICES, Practice
from english_teacher.speech import SpeechPlayer
from english_teacher.stt import DEFAULT_STT_MODEL, Transcriber
from english_teacher.tts import DEFAULT_VOICE, Speaker

ROOT = Path(__file__).resolve().parents[2]
HELP = "Enter = hablar · escribe una frase = enviarla como texto · h = ayuda · r = repetir · q = salir"

DIM, BOLD, RED, GREEN, YELLOW, CYAN, RESET = "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"


def is_ok(value: str) -> bool:
    return value.strip().strip(".").upper() in ("", "OK")


def show_feedback(fb: Feedback) -> None:
    if fb.result:
        correct = fb.result.upper().startswith("CORRECT")
        print(f"  {GREEN}🎯 ¡Bien usado!{RESET}" if correct else f"  {YELLOW}🔁 Todavía no{RESET}")
    if fb.correction and is_ok(fb.correction) and is_ok(fb.natural):
        print(f"  {GREEN}✅ {'Gramática perfecta' if fb.result else '¡Perfecto!'}{RESET}")
    if not is_ok(fb.correction):
        print(f"  {RED}✏️  Corrección:{RESET} {fb.correction}")
    if not is_ok(fb.natural):
        print(f"  {CYAN}💬 Más natural:{RESET} {fb.natural}")
    if fb.why and not is_ok(fb.why):
        print(f"  {DIM}💡 {fb.why}{RESET}")


class Session:
    def __init__(self, args: argparse.Namespace, practice: Practice):
        self.args = args
        self.practice = practice
        self.fluency = FluencyLog(practice.key, practice.level.name)
        self.last_line = ""  # last thing the tutor said, for the "h" command
        print(f"{DIM}Nivel {practice.level.name} · {practice.title}{RESET}")
        print(f"{DIM}Cargando Whisper '{args.stt_model}', {args.model} y Kokoro '{args.voice}'...{RESET}")
        start = time.perf_counter()
        self.stt = Transcriber(args.stt_model)
        self.tutor = Tutor(practice.system_prompt(), args.model)
        self.tutor.warm_up()
        self.player = SpeechPlayer(Speaker(args.voice, args.speed), args.output)
        print(f"{DIM}Listo en {time.perf_counter() - start:.1f}s. {HELP}{RESET}\n")
        self.log_path = ROOT / "sessions" / f"{datetime.now():%Y-%m-%d_%H%M}.md"
        self.log_path.parent.mkdir(exist_ok=True)
        scenario = getattr(practice, "scenario", None)
        title = f"{practice.title}: {scenario.title}" if scenario else practice.title
        header = f"# {title} · {practice.level.name} · {datetime.now():%Y-%m-%d %H:%M} ({args.model})\n"
        if scenario:
            header += f"\n> {scenario.setting}\n>\n> **Objetivo:** {scenario.goal}\n"
        self.log_path.write_text(header, encoding="utf-8")

    def run(self) -> None:
        if intro := self.practice.intro():
            self.speak_line(intro)
        if opening := self.practice.opening():
            self.tutor_turn(opening)
        while not self.practice.finished:
            if note := self.practice.announce():
                print(f"  {BOLD}{YELLOW}{note}{RESET}")
            status = self.practice.status()
            tag = f"{CYAN}[{status}]{RESET} " if status else ""
            cmd = input(f"{tag}{BOLD}🎙  Enter para hablar › {RESET}").strip()
            if cmd.lower() == "q":
                break
            if cmd.lower() == "r":
                self.player.repeat()
                self.player.wait()
                continue
            if cmd.lower() == "h":
                self.show_help()
                continue
            sentence, fluency = (cmd, None) if cmd else self.listen()
            if sentence:
                self.respond(sentence, fluency)

    def listen(self) -> tuple[str, Fluency | None]:
        audio = record_until_enter(self.args.input)
        if len(audio) < 0.3 * SAMPLE_RATE:
            print(f"{DIM}(grabación demasiado corta){RESET}")
            return "", None
        text = self.stt.transcribe(audio)
        if not text:
            print(f"{DIM}(no se detectó voz){RESET}")
            return "", None
        return text, measure(audio, text)

    def show_help(self) -> None:
        suggestions = self.practice.help(self.tutor, self.last_line)
        if suggestions is None:
            print(f"{DIM}(no hay ayuda en esta práctica){RESET}")
            return
        print(f"  {CYAN}💡 Podrías decir:{RESET}")
        for s in suggestions:
            print(f"     • {s}")
        print()

    def debrief(self) -> None:
        print(f"{DIM}Preparando el repaso...{RESET}")
        review = self.practice.debrief(self.tutor)
        if not review:
            return
        print(f"\n{BOLD}📋 Repaso{RESET}")
        if review.spoken:
            print(f"{BOLD}{GREEN}🗣  Tutor:{RESET} {review.spoken}")
        for line in review.lines:
            print(line)
        print()
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write("\n## Repaso\n\n" + review.spoken + "\n\n" + "\n".join(review.lines) + "\n")
        if review.spoken:
            self.player.new_utterance()
            self.player.say(review.spoken)
            self.player.wait()

    def respond(self, sentence: str, fluency: Fluency | None = None) -> None:
        print(f"\n{BOLD}Tú:{RESET} {sentence}")
        if fluency:
            self.fluency.add(fluency)
            print(f"  {DIM}⏱  {fluency.describe()}{RESET}")
        status = self.practice.status()
        if self.practice.grade_after_reply:
            # The reply doesn't depend on the grade: start speaking right away and grade while it plays
            reply = self.speak(self.practice.reply_instruction(sentence, None), fields=False)
            fb = self.practice.grade(self.tutor, sentence)
            show_feedback(fb)
            fb.reply, fb.raw = reply.reply, reply.raw
        elif (fb := self.practice.grade(self.tutor, sentence)) is None:
            # Single call: feedback fields and REPLY come in the same answer
            fb = self.speak(self.practice.wrap(sentence), fields=True)
            if fb.parsed:
                show_feedback(fb)
            else:
                print(f"{YELLOW}(el modelo no respetó el formato){RESET}\n{fb.raw}")
        else:
            # Graded: show the feedback right away, then the tutor says what the practice asks for:
            # first any fixed text (plays immediately), then the model's reply if one is needed
            show_feedback(fb)
            self.player.new_utterance()
            if self.args.say_natural:
                self.say_natural(fb)
            quick = self.practice.quick_reply(sentence, fb) or ""
            if quick:
                self.player.say(quick, self.practice.voice)
            fb.reply = fb.raw = quick
            if instruction := self.practice.reply_instruction(sentence, fb):
                reply = self.speak(instruction, fields=False, fresh=False)
                fb.reply = f"{quick} {reply.reply}".strip()
                fb.raw = reply.raw
        self.practice.after(fb)
        self.heard(fb.reply or fb.raw)
        print(f"{BOLD}{GREEN}🗣  {self.speaker_name}:{RESET} {fb.reply or fb.raw}\n")
        self.log(sentence, fb, status, fluency)
        self.player.wait()
        if follow := self.practice.follow_up(fb):
            self.tutor_turn(follow)

    def tutor_turn(self, instruction: str) -> None:
        """The tutor speaks on its own (opening, next exercise), following a hidden instruction."""
        fb = self.speak(instruction, fields=False)
        self.heard(fb.reply)
        print(f"{BOLD}{GREEN}🗣  {self.speaker_name}:{RESET} {fb.reply}\n")
        self.log(None, fb, self.practice.status())
        self.player.wait()

    def speak(self, message: str, fields: bool, fresh: bool = True) -> Feedback:
        """Send `message` to the tutor and speak its reply sentence by sentence while it is generated.

        fields=True: the answer has CORRECTION/NATURAL/WHY/REPLY and only REPLY is spoken.
        fields=False: the whole answer is plain spoken text.
        fresh=False: continue the current utterance (for "repeat") instead of starting a new one.
        """
        if fresh:
            self.player.new_utterance()
        raw: list[str] = []
        spoken = 0
        for s in reply_sentences(self.tutor.stream(message), raw, field=fields):
            if not spoken and fields and self.args.say_natural:
                self.say_natural(parse_feedback(raw[0]))
            spoken += 1
            self.player.say(s, self.practice.voice)
        text = raw[0] if raw else ""
        fb = parse_feedback(text) if fields else Feedback(reply=text.strip(), raw=text)
        if not spoken and text.strip():  # broken format: at least say something
            self.player.say(fb.reply or text, self.practice.voice)
        return fb

    def say_natural(self, fb: Feedback) -> None:
        better = fb.natural if not is_ok(fb.natural) else fb.correction
        if not is_ok(better):
            self.player.say(f"You could say: {better}")

    @property
    def speaker_name(self) -> str:
        scenario = getattr(self.practice, "scenario", None)
        return scenario.name if scenario else "Tutor"

    def heard(self, text: str) -> None:
        self.last_line = text
        self.practice.heard(text)

    def speak_line(self, text: str) -> None:
        """The narrator (tutor's own voice) says a fixed text."""
        self.heard(text)
        print(f"{BOLD}{GREEN}🗣  Tutor:{RESET} {text}\n")
        self.player.new_utterance()
        self.player.say(text)
        self.player.wait()

    def log(self, sentence: str | None, fb: Feedback, status: str | None, fluency: Fluency | None = None) -> None:
        lines = [""]
        if status:
            lines.append(f"*{status}*\n")
        if sentence:
            lines.append(f"**Tú:** {sentence}")
        if fluency:
            lines.append(f"- ⏱ {fluency.describe()}")
        if fb.result:
            lines.append(f"- 🎯 {fb.result}")
        if not is_ok(fb.correction):
            lines.append(f"- ✏️ {fb.correction}")
        if not is_ok(fb.natural):
            lines.append(f"- 💬 {fb.natural}")
        if fb.why and not is_ok(fb.why):
            lines.append(f"- 💡 {fb.why}")
        lines.append(f"\n**{self.speaker_name}:** {fb.reply or fb.raw}")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def choose_practice() -> str:
    practices = list(PRACTICES.values())
    print(f"{BOLD}¿Qué quieres practicar?{RESET}")
    for i, p in enumerate(practices, 1):
        print(f"  {i}. {p.title} {DIM}— {p.description}{RESET}")
    while True:
        choice = input("› ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(practices):
            return practices[int(choice) - 1].key
        if choice in PRACTICES:
            return choice


def device_arg(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def main() -> None:
    parser = argparse.ArgumentParser(description="Tutor de inglés local por voz.")
    parser.add_argument("practice", nargs="?", choices=PRACTICES, help="tipo de práctica (si no, muestra un menú)")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help=f"modelo de Ollama (por defecto {DEFAULT_MODEL})")
    parser.add_argument("-w", "--stt-model", default=DEFAULT_STT_MODEL, help="tamaño de Whisper")
    parser.add_argument("-v", "--voice", default=DEFAULT_VOICE, help="voz de Kokoro")
    parser.add_argument("-s", "--speed", type=float, help="velocidad de la voz (por defecto, la del nivel)")
    parser.add_argument("-l", "--level", choices=LEVELS, help="nivel (se guarda como predeterminado)")
    parser.add_argument("-i", "--input", type=device_arg, help="dispositivo de entrada")
    parser.add_argument("-o", "--output", type=device_arg, help="dispositivo de salida")
    parser.add_argument("--say-natural", action="store_true", help="decir en voz alta la versión corregida antes de responder")
    args = parser.parse_args()

    if args.level:
        settings.save({"level": args.level})
    level = LEVELS[args.level or settings.load().get("level", DEFAULT_LEVEL)]
    if args.speed is None:
        args.speed = level.speed

    practice = PRACTICES[args.practice or choose_practice()](level)
    practice.setup(args.model)
    session = Session(args, practice)
    try:
        session.run()
        session.debrief()
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        session.player.close()
        summaries = [s for s in (practice.summary(), session.fluency.summary()) if s]
        if summaries:
            for summary in summaries:
                print(f"{BOLD}{summary}{RESET}")
            with session.log_path.open("a", encoding="utf-8") as f:
                f.write("\n---\n" + "\n\n".join(summaries) + "\n")
        print(f"{DIM}Sesión guardada en {session.log_path.relative_to(ROOT)}{RESET}")


if __name__ == "__main__":
    main()
