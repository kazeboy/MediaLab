/*
 * Activity registry: every download job and batch started in this browser tab, across all
 * platform tabs, with the backend as the source of truth.
 *
 * - Entries are created when the UI starts a job or batch and are refreshed by ONE polling loop.
 * - Nothing is persisted: after a page reload the registry is empty, and after a backend restart
 *   entries are marked "no longer available" (job_not_found / batch_not_found). The registry
 *   never invents job state; it only mirrors the last backend response.
 * - Save / Retry / Cancel live here so they work from the Downloads drawer, from any tab, and
 *   after the user analyses another link or clicks New Download.
 * - Batches are Short Drama series or (v1.9) X / TikTok link batches; both share one shape.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ApiError,
  batchAction,
  cancelJob as apiCancelJob,
  createBatch,
  createUrlBatch,
  getBatch,
  getJob,
  itemAction as apiItemAction,
  startDownload,
  toErrorBody,
} from "./api";
import { saveToFolder, saveWithBrowser, type DirHandle } from "./save";
import type { ApiErrorBody, BatchEpisode, BatchRequest, BatchResponse, JobResponse, Platform, UrlBatchRequest } from "./types";

export type SaveStatus = { state: "idle" | "saving" | "done" | "error"; message?: string };

interface Base {
  key: string;
  platform: Platform;
  title: string;
  subtitle?: string;
  createdAt: number;
  lost?: ApiErrorBody; // the backend no longer knows this job/batch
  actionError?: ApiErrorBody; // last failed Retry/Cancel/Save request
}

export interface JobEntry extends Base {
  kind: "job";
  job: JobResponse;
  request: { analysisId: string; videoIndex: number; optionId: string };
  saveRequested: boolean;
}

export interface BatchEntry extends Base {
  kind: "batch";
  batch: BatchResponse;
  folder: DirHandle | null;
  clientErrors: Record<number, string>;
  savedNames: Record<number, string>;
  finalSave: SaveStatus;
}

export type ActivityEntry = JobEntry | BatchEntry;

const ACTIVE_JOB = new Set(["queued", "downloading", "processing"]);
export const ACTIVE_BATCH = new Set(["planning", "running", "paused", "packaging", "ready", "saving"]);
export const LOCKED_BATCH = new Set([...ACTIVE_BATCH, "needs_decision", "failed"]);

export function jobIsActive(job: JobResponse) {
  return ACTIVE_JOB.has(job.state);
}

/** "video" / "episode" for a batch's items. */
export function itemNoun(b: BatchResponse, count = 1): string {
  const noun = b.source === "urls" ? "video" : "episode";
  return count === 1 ? noun : `${noun}s`;
}

/** Does this entry still change on the backend (so it must be polled)? */
export function needsPolling(e: ActivityEntry): boolean {
  if (e.lost) return false;
  if (e.kind === "job") {
    if (ACTIVE_JOB.has(e.job.state)) return true;
    const d = e.job.file?.delivery_state;
    return e.job.state === "completed" && (d === "ready" || d === "delivering");
  }
  return ACTIVE_BATCH.has(e.batch.state) || e.batch.episodes.some((x) => x.state === "ready" || x.state === "saving");
}

/** Needs the user: a file to save, a decision, or a failure they haven't dismissed. */
export function needsAttention(e: ActivityEntry): boolean {
  if (e.lost) return false;
  if (e.kind === "job") {
    return e.job.state === "failed" || (e.job.state === "completed" && e.job.file?.delivery_state === "ready");
  }
  return ["ready", "needs_decision", "failed"].includes(e.batch.state);
}

export function isRunning(e: ActivityEntry): boolean {
  if (e.lost) return false;
  return e.kind === "job" ? ACTIVE_JOB.has(e.job.state) : ["planning", "running", "paused", "packaging", "saving"].includes(e.batch.state);
}

/** One-line, summary-first status for lists and announcements. */
export function summarise(e: ActivityEntry): string {
  if (e.lost) return "No longer available (MediaLab was restarted or the item expired)";
  if (e.kind === "job") {
    const j = e.job;
    if (j.state === "completed") {
      const d = j.file?.delivery_state;
      return d === "delivered" ? "Saved" : d === "expired" ? "Expired (not saved in time)" : d === "delivering" ? "Saving…" : "Ready to save";
    }
    if (j.state === "failed") return j.error?.message ?? "Failed";
    if (j.state === "cancelled") return "Cancelled";
    return j.progress.stage ?? (j.state === "queued" ? "Queued" : "Downloading");
  }
  const b = e.batch;
  const c = b.counts;
  const total = b.episodes.length;
  const done = b.output === "files" ? c.saved : c.downloaded;
  const items = itemNoun(b, total);
  const kind = b.output === "zip" ? "ZIP" : b.output === "merge" ? "Merged video" : items[0].toUpperCase() + items.slice(1);
  const notDone = c.failed + c.skipped + c.cancelled;
  switch (b.state) {
    case "planning":
      return "Choosing one quality for all episodes";
    case "packaging":
      return b.stage ?? (b.output === "zip" ? "Packaging ZIP" : "Merging video");
    case "ready":
      return `${kind} ready to save`;
    case "saving":
      return "Saving…";
    case "needs_decision":
      return b.stopped
        ? `Stopped: ${c.downloaded} ${itemNoun(b, c.downloaded)} finished. Build the ZIP or discard them.`
        : `${notDone} ${itemNoun(b, notDone)} not downloaded. Retry or continue.`;
    case "failed":
      return b.error?.message ?? "Packaging failed";
    case "completed":
      return b.output === "files" ? `All ${total} ${items} saved` : `${kind} saved`;
    case "partial":
      return `${done} of ${total} saved, ${notDone} not included`;
    case "cancelled":
      return "Cancelled";
    case "paused":
      return `Paused: ${done} of ${total} ${b.output === "files" ? "saved" : "downloaded"}`;
    default: {
      const waiting = c.pending;
      const failed = c.failed + c.skipped;
      const verb = b.output === "files" ? "saved" : "downloaded";
      const parts = [`${done} of ${total} ${verb}`];
      if (failed) parts.push(`${failed} failed`);
      if (c.cancelled) parts.push(`${c.cancelled} cancelled`);
      if (waiting) parts.push(`${waiting} waiting`);
      return `${b.stopped ? "Stopped: " : ""}${parts.join(", ")}`;
    }
  }
}

export interface ActivityApi {
  entries: ActivityEntry[];
  get: (key: string) => ActivityEntry | undefined;
  startJob: (meta: { platform: Platform; title: string; subtitle?: string; analysisId: string; videoIndex: number; optionId: string }) => Promise<string>;
  retryJob: (key: string) => Promise<void>;
  cancelJob: (key: string) => Promise<void>;
  saveJob: (key: string) => void;
  startBatch: (request: BatchRequest, meta: { title: string; subtitle?: string }, folder: DirHandle | null) => Promise<string>;
  startUrlBatch: (request: UrlBatchRequest, meta: { title: string; subtitle?: string }, folder: DirHandle | null) => Promise<string>;
  batchControl: (key: string, action: "pause" | "resume" | "cancel" | "continue") => Promise<void>;
  retryEpisode: (key: string, episode: number) => Promise<void>;
  cancelItem: (key: string, item: number) => Promise<void>;
  saveBatchResult: (key: string) => Promise<void>;
  saveEpisodeAgain: (key: string, episode: BatchEpisode) => void;
  dismiss: (key: string) => void;
  clearFinished: () => void;
  runningCount: number;
  attentionCount: number;
  announcement: string;
}

const ActivityContext = createContext<ActivityApi | null>(null);

export function useActivity(): ActivityApi {
  const ctx = useContext(ActivityContext);
  if (!ctx) throw new Error("useActivity must be used inside <ActivityProvider>");
  return ctx;
}

const POLL_MS = 800;

export function ActivityProvider({ children, pollMs = POLL_MS }: { children: ReactNode; pollMs?: number }) {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [announcement, setAnnouncement] = useState("");
  const entriesRef = useRef(entries);
  entriesRef.current = entries;
  const handled = useRef(new Set<string>()); // file IDs already handed to the browser (files mode)
  const savingBatch = useRef(new Set<string>());

  const update = useCallback((key: string, fn: (e: ActivityEntry) => ActivityEntry) => {
    setEntries((list) => list.map((e) => (e.key === key ? fn(e) : e)));
  }, []);

  // ---- announcements: only meaningful stage changes, never every percentage
  const lastSummary = useRef(new Map<string, string>());
  useEffect(() => {
    for (const e of entries) {
      const s = summarise(e);
      const prev = lastSummary.current.get(e.key);
      const stateKey = e.kind === "job" ? `${e.job.state}/${e.job.file?.delivery_state ?? ""}` : e.batch.state;
      const key = `${stateKey}`;
      if (prev !== key) {
        lastSummary.current.set(e.key, key);
        if (prev !== undefined) setAnnouncement(`${e.title}: ${s}`);
      }
    }
  }, [entries]);

  // ---- one polling loop for everything that can still change
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setInterval(async () => {
      const due = entriesRef.current.filter(needsPolling);
      await Promise.all(
        due.map(async (e) => {
          try {
            if (e.kind === "job") {
              const job = await getJob(e.job.job_id, controller.signal);
              update(e.key, (x) => ({ ...x, job }) as JobEntry);
            } else {
              const batch = await getBatch(e.batch.batch_id, controller.signal);
              update(e.key, (x) => ({ ...x, batch }) as BatchEntry);
            }
          } catch (err) {
            if ((err as Error).name === "AbortError") return;
            const body = toErrorBody(err);
            if (body.code === "job_not_found" || body.code === "batch_not_found") {
              update(e.key, (x) => ({ ...x, lost: body }));
            }
            // Other errors (backend briefly unreachable): keep the entry and try again next tick.
          }
        }),
      );
    }, pollMs);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [pollMs, update]);

  // ---- "Separate files" batches: hand finished episodes to the browser one at a time
  useEffect(() => {
    for (const e of entries) {
      if (e.kind !== "batch" || e.lost || e.batch.output !== "files" || e.batch.state === "cancelled") continue;
      if (savingBatch.current.has(e.key) || e.batch.episodes.some((x) => x.state === "saving")) continue;
      const next = e.batch.episodes.find(
        (x) => x.state === "ready" && x.file_id && !handled.current.has(x.file_id) && !e.clientErrors[x.number],
      );
      if (next) void saveEpisode(e.key, next, e.folder);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries]);

  async function saveEpisode(key: string, ep: BatchEpisode, folder: DirHandle | null) {
    if (!ep.download_url || !ep.filename || !ep.file_id) return;
    handled.current.add(ep.file_id);
    savingBatch.current.add(key);
    try {
      if (folder) {
        const name = await saveToFolder(folder, ep.download_url, ep.filename);
        update(key, (x) => ({ ...x, savedNames: { ...(x as BatchEntry).savedNames, [ep.number]: name } }) as BatchEntry);
      } else {
        saveWithBrowser(ep.download_url, ep.filename);
        await new Promise((r) => window.setTimeout(r, 1500)); // let the browser start the transfer
      }
    } catch (err) {
      handled.current.delete(ep.file_id);
      update(key, (x) => ({
        ...x,
        clientErrors: { ...(x as BatchEntry).clientErrors, [ep.number]: (err as Error).message || "Saving failed." },
      }) as BatchEntry);
    } finally {
      savingBatch.current.delete(key);
    }
  }

  const api = useMemo<ActivityApi>(() => {
    const get = (key: string) => entriesRef.current.find((e) => e.key === key);
    return {
      entries,
      get,
      async startJob(meta) {
        let job: JobResponse;
        try {
          job = await startDownload(meta.analysisId, meta.videoIndex, meta.optionId);
        } catch (err) {
          // The server refuses a second identical download (double click, another tab): follow the running one.
          const running = err instanceof ApiError && err.code === "already_downloading" ? String(err.body.details?.job_id ?? "") : "";
          if (!running) throw err;
          const existing = `job:${running}`;
          if (get(existing)) return existing;
          job = await getJob(running);
        }
        const key = `job:${job.job_id}`;
        setEntries((list) => [
          { key, kind: "job", platform: meta.platform, title: meta.title, subtitle: meta.subtitle, createdAt: Date.now(), job,
            request: { analysisId: meta.analysisId, videoIndex: meta.videoIndex, optionId: meta.optionId }, saveRequested: false },
          ...list.filter((x) => x.key !== key),
        ]);
        return key;
      },
      async retryJob(key) {
        const e = get(key);
        if (!e || e.kind !== "job") return;
        try {
          const job = await startDownload(e.request.analysisId, e.request.videoIndex, e.request.optionId);
          const newKey = `job:${job.job_id}`;
          setEntries((list) => [
            { ...e, key: newKey, job, saveRequested: false, lost: undefined, actionError: undefined, createdAt: Date.now() },
            ...list.filter((x) => x.key !== key),
          ]);
        } catch (err) {
          update(key, (x) => ({ ...x, actionError: toErrorBody(err, "Couldn't restart the download.") }));
        }
      },
      async cancelJob(key) {
        const e = get(key);
        if (!e || e.kind !== "job") return;
        try {
          const job = await apiCancelJob(e.job.job_id);
          update(key, (x) => ({ ...x, job }) as JobEntry);
        } catch (err) {
          update(key, (x) => ({ ...x, actionError: toErrorBody(err) }));
        }
      },
      saveJob(key) {
        const e = get(key);
        if (!e || e.kind !== "job" || !e.job.file) return;
        saveWithBrowser(e.job.file.download_url, e.job.file.filename);
        update(key, (x) => ({ ...x, saveRequested: true }) as JobEntry);
      },
      async startBatch(request, meta, folder) {
        const batch = await createBatch(request);
        const key = `batch:${batch.batch_id}`;
        setEntries((list) => [
          { key, kind: "batch", platform: "tiktok_shortdrama", title: meta.title, subtitle: meta.subtitle, createdAt: Date.now(),
            batch, folder, clientErrors: {}, savedNames: {}, finalSave: { state: "idle" } },
          ...list,
        ]);
        return key;
      },
      async startUrlBatch(request, meta, folder) {
        const batch = await createUrlBatch(request);
        const key = `batch:${batch.batch_id}`;
        setEntries((list) => [
          { key, kind: "batch", platform: request.platform, title: meta.title, subtitle: meta.subtitle, createdAt: Date.now(),
            batch, folder, clientErrors: {}, savedNames: {}, finalSave: { state: "idle" } },
          ...list,
        ]);
        return key;
      },
      async batchControl(key, action) {
        const e = get(key);
        if (!e || e.kind !== "batch") return;
        try {
          const batch = await batchAction(e.batch.batch_id, action);
          update(key, (x) => ({ ...x, batch, actionError: undefined }) as BatchEntry);
        } catch (err) {
          const body = toErrorBody(err);
          update(key, (x) => ({ ...x, actionError: body, lost: body.code === "batch_not_found" ? body : x.lost }));
        }
      },
      async retryEpisode(key, episode) {
        const e = get(key);
        if (!e || e.kind !== "batch") return;
        try {
          const batch = await apiItemAction(e.batch.batch_id, episode, "retry");
          update(key, (x) => {
            const errors = { ...(x as BatchEntry).clientErrors };
            delete errors[episode];
            return { ...x, batch, clientErrors: errors, actionError: undefined } as BatchEntry;
          });
        } catch (err) {
          update(key, (x) => ({ ...x, actionError: toErrorBody(err) }));
        }
      },
      async cancelItem(key, item) {
        const e = get(key);
        if (!e || e.kind !== "batch") return;
        try {
          const batch = await apiItemAction(e.batch.batch_id, item, "cancel");
          update(key, (x) => ({ ...x, batch, actionError: undefined }) as BatchEntry);
        } catch (err) {
          update(key, (x) => ({ ...x, actionError: toErrorBody(err) }));
        }
      },
      async saveBatchResult(key) {
        const e = get(key);
        const result = e?.kind === "batch" ? e.batch.result : null;
        if (!e || e.kind !== "batch" || !result?.download_url) return;
        update(key, (x) => ({ ...x, finalSave: { state: "saving" } }) as BatchEntry);
        try {
          if (e.folder) {
            const name = await saveToFolder(e.folder, result.download_url, result.filename);
            update(key, (x) => ({ ...x, finalSave: { state: "done", message: `Saved into “${e.folder!.name}” as ${name}.` } }) as BatchEntry);
          } else {
            saveWithBrowser(result.download_url, result.filename);
            update(key, (x) => ({ ...x, finalSave: { state: "done", message: "Sent to your browser's downloads." } }) as BatchEntry);
          }
        } catch (err) {
          update(key, (x) => ({ ...x, finalSave: { state: "error", message: (err as Error).message || "Saving failed." } }) as BatchEntry);
        }
      },
      saveEpisodeAgain(key, episode) {
        const e = get(key);
        if (!e || e.kind !== "batch") return;
        update(key, (x) => {
          const errors = { ...(x as BatchEntry).clientErrors };
          delete errors[episode.number];
          return { ...x, clientErrors: errors } as BatchEntry;
        });
        void saveEpisode(key, episode, e.folder);
      },
      dismiss(key) {
        setEntries((list) => list.filter((e) => e.key !== key));
      },
      clearFinished() {
        setEntries((list) => list.filter((e) => needsPolling(e) || needsAttention(e)));
      },
      runningCount: entries.filter(isRunning).length,
      attentionCount: entries.filter(needsAttention).length,
      announcement,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries, announcement, update]);

  return (
    <ActivityContext.Provider value={api}>
      {children}
      <div aria-live="polite" className="sr-only">{announcement}</div>
    </ActivityContext.Provider>
  );
}
