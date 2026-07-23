__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json

import pytest

from ract.skill_marketplace import load_catalog


def test_load_catalog_round_trip(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"skills": [{"name": "demo"}]}), encoding="utf-8")
    catalog = load_catalog(str(path))
    assert catalog["skills"][0]["name"] == "demo"


def test_load_catalog_missing_file(tmp_path):
    with pytest.raises(ValueError):
        load_catalog(str(tmp_path / "missing.json"))
