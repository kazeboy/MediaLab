import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LOCKED_BATCH, useActivity, type BatchEntry } from "../../lib/activity";
import { getSeries, toErrorBody } from "../../lib/api";
import { formatDuration } from "../../lib/format";
import { clickEpisode, fromEpisode, keepAccessible, rangeOf } from "../../lib/selection";
import type { ApiErrorBody, BatchEpisode, OutputMode, SeriesInfo } from "../../lib/types";
import { ErrorAlert } from "../ErrorAlert";
import { Badge, Button, Card, Disclosure, EmptyState, FilmIcon, LoadingState } from "../ui";
import { Thumbnail } from "../VideoDetails";
import { BatchActionBar, type BatchOptions } from "./BatchActionBar";
import { BatchProgress } from "./BatchProgress";
import { EpisodeList } from "./EpisodeList";

const OUTPUT_KEY = "medialab.batchOutput";

function savedOutput(): OutputMode {
  try {
    const v = localStorage.getItem(OUTPUT_KEY);
    return v === "merge" || v === "files" || v === "zip" ? v : "zip";
  } catch {
    return "zip";
  }
}

interface Props {
  seriesId: string | null;
  currentEpisode: number | null;
  active: boolean;
  onOpenSettings: () => void;
  onBackToEpisode: () => void;
}

export function SeriesView({ seriesId, currentEpisode, active, onOpenSettings, onBackToEpisode }: Props) {
  const activity = useActivity();
  const [series, setSeries] = useState<SeriesInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const anchor = useRef<number | null>(null);
  const [options, setOptions] = useState<BatchOptions>(() => ({
    output: savedOutput(), quality: "best", strict: false, concurrency: 1, allowPartial: false, folder: null,
  }));
  const [rangeFrom, setRangeFrom] = useState("1");
  const [rangeTo, setRangeTo] = useState("10");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<ApiErrorBody | null>(null);
  const loadedFor = useRef<string | null>(null);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const info = await getSeries(id);
      setSeries(info);
      const accessible = info.episodes.filter((e) => e.available).map((e) => e.number);
      // A refresh never adds episodes; a new series starts with the current episode selected.
      // (Decide before updating loadedFor: the state updater below runs later.)
      const refresh = loadedFor.current === id;
      loadedFor.current = id;
      if (!refresh) anchor.current = currentEpisode && accessible.includes(currentEpisode) ? currentEpisode : null;
      setSelected((prev) =>
        refresh ? keepAccessible(prev, accessible)
          : new Set(currentEpisode && accessible.includes(currentEpisode) ? [currentEpisode] : []),
      );
    } catch (err) {
      setError(toErrorBody(err, "Couldn't load the series."));
    } finally {
      setLoading(false);
    }
  }, [currentEpisode]);

  // Load lazily, the first time the view is shown for a series.
  useEffect(() => {
    if (active && seriesId && loadedFor.current !== seriesId) void load(seriesId);
  }, [active, seriesId, load]);

  const accessible = useMemo(() => series?.episodes.filter((e) => e.available).map((e) => e.number) ?? [], [series]);

  // The most recent batch for this series (it survives tab switches and new analyses).
  const batchEntry = activity.entries.find((e): e is BatchEntry => e.kind === "batch" && e.batch.series_id === seriesId);
  const locked = !!batchEntry && !batchEntry.lost && LOCKED_BATCH.has(batchEntry.batch.state);
  const batchEpisodes = useMemo(
    () => new Map<number, BatchEpisode>(batchEntry && !batchEntry.lost ? batchEntry.batch.episodes.map((e) => [e.number, e]) : []),
    [batchEntry],
  );

  const duration = useMemo(() => {
    const eps = series?.episodes.filter((e) => selected.has(e.number)) ?? [];
    return eps.length && eps.every((e) => e.duration_seconds != null) ? eps.reduce((t, e) => t + (e.duration_seconds ?? 0), 0) : null;
  }, [series, selected]);

  function setOutputs(o: BatchOptions) {
    setOptions(o);
    try {
      localStorage.setItem(OUTPUT_KEY, o.output);
    } catch {
      /* storage unavailable: keep the in-memory choice */
    }
  }

  async function start(numbers: number[]) {
    if (!series || numbers.length === 0) return;
    setStarting(true);
    setStartError(null);
    try {
      await activity.startBatch(
        { series_id: series.series_id, episodes: [...numbers].sort((a, b) => a - b), quality: options.quality,
          strict: options.strict, concurrency: options.concurrency, output: options.output, allow_partial: options.allowPartial },
        { title: series.title ?? "Short Drama series", subtitle: `${numbers.length} episode${numbers.length === 1 ? "" : "s"}` },
        options.folder,
      );
    } catch (err) {
      setStartError(toErrorBody(err, "Couldn't start the batch."));
    } finally {
      setStarting(false);
    }
  }

  if (!seriesId) {
    return (
      <Card>
        <EmptyState title="No series yet" icon={<FilmIcon className="h-8 w-8" />}>
          Analyse any episode in the Episode view, then open its series here.
          <div className="mt-3"><Button onClick={onBackToEpisode}>Go to Episode</Button></div>
        </EmptyState>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {loading && !series && <Card><LoadingState>Loading the episode list from TikTok…</LoadingState></Card>}
      {error && <ErrorAlert title="Series unavailable" error={error} onRetry={() => void load(seriesId)} />}

      {series && (
        <>
          <Card className="flex gap-4">
            <Thumbnail src={series.cover_url} className="aspect-[3/4] w-20 sm:w-24" />
            <div className="min-w-0 flex-1">
              <h2 className="text-lg leading-snug font-bold">{series.title ?? "Short Drama"}</h2>
              <p className="text-sm text-muted">
                {series.publisher_name ?? (series.publisher_handle ? `@${series.publisher_handle}` : "")}
                {series.episode_count != null && <span className="text-subtle"> · {series.episode_count} episodes</span>}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {series.account_used ? (
                  <Badge tone="accent" className="whitespace-normal">{accessible.length} of {series.episodes.length} playable with your account</Badge>
                ) : (
                  <>
                    <Badge tone="warn" className="whitespace-normal">Not signed in: episodes are locked</Badge>
                    <Button size="sm" variant="ghost" onClick={onOpenSettings}>Link TikTok account</Button>
                  </>
                )}
              </div>
              {series.description && <p className="mt-2 line-clamp-2 text-sm text-muted">{series.description}</p>}
            </div>
          </Card>

          {batchEntry && <BatchProgress entry={batchEntry} />}
          {startError && <ErrorAlert title="Couldn't start the batch" error={startError} />}

          <section aria-labelledby="episodes-heading" className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="episodes-heading" className="mr-auto text-base font-semibold">Episodes</h2>
              <Button size="sm" disabled={locked || accessible.length === 0} onClick={() => setSelected(new Set(accessible))}>
                Select all accessible
              </Button>
              <Button size="sm" variant="ghost" disabled={locked || selected.size === 0} onClick={() => setSelected(new Set())}>
                Clear
              </Button>
              <span className="w-full sm:hidden">
                <Button size="sm" variant="secondary" disabled={locked || accessible.length === 0} onClick={() => void start(accessible)}>
                  Download all accessible ({accessible.length})
                </Button>
              </span>
            </div>
            <Disclosure summary="Select a range">
            <form className="flex flex-wrap items-end gap-2 text-sm" onSubmit={(e) => { e.preventDefault(); setSelected(rangeOf(Number(rangeFrom), Number(rangeTo), accessible)); }}>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted">From E</span>
                <input type="number" min={1} value={rangeFrom} onChange={(e) => setRangeFrom(e.target.value)} disabled={locked}
                  className="min-h-9 w-20 rounded-lg border border-line-strong bg-surface px-2" />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted">to E</span>
                <input type="number" min={1} value={rangeTo} onChange={(e) => setRangeTo(e.target.value)} disabled={locked}
                  className="min-h-9 w-20 rounded-lg border border-line-strong bg-surface px-2" />
              </label>
              <Button size="sm" type="submit" disabled={locked}>Select range</Button>
              <Button size="sm" variant="ghost" disabled={locked} onClick={() => setSelected(fromEpisode(Number(rangeFrom), accessible))}>
                From E{rangeFrom || "?"} to the end
              </Button>
              
            </form>
              <p className="mt-2 text-xs text-subtle">Tip: Shift+click an episode to select everything from the previous click.</p>
            </Disclosure>
            <EpisodeList
              episodes={series.episodes}
              selected={selected}
              currentEpisode={currentEpisode}
              batchEpisodes={batchEpisodes}
              disabled={locked}
              onClick={(n, shift) => {
                const r = clickEpisode(selected, n, accessible, shift, anchor.current);
                anchor.current = r.anchor;
                setSelected(r.selected);
              }}
            />
          </section>

          <BatchActionBar
            count={selected.size}
            accessibleCount={accessible.length}
            durationSeconds={duration}
            options={options}
            onOptions={setOutputs}
            onDownloadSelected={() => void start([...selected])}
            onDownloadAll={() => void start(accessible)}
            busy={starting}
            disabled={locked}
          />
          {locked && <p className="text-center text-xs text-subtle">Selection is locked while this series' batch is active{batchEntry?.batch.state === "ready" ? " (save or cancel it first)" : ""}.</p>}
          {duration != null && selected.size > 1 && options.output === "merge" && (
            <p className="text-center text-xs text-subtle">The merged video will be about {formatDuration(duration)} long.</p>
          )}
        </>
      )}
    </div>
  );
}
