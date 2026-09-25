from english_teacher.llm import parse_feedback, reply_sentences

OUTPUT = (
    "CORRECTION: She doesn't like coffee.\n"
    "NATURAL: OK\n"
    "WHY: Con she se usa doesn't.\n"
    "REPLY: Oh, really? What does she drink instead! I prefer tea.\n"
)


def chunks(text: str, size: int):
    return (text[i:i + size] for i in range(0, len(text), size))


def test_reply_sentences_any_chunk_size():
    # Model tokens can split "REPLY:" or a sentence end anywhere
    for size in (1, 2, 3, 7, 50, len(OUTPUT)):
        raw: list[str] = []
        got = list(reply_sentences(chunks(OUTPUT, size), raw))
        assert got == ["Oh, really?", "What does she drink instead!", "I prefer tea."], size
        assert raw[0] == OUTPUT


def test_sentences_are_yielded_before_stream_ends():
    raw: list[str] = []
    gen = reply_sentences(iter(["REPLY: Hello there. ", "How are", " you?"]), raw)
    assert next(gen) == "Hello there."  # available before "How are you?" finishes


def test_reply_without_final_punctuation():
    assert list(reply_sentences(iter(["REPLY: Tell me more"]), [])) == ["Tell me more"]


def test_no_reply_field():
    assert list(reply_sentences(iter(["just some text. more."]), [])) == []


def test_parse_feedback_bold_fields():
    fb = parse_feedback("**CORRECTION:** I agree.\n**NATURAL:** OK\n**WHY:** x\n**REPLY:** Why?")
    assert (fb.correction, fb.natural, fb.reply) == ("I agree.", "OK", "Why?")
    assert fb.parsed


def test_plain_text_mode_speaks_everything():
    pieces = iter(["Give up means to ", "stop trying. For example, I gave up. ", "Your turn!"])
    raw: list[str] = []
    got = list(reply_sentences(pieces, raw, field=False))
    assert got == ["Give up means to stop trying.", "For example, I gave up.", "Your turn!"]
