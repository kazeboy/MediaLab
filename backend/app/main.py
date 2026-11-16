"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .api.routes import router
from .config import LOOPBACK_HOSTS, Settings
from .errors import AppError, ErrorCode
from .media import MediaProcessor
from .providers.base import VideoProvider
from .services import Services
from .storage import cleanup_temp_root
from .tiktok_account import TikTokAccountStore
from .user_settings import SETTINGS_FILENAME, SettingsStore, UserSettings

log = logging.getLogger("medialab")

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _error(code: ErrorCode | str, message: str, status: int) -> JSONResponse:
    value = code.value if isinstance(code, ErrorCode) else code
    return JSONResponse({"error": {"code": value, "message": message, "retryable": False}}, status_code=status)


def _cause_chain(exc: BaseException) -> str:
    parts, seen = [], set()
    cur: BaseException | None = exc.__cause__ or exc.__context__
    while cur is not None and id(cur) not in seen and len(parts) < 4:
        seen.add(id(cur))
        parts.append(f"{type(cur).__name__}: {str(cur)[:300]}")
        cur = cur.__cause__ or cur.__context__
    return " <- ".join(parts) or "-"


def run_cleanup(services: Services) -> dict[str, int]:
    s = services.settings
    return {
        "temp_dirs": cleanup_temp_root(s.temp_dir, s.temp_max_age_seconds,
                                       services.jobs.active_dir_names() | services.batches.active_dir_names()),
        "deliveries": services.deliveries.prune(),
        "analyses": services.analyses.prune(),
        "jobs": services.jobs.prune(),
        "batches": services.batches.prune(),
        "bulk": services.bulk.prune(),
    }


def build_settings_store(settings: Settings) -> SettingsStore:
    """GUI settings file; the environment only provides first-run values."""
    initial = UserSettings(
        fxtwitter_fallback=settings.fxtwitter_fallback,
        max_file_size_mb=min(max(settings.max_file_size_mb, 256), 65536),
        batch_output_max_mb=min(max(settings.batch_output_max_mb, 256), 262144),
    )
    store = SettingsStore(settings.config_dir / SETTINGS_FILENAME, initial)
    if store.persisted:
        current = store.get()
        for var, value in (("MEDIALAB_FXTWITTER_FALLBACK", current.fxtwitter_fallback),
                           ("MEDIALAB_MAX_FILE_SIZE_MB", current.max_file_size_mb)):
            if var in os.environ:
                log.info("%s from the environment is ignored: the saved GUI setting (%s) takes precedence.", var, value)
    return store


def build_default_provider(settings: Settings, store: SettingsStore, account: TikTokAccountStore) -> VideoProvider:
    from .providers.chain import ProviderChain
    from .providers.fxtwitter_provider import FxTwitterProvider
    from .providers.router import PlatformRouter
    from .providers.ytdlp_provider import YtDlpProvider
    from .providers.tiktok_shortdrama import TikTokShortDramaProvider
    from .validation import PLATFORM_SHORTDRAMA, PLATFORM_TIKTOK, PLATFORM_X

    x_chain = ProviderChain(
        YtDlpProvider(settings, PLATFORM_X),
        FxTwitterProvider(settings),
        enabled=lambda: store.get().fxtwitter_fallback,  # read live: no restart needed
    )
    # TikTok uses yt-dlp only; the FxTwitter fallback is never involved. Only the Short Drama
    # provider can use the (optional, user-linked) TikTok account; the TikTok Videos tab stays anonymous.
    shortdrama = TikTokShortDramaProvider(settings, account)
    tiktok = YtDlpProvider(settings, PLATFORM_TIKTOK)
    tiktok.drama_probe = shortdrama.is_drama_episode
    return PlatformRouter({
        PLATFORM_X: x_chain,
        PLATFORM_TIKTOK: tiktok,
        PLATFORM_SHORTDRAMA: shortdrama,
    })


def create_app(
    settings: Settings | None = None,
    provider: VideoProvider | None = None,
    processor: MediaProcessor | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if os.environ.get("MEDIALAB_DOWNLOAD_DIR"):
        log.warning("MEDIALAB_DOWNLOAD_DIR is no longer used: videos are saved by your browser (v1.2).")
    settings_store = build_settings_store(settings)
    tiktok_account = TikTokAccountStore(settings.config_dir)
    if provider is None:
        provider = build_default_provider(settings, settings_store, tiktok_account)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services: Services = app.state.services
        try:
            settings.prepare_directories()
        except ValueError as exc:
            log.error("%s", exc)
            raise
        # Job directories and undelivered files from a previous run are never in use: remove them all.
        cleanup_temp_root(settings.temp_dir, 0)
        services.deliveries.reset()
        if not services.processor.available():
            log.warning("FFmpeg/FFprobe not found - downloads will fail until they are installed.")

        async def periodic_cleanup() -> None:
            while True:
                await asyncio.sleep(settings.cleanup_interval_seconds)
                try:
                    removed = await asyncio.to_thread(run_cleanup, services)
                    if any(removed.values()):
                        log.info("Cleanup: %s", removed)
                except Exception:  # noqa: BLE001
                    log.exception("Cleanup failed")

        task = asyncio.create_task(periodic_cleanup())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            services.shutdown()

    app = FastAPI(
        title="MediaLab",
        version=__version__,
        description="Local MP4 downloader for X posts, TikTok videos and TikTok Short Drama episodes.",
        lifespan=lifespan,
    )
    app.state.services = Services.build(settings, settings_store, provider, processor, tiktok_account)

    # DNS-rebinding protection: only answer requests addressed to this machine.
    allowed_hosts = sorted(LOOPBACK_HOSTS | {"[::1]"} | ({settings.host} if settings.allow_non_local else set()))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def same_origin_guard(request: Request, call_next):
        """Reject requests sent by other websites (CSRF and cross-site side effects).

        Any method: a browser-declared cross-site request (``Sec-Fetch-Site: cross-site``) or a
        foreign ``Origin`` is refused, so another site can't, for example, make MediaLab call
        TikTok with the linked session through a GET. State-changing methods also refuse
        ``Origin: null``. Clients that send neither header (curl, scripts) are unaffected.
        """
        origin = request.headers.get("origin")
        cross_site = request.headers.get("sec-fetch-site") == "cross-site"
        foreign = False
        if origin and origin != "null":
            host = (urlsplit(origin).hostname or "").lower()
            foreign = host not in LOOPBACK_HOSTS and not (settings.allow_non_local and host == settings.host)
        if request.url.path.startswith("/api/") and (
            cross_site or foreign or (request.method in _UNSAFE_METHODS and origin == "null")
        ):
            return _error(ErrorCode.FORBIDDEN, "Cross-origin requests are not allowed.", 403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        # Diagnostics stay server-side: code, route and the underlying cause chain.
        level = logging.WARNING if exc.status_code >= 500 else logging.INFO
        log.log(level, "%s %s -> %s (%s): %s | cause: %s", request.method, request.url.path,
                exc.code.value, exc.status_code, exc.message, _cause_chain(exc))
        return JSONResponse({"error": exc.body()}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        message = f"Invalid request: {field + ': ' if field else ''}{first.get('msg', 'invalid input')}"
        return _error(ErrorCode.VALIDATION_ERROR, message, 422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error(code, str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error", exc_info=exc)
        return _error(ErrorCode.INTERNAL_ERROR, "Something went wrong inside MediaLab.", 500)

    app.include_router(router)

    if settings.serve_frontend and (settings.frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")

    return app
