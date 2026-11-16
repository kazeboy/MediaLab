import type {
  AnalyseResponse,
  ApiErrorBody,
  AppSettings,
  JobResponse,
  Platform,
  SettingsPatch,
  TikTokAccount,
  BatchRequest,
  BatchResponse,
  BulkAnalysis,
  SeriesInfo,
  UrlBatchRequest,
} from "./types";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly body: ApiErrorBody;

  constructor(body: ApiErrorBody, status: number) {
    super(body.message);
    this.code = body.code;
    this.status = status;
    this.body = body;
  }
}

/** Turn anything thrown into a displayable error body. */
export function toErrorBody(err: unknown, fallback = "Something unexpected went wrong."): ApiErrorBody {
  if (err instanceof ApiError) return err.body;
  return { code: "client_error", message: fallback, retryable: true };
}

const BACKEND_UNREACHABLE: ApiErrorBody = {
  code: "backend_unreachable",
  message: "MediaLab cannot connect to its local backend.",
  action: "Check that the application is running (the terminal with `make dev`), then try again.",
  retryable: true,
};

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      signal,
      headers: { "Content-Type": "application/json", Accept: "application/json", ...init?.headers },
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(BACKEND_UNREACHABLE, 0);
  }
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON body */
  }
  if (!response.ok) {
    const body = (data as { error?: ApiErrorBody } | null)?.error;
    if (body) throw new ApiError(body, response.status);
    // Every MediaLab error has a JSON {error} body. A 502/503/504 without one comes from the
    // dev proxy (Vite) when nothing answers on the backend port.
    if ([502, 503, 504].includes(response.status)) throw new ApiError(BACKEND_UNREACHABLE, response.status);
    throw new ApiError({ code: "http_error", message: `Request failed (HTTP ${response.status}).` }, response.status);
  }
  return data as T;
}

export function analyse(url: string, platform: Platform, signal?: AbortSignal): Promise<AnalyseResponse> {
  return request("/api/analyse", { method: "POST", body: JSON.stringify({ url, platform }) }, signal);
}

export function startDownload(analysisId: string, videoIndex: number, optionId: string): Promise<JobResponse> {
  return request("/api/download", {
    method: "POST",
    body: JSON.stringify({ analysis_id: analysisId, video_index: videoIndex, option_id: optionId }),
  });
}

export function getSettings(): Promise<AppSettings> {
  return request("/api/settings");
}

export function updateSettings(patch: SettingsPatch): Promise<AppSettings> {
  return request("/api/settings", { method: "PATCH", body: JSON.stringify(patch) });
}

export function cancelJob(jobId: string): Promise<JobResponse> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}

export function getJob(jobId: string, signal?: AbortSignal): Promise<JobResponse> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`, undefined, signal);
}

export function getTikTokAccount(): Promise<TikTokAccount> {
  return request("/api/tiktok-account");
}

/** Send the user's own tiktok.com cookies.txt export (used by the Short Drama tab only). */
export function linkTikTokAccount(cookiesTxt: string): Promise<TikTokAccount> {
  return request("/api/tiktok-account", { method: "PUT", body: JSON.stringify({ cookies_txt: cookiesTxt }) });
}

export function unlinkTikTokAccount(): Promise<TikTokAccount> {
  return request("/api/tiktok-account", { method: "DELETE" });
}

export function getSeries(seriesId: string): Promise<SeriesInfo> {
  return request(`/api/shortdrama/series/${encodeURIComponent(seriesId)}`);
}

export function createBatch(body: BatchRequest): Promise<BatchResponse> {
  return request("/api/shortdrama/batches", { method: "POST", body: JSON.stringify(body) });
}

/* Every batch (Short Drama or links) lives under /api/batches since v1.9. */
export function getBatch(batchId: string, signal?: AbortSignal): Promise<BatchResponse> {
  return request(`/api/batches/${encodeURIComponent(batchId)}`, undefined, signal);
}

export function batchAction(
  batchId: string,
  action: "pause" | "resume" | "cancel" | "continue",
): Promise<BatchResponse> {
  return request(`/api/batches/${encodeURIComponent(batchId)}/${action}`, { method: "POST" });
}

export function itemAction(batchId: string, item: number, action: "retry" | "cancel"): Promise<BatchResponse> {
  return request(`/api/batches/${encodeURIComponent(batchId)}/items/${item}/${action}`, { method: "POST" });
}

/** Kept for existing callers: retry one Short Drama episode. */
export function retryEpisode(batchId: string, episode: number): Promise<BatchResponse> {
  return itemAction(batchId, episode, "retry");
}

export function createUrlBatch(body: UrlBatchRequest): Promise<BatchResponse> {
  return request("/api/batches", { method: "POST", body: JSON.stringify(body) });
}

export function createBulkAnalysis(platform: "x" | "tiktok", urls: string[], signal?: AbortSignal): Promise<BulkAnalysis> {
  return request("/api/bulk-analyses", { method: "POST", body: JSON.stringify({ platform, urls }) }, signal);
}

export function getBulkAnalysis(bulkId: string, signal?: AbortSignal): Promise<BulkAnalysis> {
  return request(`/api/bulk-analyses/${encodeURIComponent(bulkId)}`, undefined, signal);
}

export function cancelBulkAnalysis(bulkId: string): Promise<BulkAnalysis> {
  return request(`/api/bulk-analyses/${encodeURIComponent(bulkId)}/cancel`, { method: "POST" });
}
