import { isRunning, itemNoun, needsAttention, summarise, useActivity, type ActivityEntry } from "../../lib/activity";
import { formatBytes } from "../../lib/format";
import { PLATFORM_INFO } from "../../lib/platform";
import { EpisodeRows } from "../shortdrama/BatchProgress";
import { Badge, Button, Dialog, Disclosure, DownloadIcon, EmptyState, InboxIcon, ProgressBar, RetryIcon } from "../ui";

/** All jobs and batches started in this browser tab, across the three platform tabs. */
export function DownloadsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const activity = useActivity();
  const attention = activity.entries.filter(needsAttention);
  const running = activity.entries.filter((e) => isRunning(e) && !needsAttention(e));
  const finished = activity.entries.filter((e) => !isRunning(e) && !needsAttention(e));

  return (
    <Dialog open={open} onClose={onClose} placement="right" title="Downloads"
      description={activity.entries.length ? `${running.length} running · ${attention.length} need attention` : undefined}
      footer={finished.length > 0 ? (
        <Button size="sm" variant="ghost" onClick={activity.clearFinished}>Clear finished</Button>
      ) : undefined}>
      {activity.entries.length === 0 ? (
        <EmptyState title="Nothing here yet" icon={<InboxIcon className="h-8 w-8" />}>
          Downloads and batches you start appear here, from every tab, until you close this page.
        </EmptyState>
      ) : (
        <div className="space-y-5">
          {attention.length > 0 && <Group title="Needs attention" entries={attention} />}
          {running.length > 0 && <Group title="In progress" entries={running} />}
          {finished.length > 0 && (
            <Disclosure summary={`Finished (${finished.length})`}>
              <Group entries={finished} />
            </Disclosure>
          )}
          <p className="text-xs text-subtle">
            This list lives in this browser tab only. If MediaLab restarts, running downloads stop and are shown as no longer available.
          </p>
        </div>
      )}
    </Dialog>
  );
}

function Group({ title, entries }: { title?: string; entries: ActivityEntry[] }) {
  return (
    <section>
      {title && <h3 className="mb-2 text-xs font-semibold tracking-wide text-subtle uppercase">{title}</h3>}
      <ul className="space-y-2">
        {entries.map((e) => <Item key={e.key} entry={e} />)}
      </ul>
    </section>
  );
}

export function Item({ entry }: { entry: ActivityEntry }) {
  const summary = summarise(entry);
  const attention = needsAttention(entry);
  const failed = !entry.lost && ((entry.kind === "job" && entry.job.state === "failed") || (entry.kind === "batch" && entry.batch.state === "failed"));
  let percent: number | null | undefined;
  let size: number | null = null;
  if (entry.kind === "job") {
    percent = isRunning(entry) ? (entry.job.state === "processing" ? null : entry.job.progress.percent) : undefined;
    size = entry.job.file?.size_bytes ?? entry.job.progress.total_bytes;
  } else {
    percent = isRunning(entry) ? entry.batch.percent : undefined;
    size = entry.batch.result?.size_bytes ?? null;
  }

  return (
    <li className={`rounded-xl border p-3 ${attention ? "border-accent-line bg-surface dark:bg-accent-soft" : "border-line"}`}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{entry.title}</p>
          <p className="truncate text-xs text-subtle">
            {PLATFORM_INFO[entry.platform].label}
            {entry.subtitle && ` · ${entry.subtitle}`}
            {size ? ` · ${formatBytes(size)}` : ""}
          </p>
        </div>
        {failed && <Badge tone="danger">Failed</Badge>}
        {entry.lost && <Badge>Unavailable</Badge>}
      </div>
      <p className={`mt-1.5 text-sm ${failed ? "text-red-700 dark:text-red-300" : "text-muted"}`}>{summary}</p>
      {percent !== undefined && <div className="mt-2"><ProgressBar size="sm" value={percent} label={`${entry.title} progress`} /></div>}
      {entry.actionError && <p className="mt-1 text-xs text-red-700 dark:text-red-300">{entry.actionError.message}</p>}
      <Actions entry={entry} />
      {entry.kind === "batch" && !entry.lost && entry.batch.episodes.length > 1 && (
        <Disclosure summary={`${entry.batch.episodes.length} ${itemNoun(entry.batch, 2)}`} className="mt-2">
          <EpisodeRows entry={entry} episodes={entry.batch.episodes} />
        </Disclosure>
      )}
      {entry.kind === "job" && entry.job.error && !entry.lost && (
        <Disclosure summary="Details" className="mt-2">
          <p className="text-xs text-muted">{entry.job.error.action}</p>
          <p className="mt-1 font-mono text-xs text-subtle">{entry.job.error.code}</p>
        </Disclosure>
      )}
    </li>
  );
}

function Actions({ entry }: { entry: ActivityEntry }) {
  const activity = useActivity();
  const buttons = [];
  if (entry.kind === "job" && !entry.lost) {
    const j = entry.job;
    if (j.state === "completed" && j.file && (j.file.delivery_state === "ready" || j.file.delivery_state === "delivering")) {
      buttons.push(
        <Button key="save" size="sm" variant="primary" busy={j.file.delivery_state === "delivering"}
          icon={<DownloadIcon className="h-4 w-4" />} onClick={() => activity.saveJob(entry.key)}>Save Video</Button>,
      );
    }
    if (j.state === "failed" || j.state === "cancelled" || j.file?.delivery_state === "expired") {
      buttons.push(<Button key="retry" size="sm" icon={<RetryIcon className="h-4 w-4" />} onClick={() => void activity.retryJob(entry.key)}>Retry</Button>);
    }
    if (["queued", "downloading", "processing"].includes(j.state)) {
      buttons.push(<Button key="cancel" size="sm" variant="ghost" onClick={() => void activity.cancelJob(entry.key)}>Cancel</Button>);
    }
  }
  if (entry.kind === "job" && entry.lost) {
    buttons.push(<Button key="retry" size="sm" icon={<RetryIcon className="h-4 w-4" />} onClick={() => void activity.retryJob(entry.key)}>Retry</Button>);
  }
  if (entry.kind === "batch" && !entry.lost) {
    const b = entry.batch;
    if (b.result?.download_url) {
      buttons.push(
        <Button key="save" size="sm" variant="primary" busy={entry.finalSave.state === "saving"} icon={<DownloadIcon className="h-4 w-4" />}
          onClick={() => void activity.saveBatchResult(entry.key)}>Save {b.result.kind === "zip" ? "ZIP" : "Video"}</Button>,
      );
    }
    if (b.state === "needs_decision" || b.state === "failed") {
      buttons.push(<Button key="continue" size="sm" onClick={() => void activity.batchControl(entry.key, "continue")}>
        {b.state === "failed" ? "Retry packaging" : b.stopped ? "Build ZIP from finished" : "Continue without failed"}</Button>);
    }
    const links = b.source === "urls";
    const cancellable = ["planning", "running", "paused", "packaging", "needs_decision", "failed"].includes(b.state)
      || (!links && b.state === "ready");
    if (cancellable) {
      buttons.push(<Button key="cancel" size="sm" variant="ghost" onClick={() => void activity.batchControl(entry.key, "cancel")}>
        {b.stopped ? "Discard" : links ? "Cancel batch" : "Cancel"}</Button>);
    }
  }
  if (!isRunning(entry) && !needsAttention(entry)) {
    buttons.push(<Button key="dismiss" size="sm" variant="ghost" onClick={() => activity.dismiss(entry.key)}>Dismiss</Button>);
  }
  if (buttons.length === 0) return null;
  return <div className="mt-2 flex flex-wrap gap-2">{buttons}</div>;
}
