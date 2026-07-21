import copy
from generate_playbooks import validate_playbook

VALID = {
    "slug": "acme__widget",
    "generated_at": "2026-07-21T00:00:00+00:00",
    "model": "gpt-4.1-mini",
    "summary": "A widget that does things profitably.",
    "who_its_for": "Developers who want widget income.",
    "business_models": [
        {
            "name": "Hosted SaaS",
            "description": "Run it for customers.",
            "difficulty": "medium",
            "startup_cost": "$20-100/mo",
            "revenue_potential": "side-income",
        }
    ],
    "getting_started_steps": ["Clone it", "Deploy it", "Sell it"],
    "cost_estimate": "About $25/mo to run.",
    "risks": ["Competition", "API pricing changes"],
}


def test_valid_playbook_passes():
    assert validate_playbook(VALID) == []


def test_missing_required_field():
    bad = copy.deepcopy(VALID)
    del bad["summary"]
    assert any("summary" in e for e in validate_playbook(bad))


def test_bad_difficulty():
    bad = copy.deepcopy(VALID)
    bad["business_models"][0]["difficulty"] = "impossible"
    assert any("difficulty" in e for e in validate_playbook(bad))


def test_steps_count_bounds():
    bad = copy.deepcopy(VALID)
    bad["getting_started_steps"] = ["only one"]
    assert any("getting_started_steps" in e for e in validate_playbook(bad))


def test_risks_count_bounds():
    bad = copy.deepcopy(VALID)
    bad["risks"] = ["r"] * 6
    assert any("risks" in e for e in validate_playbook(bad))


def test_business_models_bounds():
    bad = copy.deepcopy(VALID)
    bad["business_models"] = []
    assert any("business_models" in e for e in validate_playbook(bad))


def test_non_dict_input():
    assert validate_playbook("nope") != []
