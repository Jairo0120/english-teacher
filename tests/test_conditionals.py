import json
from concurrent.futures import Future

import pytest

from english_teacher.levels import LEVELS
from english_teacher.practices import (
    ERROR_TAGS, CondItem, Conditionals, Practice, classify_error, load_conditionals,
)


class FakeTutor:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def structured(self, system, content, schema):
        self.calls.append((system, content))
        return self.answers.pop(0)


def grade_answer(correct, error_tag="none", if_clause="", main_clause="", error="", corrected="OK"):
    return {"if_clause": if_clause, "main_clause": main_clause, "correct": correct, "type": 3,
            "error_tag": error_tag, "error": error, "corrected": corrected}


@pytest.fixture
def practice(tmp_path):
    return Conditionals(LEVELS["B2"], progress_path=tmp_path / "c.json")


def set_current(practice, **kw):
    practice.current = CondItem(**kw)


def test_data_file_is_valid():
    data = load_conditionals()
    assert set(data["rules"]) == {1, 2, 3, 4}
    for kind, key in (("translations", "es"), ("fix", "wrong"), ("transform", "situation")):
        for x in data[kind]:
            assert x["type"] in (1, 2, 3, 4) and x["level"] in ("B1", "B2", "C1") and x[key] and x["en"]
    assert all(x["tag"] in ERROR_TAGS for x in data["fix"])
    assert {x["type"] for x in data["translations"]} == {1, 2, 3, 4}


def test_levels(tmp_path):
    b1 = Conditionals(LEVELS["B1"], progress_path=tmp_path / "c.json")
    c1 = Conditionals(LEVELS["C1"], progress_path=tmp_path / "c.json")
    assert b1.types == [1, 2, 3]  # B1: types 1-3, simple vocabulary
    assert all(x["level"] == "B1" for pool in b1.pools.values() for x in pool)
    assert any(x["en"].startswith(("Had I", "Were I")) for x in c1.pools["translations"])  # C1: inversions
    assert any("unless" in x["en"] for x in c1.pools["translations"])


def test_directions_alternate_with_more_es_en(practice):
    practice.fix_rate = practice.transform_rate = 0
    modes = [practice._choose().mode for _ in range(30)]
    assert modes.count("es_en") == 20 and modes.count("en_es") == 10
    assert "en_es en_es" not in " ".join(modes)


def test_classify_error_rules():
    assert classify_error("es_en", 3, "would have known", "would have told", "wrong_if_tense") == "would_in_if"
    assert classify_error("es_en", 1, "will rain", "stay", "none") == "will_in_if"
    assert classify_error("fix", 3, "had knew", "would have come", "other") == "irregular_participle"
    assert classify_error("fix", 3, "had known", "would have came", "other") == "irregular_participle"
    assert classify_error("es_en", 2, "had", "would to travel", "none") == "would_to"
    assert classify_error("es_en", 2, "were", "will talk", "will_in_if") == "will_with_past"
    assert classify_error("es_en", 1, "rains", "will stay", "meaning") == "meaning"  # will is fine in type 1
    assert classify_error("en_es", 3, "sabría", "habría dicho", "wrong_if_tense") == "spanish_structure"
    assert classify_error("es_en", 3, "had seen", "would have taken", "nonsense") == "other"


def test_correct_answer_with_was_note_and_retouches(practice):
    set_current(practice, type=2, mode="es_en", es="Si yo fuera tú...", en="If I were you, I would talk to your boss.")
    tutor = FakeTutor([grade_answer(True, corrected="If I was you, I would talk to your boss.")])
    fb = practice.grade(tutor, "if i was you i would talk with your boss")
    assert fb.result == "CORRECT" and fb.lines[0] == "  🎯 ¡Correcto!"
    assert any("«were» es lo preferido" in l for l in fb.lines)
    assert any("Retoques: If I was you, I would talk to your boss." in l for l in fb.lines)
    system, content = tutor.calls[0]
    assert content.startswith("Expected type: 2 (hypothetical") and "Reference: If I were you" in content
    assert "{{" not in system and "B2" in system


def test_two_attempts_then_reference_and_rule(practice, tmp_path):
    set_current(practice, type=3, mode="es_en", es="Si lo hubiera sabido, te lo habría dicho.",
                en="If I had known, I would have told you.")
    wrong = grade_answer(False, "wrong_if_tense", "would have known", "would have told", "No se usa would en el if.")
    fb = practice.grade(FakeTutor([wrong]), "if i would have known i would have told you")
    assert fb.lines[0] == "  🔁 Todavía no · would en la parte del if"
    assert not any("Versión correcta" in l for l in fb.lines)  # not given away on the first attempt
    assert practice.quick_reply("x", fb) == "Not quite. Try again."
    practice.after(fb)
    assert practice.attempt == 2

    fb = practice.grade(FakeTutor([dict(wrong)]), "if i would known i would have told you")
    assert fb.lines[0].startswith("  ❌ No es correcto")
    assert "  ✅ Versión correcta: If I had known, I would have told you." in fb.lines
    assert any(l.startswith("  📘 Pasado irreal: if + had + participio") for l in fb.lines)
    upcoming = practice.next
    assert practice.quick_reply("x", fb).startswith("Not quite. Check the correct version on your screen.")
    practice.after(fb)
    assert practice.current is upcoming and practice.attempt == 1

    saved = json.loads((tmp_path / "c.json").read_text())
    assert saved["type:3"] == {"attempts": 2, "correct": 0, "last": saved["type:3"]["last"]}
    assert saved["dir:es_en"]["attempts"] == 2 and saved["errors"] == {"would_in_if": 2}
    assert "Errores más repetidos: would en la parte del if (2)" in practice.summary()


def test_translation_into_spanish_listens_in_spanish(practice):
    set_current(practice, type=3, mode="en_es", es="Si lo hubiera sabido...", en="If I had known...")
    assert practice.listen_language() == "es"
    assert practice.announce() == "🇬🇧 → 🇪🇸 Traduce al español: If I had known..."
    set_current(practice, type=3, mode="fix", en="If I had known.", wrong="If I would have known.")
    assert practice.listen_language() == "en" and practice.announce().startswith("🔧 Corrige el error")
    assert Practice().listen_language() == "en"


def test_variation_used_when_ready_and_seed_kept_on_failure(practice):
    item = CondItem(type=1, mode="es_en", es="seed es", en="seed en")
    item.future = Future()
    item.future.set_result(("Si nieva, no salgo.", "If it snows, I don't go out."))
    practice._activate(item)
    assert (item.es, item.en) == ("Si nieva, no salgo.", "If it snows, I don't go out.") and item.future is None

    broken = CondItem(type=1, mode="es_en", es="seed es", en="seed en")
    broken.future = Future()
    broken.future.set_exception(ValueError("empty variation"))
    practice._activate(broken)
    assert (broken.es, broken.en) == ("seed es", "seed en")


def test_vary_asks_for_same_type(practice):
    practice.tutor = FakeTutor([{"es": "Si nieva, no salgo.", "en": "If it snows, I don't go out."}])
    assert practice._vary({"type": 1, "es": "Si llueve...", "en": "If it rains..."})[0] == "Si nieva, no salgo."
    assert "Example (type 1: real or possible" in practice.tutor.calls[0][1]
    practice.tutor = FakeTutor([{"es": "", "en": "x"}])
    with pytest.raises(ValueError):
        practice._vary({"type": 1, "es": "a", "en": "b"})


def test_weakest_type_is_prioritized(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({
        "type:1": {"attempts": 10, "correct": 10, "last": "2026-01-01"},
        "type:2": {"attempts": 10, "correct": 9, "last": "2026-01-01"},
        "type:3": {"attempts": 10, "correct": 2, "last": "2026-01-01"},
        "type:4": {"attempts": 10, "correct": 3, "last": "2026-01-01"},
    }))
    c = Conditionals(LEVELS["B2"], progress_path=path)
    assert {c._choose().type for _ in range(40)} == {3, 4}


def test_summary_by_type(practice):
    practice.results = [(CondItem(1, "es_en"), True), (CondItem(3, "fix"), False), (CondItem(3, "es_en"), True)]
    assert practice.summary().splitlines()[:2] == ["Condicionales: 2/3 bien", "  Por tipo: Real o posible 1/1 · Pasado irreal 1/2"]
