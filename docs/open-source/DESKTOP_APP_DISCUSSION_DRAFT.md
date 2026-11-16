<!--
DRAFT for a future GitHub Discussion (category: Ideas, or "Desktop app" if created).
Not posted. Review and edit before posting. Replace links to docs with full repository URLs once public.
-->

# Proposal: Standalone MediaLab applications for macOS and Windows

Hi everyone. I'd like to gather ideas and experience before deciding whether, and how, to turn MediaLab into installable desktop apps. **There is no desktop app yet, and no release date.** This is an early proposal, and your technical feedback will shape it.

## What MediaLab does today

MediaLab is a local tool for saving videos you're allowed to keep as MP4 files:

- **X** posts and **TikTok** videos, one at a time or in bulk (up to 50 links, saved as one ZIP or separate files);
- **TikTok Short Drama** episodes and whole series with your own linked account (ZIP, one merged MP4, or separate files);
- original quality with no video re-encoding, audio converted to AAC only when Apple players need it, and every file checked for working audio;
- a Downloads list with save, retry and cancel for everything you've started.

Everything runs on your own computer. There are no accounts, no servers and no telemetry.

## Why a desktop app?

Right now you need developer tools to use it: Python, Node.js and FFmpeg, then `make setup` and `make dev` in a terminal. That's fine for developers and a real barrier for everyone else.

## The experience we're aiming for

1. Download an installer for macOS or Windows.
2. Install MediaLab like any other app.
3. Open it, paste links, download.
4. No Python, Node.js or FFmpeg to install, and updates that arrive safely.

## How MediaLab is built

A React interface talks to a local Python (FastAPI) backend over `127.0.0.1`. The backend uses **yt-dlp** (with **curl_cffi**) to read metadata and download streams, and **FFmpeg/FFprobe** to build and verify the MP4s. Details are in the [architecture docs](../ARCHITECTURE.md).

## Packaging options we've looked at

| Option | In short |
|---|---|
| **Tauri 2 shell + Python backend as a sidecar** (current favourite) | Small native shell using the system webview; built-in installers and signed updates; adds Rust to the toolchain |
| **PyInstaller + a native webview (pywebview)** | Python only and closest to today's code; installers and updates would be our own work |
| **Electron + Python sidecar** | Very mature, consistent rendering; the largest download and memory use |

Whichever shell we pick, the first and hardest step is the same: freezing the Python backend (including yt-dlp, curl_cffi's native library and FFmpeg) into an app that runs on a clean Mac and a clean Windows PC. The full comparison is in [DESKTOP_PACKAGING_OPTIONS.md](DESKTOP_PACKAGING_OPTIONS.md), and a draft architecture in [DESKTOP_ARCHITECTURE_PROPOSAL.md](DESKTOP_ARCHITECTURE_PROPOSAL.md).

## Benefits and trade-offs

- **Benefits:** no setup; a real app window; native save dialogs; signed, automatic updates; the TikTok sign-in stored in the system keychain.
- **Trade-offs:** downloads of roughly 110 to 200 MB (estimate) because Python and FFmpeg come along; yt-dlp updates would arrive as app updates; code signing costs money and takes time; Windows will show SmartScreen warnings until the app builds reputation.

## Security considerations

- The backend would keep listening only on `127.0.0.1`, on a random port, and require a secret created at each launch so other programs and users on the same computer can't use it.
- TikTok cookies would move from a file into the macOS Keychain or Windows Credential Manager.
- Updates would be signed, and the app notarised on macOS and code-signed on Windows.
- MediaLab will continue not to bypass DRM, paywalls, region blocks or private accounts.

## Platforms

- **macOS:** Apple silicon first; Intel if it doesn't double the effort.
- **Windows 11:** after some Windows-specific fixes in the backend.
- **Linux:** possible later if there's interest.

## Questions for you

1. Have you shipped a Python app with PyInstaller, Nuitka, Briefcase or similar? What went wrong that we should expect?
2. Tauri sidecars or pywebview: any experience with either for a long-running local backend?
3. FFmpeg: have you distributed an LGPL build and used VideoToolbox or Media Foundation encoders instead of libx264?
4. Code signing and notarisation in GitHub Actions: tips, pitfalls, costs?
5. Would you use a desktop app, and on which platform? Is an Intel Mac build important to you?
6. Anything in the proposed security design that looks weak?

## Proposed milestones (no dates)

1. Windows-ready backend and groundwork (paths, credential storage, random port and secret).
2. A frozen backend running on clean macOS and Windows machines.
3. A desktop shell prototype.
4. Native saving and secure cookie storage.
5. Signing, notarisation and signed updates.
6. A public beta for testers.

Thanks for reading. All feedback is welcome, including "this isn't worth the complexity".
