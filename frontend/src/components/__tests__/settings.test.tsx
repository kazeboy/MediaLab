// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../lib/api";
import type { AppSettings, TikTokAccount } from "../../lib/types";
import { SettingsDialog } from "../settings/SettingsDialog";

vi.mock("../../lib/api", async (orig) => ({ ...(await orig<typeof import("../../lib/api")>()), getSettings: vi.fn(), getTikTokAccount: vi.fn(),
  updateSettings: vi.fn(), linkTikTokAccount: vi.fn(), unlinkTikTokAccount: vi.fn() }));

const SETTINGS: AppSettings = {
  fxtwitter_fallback: false, fxtwitter_host: "api.fxtwitter.com", max_file_size_mb: 8192,
  file_size_limits: { min_mb: 256, max_mb: 65536, presets_mb: [2048, 8192, 16384] },
  batch_output_max_mb: 32768, batch_output_limits: { min_mb: 256, max_mb: 262144, presets_mb: [8192, 32768, 65536] },
  temp_storage: { auto_cleanup: true, retention_minutes: 30, usage_bytes: 0 }, saved: true,
};
const LINKED: TikTokAccount = { linked: true, cookie_count: 3, session_expires_at: "2027-05-11T00:00:00Z", expired: false, saved_at: null };

beforeEach(() => {
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.getTikTokAccount).mockResolvedValue(LINKED);
});

describe("Settings dialog", () => {
  it("is organised in sections and saves limits through the existing API", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    vi.mocked(api.updateSettings).mockResolvedValue({ ...SETTINGS, max_file_size_mb: 16384 });
    render(<SettingsDialog open settings={SETTINGS} onClose={() => undefined} onChange={onChange} tiktokAccount={LINKED} onTikTokAccountChange={() => undefined} />);
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs.join("|")).toMatch(/General.*Download limits.*TikTok account/);
    await user.click(screen.getByRole("tab", { name: /Download limits/ }));
    await user.click(screen.getAllByRole("button", { name: "16 GB" })[0]);
    expect(api.updateSettings).toHaveBeenCalledWith({ max_file_size_mb: 16384 });
    expect(await screen.findByText(/Video size limit set to 16 GB/)).toBeInTheDocument();
  });

  it("TikTok section shows status only, never cookie values, and hides instructions behind a disclosure", async () => {
    const user = userEvent.setup();
    render(<SettingsDialog open initialSection="account" settings={SETTINGS} onClose={() => undefined} onChange={() => undefined}
      tiktokAccount={LINKED} onTikTokAccountChange={() => undefined} />);
    expect(screen.getByText(/Linked · valid until/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
    const how = screen.getByText("How do I get cookies.txt?");
    expect(how.closest("details")).not.toHaveAttribute("open");
    expect(document.body.textContent).not.toMatch(/sessionid|sid_tt/);
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(api.unlinkTikTokAccount).toHaveBeenCalled();
  });
});
