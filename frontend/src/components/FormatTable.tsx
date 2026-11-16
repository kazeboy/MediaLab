import { codecName, formatFps, formatSize } from "../lib/format";
import type { MediaFormat } from "../lib/types";

function kind(f: MediaFormat): string {
  if (f.has_video === false) return "Audio only";
  if (f.has_audio === false) return "Video only";
  if (f.has_audio) return "Video + audio";
  return "Video (audio not reported)";
}

export function FormatTable({ formats }: { formats: MediaFormat[] }) {
  return (
    <details className="mt-4 rounded-xl border border-line">
      <summary className="cursor-pointer rounded-xl px-4 py-2.5 text-sm font-medium text-muted select-none hover:text-fg">
        Technical details: all {formats.length} formats reported by the source
      </summary>
      <div className="overflow-x-auto border-t border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-muted text-subtle">
            <tr>
              {["ID", "Type", "Resolution", "FPS", "Video", "Audio", "Bitrate", "Size", "MP4"].map((h) => (
                <th key={h} className="px-3 py-2 font-medium whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line text-muted">
            {formats.map((f) => (
              <tr key={f.format_id}>
                <td className="px-3 py-1.5 font-mono whitespace-nowrap">{f.format_id}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{kind(f)}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{f.width && f.height ? `${f.width}×${f.height}` : "unknown"}</td>
                <td className="px-3 py-1.5">{formatFps(f.fps) ?? "unknown"}</td>
                <td className="px-3 py-1.5" title={f.vcodec ?? undefined}>
                  {f.has_video === false ? "none" : (codecName(f.vcodec) ?? "unknown")}
                </td>
                <td className="px-3 py-1.5" title={f.acodec ?? undefined}>
                  {f.has_audio === false ? "none" : (codecName(f.acodec) ?? "unknown")}
                </td>
                <td className="px-3 py-1.5 whitespace-nowrap">{f.tbr ? `${Math.round(f.tbr)} kbps` : "unknown"}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{formatSize(f.filesize, f.filesize_approx) ?? "unknown"}</td>
                <td className="px-3 py-1.5">{f.mp4_compatible === true ? "Yes" : f.mp4_compatible === false ? "No" : "?"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
