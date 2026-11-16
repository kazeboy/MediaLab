# Desktop packaging options

*Research document, 2026-11-14. Nothing here has been built or measured yet. Statements about frameworks cite official documentation; sizes and timings are **estimates** to be measured in the first milestone.*

## Goal

People should download an installer, install MediaLab and open it like any other application on **macOS (Apple silicon first, Intel if practical)** and **Windows 11**, with no Python, Node.js or FFmpeg to install. Linux can follow if there is interest.

## What any option has to package

MediaLab today is a React frontend (static files after `npm run build`) talking over HTTP to a FastAPI backend on `127.0.0.1`, which runs yt-dlp, curl_cffi and FFmpeg/FFprobe subprocesses. The hard part is the same for every option: **freezing the Python backend** into a self-contained executable with:

| Component | Packaging concern |
|---|---|
| CPython runtime | Must be bundled; one build per OS and CPU architecture |
| yt-dlp | Pure Python, updated often (platforms change). Updates mean new MediaLab releases, or a carefully designed separate update channel |
| curl_cffi | Native module (`_wrapper.abi3.so` / `.pyd`) that statically links curl-impersonate; per-platform wheels exist; must be signed inside the app on macOS |
| pydantic_core | Compiled Rust extension; per-platform wheels |
| FFmpeg + FFprobe | Two native executables per platform; licence depends on the build (see [DEPENDENCY_LICENSE_AUDIT.md](DEPENDENCY_LICENSE_AUDIT.md#44-ffmpeg-the-main-question-for-situation-c)) |
| Frontend | Static `dist/` files, unchanged |

The [PyInstaller documentation](https://pyinstaller.org/en/stable/feature-notes.html) covers signing collected binaries on macOS: it ad-hoc signs by default, can sign every embedded binary with a real identity, enables the hardened runtime when an identity is given, and recommends against onefile app bundles. yt-dlp itself ships PyInstaller-built standalone executables that include curl_cffi ([yt-dlp README](https://github.com/yt-dlp/yt-dlp/)), which is good evidence that this dependency set can be frozen. **Recommendation for every option: PyInstaller in onedir mode.**

## Option A: Tauri 2 shell with a Python sidecar

The React app runs in Tauri's native webview (WKWebView on macOS, WebView2 on Windows); the frozen backend is a **sidecar** that the Rust shell starts and stops.

- **Fit:** good. The frontend stays the same apart from how it learns the backend's address and token. Tauri's [sidecar support](https://v2.tauri.app/develop/sidecar/) bundles external binaries per target triple (e.g. `-aarch64-apple-darwin`) and gates their execution through capability permissions.
- **Installers and updates:** Tauri's bundler produces `.app`/`.dmg` and Windows `.msi`/NSIS installers. Its [updater plugin](https://v2.tauri.app/plugin/updater/) requires signed updates (a public key in the config, the private key only in CI) and can't be configured without signatures.
- **Size and memory (estimates):** shell 5 to 15 MB; uses the OS webview (no bundled browser). Total dominated by Python (~40 to 80 MB) and FFmpeg (~60 to 100 MB static builds).
- **Startup (estimate):** webview opens almost instantly; the backend needs about 1 to 3 s (PyInstaller onedir) before the UI can talk to it, so the shell shows a splash or "starting" state.
- **Security:** Tauri's capability system limits what the web page can do; the backend still needs its own protection on the loopback port (see the architecture proposal).
- **Costs:** adds Rust and the Tauri CLI to the build; the maintainer must manage the sidecar lifecycle (start, health check, shutdown, crash) in Rust; WebView2 behaviour differs slightly from WKWebView (test both).
- **CI:** Tauri provides a GitHub Action; macOS runners for Apple silicon and Windows runners can build both.

## Option B: PyInstaller (or Nuitka) app with a native webview (pywebview)

One Python program starts the backend in a thread and opens a window with [pywebview](https://pywebview.flowrl.com/guide/web_engine.html), which uses WKWebView on macOS and WebView2 (Edge Chromium) on Windows.

- **Fit:** very good and the least new technology: Python only.
- **Installers and updates:** **not included.** Needs separate tools (a `.dmg` builder on macOS; Inno Setup, WiX or MSIX on Windows) and a hand-built update check. No signed-update framework.
- **Size and memory (estimates):** similar to Option A (both use the OS webview).
- **Security:** no capability system for the page; same loopback-port protection needed.
- **Nuitka** compiles Python to C and can be faster and smaller, but builds are slower and debugging packaging problems is harder; PyInstaller is the better-documented first choice.
- **CI:** straightforward Python builds on macOS and Windows runners.

## Option C: Electron with a Python sidecar

Electron bundles Chromium and Node.js; the Python backend runs as a child process.

- **Fit:** good for the UI (one consistent Chromium everywhere).
- **Installers and updates:** mature (electron-builder, auto-update).
- **Size and memory (estimates):** the bundled Chromium adds roughly 80 to 120 MB to the installer and noticeably more memory than a system webview; plus Python and FFmpeg.
- **Security:** Electron's [security guide](https://www.electronjs.org/docs/latest/tutorial/security) asks for context isolation (default on), the renderer sandbox (default since Electron 20), no Node integration for web content, and serving local pages through a custom protocol rather than `file://`. Achievable, but it's more surface to configure correctly and to keep updated (Chromium security releases).
- **Costs:** a third runtime (Node) in the shipped product; frequent Electron upgrades.

## Option D: alternatives considered and set aside

- **A browser launcher only** (a small app that starts the backend and opens the default browser): smallest change, but downloads and the UI then live in a browser tab the user can close, and the loopback API stays exposed exactly as today. Useful as an internal milestone, not as the product.
- **Rewriting the backend in another language** (Rust, Go): removes the Python packaging problem but loses yt-dlp, MediaLab's core dependency. Not credible.

## Cross-cutting requirements

| Topic | What it takes |
|---|---|
| macOS signing and notarisation | A paid Apple Developer account; a **Developer ID** certificate; the hardened runtime on executables; signing every nested binary (Python extensions, curl_cffi, FFmpeg) inside-out; submitting to Apple's notary service and stapling the ticket ([Apple documentation](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)) |
| Windows signing | Microsoft's [Artifact Signing](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options) (formerly Trusted Signing) is its recommended service for non-Store apps (paid subscription). SmartScreen warnings still appear until the publisher identity builds reputation, which Microsoft says can take weeks ([SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)); EV certificates no longer bypass this |
| Architectures | Apple silicon (arm64) first; Intel Macs need a separate x86_64 build or a universal2 build of Python and every native dependency |
| yt-dlp freshness | Platforms change often; plan frequent small releases, or a separately signed yt-dlp update channel (more complex, more risk) |
| FFmpeg | Choose an LGPL or GPL build and meet its terms ([licence audit](DEPENDENCY_LICENSE_AUDIT.md)) |
| Windows support in the code | Several code changes first (CR-04: `os.fchmod`, `%APPDATA%`, reserved file names, dev scripts) |

## Comparison

| Criterion | A: Tauri + sidecar | B: PyInstaller + pywebview | C: Electron + sidecar |
|---|---|---|---|
| Fit with current code | Good | Very good | Good |
| New technology for the maintainer | Rust, Tauri | None | Node/Electron packaging |
| Installer creation | Built in | Separate tools | Built in (electron-builder) |
| Signed auto-updates | Built in, mandatory signatures | Build yourself | Mature libraries |
| Installer size (estimate) | ~110 to 200 MB | ~110 to 190 MB | ~200 to 320 MB |
| Memory | OS webview | OS webview | Bundled Chromium (highest) |
| Page/permission security model | Capabilities | Minimal | Strong if configured correctly |
| Rendering consistency | WKWebView vs WebView2 | WKWebView vs WebView2 | Identical (Chromium) |
| Maintenance burden | Medium | Low to medium (updater and installers are DIY) | Medium to high |

## Recommendation

**Target Option A (Tauri 2 with a PyInstaller onedir sidecar), reached through a shared first step.**

1. Milestone 1 is the same for A and B: freeze the backend with PyInstaller (onedir), with FFmpeg alongside, and make it run on a clean Apple-silicon Mac and a clean Windows 11 machine. This is where most of the risk is (native modules, signing every binary, FFmpeg licensing, Windows code fixes), and it produces real size and startup numbers.
2. Then add the Tauri shell for its installers, signed updater and capability model. If Rust turns out to be too much maintenance for one person, Option B remains a working fallback with the same frozen backend.

Electron is not recommended: it adds the most size, memory and upgrade work, and MediaLab gains little from a bundled Chromium.

Sources: [Tauri sidecar](https://v2.tauri.app/develop/sidecar/), [Tauri updater](https://v2.tauri.app/plugin/updater/), [PyInstaller feature notes](https://pyinstaller.org/en/stable/feature-notes.html), [pywebview web engines](https://pywebview.flowrl.com/guide/web_engine.html), [Electron security](https://www.electronjs.org/docs/latest/tutorial/security), [Apple notarisation](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution), [Windows code signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options), [SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation), [FFmpeg legal](https://ffmpeg.org/legal.html), [yt-dlp README](https://github.com/yt-dlp/yt-dlp/).
