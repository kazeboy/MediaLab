// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../lib/api";
import { ActivityProvider, useActivity } from "../../lib/activity";
import * as save from "../../lib/save";
import { completedJob, job } from "../../test/fixtures";
import { DownloadsDrawer } from "../downloads/DownloadsDrawer";

vi.mock("../../lib/api", async (orig) => ({ ...(await orig<typeof import("../../lib/api")>()), startDownload: vi.fn(), getJob: vi.fn(),
  cancelJob: vi.fn(), getBatch: vi.fn() }));
vi.mock("../../lib/save", async (orig) => ({ ...(await orig<typeof import("../../lib/save")>()), saveWithBrowser: vi.fn() }));

let start!: () => Promise<string>;
function Starter() {
  const activity = useActivity();
  start = () => activity.startJob({ platform: "x", title: "Post by Alice", analysisId: "c".repeat(32), videoIndex: 1, optionId: "best" });
  return null;
}

function renderDrawer() {
  return render(
    <ActivityProvider pollMs={20}>
      <Starter />
      <DownloadsDrawer open onClose={() => undefined} />
    </ActivityProvider>,
  );
}

describe("Downloads drawer + activity registry", () => {
  beforeEach(() => vi.mocked(api.startDownload).mockResolvedValue(job()));

  it("shows an empty state", () => {
    renderDrawer();
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
  });

  it("follows a job via polling, puts 'ready to save' first and saves it", async () => {
    vi.mocked(api.getJob).mockResolvedValue(completedJob("ready"));
    renderDrawer();
    await act(() => start());
    const attention = await screen.findByRole("heading", { name: "Needs attention" });
    const item = within(attention.parentElement!).getByText("Post by Alice").closest("li")!;
    expect(item).toHaveTextContent("Ready to save");
    await userEvent.click(within(item).getByRole("button", { name: "Save Video" }));
    expect(save.saveWithBrowser).toHaveBeenCalledWith(`/api/files/${"f".repeat(32)}`, "Show - E02.mp4");
  });

  it("offers Retry for a failed job and restarts it with the same request", async () => {
    vi.mocked(api.getJob).mockResolvedValue(job({ state: "failed", error: { code: "cdn_url_expired", message: "The CDN refused the link.", retryable: true } }));
    renderDrawer();
    await act(() => start());
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(api.startDownload).toHaveBeenCalledTimes(2);
    expect(api.startDownload).toHaveBeenLastCalledWith("c".repeat(32), 1, "best");
  });

  it("offers Cancel while downloading", async () => {
    vi.mocked(api.getJob).mockResolvedValue(job());
    vi.mocked(api.cancelJob).mockResolvedValue(job({ state: "failed", error: { code: "download_cancelled", message: "The download was cancelled.", retryable: false } }));
    renderDrawer();
    await act(() => start());
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(api.cancelJob).toHaveBeenCalledWith("a".repeat(32));
  });

  it("marks entries the backend no longer knows (after a restart) instead of pretending", async () => {
    vi.mocked(api.getJob).mockRejectedValue(new api.ApiError({ code: "job_not_found", message: "Download job not found." }, 404));
    renderDrawer();
    await act(() => start());
    await waitFor(() => expect(screen.getByText(/No longer available/)).toBeInTheDocument());
  });
});
