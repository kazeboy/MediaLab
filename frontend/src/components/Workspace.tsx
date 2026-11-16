import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useActivity, type JobEntry } from "../lib/activity";
import { analyse, toErrorBody } from "../lib/api";
import { formatLimit, formatSize } from "../lib/format";
import { PLATFORM_INFO } from "../lib/platform";
import type { AnalyseResponse, ApiErrorBody, AppSettings, Platform } from "../lib/types";
import { DownloadPanel } from "./DownloadPanel";
import { ErrorAlert } from "./ErrorAlert";
import { FormatTable } from "./FormatTable";
import { ResolutionPicker } from "./ResolutionPicker";
import { UrlForm } from "./UrlForm";
import { VideoDetails } from "./VideoDetails";
import { Button, Card, LoadingState, PlusIcon } from "./ui";

function defaultOption(analysis: AnalyseResponse, videoIndex: number): string | null {
  const video = analysis.videos.find((v) => v.index === videoIndex);
  return video?.options.find((o) => o.downloadable)?.option_id ?? null;
}

interface Props {
  platform: Platform;
  settings: AppSettings | null;
  /** A URL handed over from another tab (switch suggestion); analysed automatically. */
  incoming: { url: string; nonce: number } | null;
  onSwitch: (platform: Platform, url: string) => void;
  /** Short informational line under the URL field. */
  notice?: ReactNode;
  /** Called whenever a new analysis succeeds (Short Drama uses it to find the series). */
  onAnalysis?: (analysis: AnalyseResponse) => void;
  /** Extra actions shown with the video details (e.g. "Open series"). */
  actions?: (analysis: AnalyseResponse) => ReactNode;
}

/** One platform's single-video flow. Job state comes from the activity registry, not local polling. */
export function Workspace({ platform, settings, incoming, onSwitch, notice, onAnalysis, actions }: Props) {
  const activity = useActivity();
  const [url, setUrl] = useState("");
  const [analysing, setAnalysing] = useState(false);
  const [analyseError, setAnalyseError] = useState<ApiErrorBody | null>(null);
  const [analysis, setAnalysis] = useState<AnalyseResponse | null>(null);
  const [videoIndex, setVideoIndex] = useState(1);
  const [optionId, setOptionId] = useState<string | null>(null);
  const [jobKey, setJobKey] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<ApiErrorBody | null>(null);
  const analyseAbort = useRef<AbortController | null>(null);
  // Bumped by New Download: responses that belong to an earlier generation are ignored.
  const generation = useRef(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);

  const entry = (jobKey ? activity.get(jobKey) : undefined) as JobEntry | undefined;
  const jobActive = !!entry && !entry.lost && ["queued", "downloading", "processing"].includes(entry.job.state);

  const runAnalysis = useCallback(
    async (value: string) => {
      analyseAbort.current?.abort();
      const controller = new AbortController();
      analyseAbort.current = controller;
      const gen = generation.current;
      setAnalysing(true);
      setAnalyseError(null);
      try {
        const result = await analyse(value, platform, controller.signal);
        if (gen !== generation.current) return; // reset meanwhile: never repopulate the empty workspace
        setAnalysis(result);
        setVideoIndex(result.selected_video_index);
        setOptionId(defaultOption(result, result.selected_video_index));
        setJobKey(null); // the previous job stays in the Downloads drawer
        setStartError(null);
        onAnalysis?.(result);
      } catch (err) {
        if ((err as Error).name === "AbortError" || gen !== generation.current) return;
        setAnalyseError(toErrorBody(err, "Unexpected error while analysing."));
      } finally {
        if (analyseAbort.current === controller) setAnalysing(false);
      }
    },
    [platform, onAnalysis],
  );

  const incomingNonce = incoming?.nonce;
  useEffect(() => {
    if (!incoming) return;
    setUrl(incoming.url);
    void runAnalysis(incoming.url);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incomingNonce]);

  useEffect(() => {
    if (focusNonce) inputRef.current?.focus();
  }, [focusNonce]);

  /**
   * Back to the empty workspace without touching anything else: a download that already started
   * keeps running in the activity registry (Downloads drawer, Save until it expires), and the
   * other tabs, the Short Drama series selection and the settings are unchanged.
   */
  function newDownload() {
    generation.current += 1;
    analyseAbort.current?.abort();
    analyseAbort.current = null;
    setUrl("");
    setAnalysis(null);
    setAnalyseError(null);
    setAnalysing(false);
    setVideoIndex(1);
    setOptionId(null);
    setJobKey(null);
    setStartError(null);
    setStarting(false);
    setFocusNonce((n) => n + 1);
  }

  const video = analysis?.videos.find((v) => v.index === videoIndex) ?? analysis?.videos[0];
  const selectedOption = video?.options.find((o) => o.option_id === optionId) ?? null;

  async function download() {
    if (!analysis || !optionId || !video) return;
    setStarting(true);
    setStartError(null);
    const gen = generation.current;
    const drama = analysis.post.drama;
    const title = drama
      ? `${drama.series_title ?? "Short Drama"}${drama.episode != null ? ` · E${String(drama.episode).padStart(2, "0")}` : ""}`
      : (analysis.post.author_name ?? analysis.post.author_handle ?? `${PLATFORM_INFO[platform].label} video`);
    try {
      const key = await activity.startJob({
        platform,
        title,
        subtitle: selectedOption?.label,
        analysisId: analysis.analysis_id,
        videoIndex: video.index,
        optionId,
      });
      if (gen === generation.current) setJobKey(key); // otherwise it lives on in the Downloads drawer
    } catch (err) {
      if (gen === generation.current) setStartError(toErrorBody(err));
    } finally {
      if (gen === generation.current) setStarting(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <UrlForm platform={platform} url={url} onUrlChange={setUrl} busy={analysing} onAnalyse={runAnalysis}
          onSwitch={onSwitch} notice={notice} inputRef={inputRef}
          extraAction={(analysis || analysing || analyseError) ? (
            <Button variant="secondary" size="lg" onClick={newDownload} icon={<PlusIcon className="h-5 w-5" />}
              title="Clear this link and start another. Downloads already started continue in Downloads.">
              New Download
            </Button>
          ) : null} />
        {analyseError && (
          <div className="mt-4">
            <ErrorAlert title="Analysis failed" error={analyseError} onRetry={() => runAnalysis(url.trim())}
              onSwitch={(p) => onSwitch(p, String(analyseError.details?.url ?? url.trim()))} />
          </div>
        )}
      </Card>

      {analysing && !analysis && (
        <Card><LoadingState>Looking up the {PLATFORM_INFO[platform].label} video and its formats…</LoadingState></Card>
      )}

      {analysis && video && (
        <Card className={analysing ? "opacity-60 transition-opacity" : ""} aria-label="Video">
          <VideoDetails analysis={analysis} video={video} disabled={jobActive} actions={actions?.(analysis)}
            onSelectVideo={(index) => {
              setVideoIndex(index);
              setOptionId(defaultOption(analysis, index));
              setJobKey(null);
              setStartError(null);
            }} />
          <hr className="my-6 border-line" />
          <ResolutionPicker video={video} selected={optionId} onSelect={setOptionId} disabled={jobActive} />
          <FormatTable formats={video.formats} />
          <hr className="my-6 border-line" />
          <DownloadPanel
            expectedSize={selectedOption ? formatSize(selectedOption.filesize, selectedOption.filesize_approx) : null}
            sizeLimit={settings ? formatLimit(settings.max_file_size_mb) : null}
            entry={entry ?? null}
            startError={startError}
            canDownload={!!optionId && !analysing}
            starting={starting}
            onDownload={() => void download()}
            onSave={() => jobKey && activity.saveJob(jobKey)}
            onCancel={() => jobKey && void activity.cancelJob(jobKey)}
          />
        </Card>
      )}
    </div>
  );
}
