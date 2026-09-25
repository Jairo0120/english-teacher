import pytest

from english_teacher.levels import LEVELS
from english_teacher.practices import ListeningText, Paraphrase, reuse_ratio

ORIGINAL = "Pilot programs across various industries have demonstrated surprisingly positive outcomes for workers."


class FakeTutor:
    def __init__(self, answers: list[dict]):
        self.answers = answers
        self.calls = []

    def structured(self, system, content, schema):
        self.calls.append((system, content))
        return self.answers[min(len(self.calls), len(self.answers)) - 1]


TEXT = {"title": "Four days", "text": ORIGINAL, "point_1": "a", "point_2": "b", "point_3": "c", "point_4": "d"}
GRADE = {"covered_1": True, "covered_2": False, "covered_3": True, "covered_4": True,
         "wrong_info": "Dijo menos productividad.", "comment": "Good job."}
REVIEW = {"mistakes": [{"wrong": "he think", "fix": "he thinks"}], "model": "Trials were positive."}


def test_reuse_ratio():
    assert reuse_ratio(ORIGINAL, "companies that tried it got good results") == 0
    assert reuse_ratio(ORIGINAL, ORIGINAL.lower()) == 1
    assert reuse_ratio(ORIGINAL, "they said pilot programs across various companies were good") == pytest.approx(2 / 7)
    assert reuse_ratio(ORIGINAL, "too short") == 0


@pytest.fixture
def practice():
    return Paraphrase(LEVELS["B2"], topic="")


def test_round_flow(practice):
    tutor = FakeTutor([TEXT, GRADE, REVIEW, {**TEXT, "title": "Second"}])
    practice.prepare(tutor)  # starts generating the first text
    assert practice.round_pending() and practice.announce() is None
    assert practice.next_round(tutor) == ORIGINAL
    assert not practice.round_pending() and "propias palabras" in practice.announce()
    assert "Kind of text:" in tutor.calls[0][1] and "60 and 75 words" in tutor.calls[0][0]

    fb = practice.grade(tutor, "pilot programs across various industries were good")
    assert "Copied word for word: 60%" in tutor.calls[1][1] and "Key ideas:\n1. a" in tutor.calls[1][1]
    assert fb.lines[0] == "  📊 Ideas: 3/4 · copiado literal: 60%  ⚠️ parafrasea más"
    assert "     ❌ b" in fb.lines and any("Dato incorrecto" in l for l in fb.lines)
    late = practice.late_feedback()  # mistakes + model, prepared in the background
    assert late == ["  ✏️  he think → he thinks", "  💡 Versión modelo: Trials were positive.",
                    f"  📝 Texto original: {ORIGINAL}"]
    assert practice.late_feedback() == []  # shown once
    assert practice.quick_reply("x", fb) == "Good job. Press Enter when you're ready for the next one."
    assert practice.reply_instruction("x", fb) is None

    practice.after(fb)
    assert practice.round_pending()
    practice.next_round(tutor)  # was prefetched during grading
    assert "different from these earlier texts: Four days" in tutor.calls[3][1]
    assert practice.summary() == "Parafraseo: 1 textos · ideas cubiertas 3/4 · copiado literal medio 60%"


def test_fixed_topic_is_used(practice):
    practice.topic = "the history of the bicycle"
    tutor = FakeTutor([TEXT])
    practice.next_round(tutor)
    assert tutor.calls[0][1].startswith("Topic: the history of the bicycle")


def test_level_changes_length():
    tutor = FakeTutor([TEXT])
    Paraphrase(LEVELS["C1"], topic="").next_round(tutor)
    assert "75 and 90 words" in tutor.calls[0][0]
