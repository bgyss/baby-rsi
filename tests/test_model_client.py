"""Offline model-client surface: code extraction + the scripted test client (Goal 02)."""

import pytest

from siro.model_client import (
    LocalOpenAIClient,
    ModelClient,
    NullModelClient,
    ScriptedModelClient,
    extract_code,
)


def test_extract_code_from_fenced_block():
    text = "Here is my answer:\n```python\ndef f():\n    return 1\n```\nDone."
    assert extract_code(text) == "def f():\n    return 1\n"


def test_extract_code_without_fence():
    assert extract_code("def f():\n    return 1") == "def f():\n    return 1\n"


def test_scripted_client_replays_in_order():
    client = ScriptedModelClient(["a", "b"])
    assert client.generate("p") == "a"
    assert client.generate("p") == "b"
    assert client.generate("p") == "b"  # last response repeats


def test_scripted_client_requires_responses():
    with pytest.raises(ValueError):
        ScriptedModelClient([])


def test_clients_satisfy_protocol():
    assert isinstance(ScriptedModelClient(["x"]), ModelClient)
    assert isinstance(LocalOpenAIClient(), ModelClient)
    assert isinstance(NullModelClient(), ModelClient)


def test_null_client_refuses():
    with pytest.raises(NotImplementedError):
        NullModelClient().generate("p")
