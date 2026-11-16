# Frontend design system (v1.8.1; download workflows v1.9)

The rules and building blocks behind MediaLab's UI. Everything here describes the code as it is: tokens live in `frontend/src/index.css`, components in `frontend/src/components/ui/` (`primitives.tsx`, `interactive.tsx`, re-exported from `ui/index.ts`), the logo in `frontend/src/components/brand/Logo.tsx` and `frontend/public/brand/`, and cross-tab activity in `frontend/src/lib/activity.tsx`.

v1.7 introduced the structure (tokens, kit, navigation); v1.8 replaced the indigo identity with MediaLab's own black, charcoal and amber identity and a custom logo, without changing any interaction or workflow.

## 1. Principles

1. **One task per screen area.** Each area has at most one primary (filled amber) button; everything else is secondary or ghost.
2. **Summary first, detail on demand.** Progress, errors and options show a one-line summary; codes, format tables, ranges and how-tos sit behind a disclosure.
3. **State is always text.** Colour and icons are secondary cues; every badge, progress bar and episode state has a readable label.
4. **Nothing gets lost.** Every job and batch is visible from every tab (Downloads drawer). Switching tabs or views never unmounts work in progress or hides its Save button.
5. **Honest labels.** The UI says what really happened ("Video copied · audio converted to AAC", "joined without re-encoding", omitted episodes) and never shows 100 % before verification.
6. **Same component, same behaviour.** Every new screen uses the `ui` kit; no ad-hoc button, dialog or tab styles.
7. **Amber means "act here" or "selected", nothing else.** Success stays green, errors red, warnings orange (a distinct, redder hue with dark text, always with words). The logo's bright orange `#F97316` isn't used in the interface.
8. **Cinematic, not flashy.** Near-black and charcoal surfaces, hierarchy from surface steps and hairline borders, small shadows only on floating layers; no gradients, glow, glass/blur or decorative animation.

## 2. Visual identity

### Palette

| Role | Value | Notes |
|---|---|---|
| Primary amber | `#FFB300` | Fills only: primary buttons, active tab, progress, toggles, checkbox/radio accent |
| Secondary orange | `#F97316` | The logo's back layer only |
| Ink (dark canvas, emblem detail) | `#0B0D10` | Dark page background; sprockets and waveform in the emblem; text on amber in dark mode |
| Dark card | `#171A20` | Dark surfaces |
| Primary text (dark) | `#F5F5F4` | |

Dark mode is the flagship and the **default for everyone**; the light theme uses neutral white and cool-grey surfaces (no cream or beige) with the same amber accents, so both feel like one product.

### Logo

The emblem is an amber film frame (four sprocket holes top and bottom) carrying a five-bar audio waveform, layered over an orange frame offset up and to the right. It suggests media *processing* (layered sources, forward motion) rather than a play button. The wordmark is **Media** in the text colour and **Lab** in amber, set in the system sans-serif at extra-bold weight (no web font).

| Asset | File | Use |
|---|---|---|
| Emblem, React | `components/brand/Logo.tsx` → `LogoMark` | App header (40–44 px); decorative (`aria-hidden`), the `h1` carries the name |
| Wordmark, React | `Logo.tsx` → `Wordmark` | App header; "Lab" uses `--wordmark-lab` (amber in dark, `#B06D00` in light) |
| Emblem | `public/brand/medialab-mark.svg` | ≥ 40 px |
| Emblem, small | `public/brand/medialab-mark-small.svg` | ≤ 32 px: three larger sprockets, four thicker bars (same silhouette) |
| Favicon | `public/favicon.svg`, `public/favicon.ico` (16 + 32 px) | The emblem redrawn on a 16 px grid (two frames, three sprockets per row, four 1 px bars) so it stays sharp in a browser tab; transparent, works on light and dark browser chrome. Linked from `index.html` as `/favicon.ico?v=2` and `/favicon.svg?v=2` (see below) |
| Horizontal logo, dark background | `public/brand/medialab-logo-on-dark.svg` | "Media" `#F5F5F4`, "Lab" `#FFB300` |
| Horizontal logo, light background | `public/brand/medialab-logo-on-light.svg` | "Media" `#111318`, "Lab" `#B06D00` (4.2:1 on white; amber itself would be 1.8:1) |
| Application icon | `public/brand/medialab-app-icon.svg`, `medialab-app-icon-512.png`, `public/apple-touch-icon.png` (180 px) | Emblem on an ink rounded square; PNGs rendered from the SVG with headless Chrome |

Rules: keep the emblem's own colours on any background (it carries its own contrast); don't recolour, rotate, outline or add effects; keep clear space of at least a quarter of the emblem's width; use the small variant at 32 px and below. The SVG wordmarks use `<text>` with the system font stack, so their exact glyphs depend on the viewer's fonts. `Logo.tsx` and the SVG files share the same geometry and must be changed together.

## 3. Colour tokens

Semantic colours are CSS variables in `index.css`: `:root` holds the dark theme, `:root[data-theme="light"]` the light one (see §3.1). They are exposed to Tailwind v4 through `@theme inline`. Components use only these utilities (plus the status palettes below); there are no `brand-*`/`indigo-*` utilities any more.

| Token (CSS var) | Utility | Light | Dark | Use |
|---|---|---|---|---|
| `--canvas` | `bg-canvas` (`body`) | `#f4f5f7` cool grey | `#0b0d10` near-black | Page background |
| `--surface` | `bg-surface` | `#ffffff` | `#171a20` charcoal | Cards, dialogs, drawers, sticky bar, inputs |
| `--surface-muted` | `bg-surface-muted` | `#eef0f3` | `#20242c` | Hover, segmented track, neutral badges, progress track |
| `--line` | `border-line` | `#e3e6ea` | `#262a33` | Card and divider borders |
| `--line-strong` | `border-line-strong` | `#cdd2d9` | `#3a3f4a` | Inputs, secondary buttons, toggle track (off) |
| `--text` | `text-fg` | `#111318` | `#f5f5f4` | Body text |
| `--text-muted` | `text-muted` | `#4b5260` | `#c8c5c0` | Labels, secondary text |
| `--text-subtle` | `text-subtle` | `#5c6370` | `#a19d96` | Hints, metadata |
| `--accent` | `bg-accent` | `#ffb300` | `#ffb300` | Primary buttons, active tab, progress fill, toggle on, form-control accent |
| `--accent-hover` | `hover:bg-accent-hover` | `#f2a600` | `#ffc233` | Primary button hover |
| `--on-accent` | `text-on-accent` | `#111318` | `#0b0d10` | Text and icons on amber |
| `--accent-text` | `text-accent-fg` | `#8a5100` | `#ffb300` | Amber used as text (links, accent badges) |
| `--accent-soft` | `bg-accent-soft` | `#fff3d1` | amber 10 % | Selected episode rows and quality cards, accent badges, URL notices |
| `--accent-line` | `border-accent-line`, `ring-accent-line` | `#e9a100` | amber 55 % | Selected borders, active segment ring, focused input border |
| `--focus` | focus outline | `#b45309` | `#ffb300` | `:focus-visible` ring (2 px, offset 2 px) |
| `--scrim` | `bg-scrim` | `#111318` 45 % | black 60 % | Dialog/drawer backdrop |
| `--wordmark-lab` | `text-wordmark-lab` | `#b06d00` | `#ffb300` | "Lab" in the wordmark only |

**Status palettes** (Badge, Alert, inline hints) keep their meaning and are deliberately *not* amber: `success` emerald, `danger` red, `warn` orange (`orange-800` text on `orange-50/100` in light, `orange-300` on a 15 % tint in dark), `neutral`, and `accent` (amber, for "selected/your account" rather than status). Completed files sit in a green success card; their **Save** button is the amber primary action.

### Contrast decisions (measured)

| Pair | Ratio | Decision |
|---|---|---|
| White on amber `#FFB300` | 1.79:1 | **Never used.** Text on amber is near-black |
| `#0B0D10` / `#111318` on amber | 10.8:1 / 10.4:1 | Primary buttons, active tab, header badge |
| Amber on white | 1.79:1 | Never used as light-mode text; `--accent-text` `#8A5100` instead (6.5:1 on white, 5.7:1 on `#EEF0F3`) |
| Amber on `#171A20` / `#20242C` | 9.7:1 / 8.7:1 | Amber text is fine in dark mode |
| Focus ring `#B45309` on `#F4F5F7` / white | 4.6:1 / 5.0:1 | Light-mode focus (amber would fail the 3:1 non-text minimum) |
| `--text-subtle` light / dark on `surface-muted` | 5.3:1 / 5.8:1 | Smallest text everywhere |
| "Lab" `#B06D00` on white / on `#F4F5F7` | 4.2:1 / 3.8:1 | Large bold text (needs 3:1) |

The v1.8 audit (see [TESTING.md](TESTING.md#visual-and-accessibility-audit)) measured every visible text node in every view at 1600, 1280, 768 and 375 px with the final cool-grey light palette: no failures; lowest body-text ratio 5.3:1 (light) and 5.33:1 (dark); lowest overall 3.82:1 for the large bold "Lab" of the light-mode wordmark (needs 3:1).

### 3.1 Theme selection and the header toggle

| Rule | Implementation |
|---|---|
| Dark by default, for every new user, regardless of the macOS/browser appearance | `:root` = dark tokens; no `prefers-color-scheme` rules; `color-scheme: dark` |
| Light only when chosen | `<html data-theme="light">` switches tokens and `color-scheme: light`; Tailwind's `dark:` variant is redefined as `html:not([data-theme="light"])` (`@custom-variant` in `index.css`) |
| Remembered | `localStorage["medialab.theme"]` = `"dark"` or `"light"` (written only when the user toggles); any other value or blocked storage means dark |
| No flash | An inline script in `index.html` sets `data-theme` and the `theme-color` meta before the stylesheet and React load; an inline `<style>` paints the page colour of that theme on the very first frame |
| Toggle | Header, immediately left of Settings: a **sun** in dark mode ("Switch to light theme"), a **moon** in light mode ("Switch to dark theme"); the label is both `aria-label` and `title` tooltip; a native button, so Tab, Enter and Space work; same 40 px ghost icon-button style as Settings |
| Other tabs | `useTheme` (`lib/theme.ts`) follows `storage` events, so another open MediaLab tab switches too |

The inline script and `lib/theme.ts` share the key, the default and the `theme-color` values (`#0b0d10` / `#f4f5f7`); `lib/__tests__/theme.test.tsx` runs the script from `index.html` and checks they match.

**Favicon cache-busting.** v1.6 served a purple play button at the same `/favicon.svg` URL. Browsers keep favicons in a separate, long-lived icon cache keyed by URL, so after v1.8 replaced the file in place some tabs kept showing the purple icon even though the server returned the amber one. The icon links therefore carry `?v=2`; bump it whenever the favicon artwork changes. `favicon.ico` also gives browsers that probe `/favicon.ico` (previously a 404) the right icon. `src/__tests__/brand-assets.test.ts` checks the links, the files and that the old colour is gone.

## 4. Typography

Two typefaces since v1.8.1, both self-hosted:

| Role | Typeface | Weights | Token / utility | Used for |
|---|---|---|---|---|
| Headings and titles | **Manrope** | 600 section headings; 700 major titles | `--font-heading` / `font-heading` | `h1`–`h3` and `legend` (base layer): video and series titles, dialog and drawer titles (700); "Episodes", "Quality", Settings sections, drawer groups (600); the sticky bar's "n episodes selected" summary |
| Body and controls | **DM Sans** | 400 body; 500 labels; 600 buttons, tabs, emphasis | `--font-sans` (the default) | Everything else: buttons, tabs, labels, inputs and placeholders, descriptions, helper text, tooltips, episode rows, status and error text, Settings, the Downloads drawer |
| Technical values | System monospace | 400 | `font-mono` | Error codes, format IDs, episode codes (E01), hosts, file names in technical details |
| Wordmark | System sans-serif (unchanged) | 800 | `--font-wordmark` / `font-wordmark` | "Media**Lab**" only, so the logo stays independent of the UI fonts |

- **Files:** `frontend/public/fonts/`: WOFF2 for the five weights above, each in a Latin and a Latin Extended subset (10 files, 128 KB in total; a page normally loads only the five Latin files, about 71 KB). Taken from Fontsource 5.3.0 (`@fontsource/manrope`, `@fontsource/dm-sans`), which repackages the Google Fonts builds. No CDN: nothing is fetched from Google Fonts or elsewhere.
- **Licence:** both fonts are under the SIL Open Font License 1.1 (redistribution and bundling allowed; the fonts may not be sold on their own). The licence texts with the copyright lines ship next to the files: `fonts/OFL-Manrope.txt` and `fonts/OFL-DMSans.txt`.
- **Loading:** `@font-face` rules in `src/index.css` with `font-display: swap` (text is never invisible) and `unicode-range`, so other scripts such as Chinese or Japanese drama titles fall back to the system font per character. `index.html` preloads the five Latin files, so they arrive with the page; measured layout shift on load 0.002 (the "good" threshold is 0.1).
- **Fallback:** if a file fails, text uses the previous system stack (`--font-system`).
- **Weights not loaded** (DM Sans 700, Manrope 400/500) are never requested: `strong`/`b` are set to 600, and the header badge uses `font-semibold`.
- Sizes: `text-xs` for badges and metadata, `text-sm` for most UI text, buttons and labels, `text-base` for large buttons, `text-lg` for dialog titles and section headings, and `text-xl`/`text-2xl` for the app title.
- Weight: `font-bold` for major titles (video, series, dialog); `font-semibold` for section headings, buttons, tabs and card titles; `font-medium` for labels; otherwise normal. No all-caps except the small drawer and batch group labels.
- Numbers that change (bytes, ETA, episode codes) use the default figures; filenames and codes use `font-mono` only inside technical details.
- **Punctuation:** MediaLab's own copy uses no em dashes. Rewrite with a full stop, comma, colon or parentheses ("Sign-in expired. Export the cookies again."; "Paused: 3 of 10 downloaded"). Empty table cells say "unknown" or "none". Titles and descriptions from X or TikTok are shown exactly as received. `src/__tests__/copy-punctuation.test.ts` (frontend source, README, CHANGELOG, docs) and `backend/tests/test_copy_punctuation.py` enforce this.
- Long titles truncate on one line (`truncate`, `min-w-0` on flex children). Descriptions use `line-clamp`. Nothing scrolls horizontally.

## 5. Spacing and shape

- Tailwind's 4 px scale. The page column is `max-w-4xl` with `px-4`; cards use `p-5` (`sm:p-6`); dialog bodies use `px-5 py-4`.
- Vertical rhythm: `space-y-4`/`gap-4` between cards, `gap-2`/`gap-3` inside them.
- Radii: `rounded-2xl` for cards, dialogs and the tab bar; `rounded-xl` for md/lg buttons, tabs and alerts; `rounded-lg` for small buttons and inputs; `rounded-md` for badges.
- Elevation: hierarchy comes from surface steps (canvas → surface → surface-muted) and hairline borders. `shadow-sm` on cards (barely visible in dark mode); `shadow-lg`/`shadow-xl` only for floating layers (sticky bar on wide screens, popovers, dialogs). No blur or translucency: the sticky bar is solid `bg-surface`.

## 6. Shared components (`components/ui`)

| Component | Notes |
|---|---|
| `Button` | Variants `primary` (amber fill, dark text: Analyse, Download, Save Video/ZIP), `secondary` (default), `ghost`, `danger`, `success` (emerald-700, kept in the kit but no longer used for Save); sizes `sm` (min-h 36 px), `md` (40 px), `lg` (48 px). `busy` shows a spinner and disables the button with `aria-busy`. `icon` goes before the label. |
| `Card` | The content container (`section` by default). |
| `Badge` | Short status text with a `tone`. |
| `Alert` | `error` (role `alert`), `success`, `info`, `warn` (role `status`), with a title and an optional body. Error codes appear in `ErrorAlert` under "Technical details". |
| `Disclosure` | `details/summary` with a rotating chevron; the summary is at least 36 px tall. Used for "Select a range", "Technical details", "Finished", "Source details" and "How do I get cookies.txt?". |
| `ProgressBar` | `role="progressbar"` with a label. `value=null` gives an indeterminate animation. |
| `Spinner`, `LoadingState`, `EmptyState` | Loading and empty patterns (`LoadingState` is `role="status"`). |
| `Checkbox`, `SelectField` | A label wraps the control, so the whole row is the hit target. |
| Icons | `DownloadIcon`, `CloseIcon`, `ChevronIcon`, `RetryIcon`, `FolderIcon`, `SlidersIcon`, `FilmIcon`, `InboxIcon`, `GearIcon`: 24×24 strokes, `aria-hidden`. |
| `Tabs` + `tabPanelProps` | WAI-ARIA tabs (see §7). Variant `primary` for platforms and settings sections, `segmented` for Episode / Series. |
| `Dialog` | Modal; centred or a right-hand drawer (see §8); backdrop `bg-scrim`. |
| `Popover` | Non-modal panel above a trigger (`data-popover-trigger`); closes on Escape or an outside click. Used for the batch Options. |
| `useModal` | Focus trap, Escape, body scroll lock and focus return; shared by every modal. |

### Component styling (v1.8)

| Element | Style |
|---|---|
| Primary button | `bg-accent text-on-accent`, hover `bg-accent-hover`; no shadow. Disabled: 50 % opacity |
| Secondary / ghost / danger | Unchanged structure; neutral borders (`line-strong`) |
| Text inputs | `bg-surface`, `border-line-strong`; focus: `border-accent-line` + focus ring |
| Platform tabs | Track `bg-surface` with border; active `bg-accent text-on-accent` |
| Segmented control | Track `bg-surface-muted`; active `bg-surface` + `ring-1 ring-accent-line` |
| Quality (resolution) cards | Selected: `border-accent-line bg-accent-soft ring-1 ring-accent-line`; radio uses the amber accent |
| Episode rows | Checked: `bg-accent-soft`; checkbox accent amber; "Current" is an accent badge |
| Progress bars | Amber fill on `surface-muted` track (green is reserved for the finished-file card) |
| Toggles (Settings) | On: `bg-accent`; off: `bg-line-strong` |
| Download status | Ready file: green success card with an amber **Save** button; errors: red alert |
| Downloads drawer | "Needs attention" items: amber border (`bg-surface` in light so the amber Save button keeps its edge; amber tint in dark) |
| Sticky batch bar | Solid `bg-surface`, top border; floating card with `shadow-lg` from `sm` |
| Header | Emblem + wordmark; ghost icon buttons; amber badge when attention is needed |

## 7. Navigation

- **Header:** the emblem and wordmark, then the **Downloads** button (a badge with running + needs-attention items, filled amber when something needs attention; aria-label such as "Downloads (1 running, 1 need attention)") the **theme toggle** (sun/moon, §3.1) and the **Settings** gear.
- **Platform tabs:** X · TikTok Videos · TikTok Short Drama. Below `sm` the labels shorten to X · TikTok · Short Drama, and the accessible name is always the full label. Panels stay mounted (`hidden`), so each tab keeps its URL, analysis and running job.
- **Keyboard:** one tab stop for the whole tab list (roving `tabIndex`). Left/Right move and activate; Home/End jump to the first or last tab.
- **Wrong-tab detection:** a link pasted in the wrong tab offers a one-click switch that carries the URL across.
- **Active states:** the active platform tab is filled amber with dark text; the active segment (Episode | Series, Settings sections) is a raised `surface` pill with an amber hairline ring; inactive items are `text-muted` with a `surface-muted` hover.
- **Short Drama:** a segmented **Episode | Series** control. "Open series (N episodes)" from an analysed episode switches to Series, with that episode preselected.
- **X and TikTok Videos** (v1.9): a segmented **Single | Bulk** control in the same style. Both views stay mounted; a link handed over from another tab opens in Single.
- **New Download** (v1.9): a secondary button with a plus icon right after **Analyse** (same row; it wraps below on phones), shown once there is a result, an analysis in progress or an error. It resets only that workspace and puts focus back in the URL field. In Bulk the equivalent is **New Bulk Download**.

## 8. Dialogs and drawers

| Placement | Desktop / tablet | Phone (< 640 px) | Used by |
|---|---|---|---|
| `center` | Centred, `max-w-lg` (`wide`: `max-w-2xl`), max 85 vh, scrolling body | Full-screen sheet | Settings |
| `right` | Right-hand drawer, `max-w-md`, full height | Full width | Downloads |

- The header (title, optional description, Close button) is sticky. The body scrolls; an optional footer is pinned.
- `role="dialog"`, `aria-modal`, `aria-labelledby` and `aria-describedby`. Focus moves into the dialog (`[data-autofocus]` or the container), Tab/Shift+Tab cycle inside it, Escape and the backdrop close it, and focus returns to the opener (Downloads or Settings button).
- The container itself has no focus ring (`outline-none`). The global focus style is in `@layer base`, so this utility wins; it was unlayered before the v1.7 fix and drew a ring around the whole drawer.
- **Settings** is split into sections (General · Download limits · TikTok account), which can be opened at a given section (e.g. from a "link your account" error).

## 9. Responsive behaviour

| Width | Behaviour |
|---|---|
| ≥ 640 px (`sm`) | Full tab labels; centred dialogs; the batch action bar is a floating rounded card at the bottom of the column. |
| < 640 px | Short tab labels; dialogs become sheets; the batch bar spans the full width with `pb-safe` (`env(safe-area-inset-bottom)`); some secondary actions move into the Options popover or onto their own line. |

- **Sticky batch action bar** (Series view): the selection summary ("N episodes selected · about M min"), output select, Options, the primary Download button and "All accessible". It stays pinned to the bottom of the viewport without covering the last episode row.
- **Episode list:** the page scrolls (no nested scroll area). Each row is a full-width label (≥ 56 px tall) with a thumbnail, episode code, title, a "Current" badge and the duration.
- Verified (v1.8) at 1600×1000, 1280×900, 768×1024 and 375×812 in both themes: no horizontal overflow and no clipped text (see [TESTING.md](TESTING.md#visual-and-accessibility-audit)).

## 10. Accessibility conventions

- **Focus:** a single `:focus-visible` style (2 px solid `--focus`, offset 2 px) that only shows for keyboard focus. Never remove it on interactive elements.
- **Targets:** buttons and tabs are at least 36–48 px tall. Checkboxes sit inside full-row labels. Disclosure summaries are at least 36 px.
- **Names:** icon-only buttons have an `aria-label` (Settings, Close, Options). Short tab labels keep the full accessible name. The logo emblem is decorative; the `h1` reads "MediaLab". Radio and checkbox options are labelled.
- **Selection:** episode rows support click, Space, Shift+click range (from the last-clicked anchor) and "Select a range" (from/to). The selection is locked while a batch for the series runs.
- **Live regions:** one polite `aria-live` region in the activity provider announces **stage changes only** (started, ready to save, failed, cancelled), never every percentage. The sticky bar's summary is `aria-live="off"`.
- **Motion:** `prefers-reduced-motion` shortens all animations and transitions to almost nothing.
- **Headings:** `h1` app title, `h2` per card or dialog, with no skipped levels.

## 11. Activity and progress presentation

All downloads and batches are held in **one registry** (`ActivityProvider`, `lib/activity.tsx`). It polls the backend every 800 ms while anything needs it, and the views and the drawer read from it.

| Entry | Summary line | Actions |
|---|---|---|
| Job (single video) | Stage · percent · bytes · speed · ETA, then "Ready to save" / "Saved" / error | Save Video, Retry (retryable errors), Cancel (queued, downloading or processing), Dismiss |
| Batch (Short Drama) | "3 of 10 saved · 1 failed · …" and the batch stage | Save ZIP / Save Video, Continue without failed (or Retry packaging), Retry episode, Cancel, Dismiss; Pause/Resume in the Series view's batch progress |
| Batch (X / TikTok links, v1.9) | "1 of 3 downloaded, 1 cancelled, 1 waiting", "Stopped: …" after a cancel | Save ZIP, Cancel batch (then **Discard**), Build ZIP from finished, Continue without failed, per-video Cancel and Retry in the expandable list, Pause/Resume in the Bulk view |

- **Downloads drawer groups:** *Needs attention* (ready to save, failed, waiting for a decision, lost) first, then *In progress*, then *Finished* (collapsed in a disclosure, with "Clear finished").
- **Header badge:** running + needs-attention count; amber when anything needs attention, neutral otherwise.
- **Batch progress:** summary first, then a "Needs attention" list of failed/skipped/cancelled episodes above a collapsed list of finished ones, each with a text state (`EPISODE_STATE` labels).
- **Lost entries:** if the backend no longer knows a job or batch (restart), the entry says so once and polling stops.
- **Separate-files batches** auto-save each episode from the provider, so this works even when the Series view isn't visible.
- **Bulk view** (v1.9), summary-first: the links text area with a live count line ("6 lines · 3 to analyse · 1 duplicate · 2 not an X link") and the limit warning; then a review card (thumbnail, title, @creator, chosen resolution and size, the fallback note, the per-link error with "Open in …" for other tabs; checkboxes have a 44 px hit area); quality and "Save as" selects with one explanatory line; parallel downloads, partial ZIP and the folder choice in a **More options** disclosure. Once started, the review is replaced by the shared batch progress. Item labels are `#1`, `#2`… (Short Drama keeps `E01`); states read Waiting, Starting, Downloading, Verifying, Ready to save, Downloaded / Saved, Failed, Cancelled.
- **Cancel** for a single download is a visible secondary button next to the percentage in the progress card (`aria-label="Cancel download"`), also during processing; the drawer's Cancel acts on the same job. Cancelled downloads show an info alert, not an error.
- **Progress bars** are indeterminate until the total is known. Percentages come from real bytes, and the final state appears only after verification.
