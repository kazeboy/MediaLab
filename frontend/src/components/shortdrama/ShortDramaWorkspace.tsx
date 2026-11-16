import { useCallback, useState } from "react";
import type { AnalyseResponse, AppSettings, Platform } from "../../lib/types";
import { Button, Tabs, tabPanelProps } from "../ui";
import { Workspace } from "../Workspace";
import { SeriesView } from "./SeriesView";

type View = "episode" | "series";

interface Props {
  settings: AppSettings | null;
  tiktokLinked: boolean;
  incoming: { url: string; nonce: number } | null;
  onSwitch: (platform: Platform, url: string) => void;
  onOpenSettings: () => void;
}

/**
 * Short Drama has two views: Episode (download one episode) and Series (select and batch).
 * Both stay mounted, so switching never discards an analysis, a selection or a running download.
 */
export function ShortDramaWorkspace({ settings, tiktokLinked, incoming, onSwitch, onOpenSettings }: Props) {
  const [view, setView] = useState<View>("episode");
  const [series, setSeries] = useState<{ id: string; episode: number | null } | null>(null);

  const onAnalysis = useCallback((a: AnalyseResponse) => {
    if (a.post.drama) setSeries({ id: a.post.drama.series_id, episode: a.post.drama.episode });
  }, []);

  const notice = (
    <p className="mt-3 text-sm text-muted">
      {tiktokLinked ? "Using your linked TikTok account (this tab only)." : (
        <>
          TikTok shows Short Drama episodes only to signed-in viewers.{" "}
          <button type="button" onClick={onOpenSettings} className="font-medium text-accent-fg underline underline-offset-2 hover:no-underline">
            Link your TikTok account
          </button>
        </>
      )}
    </p>
  );

  return (
    <div className="space-y-5">
      <Tabs<View>
        variant="segmented"
        label="Short Drama view"
        idPrefix="sd-view"
        value={view}
        onChange={setView}
        items={[
          { id: "episode", label: "Episode" },
          { id: "series", label: "Series" },
        ]}
      />
      <div {...tabPanelProps("sd-view", "episode", view === "episode")}>
        <Workspace
          platform="tiktok_shortdrama"
          settings={settings}
          incoming={incoming}
          onSwitch={onSwitch}
          notice={notice}
          onAnalysis={onAnalysis}
          actions={(a) => a.post.drama ? (
            <Button variant="secondary" onClick={() => setView("series")}>
              Open series{a.post.drama.episode_count ? ` (${a.post.drama.episode_count} episodes)` : ""}
            </Button>
          ) : null}
        />
      </div>
      <div {...tabPanelProps("sd-view", "series", view === "series")}>
        <SeriesView
          seriesId={series?.id ?? null}
          currentEpisode={series?.episode ?? null}
          active={view === "series"}
          onOpenSettings={onOpenSettings}
          onBackToEpisode={() => setView("episode")}
        />
      </div>
    </div>
  );
}
