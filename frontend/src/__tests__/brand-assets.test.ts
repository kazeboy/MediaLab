import { describe, expect, it } from "vitest";
import html from "../../index.html?raw";
import css from "../index.css?raw";
import faviconSvg from "../../public/favicon.svg?raw";
import faviconIco from "../../public/favicon.ico?inline";
import logoTsx from "../components/brand/Logo.tsx?raw";

/** Everything shipped from frontend/public (paths relative to the site root, e.g. "/fonts/x.woff2"). */
const publicFiles = Object.keys(import.meta.glob("../../public/**/*")).map((p) => p.replace("../../public", ""));

const OLD_ICON_COLOUR = "#4f46e5"; // v1.6 indigo play button

describe("favicon", () => {
  const iconLinks = [...html.matchAll(/<link[^>]+rel="(?:icon|shortcut icon|apple-touch-icon|mask-icon)"[^>]*>/g)].map((m) => m[0]);
  const hrefs = iconLinks.map((l) => l.match(/href="([^"]+)"/)![1]);

  it("declares exactly the amber icon set, versioned so a cached v1.6 icon is not reused", () => {
    expect(hrefs).toEqual(["/favicon.ico?v=2", "/favicon.svg?v=2", "/apple-touch-icon.png?v=2"]);
    expect(html).not.toContain("vite.svg");
    expect(html).not.toMatch(/manifest/);
  });

  it("references only files that exist in public/", () => {
    for (const href of hrefs) expect(publicFiles).toContain(href.split("?")[0]);
  });

  it("serves the simplified amber emblem as SVG, not the old purple play button", () => {
    expect(faviconSvg).toContain('viewBox="0 0 16 16"'); // drawn on the 16 px grid
    expect(faviconSvg).toContain("#FFB300"); // amber frame
    expect(faviconSvg).toContain("#F97316"); // orange back frame
    expect(faviconSvg.toLowerCase()).not.toContain(OLD_ICON_COLOUR);
    expect(faviconSvg).not.toMatch(/<path/); // the old icon's play triangle was a path
    expect(faviconSvg).not.toMatch(/<rect[^>]*width="16"[^>]*height="16"/); // transparent, no background tile
  });

  it("ships a favicon.ico holding 16×16 and 32×32 images", () => {
    const bytes = Uint8Array.from(atob(faviconIco.split(",")[1]), (c) => c.charCodeAt(0));
    expect([bytes[0], bytes[1], bytes[2], bytes[3]]).toEqual([0, 0, 1, 0]); // ICO header
    const count = bytes[4];
    const sizes = Array.from({ length: count }, (_, i) => bytes[6 + i * 16] || 256);
    expect(sizes.sort((a, b) => a - b)).toEqual([16, 32]);
  });
});

const FONT_FACES = [
  ["Manrope", "manrope", [600, 700]],
  ["DM Sans", "dm-sans", [400, 500, 600]],
] as const;

describe("typography", () => {
  const faces = [...css.matchAll(/@font-face\s*{([^}]*)}/g)].map((m) => m[1]);

  it("self-hosts only the weights the UI uses, with font-display: swap", () => {
    for (const [family, slug, weights] of FONT_FACES) {
      const own = faces.filter((f) => f.includes(`font-family: "${family}"`));
      expect([...new Set(own.map((f) => Number(f.match(/font-weight: (\d+)/)![1])))]).toEqual([...weights]);
      for (const f of own) {
        expect(f).toContain("font-display: swap");
        const url = f.match(/url\("([^"]+)"\)/)![1];
        expect(url).toMatch(new RegExp(`^/fonts/${slug}-latin(-ext)?-\\d{3}-normal\\.woff2$`));
        expect(publicFiles).toContain(url);
      }
    }
    expect(faces).toHaveLength(10); // 5 weights × (Latin, Latin Extended)
  });

  it("loads no fonts or styles from a CDN", () => {
    for (const source of [css, html]) {
      expect(source).not.toMatch(/fonts\.googleapis|fonts\.gstatic|use\.typekit|fonts\.bunny/);
      expect(source).not.toMatch(/url\(["']?https?:/);
    }
  });

  it("keeps the OFL licence texts next to the font files", () => {
    expect(publicFiles).toEqual(expect.arrayContaining(["/fonts/OFL-Manrope.txt", "/fonts/OFL-DMSans.txt"]));
  });

  it("preloads existing Latin font files", () => {
    const preloads = [...html.matchAll(/<link rel="preload" href="([^"]+)" as="font" type="font\/woff2" crossorigin \/>/g)].map((m) => m[1]);
    expect(preloads).toHaveLength(5);
    for (const p of preloads) expect(publicFiles).toContain(p);
  });

  it("assigns DM Sans to body text, Manrope to headings and keeps the wordmark on the system font", () => {
    const token = (name: string) => css.match(new RegExp(`--font-${name}: ([^;]+);`))![1];
    expect(token("sans")).toMatch(/^"DM Sans", var\(--font-system\)$/);
    expect(token("heading")).toMatch(/^"Manrope", var\(--font-system\)$/);
    expect(token("wordmark")).toBe("var(--font-system)");
    expect(token("system")).not.toMatch(/Manrope|DM Sans/);
    expect(css).toMatch(/h1,\s*h2,\s*h3,\s*legend\s*{\s*font-family: var\(--font-heading\);/);
    expect(css).toMatch(/:root\s*{[^}]*font-family: var\(--font-sans\);/);
    expect(logoTsx).toMatch(/className={`font-wordmark font-extrabold tracking-tight/);
  });
});
