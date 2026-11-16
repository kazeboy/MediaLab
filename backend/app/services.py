"""Service container shared by the API routes."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from fastapi import Request

from .batches import BatchManager
from .bulk import BulkAnalysisManager
from .config import Settings
from .jobs import JobManager
from .media import MediaProcessor
from .providers.base import VideoProvider
from .storage import AnalysisStore, DeliveryStore
from .tiktok_account import TikTokAccountStore
from .user_settings import SettingsStore


@dataclass
class Services:
    settings: Settings
    settings_store: SettingsStore
    provider: VideoProvider
    processor: MediaProcessor
    analyses: AnalysisStore
    deliveries: DeliveryStore
    jobs: JobManager
    analysis_executor: ThreadPoolExecutor
    tiktok_account: TikTokAccountStore
    batches: BatchManager
    bulk: BulkAnalysisManager
    analysis_slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))

    @classmethod
    def build(
        cls,
        settings: Settings,
        settings_store: SettingsStore,
        provider: VideoProvider,
        processor: MediaProcessor | None = None,
        tiktok_account: TikTokAccountStore | None = None,
    ) -> "Services":
        processor = processor or MediaProcessor(
            settings.ffmpeg_path, settings.ffprobe_path, settings.ffmpeg_timeout_seconds
        )
        deliveries = DeliveryStore(settings.temp_dir, settings.delivery_retention_seconds, settings.job_ttl_seconds)
        jobs = JobManager(settings, provider, processor, deliveries)
        # Batches use the Short Drama provider directly (series lookup); None if the router has none.
        shortdrama = getattr(provider, "providers", {}).get("tiktok_shortdrama")
        if shortdrama is not None and not hasattr(shortdrama, "series"):
            shortdrama = None
        analyses = AnalysisStore(settings.analysis_ttl_seconds)
        return cls(
            settings=settings,
            settings_store=settings_store,
            provider=provider,
            processor=processor,
            analyses=analyses,
            deliveries=deliveries,
            jobs=jobs,
            analysis_executor=ThreadPoolExecutor(
                max_workers=settings.max_concurrent_analyses, thread_name_prefix="medialab-analyse"
            ),
            analysis_slots=asyncio.Semaphore(settings.max_concurrent_analyses),
            tiktok_account=tiktok_account or TikTokAccountStore(settings.config_dir),
            batches=BatchManager(settings, settings_store, shortdrama, jobs, deliveries, analyses=analyses,
                                 router=provider),
            bulk=BulkAnalysisManager(settings, settings_store, provider, analyses),
        )

    def shutdown(self) -> None:
        self.bulk.shutdown()
        self.batches.shutdown()
        self.jobs.shutdown()
        self.analysis_executor.shutdown(wait=False, cancel_futures=True)


def get_services(request: Request) -> Services:
    return request.app.state.services
