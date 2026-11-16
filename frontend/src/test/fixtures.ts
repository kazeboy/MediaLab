/* Deterministic API responses shaped like the backend's schemas (see docs/API.md). */
import type { AnalyseResponse, BatchResponse, BulkAnalysis, BulkItem, JobResponse, SeriesInfo } from "../lib/types";

export function job(overrides: Partial<JobResponse> = {}): JobResponse {
  return {
    job_id: "a".repeat(32),
    state: "downloading",
    video_index: 1,
    option_id: "best",
    option_label: "Best Available (720p)",
    created_at: "2026-11-12T10:00:00Z",
    updated_at: "2026-11-12T10:00:01Z",
    progress: { stage: "Downloading video", downloaded_bytes: 500, total_bytes: 1000, total_is_estimate: false, percent: 50, speed_bytes_per_second: null, eta_seconds: null },
    file: null,
    error: null,
    ...overrides,
  } as JobResponse;
}

export function completedJob(delivery: "ready" | "delivered" = "ready"): JobResponse {
  return job({
    state: "completed",
    progress: { stage: "Ready to save", downloaded_bytes: 1000, total_bytes: 1000, total_is_estimate: false, percent: 100, speed_bytes_per_second: null, eta_seconds: null },
    file: {
      file_id: "f".repeat(32), filename: "Show - E02.mp4", size_bytes: 1000, width: 720, height: 1280, fps: 24,
      video_codec: "hevc", audio_codec: "aac", duration_seconds: 115, audio_converted: true, source_audio_codec: "mp3",
      audio_silent_source: false, download_url: `/api/files/${"f".repeat(32)}`, delivery_state: delivery, available_until: null,
    },
  } as Partial<JobResponse>);
}

export const SERIES: SeriesInfo = {
  series_id: "7100000000000000101",
  title: "Harbor & Crown Example 2",
  description: null,
  episode_count: 6,
  cover_url: null,
  publisher_handle: "publisher",
  publisher_name: "Publisher",
  account_used: true,
  episodes: [1, 2, 3, 4, 5, 6].map((n) => ({
    number: n, item_id: String(7700000000000000000 + n), title: `Show EP${n}`, duration_seconds: 100,
    thumbnail_url: null, available: n !== 4, availability: n !== 4 ? "available" : "locked", publisher_handle: "publisher",
  })) as SeriesInfo["episodes"],
};

export function batch(overrides: Partial<BatchResponse> = {}): BatchResponse {
  return {
    batch_id: "b".repeat(32), series_id: SERIES.series_id, series_title: SERIES.title, quality: "best", strict: false,
    concurrency: 1, output: "zip", allow_partial: false, state: "running", stage: null, plan_note: null, package_percent: 0,
    counts: { pending: 1, resolving: 0, downloading: 1, processing: 0, ready: 0, saving: 0, saved: 0, downloaded: 0, failed: 0, skipped: 0, cancelled: 0 },
    percent: 20, estimated_duration_seconds: 200, estimated_size_bytes: null,
    episodes: [], result: null, error: null, ...overrides,
  } as BatchResponse;
}

export function analysis(): AnalyseResponse {
  return {
    analysis_id: "c".repeat(32), platform: "tiktok_shortdrama", provider: "tiktok-shortdrama",
    post: { url: "https://www.tiktok.com/@publisher/video/7700000000000000002", post_id: "7700000000000000002",
      author_name: "Publisher", author_handle: "publisher", text: "Show EP2", possibly_sensitive: null,
      drama: { series_id: SERIES.series_id, series_title: SERIES.title, episode: 2, episode_count: 6, account_used: true } },
    videos: [{ index: 1, video_id: "x", title: "Show EP2", duration_seconds: 100, thumbnail_url: null, formats: [],
      options: [{ option_id: "best", label: "Best Available (720p)", is_best: true, width: 720, height: 1280, fps: 24,
        vcodec: "h265", acodec: "mp3", has_audio: true, video_format_id: "v", audio_format_id: "audio", requires_merge: true,
        tbr: null, filesize: 9000000, filesize_approx: null, downloadable: true, too_large: false, audio_converted: true,
        fallback_audio_format_id: null, note: null }] }],
    selected_video_index: 1,
    expires_at: "2026-11-12T11:00:00Z",
  } as unknown as AnalyseResponse;
}

/* ---------------------------------------------------------------- bulk (v1.9) */
export function bulkItem(index: number, overrides: Partial<BulkItem> = {}): BulkItem {
  return {
    index, input: `https://x.com/u/status/${100 + index}`, state: "ready", canonical_url: `https://x.com/u/status/${100 + index}`,
    duplicate_of: null, analysis_id: String(index).repeat(32).slice(0, 32), title: `Clip ${index}`, author: "u",
    duration_seconds: 15, thumbnail_url: null, video_count: 1, video_index: 1, qualities: ["720p", "360p"],
    estimates: {
      best: { label: "Best Available (720p)", size_bytes: 1_000_000, size_is_estimate: false, note: null },
      "1080p": { label: "720p", size_bytes: 1_000_000, size_is_estimate: false, note: "1080p isn't available; used 720p, the next lower resolution." },
      "720p": { label: "720p", size_bytes: 1_000_000, size_is_estimate: false, note: null },
      "480p": { label: "360p", size_bytes: 400_000, size_is_estimate: false, note: "480p isn't available; used 360p, the next lower resolution." },
    },
    error: null, ...overrides,
  } as BulkItem;
}

export function bulkAnalysis(items: BulkItem[], state: BulkAnalysis["state"] = "done"): BulkAnalysis {
  const states = ["waiting", "analysing", "ready", "failed", "invalid", "duplicate", "cancelled"] as const;
  return {
    bulk_id: "d".repeat(32), platform: "x", state, limit: 50,
    counts: Object.fromEntries(states.map((s) => [s, items.filter((i) => i.state === s).length])) as BulkAnalysis["counts"],
    items,
  };
}

/** A running two-video X link batch (ZIP). */
export function urlBatch(overrides: Partial<BatchResponse> = {}): BatchResponse {
  return batch({
    batch_id: "e".repeat(32), source: "urls", platform: "x", stopped: false, series_id: "", series_title: "X bulk download",
    concurrency: 2, output: "zip",
    counts: { pending: 1, resolving: 0, downloading: 1, processing: 0, ready: 0, saving: 0, saved: 0, downloaded: 0, failed: 0, skipped: 0, cancelled: 0 },
    episodes: [1, 2].map((n) => ({
      number: n, item_id: String(100 + n), title: `Clip ${n}`, state: n === 1 ? "downloading" : "pending", stage: null,
      percent: n === 1 ? 40 : null, downloaded_bytes: 0, total_bytes: null, option_label: null, note: null, attempts: n === 1 ? 1 : 0,
      file_id: null, filename: null, size_bytes: null, download_url: null, error: null, author: "u",
    })) as BatchResponse["episodes"],
    ...overrides,
  });
}
