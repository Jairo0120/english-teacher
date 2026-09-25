import json

import pytest

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
    return PhrasalVerbs(verbs, tmp_path / "progress.json")


def grade(practice, sentence="x", verb_words="gived up", meaning_ok=True):
    tutor = FakeTutor({"verb_words": verb_words, "meaning_ok": meaning_ok,
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
    reloaded = PhrasalVerbs(tmp_path / "verbs.txt", tmp_path / "progress.json")
    assert all(reloaded._pick(exclude=set()) != first for _ in range(50))


def test_picks_are_not_always_alphabetical(practice):
    assert len({practice._pick(exclude=set()) for _ in range(100)}) > 3


def test_practices_have_prompts():
    for cls in PRACTICES.values():
        assert cls.title and cls.description and cls().system_prompt()
