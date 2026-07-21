import json

import generate_playbooks as gp
from tests.test_validate import VALID


def test_extract_preview_shape():
    preview = gp.extract_preview(VALID)
    assert preview == {
        "slug": "acme__widget",
        "summary": VALID["summary"],
        "who_its_for": VALID["who_its_for"],
        "first_business_model": VALID["business_models"][0],
    }


def test_update_previews_creates_and_merges(tmp_path):
    path = str(tmp_path / "data" / "previews.json")
    gp.update_previews([{"slug": "b__two", "summary": "s", "who_its_for": "w",
                         "first_business_model": {}}], path=path)
    gp.update_previews([{"slug": "a__one", "summary": "s", "who_its_for": "w",
                         "first_business_model": {}},
                        {"slug": "b__two", "summary": "UPDATED", "who_its_for": "w",
                         "first_business_model": {}}], path=path)
    data = json.loads(open(path).read())
    assert [p["slug"] for p in data] == ["a__one", "b__two"]
    assert data[1]["summary"] == "UPDATED"
