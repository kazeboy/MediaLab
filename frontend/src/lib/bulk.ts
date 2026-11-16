/*
 * Instant, offline preview of a pasted list of links (Bulk mode): blank lines removed, whitespace
 * trimmed, duplicates and links for another tab flagged before anything is sent. The backend
 * repeats every check (POST /api/bulk-analyses) and is authoritative: this only drives the
 * counts shown under the text area and the Analyse button.
 */
import { detectPlatform, suggestedTab } from "./platform";
import type { Platform } from "./types";

export type LineStatus = "ok" | "duplicate" | "other_tab" | "unrecognised";

export interface ParsedLine {
  index: number; // 1-based, after blank lines are removed
  text: string;
  status: LineStatus;
  duplicateOf?: number;
  otherTab?: Platform;
}

export interface ParsedLinks {
  lines: ParsedLine[];
  valid: number;
  duplicates: number;
  invalid: number;
}

/** Post identity used for duplicate detection: x.com and twitter.com links of one post match. */
function identity(text: string): string {
  const x = text.match(/\/status(?:es)?\/(\d+)(?:\/video\/(\d+))?/i);
  if (x && /(x|twitter)\.com\//i.test(text)) return `x:${x[1]}:${x[2] ?? "1"}`;
  const tt = text.match(/tiktok\.com\/@[^/]+\/video\/(\d+)/i);
  if (tt) return `tiktok:${tt[1]}`;
  return text.toLowerCase().replace(/^https?:\/\//, "").replace(/\/+$/, "");
}

export function parseLinks(raw: string, platform: Platform): ParsedLinks {
  const texts = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const seen = new Map<string, number>();
  const lines = texts.map<ParsedLine>((text, i) => {
    const index = i + 1;
    const other = suggestedTab(text, platform);
    if (other) return { index, text, status: "other_tab", otherTab: other };
    if (!detectPlatform(text)) return { index, text, status: "unrecognised" };
    const id = identity(text);
    const first = seen.get(id);
    if (first !== undefined) return { index, text, status: "duplicate", duplicateOf: first };
    seen.set(id, index);
    return { index, text, status: "ok" };
  });
  return {
    lines,
    valid: lines.filter((l) => l.status === "ok").length,
    duplicates: lines.filter((l) => l.status === "duplicate").length,
    invalid: lines.filter((l) => l.status === "other_tab" || l.status === "unrecognised").length,
  };
}
