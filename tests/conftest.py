"""No test reaches the internet. A test that needs a source patches it; one that forgets fails
loudly here instead of passing on whatever the network said that day."""

import pytest

from rankloom import ai, github, sources


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise sources.SourceFailed("network disabled in tests")

    def refuse_ai(*args, **kwargs):
        raise ai.AIUnavailable("network disabled in tests")

    def refuse_github(*args, **kwargs):
        raise github.GitHubError("network disabled in tests")

    monkeypatch.setattr(sources, "get_json", refuse)
    monkeypatch.setattr(ai, "post", refuse_ai)
    monkeypatch.setattr(github, "request", refuse_github)
    monkeypatch.delenv("RANKLOOM_AI", raising=False)
