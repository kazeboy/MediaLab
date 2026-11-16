# UI/UX review (v1.6, implemented in v1.7; visual identity v1.8; polish v1.8.1)

Scope: the current React UI as of v1.6, reviewed in the in-app Chromium browser at desktop width and at 375×812 (phone), in light and dark mode, with keyboard checks and measured colour contrast. The v1.6 review was a proposal; **v1.7 implemented most of it** (status per finding below). The design rules that came out of it are in [FRONTEND_DESIGN_SYSTEM.md](FRONTEND_DESIGN_SYSTEM.md).

## Implemented in v1.6 (low-risk fixes)

| Change | Why |
|---|---|
| Dark-mode small grey text lifted from slate-500 to slate-400 (`index.css`) | Measured 3.75:1 on dark cards (WCAG AA needs 4.5:1); now 6.96:1 |
| Light-mode hint text `slate-400` → `slate-500` (Settings) | 2.56:1 → 4.76:1 |
| Output-format radio buttons get accessible names | Screen readers announced "on" |
| Header subtitle mentions Short Drama | It still described only "public X posts and TikTok" |
| Batch progress stays visible when the series list is hidden or another series is analysed | The final **Save ZIP / Save Video** button could become unreachable (finding UI-1) |
| Batch polling stops with a clear message when the backend no longer knows the batch | It errored every second forever after a restart (UI-2) |

## Implemented in v1.7 (redesign)

| Finding | What changed |
|---|---|
| U1 Short Drama overloaded | Segmented **Episode \| Series** views; "Open series" from an analysed episode, with that episode preselected |
| U2 Three save models | One **Downloads drawer** lists every job and batch with its Save action; the batch output (ZIP / Merged MP4 / Separate files) is chosen in one select on the sticky bar |
| U3 Settings long, no focus trap | Sections (General · Download limits · TikTok account); `useModal` focus trap, scroll lock, Escape, focus return; full-height sheet on phones; cookie how-to behind a disclosure |
| U4 Tabs keyboard / wrapping | WAI-ARIA tabs (roving tabIndex, arrows, Home/End); short labels below 640 px with the full accessible name |
| U5 Episode list | Page scroll (no nested scroll), thumbnails, full-row targets, Shift-click ranges, "Select a range" (from/to, from N), select all accessible |
| U6 Batch progress for 50 episodes | Summary line first, failed episodes under "Needs attention", finished ones collapsed |
| U7 Planning invisible | Episodes show "Checking qualities" while a merge plan runs |
| U8 Fallback soundtrack | Options say "separate soundtrack added if needed" |
| U10 Long errors | Message and action first; code and details under "Technical details" |
| U11 No cross-tab overview | Activity registry + Downloads drawer with header badge; Save, Retry and Cancel work from any tab (new `POST /api/jobs/{id}/cancel`) |
| Contrast | New `text-subtle` token (#5b6b80) and `emerald-700` success button; v1.7 audit minimum 4.91:1 light / 6.33:1 dark |
| Visual-review defects | Disclosure summaries raised to ≥ 36 px; dialog containers no longer show a focus ring when they open (global focus style moved to `@layer base`) |

Still open: U9 (formats table, kept collapsed by design), U12 (status icons in badges), episode search and a thumbnail grid / virtualised list for very long series, and a screen-reader pass with VoiceOver.

## v1.8 visual identity

v1.8 changed the look, not the workflow: black/charcoal and amber in dark mode (the default for everyone, whatever the OS appearance), neutral white and cool-grey surfaces in light mode, a remembered sun/moon theme toggle in the header, and a custom film-strip/waveform emblem replacing the generic play icon. Details and measured contrast: [FRONTEND_DESIGN_SYSTEM.md](FRONTEND_DESIGN_SYSTEM.md#2-visual-identity).

| Area | Change | Checked |
|---|---|---|
| Header | Emblem + "Media**Lab**" wordmark; favicon and app icons | Screenshots light/dark; emblem at 16–48 px |
| Primary actions | Analyse, Download, Save Video, Save ZIP: amber with dark text (9.7–10.8:1) | Audit + screenshots |
| Navigation | Active platform tab amber; active segment raised with amber ring | All widths, both themes |
| Selection | Episode rows and quality cards: amber tint + amber border | Screenshots |
| Status | Success green, errors red, warnings orange (no longer amber) | Error and ready states captured live |
| Surfaces | Solid sticky bar (no blur); amber-bordered "needs attention" items in the drawer | Light and dark |
| Theme | Dark default with a light OS appearance; header toggle by mouse and keyboard (Tab, Enter); choice kept after reload with a dark OS appearance; light theme without sepia | Browser checks at 1600/1280/768/375 px; unit and App tests |

Issues found and fixed during the v1.8 review: amber Save buttons on an amber-tinted drawer item lost their edge in light mode (the item is now white with an amber border); the sticky bar used a translucent blur (now solid).

Not checked: comparison against the brief's reference images. They weren't available to the implementation session; the identity follows the brief's written description.

## v1.8.1 visual polish

| Area | Change | Checked |
|---|---|---|
| Favicon | Browser tabs showed the old purple icon (cached under the unchanged `/favicon.svg` URL). Now a 16 px-grid amber emblem as SVG and ICO, linked with `?v=2` | Served files and HTML links verified in dev and in the production build; the browser pane fetched both new icons. The tab strip itself isn't visible to the automated browser, so the icon in a real tab still needs a look by eye |
| Typography | Manrope for headings and titles, DM Sans for body and controls, monospace for codes; wordmark unchanged | Computed fonts checked in the browser for headings, legends, body, buttons, tabs, inputs, codes and the wordmark |
| Copy | All em dashes in MediaLab's copy rewritten with full stops, colons, commas or parentheses | Search: none left in tracked files; tests guard the frontend, docs and backend |

Responsive and accessibility check: the page-script audit from [TESTING.md](TESTING.md#visual-and-accessibility-audit) at 1600, 1280, 768 and 375 px in dark and light for X (with an analysis and a finished download), TikTok (with an error), Short Drama Episode and Series (with the sticky bar), the Downloads drawer and all Settings sections: no horizontal overflow, no clipped text, no contrast failures, all headings in Manrope and all other text in DM Sans or monospace. Layout shift while the fonts load: 0.002. Two wraps at 375 px ("n episodes selected" in the sticky bar on two lines, and the Episodes heading row on two rows) happen with the old system font too, so they aren't new.

## v1.6 findings (historical)

The table below is the v1.6 state that motivated the redesign; see the section above for what changed.


Severity: **H** = blocks or misleads users, **M** = noticeable friction, **L** = polish.

| # | Finding | Where | Sev. |
|---|---|---|---|
| U1 | **The Short Drama tab is overloaded.** One long page stacks the single-episode analysis (details, resolution picker, formats table, download panel) and, below it, the whole series panel (cover, 50+ episode list, output format cards, quality/strict/parallel/folder options, two download buttons, batch progress). The series workflow (the main reason to use this tab for many users) starts far below the fold. | `Workspace`, `SeriesPanel` | H |
| U2 | **Three different "save" models** coexist: Save Video (single), automatic per-episode saving (Separate files), and one final Save (ZIP/merge), plus optional folder saving. Users must understand which applies. | `DownloadPanel`, `SeriesPanel`, `BatchProgress` | M |
| U3 | **Settings dialog is long and dense** (1,148 px tall on a 812 px phone screen), mixes everyday preferences with the TikTok account instructions, doesn't trap focus, and the page behind it still scrolls. | `SettingsPanel` | M |
| U4 | **Tabs don't follow the ARIA tabs keyboard pattern** (each tab is a separate Tab stop; no arrow-key navigation). They also wrap to two lines on phones. | `App.tsx` | M |
| U5 | **Episode list scales poorly**: a nested scroll area inside a scrolling page; no range selection (shift-click), search or "select from episode N"; no thumbnails although TikTok provides them. | `SeriesPanel` | M |
| U6 | **Batch progress for 50 episodes** is a long flat list; successes and failures have equal weight; no summary-first view or collapse. | `BatchProgress` | M |
| U7 | **Planning is invisible at episode level**: during merge planning, episodes show "Waiting" while the batch analyses each one; only the batch stage explains it. | `BatchProgress` | L |
| U8 | **Option labels don't reflect the soundtrack fallback**: an option may say "H.265 + AAC" and end up "AAC (converted from MP3)" after the fallback. The final file card is accurate. | `ResolutionPicker` | L |
| U9 | **Formats table** is useful for experts but adds noise for everyone (it is collapsed, which helps). | `FormatTable` | L |
| U10 | **Error messages are thorough but long**; the code shown under each message is helpful for support but visually competes with the action. | `ErrorAlert` | L |
| U11 | **No overview of activity across tabs**: a running download or batch in one tab isn't visible from another. | `App.tsx` | M |
| U12 | **Colour is the main state carrier** in badges (amber/indigo); text labels exist, which keeps it accessible, but icons would speed scanning. | `ui.Badge` | L |

What works well: clear tab separation with wrong-tab detection and one-click switching; structured errors with actions and Retry; honest labels ("Video copied · audio converted to AAC", "joined without re-encoding", omitted episodes listed); progress never shows 100 % before verification; dark/light themes; no horizontal scrolling on phones.

## Remaining recommendations

1. Status icons alongside badge colours (U12).
2. Episode search and a virtualised list for 100+ episode series.
3. A VoiceOver pass over the drawer, batch progress and the live-region announcements.
4. Optional: remember the last Short Drama view (Episode / Series) per session.

## Accessibility considerations (status v1.7)

- Every state is readable as text (not colour only); icons as a secondary cue are still open.
- Contrast: all text ≥ 4.5:1 in both themes, measured per view in v1.7.
- Live regions: one polite region announces stage changes only (implemented).
- Dialogs: focus trap, `aria-modal`, Escape, focus return (implemented and tested).
- Tabs: ARIA keyboard pattern (implemented and tested).
- Hit targets: episode rows are full-width labels (≥ 56 px); small buttons are 36 px (below the 44 px touch guideline, acceptable for a desktop-first tool).

## Mobile considerations (status v1.7)

- Phones are a secondary use case (downloads land on the computer running MediaLab), but the UI is reachable from a phone only if `MEDIALAB_ALLOW_NON_LOCAL` is set; normally it's the same Mac in a narrow window.
- Tabs use short labels at 375 px and no longer wrap.
- Settings is a full-height sheet with a sticky header on phones.
- The episode list uses page scroll with full-row targets; the action bar is sticky and respects the safe area.
- Folder saving is unavailable on mobile browsers; the UI already falls back to normal downloads.
