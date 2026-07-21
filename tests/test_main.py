import csv
import json

import pytest

import generate_playbooks as gp
from tests.test_generate import llm_body

ROWS = [
    {"id": "1", "owner": "acme", "name": "widget", "stars": "100",
     "url": "https://github.com/acme/widget", "business_model": "b"},
    {"id": "2", "owner": "beta", "name": "gadget", "stars": "200",
     "url": "https://github.com/beta/gadget", "business_model": "b"},
]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    csv_path = tmp_path / "repos.csv"
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ROWS[0]))
        writer.writeheader()
        writer.writerows(ROWS)
    monkeypatch.setattr(gp, "CSV_FILE", str(csv_path))
    monkeypatch.setattr(gp, "PLAYBOOKS_DIR", str(tmp_path / "playbooks"))
    monkeypatch.setattr(gp, "PREVIEWS_FILE", str(tmp_path / "previews.json"))
    return tmp_path


def _fake_gen(repo):
    return dict(llm_body(), slug=gp.slug_for(repo["owner"], repo["name"]),
                generated_at="t", model="m")


def test_main_generates_only_missing(sandbox, monkeypatch):
    monkeypatch.setattr(gp, "kv_list_keys", lambda: {"acme__widget"})
    puts = []
    monkeypatch.setattr(gp, "kv_bulk_put", lambda items: puts.extend(items))
    monkeypatch.setattr(gp, "generate_playbook", _fake_gen)
    assert gp.main([]) == 0
    assert [p["key"] for p in puts] == ["beta__gadget"]
    previews = json.load(open(sandbox / "previews.json"))
    assert [p["slug"] for p in previews] == ["beta__gadget"]
    assert (sandbox / "playbooks" / "beta__gadget.json").exists()


def test_main_aborts_when_kv_listing_fails(sandbox, monkeypatch):
    def boom():
        raise gp.PlaybookError("kv down")
    monkeypatch.setattr(gp, "kv_list_keys", boom)
    assert gp.main([]) == 1


def test_main_force_regenerates(sandbox, monkeypatch):
    monkeypatch.setattr(gp, "kv_list_keys", lambda: {"acme__widget", "beta__gadget"})
    puts = []
    monkeypatch.setattr(gp, "kv_bulk_put", lambda items: puts.extend(items))
    monkeypatch.setattr(gp, "generate_playbook", _fake_gen)
    assert gp.main(["--force", "acme/widget"]) == 0
    assert [p["key"] for p in puts] == ["acme__widget"]


def test_main_skips_failed_repo_and_continues(sandbox, monkeypatch):
    monkeypatch.setattr(gp, "kv_list_keys", lambda: set())
    puts = []
    monkeypatch.setattr(gp, "kv_bulk_put", lambda items: puts.extend(items))

    def flaky(repo):
        if repo["owner"] == "acme":
            raise gp.PlaybookError("nope")
        return _fake_gen(repo)

    monkeypatch.setattr(gp, "generate_playbook", flaky)
    assert gp.main([]) == 0
    assert [p["key"] for p in puts] == ["beta__gadget"]


def test_main_respects_max(sandbox, monkeypatch):
    monkeypatch.setattr(gp, "kv_list_keys", lambda: set())
    puts = []
    monkeypatch.setattr(gp, "kv_bulk_put", lambda items: puts.extend(items))
    monkeypatch.setattr(gp, "generate_playbook", _fake_gen)
    assert gp.main(["--max", "1"]) == 0
    assert len(puts) == 1
