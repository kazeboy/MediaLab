import { useState } from "react";
import { formatDuration } from "../../lib/format";
import { folderPickerSupported, type DirHandle, type PickerWindow } from "../../lib/save";
import type { OutputMode } from "../../lib/types";
import { Button, Checkbox, DownloadIcon, FolderIcon, Popover, SelectField, SlidersIcon } from "../ui";

export interface BatchOptions {
  output: OutputMode;
  quality: string;
  strict: boolean;
  concurrency: number;
  allowPartial: boolean;
  folder: DirHandle | null;
}

export const OUTPUT_LABEL: Record<OutputMode, string> = { zip: "ZIP archive", merge: "Merged MP4", files: "Separate MP4 files" };
const OUTPUT_HELP: Record<OutputMode, string> = {
  zip: "One ZIP with an MP4 per episode, in order. Original quality.",
  merge: "One continuous MP4. Joined without re-encoding when the episodes share a format.",
  files: "Each episode saved as it finishes. Keep this page open.",
};
const QUALITIES = [
  { value: "best", label: "Best available" },
  { value: "1080p", label: "1080p" },
  { value: "720p", label: "720p" },
  { value: "576p", label: "576p" },
  { value: "480p", label: "480p" },
];

interface Props {
  count: number;
  accessibleCount: number;
  durationSeconds: number | null;
  options: BatchOptions;
  onOptions: (o: BatchOptions) => void;
  onDownloadSelected: () => void;
  onDownloadAll: () => void;
  busy: boolean;
  disabled: boolean;
}

/** Sticky bar at the bottom of the Series view. It's in the page flow, so it never covers the last row. */
export function BatchActionBar({ count, accessibleCount, durationSeconds, options, onOptions, onDownloadSelected, onDownloadAll, busy, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const set = (patch: Partial<BatchOptions>) => onOptions({ ...options, ...patch });

  async function chooseFolder() {
    try {
      const dir = await (window as PickerWindow).showDirectoryPicker!({ mode: "readwrite" });
      set({ folder: dir });
    } catch {
      /* cancelled */
    }
  }

  return (
    <div className="pb-safe sticky bottom-0 z-20 -mx-4 border-t border-line bg-surface px-4 pt-3 sm:mx-0 sm:rounded-2xl sm:border sm:shadow-lg">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 text-sm" aria-live="off">
          <p className="font-heading font-semibold">{count === 0 ? "No episodes selected" : `${count} episode${count === 1 ? "" : "s"} selected`}</p>
          {durationSeconds ? <p className="text-xs text-muted">About {formatDuration(durationSeconds)} in total</p> : null}
        </div>
        <label className="sr-only" htmlFor="batch-output">Output format</label>
        <select id="batch-output" value={options.output} disabled={disabled}
          onChange={(e) => set({ output: e.target.value as OutputMode })}
          className="min-h-10 rounded-lg border border-line-strong bg-surface px-2 text-sm">
          {(Object.keys(OUTPUT_LABEL) as OutputMode[]).map((m) => <option key={m} value={m}>{OUTPUT_LABEL[m]}</option>)}
        </select>
        <div className="relative">
          <Button data-popover-trigger aria-expanded={open} aria-haspopup="dialog" aria-label="Options" icon={<SlidersIcon className="h-4 w-4" />}
            onClick={() => setOpen((v) => !v)} disabled={disabled}>
            <span className="hidden sm:inline" aria-hidden="true">Options</span>
          </Button>
          <Popover open={open} onClose={() => setOpen(false)} label="Batch options">
            <div className="space-y-4">
              <p className="text-xs text-muted">{OUTPUT_HELP[options.output]}</p>
              <SelectField label="Preferred quality" value={options.quality} onChange={(e) => set({ quality: e.target.value })}>
                {QUALITIES.map((q) => <option key={q.value} value={q.value}>{q.label}</option>)}
              </SelectField>
              <Checkbox label="Strict quality" description="Fail episodes without this quality instead of using the next lower one."
                checked={options.strict} disabled={options.quality === "best"} onChange={(e) => set({ strict: e.target.checked })} />
              <SelectField label="Parallel downloads" value={options.concurrency} onChange={(e) => set({ concurrency: Number(e.target.value) })}>
                <option value={1}>1 (sequential)</option>
                <option value={2}>2</option>
              </SelectField>
              {options.output !== "files" && (
                <Checkbox label="Continue if an episode fails" description="Otherwise MediaLab stops before packaging so you can retry. Missing episodes are always listed."
                  checked={options.allowPartial} onChange={(e) => set({ allowPartial: e.target.checked })} />
              )}
              <div>
                <p className="text-sm font-medium text-muted">Save to</p>
                {folderPickerSupported ? (
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <Button size="sm" icon={<FolderIcon className="h-4 w-4" />} onClick={() => void chooseFolder()}>
                      {options.folder ? "Change folder" : "Choose folder"}
                    </Button>
                    <span className="text-xs text-muted">{options.folder ? `“${options.folder.name}”` : "Browser downloads"}</span>
                    {options.folder && <Button size="sm" variant="ghost" onClick={() => set({ folder: null })}>Use downloads</Button>}
                  </div>
                ) : (
                  <p className="mt-1 text-xs text-muted">Your browser's downloads folder (choosing a folder needs Chrome, Edge or another Chromium browser).</p>
                )}
              </div>
            </div>
          </Popover>
        </div>
        <Button variant="primary" busy={busy} disabled={disabled || count === 0} onClick={onDownloadSelected}
          icon={<DownloadIcon className="h-4 w-4" />}>
          Download {count > 0 ? count : ""}
        </Button>
        {/* Desktop only (on phones it's in the episode toolbar). A wrapper, because the Button's own
            display class would override `hidden`. */}
        <span className="hidden sm:block">
          <Button variant="ghost" disabled={disabled || accessibleCount === 0} onClick={onDownloadAll}>
            All accessible ({accessibleCount})
          </Button>
        </span>
      </div>
    </div>
  );
}
