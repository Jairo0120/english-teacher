"""Writing review, text only (no Whisper or Kokoro): step 1 fixes grammar, step 2 makes it sound natural.

The model only lists changes (exact fragment -> replacement + why); the code applies them. That way the
final text contains exactly the explained changes and nothing else, and the diff shown is exact.
"""

import difflib
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from english_teacher.cloud import is_cloud, make_client
from english_teacher.levels import Level, render
from english_teacher.llm import load_prompt

ROOT = Path(__file__).resolve().parents[2]
# Not real time, so it can use slower models. Qwen3 14B does the grammar step well locally; the
# naturalness step needs a stronger model, so it goes to OpenAI by default (see README)
DEFAULT_GRAMMAR_MODEL = "qwen3:14b"
DEFAULT_NATURAL_MODEL = "openai:gpt-5.4-mini"

DIM, BOLD, RED, GREEN, YELLOW, CYAN, STRIKE, RESET = (
    "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[9m", "\033[0m"
)


@dataclass
class Change:
    original: str
    new: str
    why: str
    kind: str  # "grammar", "unnatural" or "optional"


@dataclass
class Step:
    before: str
    after: str
    changes: list[Change] = field(default_factory=list)
    skipped: int = 0  # changes the model listed but that don't match the text


def split_paragraphs(text: str) -> list[str]:
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]


def _overlaps(fragment: str, corrected: str) -> bool:
    a, b = fragment.lower(), corrected.lower()
    return a in b or b in a


def apply_changes(text: str, changes: list[Change]) -> Step:
    """Apply each change to the first occurrence of its fragment; drop the ones that don't match."""
    step = Step(before=text, after=text)
    for c in changes:
        if not c.original.strip() or c.original.strip() == c.new.strip():
            step.skipped += 1
            continue
        start = step.after.find(c.original)
        if start < 0:  # models sometimes change the capitalization of the fragment
            match = re.search(re.escape(c.original), step.after, re.IGNORECASE)
            if not match:
                step.skipped += 1
                continue
            start = match.start()
            if step.after[start].isupper() and c.new[:1].islower():
                c.new = c.new[0].upper() + c.new[1:]
        step.after = step.after[:start] + c.new + step.after[start + len(c.original):]
        step.changes.append(c)
    return step


def diff(old: str, new: str, markdown: bool = False) -> str:
    """Word-level diff: removed words struck through, added words highlighted."""
    a, b = old.split(" "), new.split(" ")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(" ".join(a[i1:i2]))
            continue
        if i2 > i1:
            removed = " ".join(a[i1:i2])
            out.append(f"~~{removed}~~" if markdown else f"{RED}{STRIKE}{removed}{RESET}")
        if j2 > j1:
            added = " ".join(b[j1:j2])
            out.append(f"**{added}**" if markdown else f"{GREEN}{BOLD}{added}{RESET}")
    return " ".join(out)


class Reviewer:
    def __init__(self, grammar_client, natural_client, level: Level, fallback=None):
        """Clients only need `structured(system, content, schema) -> dict` (local Tutor or OpenAIClient).

        fallback: client for the naturalness step if natural_client fails (e.g. no network).
        """
        self.grammar_client = grammar_client
        self.natural_client = natural_client
        self.level = level
        self.fallback = fallback
        self.fallback_reason = ""  # set when the naturalness step switched to the fallback

    def grammar(self, paragraph: str) -> Step:
        d = self.grammar_client.structured(render(load_prompt("writing_grammar"), self.level), paragraph, GRAMMAR_SCHEMA)
        return apply_changes(paragraph, [
            Change(c["original"], c["corrected"], c["why_es"].strip(), "grammar") for c in d.get("changes", [])
        ])

    def natural(self, paragraph: str, just_corrected: list[str]) -> Step:
        content = paragraph
        if just_corrected:
            content += "\n\nJust corrected (keep as is): " + "; ".join(just_corrected)
        d = self._natural_call(render(load_prompt("writing_natural"), self.level), content)
        changes = [
            Change(c["original"], c["natural"], c["why_es"].strip(),
                   "optional" if c.get("kind") == "optional" else "unnatural")
            for c in d.get("changes", [])
        ]
        # Models sometimes undo step 1 even when told not to: drop changes that touch a correction
        kept = [c for c in changes if not any(_overlaps(c.original, fixed) for fixed in just_corrected)]
        step = apply_changes(paragraph, kept)
        step.skipped += len(changes) - len(kept)
        return step


    def _natural_call(self, system: str, content: str) -> dict:
        try:
            return self.natural_client.structured(system, content, NATURAL_SCHEMA)
        except Exception as e:  # network, auth, quota... the review must still finish
            if self.fallback is None or self.natural_client is self.fallback:
                raise
            self.fallback_reason = f"{type(e).__name__}: {e}"
            self.natural_client = self.fallback
            return self.natural_client.structured(system, content, NATURAL_SCHEMA)


def read_text(path: Path | None) -> str:
    if path:
        return path.read_text(encoding="utf-8")
    print(f"{BOLD}Pega tu texto y termina con Ctrl+D{RESET} (en una línea vacía):")
    return sys.stdin.read()


def show_step(i: int, total: int, step: Step, empty: str) -> None:
    print(f"\n{BOLD}Párrafo {i}/{total}{RESET}")
    if not step.changes:
        print(f"  {GREEN}✅ {empty}{RESET}")
        return
    print("  " + diff(step.before, step.after))
    for n, c in enumerate(step.changes, 1):
        icon = {"grammar": "✏️ ", "unnatural": "💬", "optional": "💡"}[c.kind]
        label = " (opcional)" if c.kind == "optional" else ""
        print(f"  {icon} {n}. {RED}{c.original}{RESET} → {GREEN}{c.new}{RESET}{DIM}{label}{RESET}")
        print(f"       {DIM}{c.why}{RESET}")


def natural_client_or_fallback(spec: str, local):
    """The naturalness client, or the local one (with a warning) if the cloud one can't be created."""
    if not is_cloud(spec):
        return make_client(spec), spec
    try:
        return make_client(spec), spec
    except Exception as e:  # typically OPENAI_API_KEY missing
        print(f"{YELLOW}⚠️  No se pudo usar {spec} ({e}).{RESET}")
        print(f"{YELLOW}   El paso 2 usará el modelo local. Define OPENAI_API_KEY para usar OpenAI.{RESET}")
        return local, "local"


def run(grammar_model: str, natural_model: str, level: Level, path: Path | None) -> None:
    text = read_text(path)
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        print("(texto vacío)")
        return
    local = make_client(grammar_model)
    natural, natural_model = natural_client_or_fallback(natural_model, local)
    if natural_model == "local":
        natural_model = grammar_model
    reviewer = Reviewer(local, natural, level, fallback=local)
    words = sum(len(p.split()) for p in paragraphs)
    print(f"\n{DIM}{len(paragraphs)} párrafos · {words} palabras · nivel {level.name}{RESET}")
    print(f"{DIM}Gramática: {grammar_model} · Naturalidad: {natural_model}"
          f"{' (el texto se envía a OpenAI)' if is_cloud(natural_model) else ''}{RESET}")

    print(f"\n{BOLD}{CYAN}━━ Paso 1: gramática ━━{RESET}")
    grammar = []
    for i, p in enumerate(paragraphs, 1):
        print(f"{DIM}(revisando párrafo {i}/{len(paragraphs)}...){RESET}", end="\r", flush=True)
        grammar.append(reviewer.grammar(p))
        show_step(i, len(paragraphs), grammar[-1], "Sin errores de gramática")
    total = sum(len(s.changes) for s in grammar)
    print(f"\n{BOLD}{total} {'error' if total == 1 else 'errores'} de gramática{RESET}")

    # Step 2 runs in the background while the student reads step 1
    with ThreadPoolExecutor(max_workers=1) as pool:
        futures = [pool.submit(reviewer.natural, s.after, [c.new for c in s.changes]) for s in grammar]
        input(f"\n{BOLD}⏎  Enter para el paso 2 (naturalidad) › {RESET}")
        print(f"\n{BOLD}{CYAN}━━ Paso 2: naturalidad ━━{RESET}")
        natural = []
        for i, future in enumerate(futures, 1):
            if not future.done():
                print(f"{DIM}(revisando párrafo {i}/{len(futures)}...){RESET}", end="\r", flush=True)
            natural.append(future.result())
            if reviewer.fallback_reason:
                print(f"{YELLOW}⚠️  {natural_model} falló ({reviewer.fallback_reason}); "
                      f"sigo con {grammar_model}.{RESET}")
                natural_model, reviewer.fallback_reason = grammar_model, ""
            show_step(i, len(futures), natural[-1], "Suena natural")

    final = "\n\n".join(s.after for s in natural)
    print(f"\n{BOLD}{CYAN}━━ Texto final ━━{RESET}\n\n{final}\n")
    report = save_report(paragraphs, grammar, natural, f"{grammar_model} + {natural_model}", level)
    print(f"{DIM}Informe guardado en {report.relative_to(ROOT)}{RESET}")


def save_report(paragraphs: list[str], grammar: list[Step], natural: list[Step], model: str, level: Level) -> Path:
    def section(steps: list[Step], empty: str) -> list[str]:
        lines = []
        for i, step in enumerate(steps, 1):
            lines += [f"### Párrafo {i}", ""]
            if not step.changes:
                lines += [f"✅ {empty}", ""]
                continue
            lines += [diff(step.before, step.after, markdown=True), ""]
            for n, c in enumerate(step.changes, 1):
                label = " *(opcional)*" if c.kind == "optional" else ""
                lines.append(f"{n}. ~~{c.original}~~ → **{c.new}**{label} — {c.why}")
            lines.append("")
        return lines

    now = datetime.now()
    lines = [f"# Revisión de texto · {now:%Y-%m-%d %H:%M}", "", f"*{model} · nivel {level.name}*", "",
             "## Texto original", "", "\n\n".join(paragraphs), "",
             "## Paso 1: gramática", "", *section(grammar, "Sin errores de gramática"),
             "## Paso 2: naturalidad", "", *section(natural, "Suena natural"),
             "## Texto final", "", "\n\n".join(s.after for s in natural), ""]
    path = ROOT / "writings" / f"{now:%Y-%m-%d_%H%M%S}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _changes_schema(new_key: str, kind: bool = False) -> dict:
    props = {"original": {"type": "string"}, new_key: {"type": "string"}, "why_es": {"type": "string"}}
    if kind:
        props["kind"] = {"type": "string", "enum": ["unnatural", "optional"]}
    return {
        "type": "object",
        "properties": {"changes": {"type": "array", "items": {"type": "object", "properties": props, "required": list(props)}}},
        "required": ["changes"],
    }


GRAMMAR_SCHEMA = _changes_schema("corrected")
NATURAL_SCHEMA = _changes_schema("natural", kind=True)
