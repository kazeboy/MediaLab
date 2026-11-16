# Third-party notices

MediaLab's own code is MIT-licensed ([LICENSE](LICENSE)); its brand assets are reserved ([BRAND_ASSETS.md](BRAND_ASSETS.md)). This file lists third-party material that is **included in this repository**, and the main third-party software MediaLab **installs or uses** when you run it from source. Each component remains under its own licence.

## Included in this repository

| Component | Files | Licence | Notice |
|---|---|---|---|
| Manrope (weights 600, 700; Latin and Latin Extended subsets), via Fontsource 5.3.0 | `frontend/public/fonts/manrope-*.woff2` | SIL Open Font License 1.1 | Copyright 2019 The Manrope Project Authors. Full text: `frontend/public/fonts/OFL-Manrope.txt` |
| DM Sans (weights 400, 500, 600; Latin and Latin Extended subsets), via Fontsource 5.3.0 | `frontend/public/fonts/dm-sans-*.woff2` | SIL Open Font License 1.1 | Copyright 2014 The DM Sans Project Authors. Full text: `frontend/public/fonts/OFL-DMSans.txt` |

No other third-party code, media or artwork is committed. Test media is generated with FFmpeg while the tests run.

## Installed when running from source (not included here)

These are downloaded by `make setup` (pip and npm) or installed by you, each with its own licence:

| Software | Used for | Licence |
|---|---|---|
| yt-dlp | Metadata extraction and downloads | Unlicense |
| curl_cffi | Browser-like HTTPS for yt-dlp (includes curl-impersonate, libcurl and BoringSSL in its compiled module) | MIT (bundled libraries under their own licences) |
| FastAPI, Starlette, Uvicorn, Pydantic | Local web API | MIT / BSD-3-Clause |
| certifi | CA certificates | MPL-2.0 |
| React, React DOM | User interface (compiled into the built frontend) | MIT |
| FFmpeg and FFprobe | MP4 assembly, audio conversion, verification | LGPL 2.1+ or GPL 2+, depending on the build you install |

The complete, version-by-version list with licences is in [docs/open-source/DEPENDENCY_LICENSE_AUDIT.md](docs/open-source/DEPENDENCY_LICENSE_AUDIT.md).

## Future binary releases

No binary or installer is distributed today. A future desktop release would bundle many of the components above and must ship their licence texts and notices (and, for LGPL/GPL components such as FFmpeg, meet their source-availability terms). See the licence audit for the open questions.
