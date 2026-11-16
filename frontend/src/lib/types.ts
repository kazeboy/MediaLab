// Mirrors backend/app/schemas.py and backend/app/models.py.

export interface MediaFormat {
  format_id: string;
  ext: string | null;
  protocol: string | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  vcodec: string | null;
  acodec: string | null;
  has_video: boolean | null;
  has_audio: boolean | null;
  tbr: number | null;
  filesize: number | null;
  filesize_approx: number | null;
  mp4_compatible: boolean | null;
}

export interface ResolutionOption {
  option_id: string;
  label: string;
  is_best: boolean;
  width: number | null;
  height: number | null;
  fps: number | null;
  vcodec: string | null;
  acodec: string | null;
  has_audio: boolean | null;
  video_format_id: string;
  audio_format_id: string | null;
  requires_merge: boolean;
  tbr: number | null;
  filesize: number | null;
  filesize_approx: number | null;
  downloadable: boolean;
  too_large: boolean;
  /** Audio is converted to AAC (e.g. from MP3) so Apple players can play it; video is never re-encoded. */
  audio_converted: boolean;
  /** Separate audio the backend adds if this stream turns out to have no audio track. */
  fallback_audio_format_id: string | null;
  note: string | null;
}

export interface VideoResult {
  index: number;
  video_id: string | null;
  title: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  formats: MediaFormat[];
  options: ResolutionOption[];
}

export type Platform = "x" | "tiktok" | "tiktok_shortdrama";

export interface DramaInfo {
  series_id: string;
  series_title: string | null;
  episode: number | null;
  episode_count: number | null;
  account_used: boolean;
}

/** Status of the optional TikTok sign-in (Short Drama only). Cookie values are never sent to the UI. */
export interface TikTokAccount {
  linked: boolean;
  cookie_count: number;
  session_expires_at: string | null;
  expired: boolean;
  saved_at: string | null;
}

export interface AnalyseResponse {
  analysis_id: string;
  platform: Platform;
  provider: string;
  post: {
    url: string;
    post_id: string;
    author_name: string | null;
    author_handle: string | null;
    text: string | null;
    possibly_sensitive: boolean | null;
    drama: DramaInfo | null;
  };
  videos: VideoResult[];
  selected_video_index: number;
  expires_at: string;
}

export type JobState = "queued" | "downloading" | "processing" | "completed" | "failed" | "cancelled";

export interface JobResponse {
  job_id: string;
  state: JobState;
  video_index: number;
  option_id: string;
  option_label: string;
  created_at: string;
  updated_at: string;
  progress: {
    stage: string | null;
    downloaded_bytes: number;
    total_bytes: number | null;
    total_is_estimate: boolean;
    percent: number | null;
    speed_bytes_per_second: number | null;
    eta_seconds: number | null;
  };
  file: {
    file_id: string;
    filename: string;
    size_bytes: number;
    width: number | null;
    height: number | null;
    fps: number | null;
    video_codec: string | null;
    audio_codec: string | null;
    audio_converted: boolean;
    source_audio_codec: string | null;
    audio_silent_source: boolean;
    duration_seconds: number | null;
    download_url: string;
    delivery_state: DeliveryState;
    available_until: string | null;
  } | null;
  error: ApiErrorBody | null;
}


export type DeliveryState = "ready" | "delivering" | "delivered" | "expired";

export interface AppSettings {
  fxtwitter_fallback: boolean;
  fxtwitter_host: string;
  max_file_size_mb: number;
  file_size_limits: { min_mb: number; max_mb: number; presets_mb: number[] };
  batch_output_max_mb: number;
  batch_output_limits: { min_mb: number; max_mb: number; presets_mb: number[] };
  temp_storage: { auto_cleanup: boolean; retention_minutes: number; usage_bytes: number };
  saved: boolean;
}

export type SettingsPatch = Partial<Pick<AppSettings, "fxtwitter_fallback" | "max_file_size_mb" | "batch_output_max_mb">>;

export interface ApiErrorBody {
  code: string;
  message: string;
  action?: string | null;
  retryable?: boolean;
  details?: Record<string, unknown> | null;
}

export interface SeriesEpisode {
  number: number;
  item_id: string;
  title: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  available: boolean;
  availability: "available" | "login_required" | "locked";
  publisher_handle: string | null;
}

export interface SeriesInfo {
  series_id: string;
  title: string | null;
  description: string | null;
  episode_count: number | null;
  cover_url: string | null;
  publisher_handle: string | null;
  publisher_name: string | null;
  account_used: boolean;
  episodes: SeriesEpisode[];
}

export type EpisodeState =
  | "pending"
  | "resolving"
  | "downloading"
  | "processing"
  | "ready"
  | "saving"
  | "saved"
  | "downloaded"
  | "failed"
  | "skipped"
  | "cancelled";

export interface BatchEpisode {
  number: number;
  item_id: string;
  title: string | null;
  state: EpisodeState;
  stage: string | null;
  percent: number | null;
  downloaded_bytes: number;
  total_bytes: number | null;
  option_label: string | null;
  note: string | null;
  attempts: number;
  file_id: string | null;
  filename: string | null;
  size_bytes: number | null;
  download_url: string | null;
  error: ApiErrorBody | null;
  /** Link batches (v1.9) */
  author?: string | null;
  duration_seconds?: number | null;
  thumbnail_url?: string | null;
}

export type OutputMode = "files" | "zip" | "merge";

export type BatchState =
  | "planning"
  | "running"
  | "paused"
  | "needs_decision"
  | "packaging"
  | "ready"
  | "saving"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";

export interface BatchResult {
  file_id: string;
  filename: string;
  size_bytes: number;
  kind: "zip" | "mp4";
  method: "stream_copy" | "re_encoded" | "stored" | null;
  reason: string | null;
  duration_seconds: number | null;
  included: number[];
  omitted: number[];
  width: number | null;
  height: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  download_url: string | null;
  delivery_state: string | null;
}

export type BatchSource = "shortdrama" | "urls";

export interface BatchResponse {
  batch_id: string;
  source?: BatchSource;
  platform?: Platform;
  /** Link batches: cancelled while finished videos were kept. */
  stopped?: boolean;
  series_id: string;
  series_title: string | null;
  quality: string;
  strict: boolean;
  concurrency: number;
  output: OutputMode;
  allow_partial: boolean;
  state: BatchState;
  stage: string | null;
  plan_note: string | null;
  package_percent: number;
  counts: Record<EpisodeState, number>;
  percent: number;
  estimated_duration_seconds: number | null;
  estimated_size_bytes: number | null;
  episodes: BatchEpisode[];
  result: BatchResult | null;
  error: ApiErrorBody | null;
}

/* ---------------------------------------------------------------- bulk (v1.9) */
export type BulkItemState = "waiting" | "analysing" | "ready" | "failed" | "invalid" | "duplicate" | "cancelled";
export type QualityPreference = "best" | "1080p" | "720p" | "480p";

export interface BulkEstimate {
  label: string;
  size_bytes: number | null;
  size_is_estimate: boolean;
  note: string | null;
}

export interface BulkItem {
  index: number;
  input: string;
  state: BulkItemState;
  canonical_url: string | null;
  duplicate_of: number | null;
  analysis_id: string | null;
  title: string | null;
  author: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  video_count: number;
  video_index: number;
  qualities: string[];
  estimates: Partial<Record<QualityPreference, BulkEstimate>>;
  error: ApiErrorBody | null;
}

export interface BulkAnalysis {
  bulk_id: string;
  platform: Platform;
  state: "running" | "done" | "cancelled";
  limit: number;
  counts: Record<BulkItemState, number>;
  items: BulkItem[];
}

export interface UrlBatchRequest {
  platform: "x" | "tiktok";
  analysis_ids: string[];
  quality: QualityPreference;
  output: "files" | "zip";
  concurrency: number;
  allow_partial: boolean;
}

export interface BatchRequest {
  series_id: string;
  episodes: number[];
  quality: string;
  strict: boolean;
  concurrency: number;
  output: OutputMode;
  allow_partial: boolean;
}
