"""GUI settings: defaults, validation, persistence, precedence and live effect."""

import json
import os
import stat
import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.user_settings import SETTINGS_FILENAME, SettingsPatch, SettingsStore, UserSettings

from .conftest import FakeProcessor, FakeProvider, wait_for_job

URL = "https://x.com/medialab_test/status/1800000000000000001"


def make_client(settings, provider=None):
    app = create_app(settings, provider=provider or FakeProvider(), processor=FakeProcessor())
    return TestClient(app, base_url="http://127.0.0.1")


def test_defaults_for_fresh_install(settings):
    with make_client(settings) as c:
        body = c.get("/api/settings").json()
    assert body["fxtwitter_fallback"] is False
    assert body["max_file_size_mb"] == 8192
    assert body["saved"] is False
    assert body["file_size_limits"] == {"min_mb": 256, "max_mb": 65536, "presets_mb": [2048, 8192, 16384]}
    assert body["temp_storage"]["auto_cleanup"] is True
    assert body["temp_storage"]["retention_minutes"] == 30
    assert isinstance(body["temp_storage"]["usage_bytes"], int)
    assert str(settings.temp_dir) not in json.dumps(body) and str(settings.config_dir) not in json.dumps(body)


def test_update_and_read_back(settings):
    with make_client(settings) as c:
        res = c.patch("/api/settings", json={"max_file_size_mb": 16384})
        assert res.status_code == 200
        assert res.json()["max_file_size_mb"] == 16384 and res.json()["fxtwitter_fallback"] is False
        res = c.patch("/api/settings", json={"fxtwitter_fallback": True})
        assert res.json()["max_file_size_mb"] == 16384  # partial update keeps other values
        assert c.get("/api/settings").json()["fxtwitter_fallback"] is True


def test_persists_across_restarts(settings):
    with make_client(settings) as c:
        c.patch("/api/settings", json={"fxtwitter_fallback": True, "max_file_size_mb": 2048})
    path = settings.config_dir / SETTINGS_FILENAME
    assert json.loads(path.read_text()) == {"fxtwitter_fallback": True, "max_file_size_mb": 2048, "batch_output_max_mb": 32768}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    with make_client(settings) as c:  # a brand-new app instance
        body = c.get("/api/settings").json()
    assert body["fxtwitter_fallback"] is True and body["max_file_size_mb"] == 2048 and body["saved"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"max_file_size_mb": 100},          # below minimum
        {"max_file_size_mb": 70000},        # above maximum
        {"max_file_size_mb": "8192"},       # strings are not coerced
        {"max_file_size_mb": 8192.5},
        {"fxtwitter_fallback": "true"},
        {"fxtwitter_fallback": 1},
        {"temp_dir": "/etc"},               # arbitrary keys / paths are rejected
        {"MEDIALAB_HOST": "0.0.0.0"},
        {"media_host_suffixes": ["evil.example"]},
    ],
)
def test_invalid_values_rejected(settings, payload):
    with make_client(settings) as c:
        res = c.patch("/api/settings", json=payload)
        assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"
        assert c.get("/api/settings").json()["max_file_size_mb"] == 8192  # unchanged
    assert not (settings.config_dir / SETTINGS_FILENAME).exists()


def test_settings_api_is_local_only(settings):
    with make_client(settings) as c:
        res = c.patch("/api/settings", json={"fxtwitter_fallback": True}, headers={"Origin": "https://evil.example"})
        assert res.status_code == 403
    app = create_app(settings, provider=FakeProvider(), processor=FakeProcessor())
    with TestClient(app, base_url="http://attacker.example") as c:
        assert c.get("/api/settings").status_code == 400  # Host header check


def test_environment_seeds_first_run_only(settings):
    seeded = replace(settings, fxtwitter_fallback=True, max_file_size_mb=2048)
    with make_client(seeded) as c:
        body = c.get("/api/settings").json()
        assert body["fxtwitter_fallback"] is True and body["max_file_size_mb"] == 2048 and body["saved"] is False
        c.patch("/api/settings", json={"fxtwitter_fallback": False})
    with make_client(seeded) as c:  # env still says True, but the saved GUI value wins
        assert c.get("/api/settings").json()["fxtwitter_fallback"] is False


def test_corrupt_settings_file_falls_back_safely(settings):
    path = settings.config_dir / SETTINGS_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text('{"fxtwitter_fallback": "yes", "max_file_size_mb": 1}')
    with make_client(settings) as c:
        body = c.get("/api/settings").json()
    assert body["fxtwitter_fallback"] is False and body["max_file_size_mb"] == 8192
    assert (settings.config_dir / "settings.invalid.json").exists()


def test_store_is_thread_safe(tmp_path):
    store = SettingsStore(tmp_path / SETTINGS_FILENAME, UserSettings())
    sizes = [256 * k for k in range(1, 41)]
    threads = [threading.Thread(target=store.update, args=(SettingsPatch(max_file_size_mb=s),)) for s in sizes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    on_disk = json.loads((tmp_path / SETTINGS_FILENAME).read_text())
    assert on_disk["max_file_size_mb"] == store.get().max_file_size_mb in sizes
    assert not list(tmp_path.glob(".*.tmp"))


def test_size_limit_applies_to_new_jobs_not_running_ones(settings):
    provider = FakeProvider()
    provider.gate = threading.Event()
    with make_client(settings, provider) as c:
        analysis = c.post("/api/analyse", json={"url": URL}).json()
        running = c.post("/api/download", json={"analysis_id": analysis["analysis_id"], "option_id": "720p"}).json()
        # Lower the limit while the job is active.
        assert c.patch("/api/settings", json={"max_file_size_mb": 256}).status_code == 200
        jobs = c.app.state.services.jobs
        assert jobs._jobs[running["job_id"]].plan.max_file_size_bytes == 8192 * 1024 * 1024  # frozen
        provider.gate.set()
        assert wait_for_job(c, running["job_id"])["state"] == "completed"
        new = c.post("/api/download", json={"analysis_id": analysis["analysis_id"], "option_id": "720p"}).json()
        assert jobs._jobs[new["job_id"]].plan.max_file_size_bytes == 256 * 1024 * 1024
        wait_for_job(c, new["job_id"])


def test_size_limit_change_reevaluates_options(settings, monkeypatch):
    with make_client(settings) as c:
        c.patch("/api/settings", json={"max_file_size_mb": 256})
        a = c.post("/api/analyse", json={"url": URL}).json()
        services = c.app.state.services
        # Make the stored 1080p option exactly 300 MB: over 256, under 2048.
        stored = services.analyses.get(a["analysis_id"])
        stored.options[1] = [o.model_copy(update={"filesize": 300 * 1024 * 1024}) if o.option_id == "1080p" else o
                             for o in stored.options[1]]
        res = c.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": "1080p"})
        assert res.status_code == 413 and res.json()["error"]["code"] == "file_too_large"
        c.patch("/api/settings", json={"max_file_size_mb": 2048})
        res = c.post("/api/download", json={"analysis_id": a["analysis_id"], "option_id": "1080p"})
        assert res.status_code == 202
        wait_for_job(c, res.json()["job_id"])


def test_disabling_fallback_blocks_downloading_a_fallback_analysis(settings):
    from app.errors import AppError, ErrorCode
    from app.providers.chain import ProviderChain

    primary = FakeProvider(error=AppError(ErrorCode.NO_VIDEO, "none"))
    primary.name = "yt-dlp"
    second = FakeProvider()
    second.name = "fxtwitter"
    store_holder = {}
    app = create_app(replace(settings, fxtwitter_fallback=True),
                     provider=ProviderChain(primary, second, enabled=lambda: store_holder["s"].get().fxtwitter_fallback),
                     processor=FakeProcessor())
    store_holder["s"] = app.state.services.settings_store
    with TestClient(app, base_url="http://127.0.0.1") as c:
        a = c.post("/api/analyse", json={"url": URL}).json()
        assert a["provider"] == "fxtwitter"
        c.patch("/api/settings", json={"fxtwitter_fallback": False})
        res = c.post("/api/download", json={"analysis_id": a["analysis_id"]})
        assert res.status_code == 403
        res = c.post("/api/analyse", json={"url": URL})  # fallback no longer consulted
        assert res.status_code == 422 and res.json()["error"]["code"] == "no_video"
    assert len(second.calls) == 0
