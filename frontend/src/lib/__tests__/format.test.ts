import { describe, expect, it } from "vitest";
import { codecName, formatBytes, formatDuration, formatSize } from "../format";

describe("format helpers", () => {
  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(9272830)).toBe("8.8 MB");
    expect(formatBytes(null)).toBe("unknown");
    expect(formatSize(null, 2048)).toBe("~2.0 KB");
    expect(formatSize(null, null)).toBeNull();
  });
  it("formats durations", () => {
    expect(formatDuration(115.9)).toBe("1:56");
    expect(formatDuration(3725)).toBe("1:02:05");
    expect(formatDuration(undefined)).toBeNull();
  });
  it("names codecs", () => {
    expect(codecName("hvc1.1.6.L120")).toBe("HEVC");
    expect(codecName("none")).toBeNull();
  });
});
