import re

from english_teacher.levels import LEVELS
from english_teacher.writing import Change, Reviewer, apply_changes, diff, save_report, split_paragraphs

ANSI = re.compile(r"\x1b\[[0-9;]*m")


class FakeTutor:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def structured(self, system, content, schema):
        self.calls.append((system, content))
        return self.answers[len(self.calls) - 1]


def test_split_paragraphs_normalizes_whitespace():
    text = "First  line\ncontinues.\n\n\n  Second   one.  \n \nThird."
    assert split_paragraphs(text) == ["First line continues.", "Second one.", "Third."]


def test_apply_changes_exact_case_insensitive_and_skipped():
    text = "The first days we was very exciting in Bergen."
    step = apply_changes(text, [
        Change("we was", "we were", "a", "grammar"),
        Change("the first days", "the first few days", "b", "optional"),  # wrong case: still applied
        Change("very exciting", "very excited", "c", "grammar"),
        Change("in Madrid", "in Bergen", "d", "grammar"),  # not in the text
        Change("Bergen", "Bergen", "e", "grammar"),  # no-op
    ])
    assert step.after == "The first few days we were very excited in Bergen."
    assert [c.why for c in step.changes] == ["a", "b", "c"]
    assert step.skipped == 2 and step.before == text


def test_diff_marks_only_changed_words():
    old, new = "I am agree with you", "I agree with you"
    assert diff(old, new, markdown=True) == "I ~~am~~ agree with you"
    assert diff("since months ago", "for months ago", markdown=True) == "~~since~~ **for** months ago"
    assert ANSI.sub("", diff(old, new)) == "I am agree with you"  # terminal version keeps both words


def test_reviewer_steps_and_protected_corrections():
    tutor = FakeTutor([
        {"changes": [{"original": "since months", "corrected": "for months", "why_es": "for + periodo"}]},
        {"changes": [
            {"original": "make a trip", "natural": "take a trip", "kind": "unnatural", "why_es": "collocation"},
            {"original": "In general", "natural": "Overall", "kind": "optional", "why_es": "más natural"},
        ]},
    ])
    reviewer = Reviewer(tutor, tutor, LEVELS["B2"])
    g = reviewer.grammar("We planned to make a trip since months. In general it was great.")
    assert g.after == "We planned to make a trip for months. In general it was great."
    assert g.changes[0].kind == "grammar"

    n = reviewer.natural(g.after, [c.new for c in g.changes])
    assert n.after == "We planned to take a trip for months. Overall it was great."
    assert [c.kind for c in n.changes] == ["unnatural", "optional"]
    assert "Just corrected (keep as is): for months" in tutor.calls[1][1]
    assert "B2" in tutor.calls[0][0] and "{{" not in tutor.calls[1][0]


def test_report(tmp_path, monkeypatch):
    import english_teacher.writing as w
    monkeypatch.setattr(w, "ROOT", tmp_path)
    g = apply_changes("I am agree.", [Change("am agree", "agree", "No se usa be.", "grammar")])
    n = apply_changes(g.after, [])
    path = save_report(["I am agree."], [g], [n], "qwen3:14b", LEVELS["B2"])
    text = path.read_text()
    assert path.parent == tmp_path / "writings"
    assert "I ~~am~~ agree." in text and "1. ~~am agree~~ → **agree** — No se usa be." in text
    assert "✅ Suena natural" in text and text.rstrip().endswith("I agree.")


def test_naturalness_cannot_undo_grammar_corrections():
    tutor = FakeTutor([{"changes": [
        {"original": "take a trip", "natural": "go", "kind": "unnatural", "why_es": "wrong"},
        {"original": "friends of the university", "natural": "university friends", "kind": "unnatural", "why_es": "ok"},
    ]}])
    step = Reviewer(tutor, tutor, LEVELS["B2"]).natural("I decided to take a trip with friends of the university.", ["take a trip"])
    assert step.after == "I decided to take a trip with university friends."
    assert [c.why for c in step.changes] == ["ok"] and step.skipped == 1


class FailingClient:
    def structured(self, system, content, schema):
        raise ConnectionError("no network")


def test_naturalness_falls_back_to_local_model():
    local = FakeTutor([{"changes": [
        {"original": "make a trip", "natural": "take a trip", "kind": "unnatural", "why_es": "local"}]}])
    reviewer = Reviewer(local, FailingClient(), LEVELS["B2"], fallback=local)
    step = reviewer.natural("We wanted to make a trip.", [])
    assert step.after == "We wanted to take a trip." and reviewer.natural_client is local
    assert reviewer.fallback_reason == "ConnectionError: no network"
