import { describe, expect, it } from "vitest";
import { parseLinks } from "../bulk";

describe("parseLinks (Bulk preview)", () => {
  it("drops blank lines, trims whitespace and counts what will be analysed", () => {
    const p = parseLinks("\n  https://x.com/a/status/1  \n\n\thttps://x.com/b/status/2\n   \n", "x");
    expect(p.lines.map((l) => l.text)).toEqual(["https://x.com/a/status/1", "https://x.com/b/status/2"]);
    expect([p.valid, p.duplicates, p.invalid]).toEqual([2, 0, 0]);
  });

  it("recognises the same post on x.com and twitter.com as a duplicate of the first line", () => {
    const p = parseLinks("https://x.com/a/status/1\nhttps://twitter.com/someone/status/1\nhttps://x.com/a/status/1/video/2", "x");
    expect(p.lines.map((l) => l.status)).toEqual(["ok", "duplicate", "ok"]);
    expect(p.lines[1].duplicateOf).toBe(1);
  });

  it("flags links for another tab and unrecognised text without mixing platforms", () => {
    const p = parseLinks("https://www.tiktok.com/@u/video/1\nhello world\nhttps://x.com/a/status/1", "x");
    expect(p.lines[0]).toMatchObject({ status: "other_tab", otherTab: "tiktok" });
    expect(p.lines[1].status).toBe("unrecognised");
    expect([p.valid, p.invalid]).toEqual([1, 2]);
    const tt = parseLinks("https://x.com/a/status/1\nhttps://vm.tiktok.com/ZN8abc/", "tiktok");
    expect(tt.lines.map((l) => l.status)).toEqual(["other_tab", "ok"]); // share links are resolved by the server
  });

  it("handles an empty paste", () => {
    expect(parseLinks("   \n\n", "tiktok")).toEqual({ lines: [], valid: 0, duplicates: 0, invalid: 0 });
  });
});
