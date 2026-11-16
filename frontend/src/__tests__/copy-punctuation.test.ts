import { describe, expect, it } from "vitest";

/**
 * House style: MediaLab-authored copy uses no em dashes (U+2014); sentences are rewritten with full
 * stops, commas, colons or parentheses instead. Scans the project's own source and docs only.
 * Titles, descriptions and names from X/TikTok arrive at runtime and are never touched or scanned.
 */
const EM_DASH = "\u2014";

const sources: Record<string, string> = {
  ...import.meta.glob(["../**/*.{ts,tsx,css}", "../../index.html"], { query: "?raw", import: "default", eager: true }),
  ...import.meta.glob(["../../../*.md", "../../../docs/*.md"], { query: "?raw", import: "default", eager: true }),
};

/**
 * Deliberate exceptions, as "path: reason". Empty today; add an entry only for intentional Unicode test
 * data or quoted third-party text, never for MediaLab's own wording.
 */
const ALLOWED: Record<string, string> = {};

describe("UI and documentation copy", () => {
  it("scans the frontend source, README, CHANGELOG and docs", () => {
    const paths = Object.keys(sources);
    expect(paths).toEqual(expect.arrayContaining(["../App.tsx", "../../index.html", "../../../README.md", "../../../CHANGELOG.md", "../../../docs/FRONTEND_DESIGN_SYSTEM.md"]));
    expect(paths.length).toBeGreaterThan(40);
  });

  it("contains no em dashes", () => {
    const offenders = Object.entries(sources)
      .filter(([path]) => !(path in ALLOWED))
      .flatMap(([path, text]) =>
        text.split("\n").flatMap((line, i) => (line.includes(EM_DASH) ? [`${path}:${i + 1}: ${line.trim().slice(0, 80)}`] : [])),
      );
    expect(offenders).toEqual([]);
  });
});
