/**
 * MediaLab emblem: a film frame (sprocket holes) carrying an audio waveform, layered over a second
 * frame offset up and to the right (layered media, forward motion). Same geometry as the SVG files in
 * `public/brand/`. Keep them in sync (see docs/FRONTEND_DESIGN_SYSTEM.md, "Logo").
 *
 * The emblem uses fixed brand colours (it carries its own contrast), so it reads the same on light
 * and dark backgrounds.
 *
 * Brand notice: the emblem artwork and wordmark styling defined here are reserved MediaLab brand
 * assets and are not licensed under MIT (see BRAND_ASSETS.md). The component code itself is MIT.
 */
export const BRAND = { amber: "#FFB300", orange: "#F97316", ink: "#0B0D10" } as const;

const HOLES = [12, 21, 30, 39];
const BARS: [number, number][] = [[12, 6], [19, 14], [26, 20], [33, 10], [40, 14]]; // [x, height]

export function LogoMark({ className = "h-10 w-10", title }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true} aria-label={title}>
      <rect x="18" y="6" width="40" height="40" rx="8" fill={BRAND.orange} />
      <rect x="6" y="16" width="44" height="42" rx="9" fill={BRAND.amber} />
      {HOLES.map((x) => (
        <g key={x} fill={BRAND.ink}>
          <rect x={x} y="20" width="5" height="5" rx="1.5" />
          <rect x={x} y="49" width="5" height="5" rx="1.5" />
        </g>
      ))}
      {BARS.map(([x, h]) => (
        <rect key={x} x={x} y={37 - h / 2} width="4" height={h} rx="2" fill={BRAND.ink} />
      ))}
    </svg>
  );
}

/** Wordmark: "Media" in the text colour, "Lab" in amber (deepened in light mode for legibility). */
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`font-wordmark font-extrabold tracking-tight ${className}`}>
      Media<span className="text-wordmark-lab">Lab</span>
    </span>
  );
}
