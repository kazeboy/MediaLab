import type { Platform } from "./types";

export const PLATFORMS: Platform[] = ["x", "tiktok", "tiktok_shortdrama"];

export const PLATFORM_INFO: Record<Platform, { tab: string; shortTab: string; label: string; placeholder: string; inputLabel: string }> = {
  x: {
    tab: "X",
    shortTab: "X",
    label: "X",
    inputLabel: "X / Twitter post URL",
    placeholder: "https://x.com/user/status/1234567890",
  },
  tiktok: {
    tab: "TikTok Videos",
    shortTab: "TikTok",
    label: "TikTok",
    inputLabel: "TikTok video URL or share link",
    placeholder: "https://www.tiktok.com/@user/video/… or https://vm.tiktok.com/…",
  },
  tiktok_shortdrama: {
    tab: "TikTok Short Drama",
    shortTab: "Short Drama",
    label: "TikTok Short Drama",
    inputLabel: "Short Drama episode link",
    placeholder: "https://vm.tiktok.com/… or https://www.tiktok.com/shortdrama/episode/…",
  },
};

const X_URL = /^(https?:\/\/)?((www|mobile|m)\.)?(x|twitter)\.com\//i;
const TIKTOK_HOST = /^(https?:\/\/)?((www|m)\.)?tiktok\.com\//i;
const TIKTOK_SHORT = /^(https?:\/\/)?((vm|vt)\.tiktok\.com\/|((www|m)\.)?tiktok\.com\/t\/)/i;
const SHORT_DRAMA = /^(https?:\/\/)?((www|m)\.)?tiktok\.com\/shortdrama(\/|$|\?)/i;

/**
 * Best-effort, offline platform detection used to suggest the right tab.
 * TikTok short links return "tiktok_short" because only the backend can tell
 * (after following the link) whether they lead to a video or a Short Drama episode.
 */
export function detectPlatform(value: string): Platform | "tiktok_short" | null {
  const v = value.trim();
  if (!v) return null;
  if (X_URL.test(v)) return "x";
  if (SHORT_DRAMA.test(v)) return "tiktok_shortdrama";
  if (TIKTOK_SHORT.test(v)) return "tiktok_short";
  if (TIKTOK_HOST.test(v)) return "tiktok";
  return null;
}

/** The tab a URL belongs to, if it clearly belongs to a different tab than `current`. */
export function suggestedTab(value: string, current: Platform): Platform | null {
  const detected = detectPlatform(value);
  if (!detected) return null;
  if (detected === "tiktok_short") return current === "x" ? "tiktok" : null;
  // Episodes are ordinary TikTok items (/@user/video/<id>): only the backend can tell them apart.
  if (detected === "tiktok" && current === "tiktok_shortdrama") return null;
  return detected === current ? null : detected;
}
