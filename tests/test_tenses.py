import pytest

from english_teacher.levels import LEVELS
from english_teacher.llm import Feedback
from english_teacher.practices import Structure, Tenses, _spoken, load_structures


class FakeTutor:
    def __init__(self, answer: dict):
        self.answer = answer
        self.calls = []

    def structured(self, system, content, schema):
        self.calls.append(content)
        return self.answer


def structures(n=4):
    return [
        Structure(key=f"s{i}", name=f"tense {i}", name_es=f"tiempo {i}", level="B2", hint=f"hint {i}",
                  translations=[{"es": f"frase {i}.{j}", "en": f"sentence {i}.{j}"} for j in range(3)])
        for i in range(n)
    ]


@pytest.fixture
def practice(tmp_path):
    return Tenses(LEVELS["B2"], structures(), tmp_path / "p.json", diagnostic=False)


def grade(practice, target_ok=True, meaning_ok=True, natural="OK", correction="OK"):
    tutor = FakeTutor({"verb_words": "have been", "target_ok": target_ok, "meaning_ok": meaning_ok,
                       "correction": correction, "natural": natural, "why_es": "Regla."})
    return practice.grade(tutor, "answer"), tutor


def test_data_file_is_valid():
    data = load_structures()
    assert len(data) == 13 and len({s.key for s in data}) == 13
    for st in data:
        assert st.level in ("B1", "B2") and st.hint and st.name_es
        assert len(st.translations) == 3 and all(t["es"] and t["en"] for t in st.translations)


def test_b1_only_gets_b1_structures(tmp_path):
    b1 = Tenses(LEVELS["B1"], progress_path=tmp_path / "p.json", diagnostic=False)
    b2 = Tenses(LEVELS["B2"], progress_path=tmp_path / "p.json", diagnostic=False)
    assert {s.level for s in b1.structures} == {"B1"}
    assert len(b2.structures) == 13 and len(b1.structures) < 13


def test_modes_alternate_and_translations_are_announced(practice):
    assert {practice.current.mode, practice.next.mode} == {"question", "translation"}
    for _ in range(3):
        practice.after(Feedback(result="CORRECT"))
        announced = practice.announce()
        if practice.current.mode == "translation":
            assert announced == f"🇪🇸 Traduce: {practice.current.es}"
        else:
            assert announced is None


def test_grading_by_mode(practice):
    practice.current.mode = "question"
    practice.heard("How long have you been living there?")
    fb, tutor = grade(practice, meaning_ok=False)
    assert fb.result == "CORRECT"  # meaning only matters for translations
    assert "Question: How long have you been living there?" in tutor.calls[0]

    practice.current = practice._item(practice.structures[0])
    practice.current.mode, practice.current.es, practice.current.en = "translation", "Llevo aquí.", "I've been here."
    fb, tutor = grade(practice, meaning_ok=False)
    assert fb.result == "RETRY" and fb.why == "Regla."
    assert "Spanish: Llevo aquí. | Reference: I've been here." in tutor.calls[0]
    assert grade(practice, target_ok=False)[0].result == "RETRY"


def reply(practice, fb):
    """What the session does: fixed text first, then the model instruction if any."""
    return practice.quick_reply("x", fb), practice.reply_instruction("x", fb)


def test_retry_hint_is_fixed_then_answer_then_move_on(practice):
    first, upcoming = practice.current, practice.next
    fb, _ = grade(practice, target_ok=False, natural="I've lived here for years.")
    quick, instruction = reply(practice, fb)
    assert quick.startswith("Not quite. You need the tense 0 here.") or "You need the tense" in quick
    assert instruction is None  # a hint needs no model call
    practice.after(fb)
    assert practice.current is first and practice.attempt == 2

    quick, instruction = reply(practice, fb)
    expected = first.en if first.mode == "translation" else "I've lived here for years."
    assert f"A correct version would be: {expected}" in quick
    if upcoming.mode == "translation":
        assert quick.endswith(practice.TRANSLATE) and instruction is None
    else:
        assert "Do not repeat it" in instruction and upcoming.structure.hint in instruction
    practice.after(fb)
    assert practice.current is upcoming and practice.attempt == 1
    assert practice.done == [(first.structure, False)]


def test_model_is_only_used_for_new_questions(practice):
    for _ in range(6):
        fb, _ = grade(practice)
        quick, instruction = reply(practice, fb)
        assert quick.split()[0] in ("Great!", "Well", "Exactly!", "Nice")
        assert (instruction is None) == (practice.next.mode == "translation")
        practice.after(fb)


def test_spoken_structure_names():
    assert _spoken("present perfect continuous (for / since)") == "present perfect continuous"
    assert _spoken("wish / if only") == "wish or if only"


def test_intro_and_opening(tmp_path):
    for _ in range(10):
        t = Tenses(LEVELS["B2"], structures(), tmp_path / "p.json", diagnostic=False)
        if t.current.mode == "translation":
            assert t.intro().endswith(t.TRANSLATE) and t.opening() is None
        else:
            assert t.intro() == "Let's practice tenses." and t.current.structure.hint in t.opening()


def test_diagnostic_one_item_per_structure_no_retries(tmp_path):
    t = Tenses(LEVELS["B2"], structures(), tmp_path / "p.json", diagnostic=True)
    assert t.intro().startswith("Let's do a quick check")
    seen = []
    while not t.finished:
        seen.append(t.current.structure.key)
        assert t.status().startswith(f"Diagnóstico {len(seen)}/4")
        fb, _ = grade(t, target_ok=len(seen) % 2 == 0)
        quick, _ = reply(t, fb)
        assert quick.startswith("Okay, thanks.")  # neutral: doesn't say if it was right
        if len(seen) == 4:
            assert "end of the check" in quick
        t.after(fb)
    assert sorted(seen) == ["s0", "s1", "s2", "s3"]
    assert t.summary() == f"Diagnóstico: 2/4 bien · a repasar: tiempo {seen[0][1]}, tiempo {seen[2][1]}"
    again = Tenses(LEVELS["B2"], structures(), tmp_path / "p.json", diagnostic=False)
    assert again.progress.data[seen[0]]["correct"] == 0


def test_translations_not_repeated_in_a_session(practice):
    asked = []
    for _ in range(12):
        if practice.current.mode == "translation":
            asked.append(practice.current.es)
        practice.after(Feedback(result="CORRECT"))
    assert len(asked) == len(set(asked))
