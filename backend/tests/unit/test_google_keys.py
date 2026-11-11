from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from src import ai, google_keys


class GoogleModel:  # same class name the helper looks for
    system = "google"
    model_name = "gemini-test"
    settings = None


class FakeAgent:
    def __init__(self, failures):
        self.model = GoogleModel()
        self.failures = failures
        self.calls = []

    async def run(self, prompt, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            raise ModelHTTPError(429, "gemini-test", {})
        return "done"


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(google_keys, "get_config", lambda: SimpleNamespace(google_api_key="k1"))
    monkeypatch.setattr(google_keys, "_current", 0)


@pytest.mark.asyncio
async def test_no_spare_keys_changes_nothing(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEYS", raising=False)
    agent = FakeAgent(failures=1)
    with pytest.raises(ModelHTTPError):
        await ai._run_with_key_rotation(agent, "p")
    assert agent.calls == [{}]


@pytest.mark.asyncio
async def test_quota_error_moves_to_next_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEYS", "k2, k3")
    agent = FakeAgent(failures=1)
    assert await ai._run_with_key_rotation(agent, "p") == "done"
    assert agent.calls[0] == {} and "model" in agent.calls[1]
    assert google_keys._current == 1


@pytest.mark.asyncio
async def test_gives_up_after_every_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEYS", "k2")
    agent = FakeAgent(failures=5)
    with pytest.raises(ModelHTTPError):
        await ai._run_with_key_rotation(agent, "p")
    assert len(agent.calls) == 2
