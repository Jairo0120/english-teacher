"""Optional cloud models, with the same `structured()` interface as the local Tutor.

A model spec is either an Ollama model ("qwen3:14b", local) or "openai:<model>" (OpenAI API, needs
OPENAI_API_KEY in the environment). Only the writing review uses this; everything else stays local.
"""

import copy
import json

from english_teacher.llm import Tutor

OPENAI_PREFIX = "openai:"


def is_cloud(spec: str) -> bool:
    return spec.startswith(OPENAI_PREFIX)


def make_client(spec: str):
    """Client for a model spec: OpenAIClient for "openai:<model>", a local Tutor otherwise."""
    if is_cloud(spec):
        return OpenAIClient(spec.removeprefix(OPENAI_PREFIX))
    return Tutor("", spec)


def strict_schema(schema: dict) -> dict:
    """OpenAI strict mode needs every object closed and every property required."""
    schema = copy.deepcopy(schema)

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


class OpenAIClient:
    def __init__(self, model: str):
        from openai import OpenAI  # only imported when a cloud model is used

        self.model = model
        self.client = OpenAI()  # reads OPENAI_API_KEY; raises OpenAIError if it's missing

    def structured(self, system: str, content: str, schema: dict) -> dict:
        response = self.client.responses.create(
            model=self.model,
            instructions=system,
            input=content,
            text={"format": {"type": "json_schema", "name": "result", "schema": strict_schema(schema), "strict": True}},
            store=False,  # don't keep the student's texts on OpenAI's side
        )
        return json.loads(response.output_text)
