"""All current version declarations agree (backend package, API, frontend package and lockfile)."""

import json
import tomllib
from pathlib import Path

from app import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_versions_are_aligned(client):
    pyproject = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text())["project"]["version"]
    package = json.loads((ROOT / "frontend" / "package.json").read_text())["version"]
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text())
    api = client.get("/openapi.json").json()["info"]["version"]
    assert {__version__, pyproject, package, lock["version"], lock["packages"][""]["version"], api} == {"1.9.0"}


def test_openapi_schema_builds_and_lists_every_route(client):
    """/docs depends on /openapi.json; the streaming file route once broke schema generation."""
    res = client.get("/openapi.json")
    assert res.status_code == 200
    paths = res.json()["paths"]
    assert "/api/files/{file_id}" in paths and "/api/jobs/{job_id}/cancel" in paths
