// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import html from "../../../index.html?raw";
import { THEME_COLOR, THEME_KEY, useTheme } from "../theme";

/** The inline pre-render script from index.html, run exactly as the browser would. */
const inlineScript = html.match(/<script>([\s\S]*?)<\/script>/)![1];
const runInlineScript = () => new Function(inlineScript)();

function resetDocument() {
  delete document.documentElement.dataset.theme;
  document.head.innerHTML = '<meta name="theme-color" content="#0b0d10" />';
  localStorage.clear();
}

beforeEach(resetDocument);
afterEach(() => vi.restoreAllMocks());

describe("pre-render theme script (index.html)", () => {
  it("defaults to dark when nothing is saved, whatever the OS appearance", () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as never; // OS says light
    runInlineScript();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute("content", THEME_COLOR.dark);
  });

  it("applies a saved light preference before React renders", () => {
    localStorage.setItem(THEME_KEY, "light");
    runInlineScript();
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute("content", THEME_COLOR.light);
  });

  it("keeps a saved dark preference, ignores unknown values and survives blocked storage", () => {
    localStorage.setItem(THEME_KEY, "dark");
    runInlineScript();
    expect(document.documentElement.dataset.theme).toBe("dark");

    resetDocument();
    localStorage.setItem(THEME_KEY, "sepia");
    runInlineScript();
    expect(document.documentElement.dataset.theme).toBe("dark");

    resetDocument();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    runInlineScript();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("uses the same storage key and colours as lib/theme.ts", () => {
    expect(inlineScript).toContain(`"${THEME_KEY}"`);
    expect(inlineScript).toContain(THEME_COLOR.light);
    expect(html).toContain(`content="${THEME_COLOR.dark}"`);
  });
});

function Probe() {
  const { theme, toggle } = useTheme();
  return <button onClick={toggle}>{theme}</button>;
}

describe("useTheme", () => {
  it("toggles, applies the theme to <html> and remembers it across a reload", async () => {
    runInlineScript();
    const user = userEvent.setup();
    const { unmount } = render(<Probe />);
    expect(screen.getByRole("button")).toHaveTextContent("dark");

    await user.click(screen.getByRole("button"));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(THEME_KEY)).toBe("light");
    expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute("content", THEME_COLOR.light);

    // "Reload": fresh document state, inline script, new mount.
    unmount();
    delete document.documentElement.dataset.theme;
    runInlineScript();
    expect(document.documentElement.dataset.theme).toBe("light");
    render(<Probe />);
    expect(screen.getByRole("button")).toHaveTextContent("light");
  });

  it("still switches when storage can't be written", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    const user = userEvent.setup();
    render(<Probe />);
    await user.click(screen.getByRole("button"));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
