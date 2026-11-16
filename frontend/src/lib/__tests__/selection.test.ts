import { describe, expect, it } from "vitest";
import { clickEpisode, describeSelection, fromEpisode, keepAccessible, rangeOf } from "../selection";

const ACCESSIBLE = [1, 2, 3, 5, 6, 7]; // 4 is locked

describe("episode selection", () => {
  it("toggles single episodes and ignores locked ones", () => {
    let r = clickEpisode(new Set(), 2, ACCESSIBLE, false, null);
    expect([...r.selected]).toEqual([2]);
    r = clickEpisode(r.selected, 2, ACCESSIBLE, false, r.anchor);
    expect([...r.selected]).toEqual([]);
    expect([...clickEpisode(new Set([1]), 4, ACCESSIBLE, false, 1).selected]).toEqual([1]);
  });

  it("shift-click selects the accessible range from the anchor, skipping locked episodes", () => {
    const first = clickEpisode(new Set(), 2, ACCESSIBLE, false, null);
    const r = clickEpisode(first.selected, 6, ACCESSIBLE, true, first.anchor);
    expect([...r.selected].sort()).toEqual([2, 3, 5, 6]);
    expect(r.anchor).toBe(6);
  });

  it("shift-click from an unselected anchor clears the range", () => {
    const r = clickEpisode(new Set([1, 2, 3, 5]), 5, ACCESSIBLE, true, 1 /* anchor 1 selected */);
    expect(r.selected.has(5)).toBe(true);
    const cleared = clickEpisode(new Set([2, 3, 5]), 5, ACCESSIBLE, true, 1 /* anchor 1 not selected */);
    expect([...cleared.selected]).toEqual([]);
  });

  it("quick ranges and 'from episode N'", () => {
    expect([...rangeOf(3, 6, ACCESSIBLE)]).toEqual([3, 5, 6]);
    expect([...rangeOf(6, 3, ACCESSIBLE)]).toEqual([3, 5, 6]);
    expect([...fromEpisode(5, ACCESSIBLE)]).toEqual([5, 6, 7]);
  });

  it("a refresh never adds episodes the user didn't select", () => {
    expect([...keepAccessible(new Set([2, 4, 9]), ACCESSIBLE)]).toEqual([2]);
  });

  it("describes selections compactly", () => {
    expect(describeSelection(new Set())).toBe("No episodes selected");
    expect(describeSelection(new Set([3, 1, 2]))).toBe("E01–E03");
    expect(describeSelection(new Set([1, 3, 5]))).toBe("E01, E03, E05");
    expect(describeSelection(new Set([1, 3, 5, 7, 9]))).toBe("5 episodes");
  });
});
