import type { MouseEvent } from "react";
import { formatDuration } from "../../lib/format";
import type { BatchEpisode, SeriesEpisode } from "../../lib/types";
import { Badge } from "../ui";
import { Thumbnail } from "../VideoDetails";
import { EPISODE_STATE } from "./BatchProgress";

interface Props {
  episodes: SeriesEpisode[];
  selected: ReadonlySet<number>;
  currentEpisode: number | null;
  batchEpisodes: Map<number, BatchEpisode>;
  disabled: boolean;
  onClick: (episode: number, shift: boolean) => void;
}

const pad = (n: number) => `E${String(n).padStart(2, "0")}`;

/**
 * Episode rows in normal page flow (no nested scroll). Clicking anywhere on a row toggles it;
 * Shift+click selects or clears the range from the previous click. Locked episodes can't be selected.
 */
export function EpisodeList({ episodes, selected, currentEpisode, batchEpisodes, disabled, onClick }: Props) {
  return (
    <ol aria-label="Episodes" className="divide-y divide-line overflow-hidden rounded-xl border border-line">
      {episodes.map((e) => {
        const checked = selected.has(e.number);
        const status = batchEpisodes.get(e.number);
        const locked = !e.available;
        return (
          <li key={e.number}>
            <label
              className={`flex min-h-14 items-center gap-3 px-3 py-2 text-sm ${locked || disabled ? "cursor-not-allowed" : "cursor-pointer hover:bg-surface-muted"} ${checked ? "bg-accent-soft" : ""} ${locked ? "opacity-60" : ""}`}
              onClick={(ev: MouseEvent) => {
                // One handler for the whole row (so Shift+click can select a range). A click on the
                // row text is cancelled so the label doesn't forward a second click to the checkbox;
                // a click on the checkbox itself keeps its default so the box never desyncs.
                if ((ev.target as HTMLElement).tagName !== "INPUT") ev.preventDefault();
                if (!locked && !disabled) onClick(e.number, ev.shiftKey);
              }}
            >
              <input
                type="checkbox"
                className="h-4 w-4 shrink-0 accent-[var(--accent)]"
                checked={checked}
                disabled={locked || disabled}
                aria-label={`Episode ${e.number}${e.title ? `: ${e.title}` : ""}`}
                onChange={() => undefined /* state changes go through the row's click handler (Space included) */}
              />
              <span className="w-9 shrink-0 font-mono text-xs text-subtle">{pad(e.number)}</span>
              <Thumbnail src={e.thumbnail_url} className="hidden h-12 w-9 sm:block" />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{e.title ?? `Episode ${e.number}`}</span>
                <span className="mt-0.5 flex flex-wrap gap-1.5">
                  {e.number === currentEpisode && <Badge tone="accent">Current</Badge>}
                  {locked && <Badge tone="warn">{e.availability === "login_required" ? "Sign-in needed" : "Locked for your account"}</Badge>}
                  {status && <Badge tone={EPISODE_STATE[status.state].tone}>{EPISODE_STATE[status.state].label}</Badge>}
                </span>
              </span>
              <span className="w-12 shrink-0 text-right text-xs text-subtle tabular-nums">{formatDuration(e.duration_seconds) ?? ""}</span>
            </label>
          </li>
        );
      })}
    </ol>
  );
}
