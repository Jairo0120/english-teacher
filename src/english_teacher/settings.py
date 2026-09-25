"""User settings that persist between sessions (e.g. the level)."""

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[2] / "settings.json"


def load(path: Path = SETTINGS_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(values: dict, path: Path = SETTINGS_PATH) -> None:
    path.write_text(json.dumps({**load(path), **values}, indent=2), encoding="utf-8")
