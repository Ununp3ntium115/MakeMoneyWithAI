import copy

import pytest

import generate_playbooks as gp
from tests.conftest import FakeResponse, openai_chat_payload
from tests.test_validate import VALID

REPO = {
    "owner": "acme",
    "name": "widget",
    "stars": "12345",
    "url": "https://github.com/acme/widget",
    "business_model": "Sell **widgets** as a service.",
}


def llm_body():
    body = copy.deepcopy(VALID)
    for k in ("slug", "generated_at", "model"):
        body.pop(k, None)  # the LLM does not produce these; we stamp them
    return body


def test_slug_for():
    assert gp.slug_for("acme", "widget") == "acme__widget"


def test_build_prompt_mentions_repo():
    prompt = gp.build_prompt(REPO)
    assert "acme/widget" in prompt and "12345" in prompt


def test_generate_playbook_success(monkeypatch):
    monkeypatch.setattr(
        gp.requests, "post",
        lambda *a, **kw: FakeResponse(200, openai_chat_payload(llm_body())),
    )
    pb = gp.generate_playbook(REPO)
    assert pb["slug"] == "acme__widget"
    assert pb["model"] == gp.OPENAI_MODEL
    assert gp.validate_playbook(pb) == []


def test_generate_playbook_retries_once_then_succeeds(monkeypatch):
    calls = []

    def fake_post(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(200, openai_chat_payload({"garbage": True}))
        return FakeResponse(200, openai_chat_payload(llm_body()))

    monkeypatch.setattr(gp.requests, "post", fake_post)
    pb = gp.generate_playbook(REPO)
    assert len(calls) == 2 and pb["slug"] == "acme__widget"


def test_generate_playbook_fails_after_two_attempts(monkeypatch):
    monkeypatch.setattr(
        gp.requests, "post",
        lambda *a, **kw: FakeResponse(200, openai_chat_payload({"garbage": True})),
    )
    with pytest.raises(gp.PlaybookError):
        gp.generate_playbook(REPO)


def test_generate_playbook_http_error(monkeypatch):
    monkeypatch.setattr(
        gp.requests, "post",
        lambda *a, **kw: FakeResponse(500, {"error": "boom"}),
    )
    with pytest.raises(gp.PlaybookError):
        gp.generate_playbook(REPO)
