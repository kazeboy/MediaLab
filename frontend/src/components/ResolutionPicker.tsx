import { codecName, formatFps, formatSize } from "../lib/format";
import type { ResolutionOption, VideoResult } from "../lib/types";
import { Badge } from "./ui";

interface Props {
  video: VideoResult;
  selected: string | null;
  onSelect: (optionId: string) => void;
  disabled: boolean;
}

/** One line a non-expert can act on: what the file will contain. Codec names stay secondary. */
function audioSummary(o: ResolutionOption): string {
  if (o.has_audio === false) return "No audio track";
  if (o.audio_converted) return `Audio converted to AAC (from ${codecName(o.acodec) ?? "source"})`;
  if (o.has_audio === true) return "With audio";
  return "Audio not reported by the source (checked after download)";
}

function technical(o: ResolutionOption): string {
  const parts: string[] = [];
  if (o.width && o.height) parts.push(`${o.width}×${o.height}`);
  const fps = formatFps(o.fps);
  if (fps) parts.push(fps);
  const v = codecName(o.vcodec);
  const a = o.has_audio === false ? null : o.audio_converted ? "AAC" : codecName(o.acodec);
  if (v || a) parts.push([v, a].filter(Boolean).join(" + "));
  if (o.requires_merge) parts.push(o.audio_converted ? "video copied" : "streams merged losslessly");
  return parts.join(" · ");
}

export function ResolutionPicker({ video, selected, onSelect, disabled }: Props) {
  if (video.options.length === 0) {
    return <p className="text-sm text-muted">No downloadable resolutions were found for this video.</p>;
  }
  return (
    <fieldset disabled={disabled}>
      <legend className="mb-3 text-base font-semibold">Quality</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {video.options.map((o) => {
          const size = formatSize(o.filesize, o.filesize_approx);
          const active = selected === o.option_id;
          const unavailable = !o.downloadable;
          return (
            <label
              key={o.option_id}
              className={`flex cursor-pointer gap-3 rounded-xl border p-3 transition-colors ${
                unavailable
                  ? "cursor-not-allowed border-line opacity-60"
                  : active
                    ? "border-accent-line bg-accent-soft ring-1 ring-accent-line"
                    : "border-line hover:border-line-strong"
              } ${o.is_best ? "sm:col-span-2" : ""}`}
            >
              <input type="radio" name={`resolution-${video.index}`} value={o.option_id} checked={active}
                disabled={unavailable} onChange={() => onSelect(o.option_id)} className="mt-1 accent-[var(--accent)]" />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{o.is_best ? o.label.replace(/^Best Available \((.*)\)$/, "$1") : o.label}</span>
                  {o.is_best && <Badge tone="accent">Best available</Badge>}
                  {unavailable && <Badge tone="warn">{o.too_large ? "Over size limit" : "Not available as MP4"}</Badge>}
                  <span className="ml-auto text-sm text-muted tabular-nums">{size ?? "size unknown"}</span>
                </span>
                <span className={`mt-0.5 block text-sm ${o.has_audio === false ? "text-orange-800 dark:text-orange-300" : "text-muted"}`}>
                  {unavailable && o.note ? o.note : audioSummary(o)}
                  {o.fallback_audio_format_id && !unavailable && " · separate soundtrack added if needed"}
                </span>
                <span className="mt-0.5 block text-xs text-subtle">{technical(o)}</span>
              </span>
            </label>
          );
        })}
      </div>
      {video.options.some((o) => o.filesize == null && o.filesize_approx != null) && (
        <p className="mt-2 text-xs text-subtle">Sizes with “~” are estimates from the stream bitrate.</p>
      )}
    </fieldset>
  );
}
