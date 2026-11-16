// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../App";
import * as api from "../../lib/api";
import * as save from "../../lib/save";
import type { AnalyseResponse, AppSettings } from "../../lib/types";
import { analysis, completedJob, job } from "../../test/fixtures";

vi.mock("../../lib/api", async (orig) => ({
  ...(await orig<typeof import("../../lib/api")>()),
  analyse: vi.fn(), startDownload: vi.fn(), getJob: vi.fn(), cancelJob: vi.fn(),
  getSettings: vi.fn(), getTikTokAccount: vi.fn(), getBatch: vi.fn(),
}));
vi.mock("../../lib/save", async (orig) => ({ ...(await orig<typeof import("../../lib/save")>()), saveWithBrowser: vi.fn() }));

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
});

/** Analyse + download on the X tab, then move to the TikTok Videos tab with the keyboard. */
async function downloadOnXThenSwitchTab(user: ReturnType<typeof userEvent.setup>) {
  render(<App />);
  await user.type(screen.getByLabelText("X / Twitter post URL"), "https://x.com/alice/status/1");
  await user.click(screen.getByRole("button", { name: "Analyse" }));
  await user.click(await screen.findByRole("button", { name: /Download MP4/ }));
  const xTab = screen.getByRole("tab", { name: "X" });
  xTab.focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: /TikTok Videos/ })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("X / Twitter post URL")).not.toBeVisible(); // X panel hidden, not unmounted
}

describe("Downloads drawer from the header", () => {
  it("opens from the header, closes with Escape and returns focus to the Downloads button", async () => {
    const user = userEvent.setup();
    render(<App />);
    const button = screen.getByRole("button", { name: /^Downloads/ });
    await user.click(button);
    const drawer = screen.getByRole("dialog", { name: "Downloads" });
    expect(within(drawer).getByText("Nothing here yet")).toBeInTheDocument();
    expect(drawer).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Downloads" })).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("Save Video works from another platform tab", async () => {
    vi.mocked(api.getJob).mockResolvedValue(completedJob("ready"));
    const user = userEvent.setup();
    await downloadOnXThenSwitchTab(user);
    const header = screen.getByRole("button", { name: /^Downloads/ });
    await waitFor(() => expect(header).toHaveAccessibleName(/1 need attention/));
    await user.click(header);
    const drawer = screen.getByRole("dialog", { name: "Downloads" });
    const item = within(drawer).getByText("Alice").closest("li")!;
    expect(item).toHaveTextContent("X");
    await user.click(within(item).getByRole("button", { name: "Save Video" }));
    expect(save.saveWithBrowser).toHaveBeenCalledWith(`/api/files/${"f".repeat(32)}`, "Show - E02.mp4");
  });

  it("Cancel works from another platform tab", async () => {
    vi.mocked(api.getJob).mockResolvedValue(job());
    vi.mocked(api.cancelJob).mockResolvedValue(job({ state: "failed", error: { code: "download_cancelled", message: "The download was cancelled.", retryable: false } }));
    const user = userEvent.setup();
    await downloadOnXThenSwitchTab(user);
    await user.click(screen.getByRole("button", { name: /^Downloads/ }));
    await user.click(within(screen.getByRole("dialog", { name: "Downloads" })).getByRole("button", { name: "Cancel" }));
    expect(api.cancelJob).toHaveBeenCalledWith("a".repeat(32));
  });

  it("Retry works from another platform tab", async () => {
    vi.mocked(api.getJob).mockResolvedValue(job({ state: "failed", error: { code: "download_interrupted", message: "The download was interrupted.", retryable: true } }));
    const user = userEvent.setup();
    await downloadOnXThenSwitchTab(user);
    await user.click(screen.getByRole("button", { name: /^Downloads/ }));
    await user.click(await within(screen.getByRole("dialog", { name: "Downloads" })).findByRole("button", { name: "Retry" }));
    expect(api.startDownload).toHaveBeenCalledTimes(2);
  });
});

describe("Header branding", () => {
  it("names the app 'MediaLab' once, with the emblem hidden from assistive technology", () => {
    render(<App />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveAccessibleName("MediaLab");
    const mark = document.querySelector("header svg[viewBox='0 0 64 64']");
    expect(mark).toHaveAttribute("aria-hidden", "true");
  });
});

describe("Theme toggle in the header", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.dataset.theme = "dark"; // as set by index.html with no saved choice
  });

  it("starts dark, offers light with a sun, switches by click and keyboard, and persists", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<App />);
    const toggle = screen.getByRole("button", { name: "Switch to light theme" });
    expect(toggle).toHaveAttribute("title", "Switch to light theme");
    expect(document.documentElement.dataset.theme).toBe("dark");

    await user.click(toggle);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("medialab.theme")).toBe("light");
    expect(toggle).toHaveAccessibleName("Switch to dark theme");

    toggle.focus();
    await user.keyboard("{Enter}");
    expect(document.documentElement.dataset.theme).toBe("dark");
    await user.keyboard(" ");
    expect(document.documentElement.dataset.theme).toBe("light");

    unmount();
    render(<App />);
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeInTheDocument();
  });

  it("sits next to the Settings button", () => {
    render(<App />);
    const toggle = screen.getByRole("button", { name: /Switch to (light|dark) theme/ });
    expect(toggle.nextElementSibling).toBe(screen.getByRole("button", { name: "Settings" }));
  });
});

describe("Settings dialog from the header", () => {
  it("returns focus to the Settings button and supports keyboard section navigation", async () => {
    const user = userEvent.setup();
    render(<App />);
    const gear = screen.getByRole("button", { name: "Settings" });
    await user.click(gear);
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    const general = within(dialog).getByRole("tab", { name: "General" });
    general.focus();
    await user.keyboard("{ArrowRight}");
    expect(within(dialog).getByRole("tab", { name: /Download limits/ })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Escape}");
    expect(gear).toHaveFocus();
  });
});
