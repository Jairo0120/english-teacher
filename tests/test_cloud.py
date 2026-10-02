import json
from types import SimpleNamespace

import pytest

from english_teacher.cloud import OpenAIClient, is_cloud, make_client, strict_schema
from english_teacher.llm import Tutor
from english_teacher.writing import NATURAL_SCHEMA


def test_strict_schema_closes_every_object_without_touching_the_original():
    strict = strict_schema(NATURAL_SCHEMA)
    assert strict["additionalProperties"] is False and strict["required"] == ["changes"]
    item = strict["properties"]["changes"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["original", "natural", "why_es", "kind"]
    assert "additionalProperties" not in NATURAL_SCHEMA  # deep copy


def test_model_spec_routing(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert is_cloud("openai:gpt-5.4-mini") and not is_cloud("qwen3:14b")
    assert isinstance(make_client("qwen3:14b"), Tutor)
    client = make_client("openai:gpt-5.4-mini")
    assert isinstance(client, OpenAIClient) and client.model == "gpt-5.4-mini"


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(Exception, match="api_key"):
        make_client("openai:gpt-5.4-mini")


def test_structured_call(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = OpenAIClient("gpt-5.4-mini")
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(output_text=json.dumps({"changes": []}))

    monkeypatch.setattr(client.client.responses, "create", create)
    assert client.structured("system prompt", "paragraph", NATURAL_SCHEMA) == {"changes": []}
    assert sent["model"] == "gpt-5.4-mini" and sent["instructions"] == "system prompt"
    assert sent["input"] == "paragraph" and sent["store"] is False
    fmt = sent["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert fmt["schema"]["properties"]["changes"]["items"]["additionalProperties"] is False
