import { describe, expect, it } from "vitest";
import { detectPlatform, suggestedTab } from "../platform";

describe("detectPlatform", () => {
  it.each([
    ["https://x.com/user/status/123", "x"],
    ["twitter.com/user/status/123", "x"],
    ["https://www.tiktok.com/@user/video/7100000000000003001", "tiktok"],
    ["https://vm.tiktok.com/ZNExample7/", "tiktok_short"],
    ["https://www.tiktok.com/t/ZTRC5xgJp/", "tiktok_short"],
    ["https://www.tiktok.com/shortdrama/episode/7100000000000000101/2", "tiktok_shortdrama"],
    ["https://example.com/video", null],
    ["   ", null],
  ])("%s → %s", (url, expected) => {
    expect(detectPlatform(url)).toBe(expected);
  });
});

describe("suggestedTab", () => {
  it("suggests the right tab for a link pasted into the wrong one", () => {
    expect(suggestedTab("https://x.com/u/status/1", "tiktok")).toBe("x");
    expect(suggestedTab("https://www.tiktok.com/shortdrama/episode/1/2", "tiktok")).toBe("tiktok_shortdrama");
  });
  it("leaves short links to the backend in both TikTok tabs", () => {
    expect(suggestedTab("https://vm.tiktok.com/ZNExample7/", "tiktok")).toBeNull();
    expect(suggestedTab("https://vm.tiktok.com/ZNExample7/", "tiktok_shortdrama")).toBeNull();
    expect(suggestedTab("https://vm.tiktok.com/ZNExample7/", "x")).toBe("tiktok");
  });
  it("accepts TikTok item links in the Short Drama tab (episodes are TikTok items)", () => {
    expect(suggestedTab("https://www.tiktok.com/@example.studio.a/video/7100000000000001002", "tiktok_shortdrama")).toBeNull();
  });
});
