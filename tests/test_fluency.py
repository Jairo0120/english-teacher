import numpy as np
import pytest

from english_teacher.fluency import Fluency, FluencyLog, measure


def test_metrics():
    f = Fluency(words=30, span=20.0, speech=14.0, pauses=[0.3, 0.8, 1.5, 0.2])
    assert f.wpm == 90
    assert f.long_pauses == [0.8, 1.5]
    assert f.speech_ratio == pytest.approx(0.7)
    assert f.describe() == "90 ppm · 2 pausas largas (máx 1.5s) · 70% del tiempo hablando"
    assert "1 pausa larga " in Fluency(10, 10.0, 9.0, [0.9]).describe()


def test_silence_is_not_measured():
    assert measure(np.zeros(16000 * 3, dtype=np.float32), "one two three four") is None


def test_log_summary_compares_with_previous_sessions(tmp_path):
    path = tmp_path / "fluency.csv"
    old = FluencyLog("conversation", "B2", path)
    old.session = "2026-01-01T10:00:00"
    old.add(Fluency(words=40, span=30.0, speech=20.0, pauses=[]))  # 80 wpm
    new = FluencyLog("conversation", "B2", path)
    assert new.summary() is None
    new.add(Fluency(words=50, span=30.0, speech=25.0, pauses=[1.0, 2.0]))  # 100 wpm
    new.add(Fluency(words=50, span=30.0, speech=25.0, pauses=[]))
    summary = new.summary()
    assert summary.startswith("Fluidez: 100 ppm · 2.0 pausas largas por minuto")
    assert "tu sesión anterior: 80 ppm" in summary
    assert len(path.read_text().splitlines()) == 4  # header + 3 answers
