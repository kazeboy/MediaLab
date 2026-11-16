import { useEffect, useState } from "react";
import { ApiError, getSettings, getTikTokAccount, linkTikTokAccount, unlinkTikTokAccount, updateSettings } from "../../lib/api";
import { formatBytes, formatLimit } from "../../lib/format";
import type { AppSettings, SettingsPatch, TikTokAccount } from "../../lib/types";
import { Alert, Badge, Button, Disclosure, LoadingState, Tabs, tabPanelProps } from "../ui";
import { Dialog } from "../ui";

export type SettingsSection = "general" | "limits" | "account";
const MAX_COOKIE_FILE_BYTES = 1_000_000;

interface Props {
  open: boolean;
  initialSection?: SettingsSection;
  settings: AppSettings | null;
  onClose: () => void;
  onChange: (settings: AppSettings) => void;
  tiktokAccount: TikTokAccount | null;
  onTikTokAccountChange: (account: TikTokAccount) => void;
}

export function SettingsDialog({ open, initialSection = "general", settings, onClose, onChange, tiktokAccount, onTikTokAccountChange }: Props) {
  const [section, setSection] = useState<SettingsSection>(initialSection);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setSection(initialSection);
    setError(null);
    setNote(null);
    getSettings().then(onChange, () => undefined); // refresh temp usage etc.
    getTikTokAccount().then(onTikTokAccountChange, () => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialSection]);

  async function run(fn: () => Promise<void>, okNote: string, failNote: string) {
    setSaving(true);
    setError(null);
    setNote(null);
    try {
      await fn();
      setNote(okNote);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : failNote);
    } finally {
      setSaving(false);
    }
  }
  const save = (patch: SettingsPatch, okNote: string) =>
    run(async () => onChange(await updateSettings(patch)), okNote, "Could not save the settings.");

  return (
    <Dialog open={open} onClose={onClose} title="Settings" wide>
      {!settings ? (
        <LoadingState>Loading settings…</LoadingState>
      ) : (
        <div className="space-y-5">
          <Tabs<SettingsSection>
            variant="segmented"
            label="Settings sections"
            idPrefix="settings"
            value={section}
            onChange={setSection}
            items={[
              { id: "general", label: "General" },
              { id: "limits", label: "Download limits", shortLabel: "Limits" },
              { id: "account", label: "TikTok account", shortLabel: "TikTok" },
            ]}
          />
          <div role="status" aria-live="polite" className="min-h-0">
            {error && <Alert tone="error" title="Not saved">{error}</Alert>}
            {note && !error && <p className="text-sm font-medium text-emerald-700 dark:text-emerald-300">✓ {note}</p>}
          </div>

          <div {...tabPanelProps("settings", "general", section === "general")} className="space-y-4">
            <Row title="Temporary storage" description={`MediaLab deletes its copy as soon as your browser has saved a file. Unsaved files are deleted after ${settings.temp_storage.retention_minutes} minutes, and everything left over when MediaLab restarts.`}>
              <p className="text-sm">In use now: <strong className="tabular-nums">{formatBytes(settings.temp_storage.usage_bytes)}</strong></p>
            </Row>
            <Row title="Where files go" description="Your browser decides where saved files go (usually Downloads). Short Drama batches can save into a chosen folder in Chromium browsers.">
              <span />
            </Row>
            <Row title="Settings file" description={settings.saved ? "Saved on this Mac; these settings survive restarts." : "Using defaults (or .env values) until you change a setting here."}>
              <span />
            </Row>
          </div>

          <div {...tabPanelProps("settings", "limits", section === "limits")} className="space-y-6">
            <LimitPicker
              title="Maximum size per video"
              description="Per download, including each Short Drama episode. Downloads already running keep their limit."
              value={settings.max_file_size_mb}
              presets={settings.file_size_limits.presets_mb}
              min={settings.file_size_limits.min_mb}
              max={settings.file_size_limits.max_mb}
              disabled={saving}
              onPick={(mb) => void save({ max_file_size_mb: mb }, `Video size limit set to ${formatLimit(mb)}.`)}
            />
            <LimitPicker
              title="Maximum batch output size"
              description="The single ZIP or merged MP4 a Short Drama batch produces."
              value={settings.batch_output_max_mb}
              presets={settings.batch_output_limits.presets_mb}
              min={settings.batch_output_limits.min_mb}
              max={settings.batch_output_limits.max_mb}
              disabled={saving}
              onPick={(mb) => void save({ batch_output_max_mb: mb }, `Batch output limit set to ${formatLimit(mb)}.`)}
            />
            <Row title="FxTwitter fallback (X only)"
              description={<>When X returns no video, look the post up via FxTwitter, a third-party service. This sends <strong>X post IDs</strong> to <span className="font-mono">{settings.fxtwitter_host}</span>. Video files still come from X. Never used for TikTok.</>}>
              <Switch checked={settings.fxtwitter_fallback} disabled={saving} label="FxTwitter fallback"
                onChange={() => void save({ fxtwitter_fallback: !settings.fxtwitter_fallback },
                  settings.fxtwitter_fallback ? "FxTwitter fallback turned off." : "FxTwitter fallback turned on.")} />
            </Row>
          </div>

          <div {...tabPanelProps("settings", "account", section === "account")} className="space-y-4">
            <AccountSection
              account={tiktokAccount}
              disabled={saving}
              onLink={(file) => void run(async () => {
                if (file.size > MAX_COOKIE_FILE_BYTES) throw new Error("too large");
                onTikTokAccountChange(await linkTikTokAccount(await file.text()));
              }, "TikTok account linked for the Short Drama tab.", file.size > MAX_COOKIE_FILE_BYTES
                ? "That file is too large to be a cookies.txt export (limit 1 MB)." : "Could not link the TikTok account.")}
              onRemove={() => void run(async () => onTikTokAccountChange(await unlinkTikTokAccount()),
                "Removed MediaLab's copy of the TikTok cookies.", "Could not remove the TikTok account.")}
            />
          </div>
        </div>
      )}
    </Dialog>
  );
}

function Row({ title, description, children }: { title: string; description?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold">{title}</h3>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: () => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={onChange}
      className={`relative mt-0.5 inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors disabled:opacity-60 ${checked ? "bg-accent" : "bg-line-strong"}`}>
      <span className={`inline-block h-6 w-6 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-5.5" : "translate-x-0.5"}`} />
    </button>
  );
}

function LimitPicker({ title, description, value, presets, min, max, disabled, onPick }: {
  title: string; description: string; value: number; presets: number[]; min: number; max: number; disabled: boolean;
  onPick: (mb: number) => void;
}) {
  const [custom, setCustom] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const id = title.replace(/\W+/g, "-").toLowerCase();
  return (
    <fieldset>
      <legend className="text-sm font-semibold">{title}</legend>
      <p className="mt-1 text-sm text-muted">{description} Now: <strong>{formatLimit(value)}</strong>.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {presets.map((mb) => (
          <Button key={mb} size="sm" variant={value === mb ? "primary" : "secondary"} aria-pressed={value === mb} disabled={disabled} onClick={() => onPick(mb)}>
            {formatLimit(mb)}
          </Button>
        ))}
        <form className="flex items-center gap-2" onSubmit={(e) => {
          e.preventDefault();
          const mb = Math.round(Number(custom) * 1024);
          if (!Number.isFinite(mb) || mb < min || mb > max) {
            setHint(`Enter a size between ${formatLimit(min)} and ${formatLimit(max)}.`);
            return;
          }
          setHint(null);
          onPick(mb);
        }}>
          <label htmlFor={`${id}-custom`} className="sr-only">Custom size in GB</label>
          <input id={`${id}-custom`} type="number" inputMode="decimal" step="0.25" placeholder="GB" value={custom}
            onChange={(e) => setCustom(e.target.value)} className="min-h-9 w-20 rounded-lg border border-line-strong bg-surface px-2 text-sm" />
          <Button size="sm" type="submit" disabled={disabled || !custom}>Set</Button>
        </form>
      </div>
      {hint && <p className="mt-1 text-xs text-orange-800 dark:text-orange-300">{hint}</p>}
    </fieldset>
  );
}

function AccountSection({ account, disabled, onLink, onRemove }: {
  account: TikTokAccount | null; disabled: boolean; onLink: (f: File) => void; onRemove: () => void;
}) {
  const linked = !!account?.linked;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {!linked && <Badge>Not linked</Badge>}
        {linked && account!.expired && <Badge tone="warn">Sign-in expired. Export the cookies again.</Badge>}
        {linked && !account!.expired && (
          <Badge tone="success">
            Linked{account!.session_expires_at ? ` · valid until ${new Date(account!.session_expires_at).toLocaleDateString()}` : ""}
          </Badge>
        )}
      </div>
      <p className="text-sm text-muted">
        Used only by the Short Drama tab to watch episodes as you. MediaLab never asks for your password and keeps only tiktok.com cookies, readable only by you.
      </p>
      <div className="flex flex-wrap gap-2">
        <label className={`inline-flex min-h-10 cursor-pointer items-center rounded-xl border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-surface-muted ${disabled ? "pointer-events-none opacity-50" : ""}`}>
          {linked ? "Replace cookies.txt…" : "Choose cookies.txt…"}
          <input type="file" accept=".txt,text/plain" className="sr-only" aria-label="TikTok cookies.txt file" disabled={disabled}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onLink(f);
            }} />
        </label>
        {linked && <Button variant="danger" disabled={disabled} onClick={onRemove}>Remove</Button>}
      </div>
      <Disclosure summary="How do I get cookies.txt?">
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
          <li>Sign in to tiktok.com in your usual browser.</li>
          <li>Export that site's cookies in Netscape <span className="font-mono">cookies.txt</span> format, e.g. with a "cookies.txt" browser extension set to the current site only.</li>
          <li>Choose the file here, then delete the exported file.</li>
        </ol>
        <p className="mt-2 text-sm text-muted">
          Anyone with this file can act as your TikTok account. <strong>Remove</strong> deletes MediaLab's copy but doesn't sign you out at TikTok. Sign out on tiktok.com to end the session. Details: <span className="font-mono">docs/SECURITY.md</span>.
        </p>
      </Disclosure>
    </>
  );
}
