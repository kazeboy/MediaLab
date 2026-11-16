// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ErrorAlert } from "../ErrorAlert";
import { Dialog, Tabs } from "../ui";

function TabsHarness() {
  const [v, setV] = useState("x");
  return (
    <Tabs label="Platform" idPrefix="p" value={v} onChange={setV}
      items={[{ id: "x", label: "X" }, { id: "tiktok", label: "TikTok Videos", shortLabel: "TikTok" }, { id: "sd", label: "TikTok Short Drama", shortLabel: "Short Drama" }]} />
  );
}

describe("Tabs (WAI-ARIA)", () => {
  it("uses a roving tabIndex and moves with arrows, Home and End", async () => {
    const user = userEvent.setup();
    render(<TabsHarness />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.tabIndex)).toEqual([0, -1, -1]);
    tabs[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveFocus();
    expect(tabs.map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
    await user.keyboard("{End}");
    expect(tabs[2]).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(tabs[0]).toHaveFocus(); // wraps
    await user.keyboard("{ArrowLeft}");
    expect(tabs[2]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Home}");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
  });

  it("renders a short label for small screens and the full label for larger ones", () => {
    render(<TabsHarness />);
    expect(screen.getByText("TikTok", { selector: "span" })).toHaveClass("sm:hidden");
    expect(screen.getByText("TikTok Videos")).toHaveClass("hidden", "sm:inline");
  });
});

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Open settings</button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Settings">
        <button>First</button>
        <button>Last</button>
      </Dialog>
    </>
  );
}

describe("Dialog", () => {
  it("traps focus, closes on Escape, restores focus and page scroll", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const opener = screen.getByRole("button", { name: "Open settings" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Settings" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(document.body.style.overflow).toBe("hidden");
    // Tab cycles within the dialog: Close → First → Last → Close …
    const close = screen.getByRole("button", { name: "Close" });
    close.focus();
    await user.tab();
    expect(screen.getByRole("button", { name: "First" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Last" })).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Last" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });
});

describe("ErrorAlert", () => {
  const error = { code: "auth_expired", message: "Your linked TikTok sign-in has expired.", action: "Re-link the account in Settings.",
    retryable: true, details: { series_id: "1" } };

  it("puts what happened and what to do first, technical details second", async () => {
    const onRetry = vi.fn();
    render(<ErrorAlert title="Analysis failed" error={error} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Your linked TikTok sign-in has expired.");
    expect(screen.getByText("Re-link the account in Settings.")).toBeVisible();
    const code = screen.getByText("auth_expired");
    expect(code.closest("details")).not.toHaveAttribute("open"); // in the collapsed disclosure
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("offers a Switch button for wrong-platform errors", async () => {
    const onSwitch = vi.fn();
    render(<ErrorAlert title="Analysis failed" onSwitch={onSwitch}
      error={{ code: "wrong_platform", message: "This is an X link.", retryable: false, details: { detected_platform: "x" } }} />);
    await userEvent.click(screen.getByRole("button", { name: "Switch to X" }));
    expect(onSwitch).toHaveBeenCalledWith("x");
  });
});
