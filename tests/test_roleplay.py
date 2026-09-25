import pytest

from english_teacher.levels import LEVELS
from english_teacher.llm import Feedback
from english_teacher.practices import CHARACTER_VOICES, Conversation, PhrasalVerbs, RolePlay, Scenario, load_scenarios
from english_teacher.tts import VOICES


class FakeTutor:
    def __init__(self, answer: dict):
        self.answer = answer
        self.calls = []

    def structured(self, system, content, schema):
        self.calls.append((system, content))
        return self.answer


SCENE = Scenario(
    title="Hotel", name="Receptionist", character="A tired receptionist.", voice="am_michael",
    student_role="A traveler.", setting="It's 11 pm at a hotel.", goal="Get a room.",
    twists=["Only a small room is left.", "The card machine is broken."],
)


@pytest.fixture
def rp():
    return RolePlay(LEVELS["B2"], SCENE)


def play_turn(rp, sentence="hello", goal_met=False):
    # Same order as the session: reply first, then grade (grade_after_reply)
    instruction = rp.reply_instruction(sentence, None)
    fb = rp.grade(FakeTutor({"correction": "OK", "natural": "OK", "why_es": "", "goal_met": goal_met}), sentence)
    rp.after(fb)
    return instruction


def test_scenarios_are_complete_and_use_real_voices():
    all_voices = {v for names in VOICES.values() for v in names}
    scenarios = load_scenarios()
    assert len(scenarios) >= 10
    for sc in scenarios:
        assert all([sc.title, sc.name, sc.character, sc.student_role, sc.setting, sc.goal]), sc.title
        assert len(sc.twists) == 2, sc.title
        assert sc.voice in all_voices and sc.voice != "af_heart", sc.title  # af_heart is the narrator


def test_prompt_and_intro_include_the_scene(rp):
    prompt = rp.system_prompt()
    assert "A tired receptionist." in prompt and "Get a room." in prompt and "{{" not in prompt
    assert LEVELS["B2"].character in prompt
    assert rp.intro().startswith("Here's the scene. It's 11 pm at a hotel.")
    assert rp.voice == "am_michael"


def test_grader_gets_last_character_line(rp):
    rp.heard("Sorry, I can't find your booking.")
    tutor = FakeTutor({"correction": "I booked it.", "natural": "OK", "why_es": "Pasado.", "goal_met": False})
    fb = rp.grade(tutor, "i booked")
    assert "Receptionist said: Sorry, I can't find your booking." in tutor.calls[0][1]
    assert fb.correction == "I booked it." and fb.why == "Pasado."
    assert not fb.result  # no "correct / retry" in role-play


def test_twists_come_at_their_turns_and_scene_ends_at_max(rp):
    notes = [play_turn(rp, f"turn {i}") for i in range(1, rp.max_turns + 1)]
    assert notes[0] == "turn 1"  # plain turns send only what the student said
    assert "Only a small room is left." in notes[2]
    assert "The card machine is broken." in notes[5]
    assert sum("complication" in n for n in notes) == 2
    assert "time is up" in notes[-1] and "natural end" in notes[-1]
    assert rp.finished and not rp.goal_met
    assert "no conseguido" in rp.summary()


def test_goal_met_ends_the_scene(rp):
    play_turn(rp)
    assert not rp.finished
    play_turn(rp, "so you can give me the suite", goal_met=True)  # the character's reply closes the deal
    assert rp.finished and rp.goal_met and "conseguido ✅" in rp.summary()


def test_debrief(rp):
    assert rp.debrief(FakeTutor({})) is None  # nothing said yet
    play_turn(rp, "i have a reservation since two weeks")
    tutor = FakeTutor({
        "spoken": "Good job.",
        "mistakes": [{"pattern": "Present perfect", "example": "since two weeks", "fix": "for two weeks"}],
        "phrases": [{"phrase": "I'd like to speak to the manager", "meaning": "pedir hablar con el encargado"}],
    })
    review = rp.debrief(tutor)
    assert review.spoken == "Good job."
    assert "  • Present perfect: since two weeks → for two weeks" in review.lines
    assert any("speak to the manager" in line for line in review.lines)
    assert "i have a reservation since two weeks" in tutor.calls[0][1]


def test_invent_builds_a_playable_scene(rp):
    tutor = FakeTutor({
        "title": "Gimnasio", "name": "Gym manager", "character": "Strict.", "gender": "male",
        "student_role": "A member.", "setting": "You want to cancel.", "goal": "Cancel for free.",
        "twists": ["a", "b", "c"],
    })
    scene = rp.invent(tutor, "gym membership")
    assert scene.voice in CHARACTER_VOICES["male"] and scene.twists == ["a", "b"]
    assert "gym membership" in tutor.calls[0][1]


def test_help(rp):
    tutor = FakeTutor({"option_1": "a", "option_2": "b", "option_3": "c"})
    assert rp.help(tutor, "We're full tonight.") == ["a", "b", "c"]
    assert "just said: We're full tonight." in tutor.calls[0][0]
    assert Conversation(LEVELS["B2"]).help(tutor, "hi") == ["a", "b", "c"]
    assert PhrasalVerbs(LEVELS["B1"]).help(tutor, "hi") is None
