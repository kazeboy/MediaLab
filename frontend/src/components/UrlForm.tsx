import { useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { PLATFORM_INFO, detectPlatform, suggestedTab } from "../lib/platform";
import type { Platform } from "../lib/types";
import { Button } from "./ui";

interface Props {
  platform: Platform;
  url: string;
  onUrlChange: (url: string) => void;
  busy: boolean;
  onAnalyse: (url: string) => void;
  onSwitch: (platform: Platform, url: string) => void;
  notice?: ReactNode;
  /** The URL field, so the workspace can focus it (e.g. after New Download). */
  inputRef?: RefObject<HTMLInputElement | null>;
  /** Shown next to Analyse (New Download). */
  extraAction?: ReactNode;
}

export function UrlForm({ platform, url, onUrlChange, busy, onAnalyse, onSwitch, notice, inputRef, extraAction }: Props) {
  const [hint, setHint] = useState<string | null>(null);
  const info = PLATFORM_INFO[platform];
  const otherTab = suggestedTab(url, platform);

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = url.trim();
    if (!value) {
      setHint(`Paste a ${info.label} link first.`);
      return;
    }
    if (otherTab) return; // the switch suggestion below is already shown
    if (!detectPlatform(value)) {
      setHint("This link isn't recognised. Check it, or use the tab for its platform.");
      return;
    }
    setHint(null);
    onAnalyse(value);
  }

  const inputId = `url-${platform}`;
  return (
    <form onSubmit={submit} className="w-full" noValidate>
      <label htmlFor={inputId} className="mb-2 block text-sm font-medium text-muted">
        {info.inputLabel}
      </label>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          ref={inputRef}
          id={inputId}
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder={info.placeholder}
          value={url}
          onChange={(e) => {
            onUrlChange(e.target.value);
            if (hint) setHint(null);
          }}
          aria-invalid={hint ? true : undefined}
          aria-describedby={hint ? `${inputId}-hint` : undefined}
          className="min-h-12 min-w-0 flex-1 rounded-xl border border-line-strong bg-surface px-4 text-base text-fg shadow-sm placeholder:text-subtle focus:border-accent-line"
        />
        <Button type="submit" variant="primary" size="lg" busy={busy}>
          {busy ? "Analysing…" : "Analyse"}
        </Button>
        {extraAction}
      </div>
      {otherTab && (
        <div role="status" className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-accent-soft px-3 py-2 text-sm text-fg">
          <span>This looks like a {PLATFORM_INFO[otherTab].label} link.</span>
          <Button variant="primary" size="sm" onClick={() => onSwitch(otherTab, url.trim())}>
            Switch to {PLATFORM_INFO[otherTab].tab}
          </Button>
        </div>
      )}
      {hint && (
        <p id={`${inputId}-hint`} className="mt-2 text-sm text-orange-800 dark:text-orange-300">
          {hint}
        </p>
      )}
      {notice}
    </form>
  );
}
