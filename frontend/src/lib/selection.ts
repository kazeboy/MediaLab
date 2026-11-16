/* Pure episode-selection helpers (unit-tested). Only accessible episodes are ever selected. */

export type Selection = ReadonlySet<number>;

/**
 * A click on episode `n`. Without Shift it toggles `n`; with Shift (and an anchor) it applies the
 * anchor's new state to every accessible episode between the anchor and `n` (inclusive),
 * like file managers do. Returns the new selection and the new anchor.
 */
export function clickEpisode(
  selected: Selection,
  n: number,
  accessible: readonly number[],
  shift: boolean,
  anchor: number | null,
): { selected: Set<number>; anchor: number } {
  const next = new Set(selected);
  if (!accessible.includes(n)) return { selected: next, anchor: anchor ?? n };
  if (shift && anchor != null && anchor !== n) {
    const [lo, hi] = anchor < n ? [anchor, n] : [n, anchor];
    const select = !selected.has(n) || selected.has(anchor);
    for (const e of accessible) {
      if (e < lo || e > hi) continue;
      if (select) next.add(e);
      else next.delete(e);
    }
    return { selected: next, anchor: n };
  }
  if (next.has(n)) next.delete(n);
  else next.add(n);
  return { selected: next, anchor: n };
}

/** Accessible episodes in [from, to] (inclusive, either order). */
export function rangeOf(from: number, to: number, accessible: readonly number[]): Set<number> {
  const [lo, hi] = from <= to ? [from, to] : [to, from];
  return new Set(accessible.filter((e) => e >= lo && e <= hi));
}

/** Accessible episodes from `n` to the end. */
export function fromEpisode(n: number, accessible: readonly number[]): Set<number> {
  return new Set(accessible.filter((e) => e >= n));
}

/** Keep only episodes that are still accessible (e.g. after a series refresh). Never adds. */
export function keepAccessible(selected: Selection, accessible: readonly number[]): Set<number> {
  const ok = new Set(accessible);
  return new Set([...selected].filter((n) => ok.has(n)));
}

/** "E01–E10", "E01, E03, E05", "12 episodes", for compact summaries. */
export function describeSelection(selected: Selection): string {
  const nums = [...selected].sort((a, b) => a - b);
  if (nums.length === 0) return "No episodes selected";
  const pad = (n: number) => `E${String(n).padStart(2, "0")}`;
  if (nums.length === 1) return pad(nums[0]);
  const contiguous = nums[nums.length - 1] - nums[0] === nums.length - 1;
  if (contiguous) return `${pad(nums[0])}–${pad(nums[nums.length - 1])}`;
  if (nums.length <= 4) return nums.map(pad).join(", ");
  return `${nums.length} episodes`;
}
