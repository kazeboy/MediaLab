import { useEffect, useMemo, useRef, useState } from "react";
import { useActivity, type BatchEntry } from "../../lib/activity";
import { cancelBulkAnalysis, createBulkAnalysis, getBulkAnalysis, toErrorBody } from "../../lib/api";
import { parseLinks } from "../../lib/bulk";
import { formatBytes, formatDuration } from "../../lib/format";
import { PLATFORM_INFO } from "../../lib/platform";
import { folderPickerSupported, type DirHandle, type PickerWindow } from "../../lib/save";
import type { ApiErrorBody, AppSettings, BulkAnalysis, BulkItem, Platform, QualityPreference } from "../../lib/types";
import { ErrorAlert } from "../ErrorAlert";
import { BatchProgress } from "../shortdrama/BatchProgress";
import { Thumbnail } from "../VideoDetails";
import { Alert, Badge, Button, Card, Checkbox, Disclosure, DownloadIcon, FolderIcon, PlusIcon, SelectField, type Tone } from "../ui";

/** Server default (MEDIALAB_MAX_BULK_URLS); the analysis response carries the real limit. */
export const BULK_LIMIT = 50;
const POLL_MS = 800;

const QUALITY_LABEL: Record<QualityPreference, string> = {
  best: "Best available",
  "1080p": "1080p",
  "720p": "720p",
  "480p": "480p",
};

const ITEM_STATE: Record<BulkItem["state"], { label: string; tone: Tone }> = {
  waiting: { label: "Waiting", tone: "neutral" },
  analysing: { label: "Analysing", tone: "accent" },
  ready: { label: "Ready", tone: "success" },
  failed: { label: "Couldn't analyse", tone: "danger" },
  invalid: { label: "Not used", tone: "warn" },
  duplicate: { label: "Duplicate", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

interface Props {
  platform: "x" | "tiktok";
  settings: AppSettings | null;
  /** Open one link in another tab (a link that belongs there). */
  onSwitch: (platform: Platform, url: string) => void;
}

/**
 * Bulk mode for X and TikTok Videos: paste links, analyse them, review and select, then download
 * them as one queue (ZIP or separate MP4s). The queue itself lives in the activity registry, so it
 * keeps running (and stays in Downloads) after New Bulk Download, a tab switch or Single mode.
 */
export function BulkWorkspace({ platform, settings, onSwitch }: Props) {
  const activity = useActivity();
  const label = PLATFORM_INFO[platform].label;
  const [text, setText] = useState("");
  const parsed = useMemo(() => parseLinks(text, platform), [text, platform]);
  const [bulk, setBulk] = useState<BulkAnalysis | null>(null);
  const [bulkError, setBulkError] = useState<ApiErrorBody | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [quality, setQuality] = useState<QualityPreference>("best");
  const [output, setOutput] = useState<"zip" | "files">("zip");
  const [concurrency, setConcurrency] = useState(2);
  const [allowPartial, setAllowPartial] = useState(false);
  const [folder, setFolder] = useState<DirHandle | null>(null);
  const [batchKey, setBatchKey] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<ApiErrorBody | null>(null);
  const generation = useRef(0);
  const seenReady = useRef(new Set<string>()); // analysis IDs already auto-selected once
  const textRef = useRef<HTMLTextAreaElement | null>(null);
  const limit = bulk?.limit ?? BULK_LIMIT;

  /** Show a new analysis state; newly ready videos are selected by default (once), the user can untick them. */
  function absorb(next: BulkAnalysis) {
    setBulk(next);
    // Computed outside the state updater, which React may call twice.
    const fresh = next.items.filter((i) => i.state === "ready" && i.analysis_id && !seenReady.current.has(i.analysis_id))
      .map((i) => i.analysis_id!);
    fresh.forEach((id) => seenReady.current.add(id));
    if (fresh.length) setSelected((prev) => new Set([...prev, ...fresh]));
  }

  // Poll the analysis while it runs. A reset (New Bulk Download) bumps the generation, so a late
  // response can't bring an old list back.
  const bulkId = bulk?.bulk_id;
  const running = bulk?.state === "running";
  useEffect(() => {
    if (!bulkId || !running) return;
    const gen = generation.current;
    const controller = new AbortController();
    const timer = window.setInterval(async () => {
      try {
        const next = await getBulkAnalysis(bulkId, controller.signal);
        if (gen !== generation.current) return;
        absorb(next);
      } catch (err) {
        if ((err as Error).name === "AbortError" || gen !== generation.current) return;
        setBulkError(toErrorBody(err));
      }
    }, POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [bulkId, running]);

  async function analyseAll() {
    const gen = generation.current;
    setSubmitting(true);
    setBulkError(null);
    setStartError(null);
    try {
      const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      const result = await createBulkAnalysis(platform, lines);
      if (gen !== generation.current) return;
      seenReady.current = new Set();
      setSelected(new Set());
      absorb(result);
    } catch (err) {
      if (gen === generation.current) setBulkError(toErrorBody(err));
    } finally {
      if (gen === generation.current) setSubmitting(false);
    }
  }

  async function cancelAnalysis() {
    if (!bulk) return;
    try {
      setBulk(await cancelBulkAnalysis(bulk.bulk_id));
    } catch (err) {
      setBulkError(toErrorBody(err));
    }
  }

  /** Back to an empty Bulk view. A running analysis is cancelled; a started batch keeps running. */
  function reset() {
    if (bulk?.state === "running") void cancelBulkAnalysis(bulk.bulk_id).catch(() => undefined);
    generation.current += 1;
    setText("");
    setBulk(null);
    setBulkError(null);
    setSubmitting(false);
    setSelected(new Set());
    setBatchKey(null);
    setStartError(null);
    setStarting(false);
    seenReady.current = new Set();
    window.setTimeout(() => textRef.current?.focus(), 0);
  }

  const ready = bulk?.items.filter((i) => i.state === "ready" && i.analysis_id) ?? [];
  const chosen = ready.filter((i) => selected.has(i.analysis_id!));
  const sizes = chosen.map((i) => i.estimates[quality]?.size_bytes ?? null);
  const knownSize = sizes.every((s) => s != null) ? sizes.reduce<number>((a, s) => a + (s ?? 0), 0) : null;
  const estimate = chosen.some((i) => i.estimates[quality]?.size_is_estimate);

  async function start() {
    if (!bulk || chosen.length === 0) return;
    const gen = generation.current;
    setStarting(true);
    setStartError(null);
    try {
      const key = await activity.startUrlBatch(
        { platform, analysis_ids: chosen.map((i) => i.analysis_id!), quality, output, concurrency, allow_partial: allowPartial },
        { title: `${chosen.length} ${label} video${chosen.length === 1 ? "" : "s"}`,
          subtitle: `${QUALITY_LABEL[quality]} · ${output === "zip" ? "ZIP archive" : "Separate MP4 files"}` },
        output === "files" ? folder : null,
      );
      if (gen === generation.current) setBatchKey(key);
    } catch (err) {
      if (gen === generation.current) setStartError(toErrorBody(err));
    } finally {
      if (gen === generation.current) setStarting(false);
    }
  }

  async function chooseFolder() {
    try {
      setFolder(await (window as PickerWindow).showDirectoryPicker!({ mode: "readwrite" }));
    } catch {
      /* cancelled */
    }
  }

  const entry = (batchKey ? activity.get(batchKey) : undefined) as BatchEntry | undefined;
  const inputId = `bulk-${platform}`;
  const tooMany = parsed.valid > limit;
  const summaryId = `${inputId}-summary`;

  return (
    <div className="space-y-5">
      <Card>
        <label htmlFor={inputId} className="mb-2 block text-sm font-medium text-muted">
          {label} links, one per line
        </label>
        <textarea
          ref={textRef}
          id={inputId}
          rows={6}
          value={text}
          onChange={(e) => setText(e.target.value)}
          readOnly={!!bulk}
          spellCheck={false}
          autoComplete="off"
          aria-describedby={summaryId}
          placeholder={`${PLATFORM_INFO[platform].placeholder}\n${PLATFORM_INFO[platform].placeholder}`}
          className="block w-full resize-y rounded-xl border border-line-strong bg-surface px-4 py-3 font-mono text-sm leading-relaxed text-fg shadow-sm placeholder:text-subtle read-only:opacity-80 focus:border-accent-line"
        />
        <p id={summaryId} className="mt-2 text-sm text-muted" aria-live="polite">
          {parsed.lines.length === 0
            ? `Paste up to ${limit} links. Blank lines, duplicates and links for other tabs are left out.`
            : [
                `${parsed.lines.length} line${parsed.lines.length === 1 ? "" : "s"}`,
                `${parsed.valid} to analyse`,
                parsed.duplicates ? `${parsed.duplicates} duplicate${parsed.duplicates === 1 ? "" : "s"}` : null,
                parsed.invalid ? `${parsed.invalid} not ${label === "X" ? "an X" : `a ${label}`} link` : null,
              ].filter(Boolean).join(" · ")}
        </p>
        {tooMany && (
          <p className="mt-1 text-sm text-orange-800 dark:text-orange-300">
            That's {parsed.valid} different links; a bulk download can hold at most {limit}. Remove some to continue.
          </p>
        )}
        {!bulk && parsed.lines.some((l) => l.status === "other_tab") && (
          <OtherTabLinks lines={parsed.lines.filter((l) => l.status === "other_tab")} onSwitch={onSwitch} />
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {!bulk && (
            <Button variant="primary" size="lg" busy={submitting} disabled={parsed.valid === 0 || tooMany} onClick={() => void analyseAll()}>
              {submitting ? "Analysing…" : `Analyse ${parsed.valid || ""} video${parsed.valid === 1 ? "" : "s"}`.replace("  ", " ")}
            </Button>
          )}
          {bulk?.state === "running" && (
            <Button size="lg" onClick={() => void cancelAnalysis()}>Stop analysing</Button>
          )}
          {(bulk || batchKey || bulkError) && (
            <Button size="lg" variant="secondary" icon={<PlusIcon className="h-5 w-5" />} onClick={reset}
              title="Clear the list and start again. Downloads already started continue in Downloads.">
              New Bulk Download
            </Button>
          )}
        </div>
        {bulkError && (
          <div className="mt-4">
            <ErrorAlert title="Couldn't analyse the links" error={bulkError} onRetry={bulk ? undefined : () => void analyseAll()} />
          </div>
        )}
      </Card>

      {entry ? (
        <>
          <BatchProgress entry={entry} />
          <p className="text-xs text-subtle">
            This download also appears in Downloads, so you can switch tabs or start another one while it runs.
          </p>
        </>
      ) : bulk && (
        <Card aria-label="Review videos">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-semibold">
              {bulk.state === "running"
                ? `Analysing ${bulk.counts.ready + bulk.counts.failed} of ${bulk.items.length - bulk.counts.invalid - bulk.counts.duplicate}…`
                : `${ready.length} video${ready.length === 1 ? "" : "s"} ready`}
            </h2>
            {ready.length > 1 && (
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => setSelected(new Set(ready.map((i) => i.analysis_id!)))}>Select all</Button>
                <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Select none</Button>
              </div>
            )}
          </div>
          <ul className="mt-3 divide-y divide-line">
            {bulk.items.map((i) => (
              <ReviewRow key={i.index} item={i} quality={quality} checked={!!i.analysis_id && selected.has(i.analysis_id)}
                onToggle={(on) => setSelected((prev) => {
                  const out = new Set(prev);
                  if (on) out.add(i.analysis_id!); else out.delete(i.analysis_id!);
                  return out;
                })}
                onSwitch={onSwitch} />
            ))}
          </ul>

          {ready.length > 0 && (
            <div className="mt-5 space-y-4 border-t border-line pt-5">
              <div className="grid gap-3 sm:grid-cols-2">
                <SelectField label="Quality" value={quality} onChange={(e) => setQuality(e.target.value as QualityPreference)}>
                  {(Object.keys(QUALITY_LABEL) as QualityPreference[]).map((q) => <option key={q} value={q}>{QUALITY_LABEL[q]}</option>)}
                </SelectField>
                <SelectField label="Save as" value={output} onChange={(e) => setOutput(e.target.value as "zip" | "files")}>
                  <option value="zip">ZIP archive (one file)</option>
                  <option value="files">Separate MP4 files</option>
                </SelectField>
              </div>
              <p className="text-xs text-muted">
                {quality === "best"
                  ? "Each video in the highest quality it offers with sound."
                  : `${QUALITY_LABEL[quality]} where offered; otherwise the next lower resolution, or the closest one if there is none. Never upscaled.`}{" "}
                {output === "zip"
                  ? "The ZIP holds one MP4 per video, numbered in the order of your list."
                  : "Each video is saved as soon as it's ready. Keep this page open."}
              </p>
              <Disclosure summary="More options">
                <div className="space-y-4 pt-2">
                  <SelectField label="Parallel downloads" value={concurrency} onChange={(e) => setConcurrency(Number(e.target.value))}>
                    <option value={1}>1 (one at a time)</option>
                    <option value={2}>2 (default)</option>
                  </SelectField>
                  {output === "zip" ? (
                    <Checkbox label="Build the ZIP even if some videos fail" checked={allowPartial} onChange={(e) => setAllowPartial(e.target.checked)}
                      description="Otherwise MediaLab asks first, so you can retry them. Missing videos are always listed in the ZIP." />
                  ) : (
                    <div>
                      <p className="text-sm font-medium text-muted">Save to</p>
                      {folderPickerSupported ? (
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <Button size="sm" icon={<FolderIcon className="h-4 w-4" />} onClick={() => void chooseFolder()}>
                            {folder ? "Change folder" : "Choose folder"}
                          </Button>
                          <span className="text-xs text-muted">{folder ? `“${folder.name}”` : "Browser downloads"}</span>
                          {folder && <Button size="sm" variant="ghost" onClick={() => setFolder(null)}>Use downloads</Button>}
                        </div>
                      ) : (
                        <p className="mt-1 text-xs text-muted">Your browser's downloads folder (choosing a folder needs Chrome, Edge or another Chromium browser).</p>
                      )}
                    </div>
                  )}
                </div>
              </Disclosure>
              {startError && <ErrorAlert title="Couldn't start the download" error={startError} onRetry={() => void start()} />}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <Button variant="primary" size="lg" busy={starting} disabled={chosen.length === 0 || bulk.state === "running"}
                  icon={<DownloadIcon className="h-5 w-5" />} onClick={() => void start()}>
                  Download {chosen.length} video{chosen.length === 1 ? "" : "s"}
                </Button>
                <p className="text-sm text-muted">
                  {chosen.length} of {ready.length} selected
                  {knownSize != null && chosen.length > 0 && <> · {estimate ? "about " : ""}{formatBytes(knownSize)}</>}
                  {settings && <span className="text-subtle"> · limit {Math.round(settings.max_file_size_mb / 1024)} GB per video</span>}
                </p>
              </div>
              {bulk.state === "running" && <p className="text-xs text-subtle">You can start once the analysis finishes.</p>}
            </div>
          )}
          {bulk.state !== "running" && ready.length === 0 && (
            <Alert tone="warn" title="Nothing to download" className="mt-4">
              None of the links could be analysed. Check them, or start again with New Bulk Download.
            </Alert>
          )}
        </Card>
      )}
    </div>
  );
}

function OtherTabLinks({ lines, onSwitch }: { lines: { index: number; text: string; otherTab?: Platform }[]; onSwitch: Props["onSwitch"] }) {
  return (
    <div role="status" className="mt-3 rounded-xl bg-accent-soft px-3 py-2 text-sm text-fg">
      <p>These links belong to another tab and won't be included:</p>
      <ul className="mt-1 space-y-1">
        {lines.slice(0, 5).map((l) => (
          <li key={l.index} className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 truncate font-mono text-xs">{l.text}</span>
            {l.otherTab && (
              <Button size="sm" variant="ghost" onClick={() => onSwitch(l.otherTab!, l.text)}>
                Open in {PLATFORM_INFO[l.otherTab].tab}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReviewRow({ item, quality, checked, onToggle, onSwitch }: {
  item: BulkItem;
  quality: QualityPreference;
  checked: boolean;
  onToggle: (on: boolean) => void;
  onSwitch: Props["onSwitch"];
}) {
  const st = ITEM_STATE[item.state];
  const est = item.estimates[quality];
  const other = item.error?.code === "wrong_platform" ? (item.error.details?.detected_platform as Platform | undefined) : undefined;
  const title = item.title ?? item.input;
  return (
    <li className="flex items-start gap-3 py-3">
      {item.state === "ready" ? (
        // The label is the 44 px hit area around the 20 px box.
        <label className="-m-2 flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center">
          <input type="checkbox" checked={checked} onChange={(e) => onToggle(e.target.checked)}
            aria-label={`Include ${title}`} className="h-5 w-5 accent-[var(--accent)]" />
        </label>
      ) : (
        <span className="flex min-h-10 w-7 shrink-0 items-center justify-center font-mono text-xs text-subtle">{item.index}</span>
      )}
      {item.state === "ready" && (
        <Thumbnail src={item.thumbnail_url} duration={formatDuration(item.duration_seconds)} className="h-14 w-24 sm:h-16 sm:w-28" />
      )}
      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 text-sm font-medium break-words">{title}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-subtle">
          <Badge tone={st.tone}>{st.label}</Badge>
          {item.author && <span>@{item.author.replace(/^@/, "")}</span>}
          {item.state === "ready" && est && (
            <span>{est.label}{est.size_bytes != null ? ` · ${est.size_is_estimate ? "~" : ""}${formatBytes(est.size_bytes)}` : ""}</span>
          )}
          {item.state === "ready" && item.qualities.length > 0 && <span className="hidden sm:inline">Offers {item.qualities.join(", ")}</span>}
          {item.video_count > 1 && <span>Video {item.video_index} of {item.video_count} in this post</span>}
        </p>
        {item.state === "ready" && est?.note && <p className="mt-1 text-xs text-muted">{est.note}</p>}
        {item.state === "duplicate" && <p className="mt-1 text-xs text-muted">Same video as line {item.duplicate_of}; included once.</p>}
        {item.error && (
          <p className="mt-1 text-xs text-red-700 dark:text-red-300">
            {item.error.message}
            {other && (
              <Button size="sm" variant="ghost" className="ml-1" onClick={() => onSwitch(other, item.input)}>
                Open in {PLATFORM_INFO[other].tab}
              </Button>
            )}
          </p>
        )}
      </div>
    </li>
  );
}
