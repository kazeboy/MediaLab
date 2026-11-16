import type { JobEntry } from "../lib/activity";
import { codecName, formatBytes, formatDuration, formatFps, formatSpeed } from "../lib/format";
import type { ApiErrorBody, JobResponse } from "../lib/types";
import { ErrorAlert } from "./ErrorAlert";
import { Alert, Button, DownloadIcon, ProgressBar } from "./ui";

interface Props {
  expectedSize: string | null;
  sizeLimit: string | null;
  entry: JobEntry | null;
  startError: ApiErrorBody | null;
  canDownload: boolean;
  starting: boolean;
  onDownload: () => void;
  onSave: () => void;
  onCancel: () => void;
}

const STATE_LABEL: Record<JobResponse["state"], string> = {
  queued: "Queued",
  downloading: "Downloading",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function DownloadPanel({ expectedSize, sizeLimit, entry, startError, canDownload, starting, onDownload, onSave, onCancel }: Props) {
  const job = entry?.job ?? null;
  const active = !!job && ["queued", "downloading", "processing"].includes(job.state) && !entry?.lost;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button variant="primary" size="lg" onClick={onDownload} disabled={!canDownload || active} busy={starting}
          icon={<DownloadIcon className="h-5 w-5" />}>
          {active ? "Downloading…" : "Download MP4"}
        </Button>
        {canDownload && !active && (
          <p className="text-sm text-muted">
            <span className="font-medium tabular-nums text-fg">{expectedSize ?? "Size unknown"}</span>
            {expectedSize?.startsWith("~") && " (estimate)"}
            {sizeLimit && <span className="text-subtle"> · limit {sizeLimit}</span>}
          </p>
        )}
      </div>

      {startError && <ErrorAlert title="Couldn't start the download" error={startError} onRetry={onDownload} />}
      {entry?.lost && (
        <Alert tone="info" title="This download is no longer available">
          MediaLab was restarted or the download expired. Click Download MP4 to start it again.
        </Alert>
      )}
      {job && active && <Progress job={job} onCancel={onCancel} />}
      {job?.state === "cancelled" && !entry?.lost && (
        <Alert tone="info" title="Download cancelled">
          MediaLab stopped the download and deleted its temporary files. Click Download MP4 to start again.
        </Alert>
      )}
      {job?.state === "failed" && !entry?.lost && (
        <ErrorAlert
          title={job.error?.code === "download_cancelled" ? "Download cancelled" : "Download failed"}
          error={job.error ?? { code: "download_failed", message: "The download failed.", retryable: true }}
          onRetry={onDownload}
        />
      )}
      {job?.state === "completed" && job.file && !entry?.lost && (
        <Completed job={job} onSave={onSave} saveRequested={entry?.saveRequested ?? false} />
      )}
    </div>
  );
}

function Progress({ job, onCancel }: { job: JobResponse; onCancel: () => void }) {
  const p = job.progress;
  const sizeText =
    p.total_bytes != null
      ? `${formatBytes(p.downloaded_bytes)} of ${p.total_is_estimate ? "~" : ""}${formatBytes(p.total_bytes)}`
      : `${formatBytes(p.downloaded_bytes)} downloaded`;
  const extras = [formatSpeed(p.speed_bytes_per_second), p.eta_seconds != null ? `${formatDuration(p.eta_seconds)} left` : null]
    .filter(Boolean)
    .join(" · ");
  const percent = job.state === "processing" ? null : p.percent;
  return (
    <div className="rounded-xl border border-line p-4">
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span className="font-medium">{STATE_LABEL[job.state]} · {job.option_label}</span>
        <span className="flex items-center gap-3">
          <span className="text-muted tabular-nums">{percent != null ? `${percent.toFixed(0)}%` : ""}</span>
          {/* Same backend job as the Cancel in the Downloads drawer; also stops FFmpeg processing. */}
          <Button variant="secondary" size="sm" onClick={onCancel} aria-label="Cancel download">Cancel</Button>
        </span>
      </div>
      <ProgressBar value={percent} label="Download progress" />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-muted tabular-nums">
        <span>{p.stage ?? ""}</span>
        <span>{job.state === "downloading" && `${sizeText}${extras ? ` · ${extras}` : ""}`}</span>
      </div>
    </div>
  );
}

function Completed({ job, onSave, saveRequested }: { job: JobResponse; onSave: () => void; saveRequested: boolean }) {
  const f = job.file!;
  const audio = f.audio_converted
    ? `AAC (converted from ${codecName(f.source_audio_codec) ?? "source"})`
    : (codecName(f.audio_codec) ?? "no audio");
  const specs = [
    f.width && f.height ? `${f.width}×${f.height}` : null,
    formatFps(f.fps),
    [codecName(f.video_codec), audio].filter(Boolean).join(" + ") + (f.audio_silent_source ? " (source audio is silent)" : ""),
    formatDuration(f.duration_seconds),
    formatBytes(f.size_bytes),
  ].filter(Boolean);
  const state = f.delivery_state;

  if (state === "delivered") {
    return (
      <Alert tone="success" title="Saved by your browser">
        <p className="text-xs break-all opacity-90">{f.filename}</p>
        <p className="mt-1 text-xs opacity-90">MediaLab deleted its temporary copy. If the file doesn't appear in your downloads, download it again.</p>
      </Alert>
    );
  }
  if (state === "expired") {
    return (
      <Alert tone="info" title="Temporary copy deleted">
        This video wasn't saved in time. Click Download MP4 to fetch it again.
      </Alert>
    );
  }
  const busy = state === "delivering";
  const until = f.available_until ? new Date(f.available_until) : null;
  return (
    <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-50">
      <p className="font-semibold">Ready to save</p>
      <p className="mt-0.5 text-sm break-all">{f.filename}</p>
      <p className="mt-0.5 text-xs opacity-80">{specs.join(" · ")}</p>
      <Button variant="primary" className="mt-3" onClick={onSave} busy={busy} icon={<DownloadIcon className="h-4 w-4" />}>
        {busy ? "Saving…" : "Save Video"}
      </Button>
      <p className="mt-2 text-xs opacity-80">
        {busy
          ? "Your browser is receiving the video."
          : saveRequested
            ? "If the download didn't start, click Save Video again."
            : "Your browser decides where it's saved."}
        {until && !busy && ` Available until ${until.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.`}
      </p>
    </div>
  );
}
