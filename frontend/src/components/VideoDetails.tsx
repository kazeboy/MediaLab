import { useState, type ReactNode } from "react";
import { formatDuration } from "../lib/format";
import { PLATFORM_INFO } from "../lib/platform";
import type { AnalyseResponse, VideoResult } from "../lib/types";
import { Badge, Disclosure, FilmIcon } from "./ui";

interface Props {
  analysis: AnalyseResponse;
  video: VideoResult;
  onSelectVideo: (index: number) => void;
  disabled: boolean;
  actions?: ReactNode;
}

export function Thumbnail({ src, duration, className = "" }: { src: string | null; duration?: string | null; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  return (
    <div className={`relative shrink-0 overflow-hidden rounded-xl bg-surface-muted ${className}`}>
      {src && failed !== src ? (
        <img src={src} alt="" referrerPolicy="no-referrer" loading="lazy" className="h-full w-full object-cover" onError={() => setFailed(src)} />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-subtle">
          <FilmIcon className="h-7 w-7" />
        </div>
      )}
      {duration && (
        <span className="absolute right-1.5 bottom-1.5 rounded-md bg-black/75 px-1.5 py-0.5 text-xs font-medium text-white tabular-nums">
          {duration}
        </span>
      )}
    </div>
  );
}

export function VideoDetails({ analysis, video, onSelectVideo, disabled, actions }: Props) {
  const { post, videos } = analysis;
  const drama = post.drama;
  const duration = formatDuration(video.duration_seconds);
  const title = drama
    ? `${drama.series_title ?? "Short Drama"}${drama.episode != null ? ` · Episode ${drama.episode}` : ""}`
    : (post.author_name ?? "Unknown author");

  return (
    <div className="flex flex-col gap-5 sm:flex-row">
      <Thumbnail src={video.thumbnail_url} duration={duration}
        className={drama ? "aspect-[3/4] w-full sm:w-40" : "aspect-video w-full sm:w-64"} />
      <div className="min-w-0 flex-1">
        <h2 className="text-lg leading-snug font-bold">{title}</h2>
        <p className="mt-0.5 text-sm text-muted">
          {drama ? (post.author_name ?? post.author_handle ?? "") : null}
          {!drama && post.author_handle && `@${post.author_handle}`}
          {drama && post.author_handle && <span className="text-subtle"> · @{post.author_handle}</span>}
          {drama?.episode_count ? <span className="text-subtle"> · {drama.episode_count} episodes</span> : null}
        </p>
        {post.text && !drama && <p className="mt-2 line-clamp-3 text-sm whitespace-pre-line text-muted">{post.text}</p>}
        <div className="mt-3 flex flex-wrap gap-1.5">
          {duration && <Badge>{duration}</Badge>}
          {drama?.account_used && <Badge tone="accent">Your TikTok account</Badge>}
          {analysis.provider === "fxtwitter" && <Badge tone="warn">Found via FxTwitter</Badge>}
          {post.possibly_sensitive && <Badge tone="warn">Marked sensitive by the source</Badge>}
        </div>

        {videos.length > 1 && (
          <div className="mt-4">
            <p className="mb-2 text-sm font-medium text-muted">This post has {videos.length} videos</p>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Choose a video">
              {videos.map((v) => (
                <button
                  key={v.index}
                  type="button"
                  aria-pressed={v.index === video.index}
                  disabled={disabled}
                  onClick={() => onSelectVideo(v.index)}
                  className={`min-h-9 rounded-lg border px-3 text-sm font-medium disabled:opacity-50 ${
                    v.index === video.index
                      ? "border-accent-line bg-accent-soft text-fg"
                      : "border-line-strong text-muted hover:text-fg"
                  }`}
                >
                  Video {v.index}
                  {formatDuration(v.duration_seconds) && <span className="ml-1.5 text-xs opacity-75">{formatDuration(v.duration_seconds)}</span>}
                </button>
              ))}
            </div>
          </div>
        )}

        {actions && <div className="mt-4 flex flex-wrap gap-2">{actions}</div>}

        <Disclosure summary="Source details" className="mt-4">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-subtle">Platform</dt>
            <dd>{PLATFORM_INFO[analysis.platform]?.label ?? analysis.platform}</dd>
            <dt className="text-subtle">{analysis.platform === "x" ? "Post" : "Video ID"}</dt>
            <dd className="truncate font-mono">
              <a href={post.url} target="_blank" rel="noopener noreferrer" className="underline-offset-2 hover:underline">{post.post_id}</a>
            </dd>
            <dt className="text-subtle">Metadata</dt>
            <dd>{analysis.provider === "fxtwitter" ? "FxTwitter (third party); video from X's CDN" : analysis.provider}</dd>
            <dt className="text-subtle">Output</dt>
            <dd>MP4 at the source's own resolutions (never upscaled)</dd>
          </dl>
        </Disclosure>
      </div>
    </div>
  );
}
