// @vitest-environment jsdom
/* v1.9 download workflows: New Download, inline Cancel, duplicate starts, Single/Bulk, bulk queue, cross-tab Downloads. */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../App";
import { ActivityProvider } from "../../lib/activity";
import * as api from "../../lib/api";
import { ApiError } from "../../lib/api";
import type { AnalyseResponse, AppSettings } from "../../lib/types";
import { analysis, bulkAnalysis, bulkItem, job, urlBatch } from "../../test/fixtures";
import { BulkWorkspace } from "../bulk/BulkWorkspace";

vi.mock("../../lib/api", async (orig) => ({
  ...(await orig<typeof import("../../lib/api")>()),
  analyse: vi.fn(), startDownload: vi.fn(), getJob: vi.fn(), cancelJob: vi.fn(), getSettings: vi.fn(), getTikTokAccount: vi.fn(),
  getBatch: vi.fn(), batchAction: vi.fn(), itemAction: vi.fn(), createUrlBatch: vi.fn(), createBulkAnalysis: vi.fn(),
  getBulkAnalysis: vi.fn(), cancelBulkAnalysis: vi.fn(),
}));

const SETTINGS = {
  fxtwitter_fallback: false, fxtwitter_host: "api.fxtwitter.com", max_file_size_mb: 8192,
  file_size_limits: { min_mb: 256, max_mb: 65536, presets_mb: [2048, 8192, 16384] },
  batch_output_max_mb: 32768, batch_output_limits: { min_mb: 256, max_mb: 262144, presets_mb: [8192, 32768, 65536] },
  temp_storage: { auto_cleanup: true, retention_minutes: 30, usage_bytes: 0 }, saved: true,
} as AppSettings;

function xAnalysis(): AnalyseResponse {
  const a = analysis();
  return { ...a, platform: "x", provider: "yt-dlp",
    post: { ...a.post, url: "https://x.com/alice/status/1", post_id: "1", author_name: "Alice", author_handle: "alice", drama: null } };
}

beforeEach(() => {
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.getTikTokAccount).mockResolvedValue({ linked: false, cookie_count: 0, session_expires_at: null, expired: false, saved_at: null });
  vi.mocked(api.analyse).mockResolvedValue(xAnalysis());
  vi.mocked(api.startDownload).mockResolvedValue(job());
  vi.mocked(api.getJob).mockResolvedValue(job());
  vi.mocked(api.getBatch).mockResolvedValue(urlBatch());
  vi.mocked(api.createUrlBatch).mockResolvedValue(urlBatch());
  vi.mocked(api.createBulkAnalysis).mockResolvedValue(bulkAnalysis([bulkItem(1), bulkItem(2)]));
  vi.mocked(api.getBulkAnalysis).mockResolvedValue(bulkAnalysis([bulkItem(1), bulkItem(2)]));
});

const xInput = () => screen.getByLabelText("X / Twitter post URL");

async function analyseX(user: ReturnType<typeof userEvent.setup>) {
  await user.type(xInput(), "https://x.com/alice/status/1");
  await user.click(screen.getByRole("button", { name: "Analyse" }));
  await screen.findByRole("button", { name: /Download MP4/ });
}

describe("New Download", () => {
  it("clears the X workspace, focuses the URL field and leaves the running download in Downloads", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(screen.queryByRole("button", { name: "New Download" })).not.toBeInTheDocument();
    await analyseX(user);
    await user.click(screen.getByRole("button", { name: /Download MP4/ }));
    await screen.findByRole("button", { name: "Cancel download" });

    await user.click(screen.getAllByRole("button", { name: "New Download" })[0]);
    expect(xInput()).toHaveValue("");
    expect(xInput()).toHaveFocus();
    expect(screen.queryByRole("button", { name: /Download MP4/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel download" })).not.toBeInTheDocument();
    expect(api.cancelJob).not.toHaveBeenCalled(); // the download was not cancelled

    await user.click(screen.getByRole("button", { name: /^Downloads/ }));
    const drawer = screen.getByRole("dialog", { name: "Downloads" });
    expect(within(drawer).getByText("Alice")).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("keeps a completed, unsaved file reachable from Downloads", async () => {
    const { completedJob } = await import("../../test/fixtures");
    vi.mocked(api.startDownload).mockResolvedValue(completedJob("ready"));
    vi.mocked(api.getJob).mockResolvedValue(completedJob("ready"));
    const user = userEvent.setup();
    render(<App />);
    await analyseX(user);
    await user.click(screen.getByRole("button", { name: /Download MP4/ }));
    await screen.findByRole("button", { name: "Save Video" });
    await user.click(screen.getAllByRole("button", { name: "New Download" })[0]);
    await user.click(screen.getByRole("button", { name: /^Downloads/ }));
    expect(within(screen.getByRole("dialog", { name: "Downloads" })).getByRole("button", { name: "Save Video" })).toBeInTheDocument();
  });

  it("ignores an analysis that answers after the reset", async () => {
    let resolve!: (a: AnalyseResponse) => void;
    vi.mocked(api.analyse).mockImplementation(() => new Promise((r) => { resolve = r; }));
    const user = userEvent.setup();
    render(<App />);
    await user.type(xInput(), "https://x.com/alice/status/1");
    await user.click(screen.getByRole("button", { name: "Analyse" }));
    await user.click(await screen.findByRole("button", { name: "New Download" })); // offered while analysing
    await act(async () => resolve(xAnalysis()));
    expect(screen.queryByRole("button", { name: /Download MP4/ })).not.toBeInTheDocument();
    expect(xInput()).toHaveValue("");
  });

  it("reuses the same URL after a reset and doesn't touch the other tabs", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("tab", { name: /TikTok Videos/ }));
    const tiktok = screen.getByLabelText("TikTok video URL or share link");
    await user.type(tiktok, "https://www.tiktok.com/@u/video/1");
    await user.click(screen.getByRole("tab", { name: "X" }));
    await analyseX(user);
    await user.click(screen.getAllByRole("button", { name: "New Download" })[0]);
    await analyseX(user);
    expect(api.analyse).toHaveBeenCalledTimes(2);
    expect(tiktok).toHaveValue("https://www.tiktok.com/@u/video/1");
  });

  it("clears a failed analysis", async () => {
    vi.mocked(api.analyse).mockRejectedValue(new ApiError({ code: "not_found", message: "Gone.", retryable: false }, 404));
    const user = userEvent.setup();
    render(<App />);
    await user.type(xInput(), "https://x.com/alice/status/1");
    await user.click(screen.getByRole("button", { name: "Analyse" }));
    await screen.findByText("Analysis failed");
    await user.click(screen.getAllByRole("button", { name: "New Download" })[0]);
    expect(screen.queryByText("Analysis failed")).not.toBeInTheDocument();
  });
});

describe("Cancelling a single download", () => {
  it("offers Cancel beside the progress, also while processing, and shows the cancelled state", async () => {
    vi.mocked(api.startDownload).mockResolvedValue(job({ state: "processing", progress: { ...job().progress, stage: "Combining video and audio (lossless)" } }));
    vi.mocked(api.getJob).mockResolvedValue(job({ state: "processing" }));
    const cancelled = job({ state: "cancelled", error: { code: "download_cancelled", message: "The download was cancelled.", retryable: false } });
    vi.mocked(api.cancelJob).mockResolvedValue(cancelled);
    const user = userEvent.setup();
    render(<App />);
    await analyseX(user);
    await user.click(screen.getByRole("button", { name: /Download MP4/ }));
    vi.mocked(api.getJob).mockResolvedValue(cancelled);
    await user.click(await screen.findByRole("button", { name: "Cancel download" }));
    expect(api.cancelJob).toHaveBeenCalledWith("a".repeat(32));
    expect(await screen.findByText("Download cancelled")).toBeInTheDocument();
    // Retry is offered from Downloads for a cancelled job.
    await user.click(screen.getByRole("button", { name: /^Downloads/ }));
    expect(within(screen.getByRole("dialog", { name: "Downloads" })).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("follows the running job when the server refuses a duplicate start", async () => {
    vi.mocked(api.startDownload).mockRejectedValue(
      new ApiError({ code: "already_downloading", message: "Already downloading.", retryable: false, details: { job_id: "a".repeat(32) } }, 409));
    const user = userEvent.setup();
    render(<App />);
    await analyseX(user);
    await user.click(screen.getByRole("button", { name: /Download MP4/ }));
    expect(await screen.findByRole("button", { name: "Cancel download" })).toBeInTheDocument();
    expect(api.getJob).toHaveBeenCalledWith("a".repeat(32));
    expect(screen.queryByText("Couldn't start the download")).not.toBeInTheDocument();
  });
});

describe("Single and Bulk modes", () => {
  it("switches without losing the Single analysis", async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyseX(user);
    const modes = screen.getAllByRole("tablist", { name: "X download mode" })[0];
    await user.click(within(modes).getByRole("tab", { name: "Bulk" }));
    expect(screen.getByLabelText("X links, one per line")).toBeVisible();
    expect(xInput()).not.toBeVisible();
    await user.click(within(modes).getByRole("tab", { name: "Single" }));
    expect(screen.getByRole("button", { name: /Download MP4/ })).toBeVisible();
  });
});

function renderBulk() {
  return render(
    <ActivityProvider pollMs={30}>
      <BulkWorkspace platform="x" settings={SETTINGS} onSwitch={() => undefined} />
    </ActivityProvider>,
  );
}

describe("Bulk mode", () => {
  it("counts lines before analysing and refuses more than the limit", async () => {
    const user = userEvent.setup();
    renderBulk();
    const box = screen.getByLabelText("X links, one per line");
    await user.click(box);
    await user.paste("https://x.com/a/status/1\n\nhttps://twitter.com/b/status/1\nhttps://www.tiktok.com/@u/video/9\n");
    expect(screen.getByText(/3 lines · 1 to analyse · 1 duplicate · 1 not an X link/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open in TikTok Videos" })).toBeInTheDocument();
    await user.clear(box);
    await user.paste(Array.from({ length: 51 }, (_, i) => `https://x.com/a/status/${i + 1}`).join("\n"));
    expect(screen.getByText(/at most 50/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Analyse/ })).toBeDisabled();
  });

  it("analyses, lets the user deselect, and starts a ZIP batch with the chosen quality", async () => {
    vi.mocked(api.createBulkAnalysis).mockResolvedValue(bulkAnalysis([bulkItem(1), bulkItem(2),
      bulkItem(3, { state: "failed", analysis_id: null, error: { code: "not_found", message: "This post doesn't exist.", retryable: false } })]));
    const user = userEvent.setup();
    renderBulk();
    await user.click(screen.getByLabelText("X links, one per line"));
    await user.paste("https://x.com/u/status/101\n  https://x.com/u/status/102  \n\nhttps://x.com/u/status/103");
    await user.click(screen.getByRole("button", { name: "Analyse 3 videos" }));
    expect(api.createBulkAnalysis).toHaveBeenCalledWith("x", ["https://x.com/u/status/101", "https://x.com/u/status/102", "https://x.com/u/status/103"]);
    const review = await screen.findByRole("region", { name: "Review videos" });
    expect(within(review).getByText("This post doesn't exist.")).toBeInTheDocument();
    const first = within(review).getByRole("checkbox", { name: "Include Clip 1" });
    expect(first).toBeChecked();
    await user.click(first);
    await user.selectOptions(within(review).getByLabelText("Quality"), "480p");
    expect(within(review).getAllByText(/480p isn't available; used 360p/)).toHaveLength(2); // explained per video
    await user.click(within(review).getByRole("button", { name: "Download 1 video" }));
    expect(api.createUrlBatch).toHaveBeenCalledWith({ platform: "x", analysis_ids: [bulkItem(2).analysis_id], quality: "480p",
      output: "zip", concurrency: 2, allow_partial: false });
    expect(await screen.findByRole("region", { name: "Batch progress" })).toBeInTheDocument();
  });

  it("cancels one item, the whole batch, and resets without stopping the batch", async () => {
    vi.mocked(api.itemAction).mockResolvedValue(urlBatch());
    vi.mocked(api.batchAction).mockResolvedValue(urlBatch({ state: "cancelled" }));
    const user = userEvent.setup();
    renderBulk();
    await user.click(screen.getByLabelText("X links, one per line"));
    await user.paste("https://x.com/u/status/101\nhttps://x.com/u/status/102");
    await user.click(screen.getByRole("button", { name: "Analyse 2 videos" }));
    await user.click(await screen.findByRole("button", { name: "Download 2 videos" }));
    const progress = await screen.findByRole("region", { name: "Batch progress" });
    await user.click(within(progress).getByRole("button", { name: "Cancel #2" }));
    expect(api.itemAction).toHaveBeenCalledWith("e".repeat(32), 2, "cancel");
    await user.click(within(progress).getByRole("button", { name: "Cancel batch" }));
    expect(api.batchAction).toHaveBeenCalledWith("e".repeat(32), "cancel");

    await user.click(screen.getByRole("button", { name: "New Bulk Download" }));
    expect(screen.getByLabelText("X links, one per line")).toHaveValue("");
    expect(screen.queryByRole("region", { name: "Batch progress" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("X links, one per line")).toHaveFocus());
  });

  it("offers to build the ZIP from finished videos after a stop", async () => {
    vi.mocked(api.createUrlBatch).mockResolvedValue(urlBatch({ state: "needs_decision", stopped: true,
      counts: { pending: 0, resolving: 0, downloading: 0, processing: 0, ready: 0, saving: 0, saved: 0, downloaded: 1, failed: 0, skipped: 0, cancelled: 1 },
      episodes: urlBatch().episodes.map((e, i) => ({ ...e, state: i === 0 ? "downloaded" : "cancelled" })) }));
    vi.mocked(api.getBatch).mockImplementation(async () => (await vi.mocked(api.createUrlBatch).mock.results[0].value));
    vi.mocked(api.batchAction).mockResolvedValue(urlBatch({ state: "packaging" }));
    const user = userEvent.setup();
    renderBulk();
    await user.click(screen.getByLabelText("X links, one per line"));
    await user.paste("https://x.com/u/status/101\nhttps://x.com/u/status/102");
    await user.click(screen.getByRole("button", { name: "Analyse 2 videos" }));
    await user.click(await screen.findByRole("button", { name: "Download 2 videos" }));
    expect(await screen.findByText(/1 video finished before you cancelled/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Build ZIP from finished videos" }));
    expect(api.batchAction).toHaveBeenCalledWith("e".repeat(32), "continue");
  });
});

describe("Cross-tab activity", () => {
  it("starts an X bulk download, analyses on TikTok, then cancels the X batch from Downloads", async () => {
    vi.mocked(api.batchAction).mockResolvedValue(urlBatch({ state: "cancelled" }));
    const user = userEvent.setup();
    render(<App />);
    await user.click(within(screen.getAllByRole("tablist", { name: "X download mode" })[0]).getByRole("tab", { name: "Bulk" }));
    await user.click(screen.getByLabelText("X links, one per line"));
    await user.paste("https://x.com/u/status/101\nhttps://x.com/u/status/102");
    await user.click(screen.getByRole("button", { name: "Analyse 2 videos" }));
    await user.click(await screen.findByRole("button", { name: "Download 2 videos" }));

    await user.click(screen.getByRole("tab", { name: /TikTok Videos/ }));
    vi.mocked(api.analyse).mockResolvedValue({ ...xAnalysis(), platform: "tiktok" });
    await user.type(screen.getByLabelText("TikTok video URL or share link"), "https://www.tiktok.com/@u/video/1");
    await user.click(screen.getAllByRole("button", { name: "Analyse" }).find((b) => b.closest("[role=tabpanel]:not([hidden])"))!);
    await user.click(await screen.findByRole("button", { name: /Download MP4/ }));

    await user.click(screen.getByRole("button", { name: /^Downloads/ }));
    const drawer = screen.getByRole("dialog", { name: "Downloads" });
    const bulkItemEl = within(drawer).getByText("2 X videos").closest("li")!;
    expect(bulkItemEl).toHaveTextContent("X");
    expect(within(drawer).getAllByRole("listitem").length).toBeGreaterThanOrEqual(2);
    await user.click(within(bulkItemEl).getByRole("button", { name: "Cancel batch" }));
    expect(api.batchAction).toHaveBeenCalledWith("e".repeat(32), "cancel");
  });
});
