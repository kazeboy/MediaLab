"""House style: MediaLab-authored text (error messages and actions shown in the UI, docstrings,
comments) uses no em dashes (U+2014). Data from X/TikTok is never part of the source tree, so it is
not affected; the frontend has the matching check (src/__tests__/copy-punctuation.test.ts)."""

from pathlib import Path

EM_DASH = "\u2014"
ROOT = Path(__file__).resolve().parents[1]


def test_backend_source_has_no_em_dashes():
    files = [*(ROOT / "app").rglob("*.py"), *(ROOT / "tests").rglob("*.py"), ROOT.parent / ".env.example"]
    assert len(files) > 20
    offenders = [
        f"{path.relative_to(ROOT.parent)}:{number}"
        for path in files
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if EM_DASH in line
    ]
    assert offenders == []
