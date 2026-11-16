# MediaLab brand assets

MediaLab's **source code** is licensed under the [MIT licence](LICENSE). The **brand assets** listed below are **not** licensed under MIT, or under any other licence. Copyright in them is reserved by the copyright holder.

This file explains the boundary so that anyone can use, modify and redistribute the code without needing the brand.

## Reserved brand assets

| Asset | Files |
|---|---|
| Logo emblem (film frame with waveform over an offset frame) | `frontend/public/brand/medialab-mark.svg`, `frontend/public/brand/medialab-mark-small.svg` |
| Horizontal logos with the wordmark | `frontend/public/brand/medialab-logo-on-dark.svg`, `frontend/public/brand/medialab-logo-on-light.svg` |
| Application icons | `frontend/public/brand/medialab-app-icon.svg`, `frontend/public/brand/medialab-app-icon-512.png`, `frontend/public/apple-touch-icon.png` |
| Favicon artwork | `frontend/public/favicon.svg`, `frontend/public/favicon.ico` |
| The emblem artwork drawn in code | the emblem geometry and brand colours in `frontend/src/components/brand/Logo.tsx` (`LogoMark`, `BRAND`) and the "Media**Lab**" wordmark styling (`Wordmark`) |
| The name "MediaLab" used as the name of this application | wherever it identifies the product (window title, header, documentation) |

## What isn't reserved

Everything else in the repository is covered by the MIT licence (subject to third-party licences, see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)), including:

- all backend and frontend source code, tests and build files;
- the user interface components, layout, design tokens and colour values in `index.css` (a colour value on its own isn't a brand asset);
- the documentation;
- the React component code in `Logo.tsx` as code (a fork may keep the component and draw its own artwork in it).

The Manrope and DM Sans fonts in `frontend/public/fonts/` are third-party works under the SIL Open Font License 1.1, not MediaLab brand assets.

## Forks and redistribution

- **You may** use, copy, modify and distribute the code under the MIT licence, including in commercial and closed-source products.
- **If you distribute a modified version or a product built from this code**, please give it a different name and replace the reserved assets (logo, icons, favicon, wordmark artwork) with your own, so users don't mistake it for MediaLab. Internal identifiers (package names such as `medialab-backend`, folder names, variable names) can stay.
- Saying that your project is "based on MediaLab" or "a fork of MediaLab" is fine and appreciated.
- `frontend/src/__tests__/brand-assets.test.ts` checks the current brand files; update it when you replace them.
- Unmodified copies of this repository (for example a GitHub fork used to send pull requests) naturally contain the brand files; that's expected and fine.

## Notes

- MediaLab is not a registered trademark. This file states the copyright holder's reservation of the artwork and a request about the name; it doesn't claim rights beyond those that exist under applicable law. The MIT licence itself grants no trademark rights and isn't relied on to protect the name.
- Copyright holder: see [LICENSE](LICENSE) ("MediaLab contributors"). **[OWNER INPUT: confirm whether the brand assets are owned by the same holder or by a named person; to be decided before publication.]**
- Questions about using the brand: **[CONTACT PLACEHOLDER: to be confirmed before publication]**.
