"""The protocol schemas are valid and the examples match them."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

PROTOCOL = Path(__file__).resolve().parent.parent / "protocol"
NAMES = ["catalog", "show-request", "show-package"]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


SCHEMAS = {name: load(PROTOCOL / f"{name}.schema.json") for name in NAMES}
REGISTRY = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in SCHEMAS.values())


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(SCHEMAS[name], registry=REGISTRY)


def example(name: str) -> dict:
    return load(PROTOCOL / "examples" / f"{name}.json")


@pytest.mark.parametrize("name", NAMES)
def test_schema_is_valid(name):
    Draft202012Validator.check_schema(SCHEMAS[name])


@pytest.mark.parametrize("name", NAMES)
def test_example_matches_schema(name):
    validator(name).validate(example(name))


def test_catalog_rejects_file_paths():
    catalog = example("catalog")
    catalog["tracks"][0]["path"] = "/music/Butthole Surfers/Pepper.flac"
    assert not validator("catalog").is_valid(catalog)


def test_package_rejects_break_files_outside_breaks_folder():
    package = example("show-package")
    package["items"][0]["file"] = "../../etc/passwd.mp3"
    assert not validator("show-package").is_valid(package)


def test_example_cross_references():
    catalog_ids = [t["id"] for t in example("catalog")["tracks"]]
    assert len(catalog_ids) == len(set(catalog_ids))
    package = example("show-package")
    assert package["request_id"] == example("show-request")["request_id"]
    for item in package["items"]:
        if item["type"] == "track":
            assert item["track_id"] in catalog_ids
    breaks = [i for i in package["items"] if i["type"] == "break"]
    assert len({b["id"] for b in breaks}) == len(breaks)
    assert len({b["file"] for b in breaks}) == len(breaks)
