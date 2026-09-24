from bonsai_agent.llm import BonsaiLLM


class Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


def test_explicit_model_skips_discovery(monkeypatch):
    seen = []
    def no_get(*args, **kwargs): raise AssertionError("explicit model must not query /v1/models")
    def post(url, json, timeout):
        seen.append(json["model"])
        return Response({"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr("bonsai_agent.llm.requests.get", no_get)
    monkeypatch.setattr("bonsai_agent.llm.requests.post", post)
    assert BonsaiLLM(model="chosen-model").chat([{"role": "user", "content": "hi"}]) == "ok"
    assert seen == ["chosen-model"]


def test_empty_server_model_list_fails_clearly(monkeypatch):
    monkeypatch.setattr("bonsai_agent.llm.requests.get", lambda *args, **kwargs: Response({"data": []}))
    monkeypatch.setattr("bonsai_agent.llm.requests.post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("POST before model discovery")))
    try:
        BonsaiLLM(model="auto").chat([{"role": "user", "content": "hi"}])
    except (ValueError, RuntimeError) as exc:
        assert "model" in str(exc).lower()
    else:
        raise AssertionError("empty model list was accepted")


def test_tool_turn_discovers_model(monkeypatch):
    calls = []
    monkeypatch.setattr("bonsai_agent.llm.requests.get", lambda *args, **kwargs: Response({"data": [{"id": "tool-model"}]}))
    def post(url, json, timeout):
        calls.append(json)
        return Response({"choices": [{"message": {"content": "done"}}]})
    monkeypatch.setattr("bonsai_agent.llm.requests.post", post)
    BonsaiLLM(model="auto").tool_turn([{"role": "user", "content": "hi"}])
    assert calls[0]["model"] == "tool-model"
