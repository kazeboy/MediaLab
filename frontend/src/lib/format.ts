export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return "unknown";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`;
}

/** Exact size, "~estimate", or null when nothing is known. */
export function formatSize(exact: number | null, approx: number | null): string | null {
  if (exact != null) return formatBytes(exact);
  if (approx != null) return `~${formatBytes(approx)}`;
  return null;
}

export function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

const CODEC_NAMES: Record<string, string> = {
  avc1: "H.264",
  avc3: "H.264",
  h264: "H.264",
  hev1: "HEVC",
  hvc1: "HEVC",
  hevc: "HEVC",
  av01: "AV1",
  av1: "AV1",
  vp09: "VP9",
  vp9: "VP9",
  vp8: "VP8",
  mp4a: "AAC",
  aac: "AAC",
  opus: "Opus",
  vorbis: "Vorbis",
  mp3: "MP3",
  "ac-3": "AC-3",
  ac3: "AC-3",
  "ec-3": "E-AC-3",
  eac3: "E-AC-3",
};

export function codecName(codec: string | null | undefined): string | null {
  if (!codec || codec === "none") return null;
  const family = codec.toLowerCase().split(".")[0];
  return CODEC_NAMES[family] ?? codec;
}

export function formatFps(fps: number | null | undefined): string | null {
  if (!fps) return null;
  return `${Number.isInteger(fps) ? fps : fps.toFixed(2)} fps`;
}

export function formatSpeed(bps: number | null | undefined): string | null {
  return bps ? `${formatBytes(bps)}/s` : null;
}

export function formatLimit(mb: number): string {
  return mb >= 1024 && mb % 1024 === 0 ? `${mb / 1024} GB` : `${mb.toLocaleString()} MB`;
}
