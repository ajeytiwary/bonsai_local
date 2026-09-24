import sys
from bonsai_agent import cli
from bonsai_agent.llm import BonsaiLLM


def test_client_discovers_and_caches_alias(monkeypatch):
    seen = {"get": 0, "post": []}
    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return self.payload
    def get(url, timeout):
        seen["get"] += 1
        assert url.endswith("/v1/models")
        return Response({"data": [{"id": "bonsai-abliterated-mtp"}]})
    def post(url, json, timeout):
        seen["post"].append(json)
        return Response({"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr("bonsai_agent.llm.requests.get", get)
    monkeypatch.setattr("bonsai_agent.llm.requests.post", post)
    llm = BonsaiLLM(model="auto")
    for _ in range(2):
        assert llm.chat([{"role": "user", "content": "ping"}]) == "ok"
    assert seen["get"] == 1
    assert [p["model"] for p in seen["post"]] == ["bonsai-abliterated-mtp"] * 2


def test_cli_defaults_to_auto(monkeypatch, capsys):
    seen = {}
    class FakeLLM:
        def __init__(self, base_url, model): seen["model"] = model
    class FakeAgent:
        def __init__(self, root, llm, *args): pass
        def status(self, rid): return {}
    monkeypatch.setattr(cli, "BonsaiLLM", FakeLLM)
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    monkeypatch.setattr(sys, "argv", ["bonsai-agent", "--status", "1"])
    cli.main()
    assert seen["model"] == "auto"
