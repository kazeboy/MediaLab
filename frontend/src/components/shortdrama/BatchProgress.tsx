import { LOCKED_BATCH, itemNoun, summarise, useActivity, type BatchEntry } from "../../lib/activity";
import { formatBytes, formatDuration } from "../../lib/format";
import type { BatchEpisode, BatchResponse, EpisodeState } from "../../lib/types";
import { Alert, Badge, Button, Disclosure, DownloadIcon, ProgressBar, RetryIcon, type Tone } from "../ui";

export const EPISODE_STATE: Record<EpisodeState, { label: string; tone: Tone }> = {
  pending: { label: "Waiting", tone: "neutral" },
  resolving: { label: "Starting", tone: "accent" },
  downloading: { label: "Downloading", tone: "accent" },
  processing: { label: "Verifying", tone: "accent" },
  ready: { label: "Ready to save", tone: "success" },
  saving: { label: "Saving", tone: "accent" },
  saved: { label: "Saved", tone: "success" },
  downloaded: { label: "Downloaded", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  skipped: { label: "Skipped", tone: "warn" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const OK = new Set<EpisodeState>(["saved", "downloaded"]);
const BAD = new Set<EpisodeState>(["failed", "skipped", "cancelled"]);
const CANCELLABLE = new Set<EpisodeState>(["pending", "resolving", "downloading", "processing"]);

/** "E02" for a Short Drama episode, "#2" for the second link of a bulk download. */
export function itemLabel(b: BatchResponse, n: number): string {
  return b.source === "urls" ? `#${n}` : `E${String(n).padStart(2, "0")}`;
}

/** Summary-first batch status: headline, one progress bar, decisions, the final Save, then details. */
export function BatchProgress({ entry }: { entry: BatchEntry }) {
  const activity = useActivity();
  const b = entry.batch;
  const pad = (n: number) => itemLabel(b, n);
  const noun = (count: number) => itemNoun(b, count);
  const r = b.result;
  const running = ["planning", "running", "paused", "packaging"].includes(b.state) && !entry.lost;
  const packaged = b.output !== "files";
  const kind = r?.kind === "zip" ? "ZIP" : "Video";
  const failed = b.episodes.filter((e) => BAD.has(e.state));
  const done = b.episodes.filter((e) => OK.has(e.state));
  const inProgress = b.episodes.filter((e) => !OK.has(e.state) && !BAD.has(e.state));

  return (
    <section aria-label="Batch progress" className="space-y-3 rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold">{summarise(entry)}</p>
          <p className="text-sm text-muted">
            {b.output === "zip" ? "ZIP archive" : b.output === "merge" ? "Merged MP4" : "Separate files"} ·{" "}
            {b.episodes.length} {noun(b.episodes.length)}
            {b.estimated_duration_seconds ? ` · ${formatDuration(b.estimated_duration_seconds)}` : ""}
            {b.stage && running && <> · {b.stage}{b.state === "packaging" ? ` (${Math.round(b.package_percent)}%)` : ""}</>}
          </p>
        </div>
        <div className="flex gap-2">
          {b.state === "running" && <Button size="sm" onClick={() => void activity.batchControl(entry.key, "pause")}>Pause</Button>}
          {b.state === "paused" && <Button size="sm" onClick={() => void activity.batchControl(entry.key, "resume")}>Resume</Button>}
          {LOCKED_BATCH.has(b.state) && !["saving", "ready"].includes(b.state) && !entry.lost && !(b.stopped && b.state === "needs_decision") && (
            <Button size="sm" variant="danger" onClick={() => void activity.batchControl(entry.key, "cancel")}>
              {b.stopped ? "Discard unsaved" : "Cancel batch"}
            </Button>
          )}
        </div>
      </div>

      {!entry.lost && <ProgressBar value={b.percent} label="Overall batch progress" />}
      {b.plan_note && <p className="text-xs text-subtle">{b.plan_note}</p>}

      {entry.lost && (
        <Alert tone="info" title="This batch is no longer available">
          MediaLab was restarted or the batch expired; its temporary files were deleted. Start the batch again.
        </Alert>
      )}
      {entry.actionError && <Alert tone="error" title="That didn't work">{entry.actionError.message}</Alert>}

      {b.state === "needs_decision" && b.stopped && (
        <Alert tone="info" title="Stopped">
          <p>{done.length} {noun(done.length)} finished before you cancelled. Build the ZIP from them, or discard them.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button variant="primary" size="sm" onClick={() => void activity.batchControl(entry.key, "continue")}>
              Build ZIP from finished {noun(2)}
            </Button>
            <Button size="sm" variant="danger" onClick={() => void activity.batchControl(entry.key, "cancel")}>Discard them</Button>
          </div>
        </Alert>
      )}
      {b.state === "needs_decision" && !b.stopped && (
        <Alert tone="warn" title={`${failed.length} ${noun(failed.length)} couldn't be downloaded`}>
          <p>Retry them below, or build the {b.output === "zip" ? "ZIP" : "video"} without them.</p>
          <Button variant="primary" size="sm" className="mt-2" onClick={() => void activity.batchControl(entry.key, "continue")}>
            Continue without {failed.map((e) => pad(e.number)).join(", ")}
          </Button>
        </Alert>
      )}
      {b.state === "failed" && b.error && (
        <Alert tone="error" title="Packaging failed">
          <p>{b.error.message}</p>
          {b.error.action && <p className="mt-1 opacity-90">{b.error.action}</p>}
          <Button size="sm" className="mt-2" icon={<RetryIcon className="h-4 w-4" />} onClick={() => void activity.batchControl(entry.key, "continue")}>
            Retry packaging
          </Button>
        </Alert>
      )}
      {(b.state === "partial" || b.state === "cancelled") && b.error && !entry.lost && (
        <Alert tone={b.state === "cancelled" ? "info" : "warn"} title={b.state === "cancelled" ? "Batch cancelled" : `Finished with missing ${noun(2)}`}>
          {b.error.message}
        </Alert>
      )}

      {r && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-50">
          <p className="font-semibold break-all">{r.filename}</p>
          <p className="mt-0.5 text-xs opacity-80">
            {[
              formatBytes(r.size_bytes),
              r.duration_seconds ? formatDuration(r.duration_seconds) : null,
              r.width && r.height ? `${r.width}×${r.height}` : null,
              r.method === "stream_copy" ? "joined without re-encoding" : r.method === "re_encoded" ? "re-encoded to H.264 + AAC" : r.kind === "zip" ? `${r.included.length} MP4 files` : null,
            ].filter(Boolean).join(" · ")}
          </p>
          {r.omitted.length > 0 && (
            <p className="mt-1 text-sm font-medium">Not included: {r.omitted.map((n) => pad(n)).join(", ")}</p>
          )}
          {r.reason && <p className="mt-1 text-xs opacity-80">Re-encoded because the {r.reason}.</p>}
          {r.download_url && (
            <Button variant="primary" className="mt-3" busy={entry.finalSave.state === "saving"}
              icon={<DownloadIcon className="h-4 w-4" />} onClick={() => void activity.saveBatchResult(entry.key)}>
              Save {kind}
            </Button>
          )}
          {entry.finalSave.message && (
            <p className={`mt-2 text-xs ${entry.finalSave.state === "error" ? "font-semibold text-red-700 dark:text-red-300" : "opacity-80"}`}>
              {entry.finalSave.message}
            </p>
          )}
        </div>
      )}
      {b.state === "completed" && (
        <Alert tone="success" title={packaged ? `${kind} saved` : `All ${noun(2)} saved`}>MediaLab deleted its temporary copies.</Alert>
      )}

      {failed.length > 0 && <EpisodeRows title="Needs attention" entry={entry} episodes={failed} />}
      {inProgress.length > 0 && <EpisodeRows title="In progress" entry={entry} episodes={inProgress} />}
      {done.length > 0 && (
        <Disclosure summary={`${done.length} ${noun(done.length)} ${packaged ? "downloaded" : "saved"}`}>
          <EpisodeRows entry={entry} episodes={done} />
        </Disclosure>
      )}
    </section>
  );
}

export function EpisodeRows({ title, entry, episodes }: { title?: string; entry: BatchEntry; episodes: BatchEpisode[] }) {
  const activity = useActivity();
  const running = ["planning", "running", "paused", "packaging"].includes(entry.batch.state);
  const pad = (n: number) => itemLabel(entry.batch, n);
  const links = entry.batch.source === "urls";
  return (
    <div>
      {title && <h3 className="mb-1 text-xs font-semibold tracking-wide text-subtle uppercase">{title}</h3>}
      <ul className="divide-y divide-line text-sm">
        {episodes.map((ep) => {
          const st = EPISODE_STATE[ep.state];
          const clientError = entry.clientErrors[ep.number];
          return (
            <li key={ep.number} className="py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-10 font-mono text-xs text-subtle">{pad(ep.number)}</span>
                {links && <span className="min-w-0 flex-1 basis-40 truncate">{ep.title ?? ep.author ?? `Video ${ep.number}`}</span>}
                <Badge tone={st.tone}>{ep.state === "pending" && entry.batch.state === "planning" ? "Checking qualities" : st.label}</Badge>
                {ep.option_label && <span className="text-xs text-subtle">{ep.option_label}</span>}
                {ep.size_bytes != null && <span className="text-xs text-subtle">{formatBytes(ep.size_bytes)}</span>}
                {ep.attempts > 1 && <span className="text-xs text-subtle">attempt {ep.attempts}</span>}
                <span className="ml-auto flex gap-1">
                  {CANCELLABLE.has(ep.state) && !entry.lost && !["cancelled", "completed", "partial"].includes(entry.batch.state) && (
                    <Button size="sm" variant="ghost" aria-label={`Cancel ${pad(ep.number)}`} onClick={() => void activity.cancelItem(entry.key, ep.number)}>
                      Cancel
                    </Button>
                  )}
                  {ep.state === "ready" && (clientError || !running) && (
                    <Button size="sm" variant="ghost" onClick={() => activity.saveEpisodeAgain(entry.key, ep)}>Save again</Button>
                  )}
                  {["failed", "cancelled", "skipped"].includes(ep.state) && !entry.lost && (
                    <Button size="sm" variant="ghost" icon={<RetryIcon className="h-4 w-4" />} onClick={() => void activity.retryEpisode(entry.key, ep.number)}>
                      Retry
                    </Button>
                  )}
                </span>
              </div>
              {["downloading", "processing", "resolving"].includes(ep.state) && (
                <div className="mt-1.5 flex items-center gap-2">
                  <div className="flex-1"><ProgressBar size="sm" value={ep.state === "processing" ? null : ep.percent} label={`${pad(ep.number)} progress`} /></div>
                  <span className="text-xs text-subtle">{ep.stage}</span>
                </div>
              )}
              {entry.savedNames[ep.number] && <p className="mt-1 text-xs text-subtle">Saved as {entry.savedNames[ep.number]}</p>}
              {ep.note && <p className="mt-1 text-xs text-subtle">{ep.note}</p>}
              {clientError && <p className="mt-1 text-xs text-red-700 dark:text-red-300">Saving failed: {clientError}</p>}
              {ep.error && <p className="mt-1 text-xs text-red-700 dark:text-red-300">{ep.error.message}</p>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
