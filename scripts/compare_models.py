"""Compare tutor models on sentences with typical Spanish-speaker mistakes.

Usage:
    uv run scripts/compare_models.py                      # gemma3:12b vs qwen3:14b
    uv run scripts/compare_models.py -m gemma3:12b -m qwen3:8b
    uv run scripts/compare_models.py -s mis_frases.txt    # one sentence per line

Writes a side-by-side Markdown report to results/ to review in Obsidian or any editor.
"""

import argparse
import statistics
import time
from datetime import datetime
from pathlib import Path

from english_teacher.levels import DEFAULT_LEVEL, LEVELS
from english_teacher.llm import Tutor
from english_teacher.practices import Conversation

ROOT = Path(__file__).resolve().parents[1]

# (sentence as it would come out of Whisper, what a good tutor should catch)
DEFAULT_CASES = [
    ("i have 30 years", "I'm 30 (years old)"),
    ("yesterday i go to the cinema with my friends", "went: pasado"),
    ("she don't like coffee", "doesn't"),
    ("i am agree with you", "I agree"),
    ("people is very friendly here", "people are"),
    ("i want that you help me", "I want you to help me"),
    ("i'm living here since 2019", "I've been living / I've lived"),
    ("can you explain me the problem", "explain the problem to me"),
    ("it depends of the weather", "depends on"),
    ("i did a mistake in the exam", "made a mistake"),
    ("i'm boring, there is nothing to do", "I'm bored"),
    ("my english is not so good but i try to improve it every day", "correcta: no debería corregir de más"),
    ("i went to the supermarket and i buyed milk", "bought"),
    ("how do you call this in english", "what do you call this"),
    ("the last weekend i visited my parents", "last weekend (sin 'the')"),
]


def load_cases(path: Path | None) -> list[tuple[str, str]]:
    if path is None:
        return DEFAULT_CASES
    lines = path.read_text(encoding="utf-8").splitlines()
    return [(line.strip(), "") for line in lines if line.strip() and not line.startswith("#")]


def run_model(model: str, cases: list[tuple[str, str]], prompt: str) -> list[dict]:
    print(f"\n=== {model} ===")
    Tutor(prompt, model, keep_history=False).ask("hello")  # warm-up: load the model before timing
    results = []
    for i, (sentence, expected) in enumerate(cases, 1):
        tutor = Tutor(prompt, model, keep_history=False)  # fresh context per sentence for a fair comparison
        start = time.perf_counter()
        fb = tutor.ask(sentence)
        elapsed = time.perf_counter() - start
        results.append({"feedback": fb, "seconds": elapsed})
        status = "ok" if fb.parsed else "FORMATO ROTO"
        print(f"[{i:2}/{len(cases)}] {elapsed:5.1f}s {status:12} {sentence!r} -> {fb.correction or fb.raw[:60]!r}")
    return results


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>") or "—"


def write_report(models: list[str], cases: list[tuple[str, str]], all_results: dict[str, list[dict]]) -> Path:
    out = ROOT / "results" / f"compare_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.parent.mkdir(exist_ok=True)

    lines = ["# Comparación de modelos tutor", "", "## Resumen", "",
             "| Modelo | Latencia media | Latencia máx | Formato correcto |", "|---|---|---|---|"]
    for m in models:
        secs = [r["seconds"] for r in all_results[m]]
        ok = sum(r["feedback"].parsed for r in all_results[m])
        lines.append(f"| {m} | {statistics.mean(secs):.1f}s | {max(secs):.1f}s | {ok}/{len(cases)} |")

    for i, (sentence, expected) in enumerate(cases):
        lines += ["", f"## {i + 1}. `{sentence}`", ""]
        if expected:
            lines += [f"**Esperado:** {expected}", ""]
        lines += ["| Campo | " + " | ".join(models) + " |", "|---" * (len(models) + 1) + "|"]
        for field in ("correction", "natural", "why", "reply"):
            row = [cell(getattr(all_results[m][i]["feedback"], field)) for m in models]
            lines.append(f"| {field.upper()} | " + " | ".join(row) + " |")
        broken = [m for m in models if not all_results[m][i]["feedback"].parsed]
        for m in broken:
            lines += ["", f"<details><summary>Salida cruda de {m}</summary>", "",
                      "```", all_results[m][i]["feedback"].raw, "```", "</details>"]

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-m", "--model", action="append", dest="models", help="modelo de Ollama (repetible)")
    parser.add_argument("-s", "--sentences", type=Path, help="archivo con una frase por línea")
    parser.add_argument("-l", "--level", choices=LEVELS, default=DEFAULT_LEVEL, help="nivel del prompt de conversación")
    args = parser.parse_args()

    models = args.models or ["gemma3:12b", "qwen3:14b"]
    cases = load_cases(args.sentences)
    prompt = Conversation(LEVELS[args.level]).system_prompt()
    all_results = {m: run_model(m, cases, prompt) for m in models}
    report = write_report(models, cases, all_results)
    print(f"\nReporte: {report}")


if __name__ == "__main__":
    main()
