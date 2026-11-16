// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../lib/api";
import { ActivityProvider } from "../../lib/activity";
import { analysis, batch, SERIES } from "../../test/fixtures";
import { SeriesView } from "../shortdrama/SeriesView";
import { ShortDramaWorkspace } from "../shortdrama/ShortDramaWorkspace";

vi.mock("../../lib/api", async (orig) => ({ ...(await orig<typeof import("../../lib/api")>()), getSeries: vi.fn(), createBatch: vi.fn(),
  getBatch: vi.fn(), analyse: vi.fn() }));

beforeEach(() => {
  vi.mocked(api.getSeries).mockResolvedValue(SERIES);
  vi.mocked(api.createBatch).mockResolvedValue(batch());
  vi.mocked(api.getBatch).mockResolvedValue(batch());
  try { localStorage.clear(); } catch { /* ignore */ }
});

function renderSeries() {
  return render(
    <ActivityProvider pollMs={50}>
      <SeriesView seriesId={SERIES.series_id} currentEpisode={2} active onOpenSettings={() => undefined} onBackToEpisode={() => undefined} />
    </ActivityProvider>,
  );
}
const box = (n: number) => screen.getByRole("checkbox", { name: new RegExp(`^Episode ${n}\\b`) });
const checked = () => [1, 2, 3, 4, 5, 6].filter((n) => (box(n) as HTMLInputElement).checked);

describe("Series view", () => {
  it("lists episodes in order, marks locked ones and preselects the current episode", async () => {
    renderSeries();
    await screen.findByRole("list", { name: "Episodes" });
    expect(screen.getAllByRole("checkbox").length).toBe(6);
    expect(box(4)).toBeDisabled();
    expect(screen.getByText("Locked for your account")).toBeInTheDocument();
    expect(checked()).toEqual([2]);
    expect(screen.getByText("1 episode selected")).toBeInTheDocument();
  });

  it("shift-click selects a range and skips locked episodes", async () => {
    const user = userEvent.setup();
    renderSeries();
    await screen.findByRole("list", { name: "Episodes" });
    await user.keyboard("{Shift>}");
    await user.click(box(6));
    await user.keyboard("{/Shift}");
    expect(checked()).toEqual([2, 3, 5, 6]);
  });

  it("select all accessible, clear, quick range and 'from N'", async () => {
    const user = userEvent.setup();
    renderSeries();
    await screen.findByRole("list", { name: "Episodes" });
    await user.click(screen.getByRole("button", { name: "Select all accessible" }));
    expect(checked()).toEqual([1, 2, 3, 5, 6]);
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(checked()).toEqual([]);
    await user.clear(screen.getByLabelText("From E"));
    await user.type(screen.getByLabelText("From E"), "3");
    await user.clear(screen.getByLabelText("to E"));
    await user.type(screen.getByLabelText("to E"), "5");
    await user.click(screen.getByRole("button", { name: "Select range" }));
    expect(checked()).toEqual([3, 5]);
    await user.click(screen.getByRole("button", { name: /From E3 to the end/ }));
    expect(checked()).toEqual([3, 5, 6]);
  });

  it("changing the output keeps the selection and is sent with the batch", async () => {
    const user = userEvent.setup();
    renderSeries();
    await screen.findByRole("list", { name: "Episodes" });
    await user.click(box(3));
    await user.selectOptions(screen.getByLabelText("Output format"), "merge");
    expect(checked()).toEqual([2, 3]);
    await user.click(screen.getByRole("button", { name: /^Download 2/ }));
    expect(api.createBatch).toHaveBeenCalledWith(expect.objectContaining({ series_id: SERIES.series_id, episodes: [2, 3], output: "merge", quality: "best" }));
    expect(await screen.findByRole("region", { name: "Batch progress" })).toBeInTheDocument();
  });

  it("options popover: strict needs a preferred quality; partial policy only for packaged output", async () => {
    const user = userEvent.setup();
    renderSeries();
    await screen.findByRole("list", { name: "Episodes" });
    await user.click(screen.getByRole("button", { name: "Options" }));
    const pop = screen.getByRole("dialog", { name: "Batch options" });
    expect(within(pop).getByRole("checkbox", { name: /Strict quality/ })).toBeDisabled();
    await user.selectOptions(within(pop).getByLabelText("Preferred quality"), "720p");
    expect(within(pop).getByRole("checkbox", { name: /Strict quality/ })).toBeEnabled();
    expect(within(pop).getByRole("checkbox", { name: /Continue if an episode fails/ })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Batch options" })).not.toBeInTheDocument();
  });
});

describe("Short Drama Episode / Series views", () => {
  it("analysing an episode offers Open series; switching views keeps the analysis", async () => {
    vi.mocked(api.analyse).mockResolvedValue(analysis());
    const user = userEvent.setup();
    render(
      <ActivityProvider pollMs={50}>
        <ShortDramaWorkspace settings={null} tiktokLinked incoming={null} onSwitch={() => undefined} onOpenSettings={() => undefined} />
      </ActivityProvider>,
    );
    await user.type(screen.getByLabelText("Short Drama episode link"), "https://vm.tiktok.com/ZNExample7/");
    await user.click(screen.getByRole("button", { name: "Analyse" }));
    await user.click(await screen.findByRole("button", { name: /Open series/ }));
    expect(screen.getByRole("tab", { name: "Series" })).toHaveAttribute("aria-selected", "true");
    await screen.findByRole("list", { name: "Episodes" });
    expect(api.getSeries).toHaveBeenCalledWith(SERIES.series_id);
    await user.click(screen.getByRole("tab", { name: "Episode" }));
    expect(screen.getByLabelText("Short Drama episode link")).toHaveValue("https://vm.tiktok.com/ZNExample7/");
    expect(screen.getByRole("heading", { name: /Episode 2/ })).toBeInTheDocument();
    expect(api.analyse).toHaveBeenCalledTimes(1); // no re-analysis
    await user.click(screen.getByRole("tab", { name: "Series" }));
    await waitFor(() => expect(api.getSeries).toHaveBeenCalledTimes(1)); // not reloaded
  });
});

describe("Batch access across Episode / Series views", () => {
  it("keeps a running batch and its Save action when switching views", async () => {
    const { batch: makeBatch } = await import("../../test/fixtures");
    vi.mocked(api.analyse).mockResolvedValue(analysis());
    vi.mocked(api.createBatch).mockResolvedValue(makeBatch({ state: "running" }));
    // First polls: still running; then the ZIP is ready.
    const ready = makeBatch({
      state: "ready", stage: "Ready to save", percent: 97,
      counts: { pending: 0, resolving: 0, downloading: 0, processing: 0, ready: 0, saving: 0, saved: 0, downloaded: 2, failed: 0, skipped: 0, cancelled: 0 },
      result: { file_id: "e".repeat(32), filename: "Show - E02-E03.zip", size_bytes: 2048, kind: "zip", method: "stored", reason: null,
        duration_seconds: null, included: [2, 3], omitted: [], width: null, height: null, video_codec: null, audio_codec: null,
        download_url: `/api/files/${"e".repeat(32)}`, delivery_state: "ready" },
    });
    vi.mocked(api.getBatch).mockResolvedValueOnce(makeBatch({ state: "running" })).mockResolvedValue(ready);
    const saveMod = await import("../../lib/save");
    const saveSpy = vi.spyOn(saveMod, "saveWithBrowser").mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(
      <ActivityProvider pollMs={30}>
        <ShortDramaWorkspace settings={null} tiktokLinked incoming={null} onSwitch={() => undefined} onOpenSettings={() => undefined} />
      </ActivityProvider>,
    );
    await user.type(screen.getByLabelText("Short Drama episode link"), "https://vm.tiktok.com/ZNExample7/");
    await user.click(screen.getByRole("button", { name: "Analyse" }));
    await user.click(await screen.findByRole("button", { name: /Open series/ }));
    await screen.findByRole("list", { name: "Episodes" });
    await user.click(box(3));
    await user.click(screen.getByRole("button", { name: /^Download 2/ }));
    expect(await screen.findByRole("region", { name: "Batch progress" })).toBeInTheDocument();
    // Selection is locked while the batch runs.
    expect(box(5)).toBeDisabled();

    // Switch to Episode while it runs, then back: the batch is still there and becomes ready.
    await user.click(screen.getByRole("tab", { name: "Episode" }));
    expect(screen.getByRole("heading", { name: /Episode 2/ })).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "Series" }));
    const progress = await screen.findByRole("region", { name: "Batch progress" });
    const saveZip = await within(progress).findByRole("button", { name: "Save ZIP" });
    await user.click(saveZip);
    expect(saveSpy).toHaveBeenCalledWith(`/api/files/${"e".repeat(32)}`, "Show - E02-E03.zip");
    expect(api.createBatch).toHaveBeenCalledTimes(1);
  });
});
