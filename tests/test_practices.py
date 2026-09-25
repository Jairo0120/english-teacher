import json

import pytest

from english_teacher.levels import LEVELS, render
from english_teacher.llm import Feedback
from english_teacher.practices import PRACTICES, PhrasalVerbs


class FakeTutor:
    """Returns a canned grader answer and records what it was asked."""

    def __init__(self, answer: dict):
        self.answer = answer
        self.calls = []

    def structured(self, system, content, schema):
        self.calls.append(content)
        return self.answer


@pytest.fixture
def practice(tmp_path):
    verbs = tmp_path / "verbs.txt"
    verbs.write_text("# comment\ngive up\nlook after\nrun into\nput off\nset up\nfind out\n")
    return PhrasalVerbs(LEVELS["B1"], [verbs], tmp_path / "progress.json")


def grade(practice, sentence="x", verb_words="gived up", meaning_ok=True, natural_use=True):
    tutor = FakeTutor({"verb_words": verb_words, "meaning_ok": meaning_ok, "natural_use": natural_use,
                       "correction": "Fixed.", "natural": "OK", "why": "Because."})
    return practice.grade(tutor, sentence), tutor


def test_current_and_next_differ(practice):
    assert practice.current != practice.next
    assert practice.current in practice.opening()


def test_grade_correct_only_with_words_and_meaning(practice):
    fb, tutor = grade(practice, "i gived up smoking")
    assert fb.result == "CORRECT" and fb.correction == "Fixed." and fb.verb_words == "gived up"
    assert tutor.calls == [f"Target: {practice.current} | Student: i gived up smoking"]
    assert grade(practice, verb_words="", meaning_ok=True)[0].result == "RETRY"  # meaning without the verb
    assert grade(practice, verb_words="give up", meaning_ok=False)[0].result == "RETRY"


def test_reply_instruction_per_case(practice):
    cur, nxt = practice.current, practice.next
    ok, _ = grade(practice)
    assert f"introduce the next phrasal verb: {nxt}" in practice.reply_instruction("s", ok)

    missing, _ = grade(practice, verb_words="", meaning_ok=False)
    first = practice.reply_instruction("s", missing)
    assert f"did not use {cur}" in first and "try again" in first and nxt not in first

    wrong, _ = grade(practice, verb_words="looked after", meaning_ok=False)
    practice.after(wrong)  # now on the last attempt
    last = practice.reply_instruction("s", wrong)
    assert "looked after with the wrong meaning" in last
    assert f"example sentence with {cur}" in last and f"next phrasal verb: {nxt}" in last


def test_correct_advances_to_announced_next(practice):
    first, announced = practice.current, practice.next
    practice.after(Feedback(result="CORRECT"))
    assert (practice.current, practice.attempt) == (announced, 1)
    assert practice.done == [(first, True)]


def test_retry_then_move_on_after_max_attempts(practice):
    first, announced = practice.current, practice.next
    practice.after(Feedback(result="RETRY"))
    assert (practice.current, practice.attempt) == (first, 2)
    practice.after(Feedback(result="RETRY"))
    assert (practice.current, practice.attempt) == (announced, 1)
    assert practice.done == [(first, False)]
    assert "a repasar: " + first in practice.summary()


def test_follow_up_only_when_new_verb_not_introduced(practice):
    practice.after(Feedback(result="RETRY"))
    assert practice.follow_up(Feedback(reply="Almost, try again")) is None  # still on the same verb
    practice.after(Feedback(result="RETRY"))  # moved on
    assert practice.follow_up(Feedback(reply="Let's continue.")) == practice.opening()
    assert practice.follow_up(Feedback(reply=f"Now: {practice.current.upper()} means...")) is None


def test_progress_saved_and_seen_verbs_deprioritized(practice, tmp_path):
    first = practice.current
    practice.after(Feedback(result="CORRECT"))
    saved = json.loads((tmp_path / "progress.json").read_text())
    assert saved[first]["attempts"] == 1 and saved[first]["correct"] == 1
    # With 6 verbs and 1 seen, the top-5 candidates are always the 5 unseen ones
    reloaded = PhrasalVerbs(LEVELS["B1"], [tmp_path / "verbs.txt"], tmp_path / "progress.json")
    assert all(reloaded._pick(exclude=set()) != first for _ in range(50))


def test_picks_are_not_always_alphabetical(practice):
    assert len({practice._pick(exclude=set()) for _ in range(100)}) > 3


def test_all_prompts_fully_rendered_for_every_level():
    for level in LEVELS.values():
        for cls in PRACTICES.values():
            prompt = cls(level).system_prompt()
            assert cls.title and cls.description and prompt
            assert "{{" not in prompt, (level.name, cls.key)
            assert level.name in prompt


def test_render_keeps_json_braces():
    assert render('{"a": 1} {{name}}', LEVELS["C1"]) == '{"a": 1} C1'


def test_level_lists(tmp_path):
    common = PhrasalVerbs(LEVELS["B1"], progress_path=tmp_path / "p.json").verbs
    both = PhrasalVerbs(LEVELS["B2"], progress_path=tmp_path / "p.json").verbs
    advanced = PhrasalVerbs(LEVELS["C1"], progress_path=tmp_path / "p.json").verbs
    assert "get up" in common and "iron out" not in common
    assert "iron out" in advanced and "get up" not in advanced
    assert set(both) == set(common) | set(advanced) and len(both) == len(set(both))


def test_strict_levels_require_natural_use(tmp_path):
    verbs = tmp_path / "v.txt"
    verbs.write_text("come across\nfall through\niron out\n")
    b1 = PhrasalVerbs(LEVELS["B1"], [verbs], tmp_path / "p.json")
    b2 = PhrasalVerbs(LEVELS["B2"], [verbs], tmp_path / "p.json")
    assert grade(b1, verb_words="came across", natural_use=False)[0].result == "CORRECT"
    fb, _ = grade(b2, verb_words="came across", natural_use=False)
    assert fb.result == "RETRY"
    assert "wouldn't use it like that" in b2.reply_instruction("s", fb)
    assert grade(b2, verb_words="came across", natural_use=True)[0].result == "CORRECT"
