import { useEffect, useState } from "react";
import { LogoMark, Wordmark } from "./components/brand/Logo";
import { DownloadsDrawer } from "./components/downloads/DownloadsDrawer";
import { SettingsDialog, type SettingsSection } from "./components/settings/SettingsDialog";
import { ShortDramaWorkspace } from "./components/shortdrama/ShortDramaWorkspace";
import { GearIcon, InboxIcon, MoonIcon, SunIcon, Tabs, tabPanelProps } from "./components/ui";
import { PlatformWorkspace } from "./components/bulk/PlatformWorkspace";
import { ActivityProvider, useActivity } from "./lib/activity";
import { getSettings, getTikTokAccount } from "./lib/api";
import { PLATFORMS, PLATFORM_INFO } from "./lib/platform";
import { useTheme } from "./lib/theme";
import type { AppSettings, Platform, TikTokAccount } from "./lib/types";

export default function App() {
  return (
    <ActivityProvider>
      <Shell />
    </ActivityProvider>
  );
}

function Shell() {
  const activity = useActivity();
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [settingsOpen, setSettingsOpen] = useState<SettingsSection | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [tiktokAccount, setTikTokAccount] = useState<TikTokAccount | null>(null);
  const [tab, setTab] = useState<Platform>("x");
  const [incoming, setIncoming] = useState<Record<Platform, { url: string; nonce: number } | null>>({
    x: null,
    tiktok: null,
    tiktok_shortdrama: null,
  });

  useEffect(() => {
    getSettings().then(setSettings, () => setSettings(null));
    getTikTokAccount().then(setTikTokAccount, () => setTikTokAccount(null));
  }, []);

  // Move a URL to the tab it belongs to and analyse it there (other tabs keep their state).
  function switchTo(platform: Platform, url: string) {
    setIncoming((prev) => ({ ...prev, [platform]: { url, nonce: Date.now() } }));
    setTab(platform);
  }

  const count = activity.runningCount + activity.attentionCount;
  const tiktokLinked = !!tiktokAccount?.linked && !tiktokAccount.expired;

  return (
    <div className="min-h-screen bg-canvas text-fg">
      <div className="mx-auto max-w-4xl px-4 pt-6 pb-16 sm:pt-10">
        <header className="mb-6 flex items-center gap-3">
          <LogoMark className="h-10 w-10 shrink-0 sm:h-11 sm:w-11" />
          <div className="min-w-0">
            <h1 className="text-xl leading-tight sm:text-2xl"><Wordmark /></h1>
            <p className="hidden truncate text-sm text-muted sm:block">X, TikTok and TikTok Short Drama to MP4: local downloads in original quality</p>
          </div>
          <nav className="ml-auto flex items-center gap-1" aria-label="Application">
            <button type="button" onClick={() => setDrawerOpen(true)}
              aria-label={`Downloads${count ? ` (${activity.runningCount} running, ${activity.attentionCount} need attention)` : ""}`}
              className="relative inline-flex min-h-10 items-center gap-2 rounded-xl px-3 text-sm font-semibold text-muted hover:bg-surface-muted hover:text-fg">
              <InboxIcon />
              <span className="hidden sm:inline">Downloads</span>
              {count > 0 && (
                <span aria-hidden="true" className={`inline-flex min-w-5 items-center justify-center rounded-full px-1.5 text-xs font-semibold tabular-nums ${activity.attentionCount ? "bg-accent text-on-accent" : "bg-surface-muted text-fg"}`}>
                  {count}
                </span>
              )}
            </button>
            <ThemeToggle />
            <button type="button" onClick={() => setSettingsOpen("general")} aria-label="Settings" title="Settings"
              className="inline-flex min-h-10 min-w-10 items-center justify-center rounded-xl text-muted hover:bg-surface-muted hover:text-fg">
              <GearIcon className="h-6 w-6" />
            </button>
          </nav>
        </header>

        <div className="mb-6">
          <Tabs<Platform>
            label="Platform"
            idPrefix="platform"
            value={tab}
            onChange={setTab}
            items={PLATFORMS.map((p) => ({ id: p, label: PLATFORM_INFO[p].tab, shortLabel: PLATFORM_INFO[p].shortTab }))}
          />
        </div>

        <main>
          {PLATFORMS.map((p) => (
            <div key={p} {...tabPanelProps("platform", p, tab === p)}>
              {p === "tiktok_shortdrama" ? (
                <ShortDramaWorkspace settings={settings} tiktokLinked={tiktokLinked} incoming={incoming[p]} onSwitch={switchTo}
                  onOpenSettings={() => setSettingsOpen("account")} />
              ) : (
                <PlatformWorkspace platform={p} settings={settings} incoming={incoming[p]} onSwitch={switchTo}
                  notice={p === "x" && settings?.fxtwitter_fallback ? (
                    <p className="mt-3 text-sm text-muted">
                      FxTwitter fallback is on: if X returns no video, the post ID is sent to{" "}
                      <span className="font-mono">{settings.fxtwitter_host}</span>.
                    </p>
                  ) : undefined} />
              )}
            </div>
          ))}
        </main>

        <footer className="mt-12 text-center text-xs leading-relaxed text-subtle">
          Only download content you have the right to save. Respect creators' copyright and the platforms' terms.
          <br />
          MediaLab runs on your machine and never asks for your X or TikTok password.
        </footer>
      </div>

      <DownloadsDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <SettingsDialog
        open={settingsOpen !== null}
        initialSection={settingsOpen ?? "general"}
        settings={settings}
        onClose={() => setSettingsOpen(null)}
        onChange={setSettings}
        tiktokAccount={tiktokAccount}
        onTikTokAccountChange={setTikTokAccount}
      />
    </div>
  );
}

/** Header theme switch: shows where it goes (sun → light, moon → dark). */
function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const label = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  return (
    <button type="button" onClick={toggle} aria-label={label} title={label}
      className="inline-flex min-h-10 min-w-10 items-center justify-center rounded-xl text-muted hover:bg-surface-muted hover:text-fg">
      {theme === "dark" ? <SunIcon className="h-6 w-6" /> : <MoonIcon className="h-6 w-6" />}
    </button>
  );
}
