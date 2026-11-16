# Media pipeline

How MediaLab turns source streams into an MP4 (or a ZIP of MP4s) that plays with sound in QuickTime and Safari, and how it checks that. Code: `selection.py`, `jobs.py`, `media.py`, `packaging.py`.

## 1. Source formats and option building

Sources offer some combination of:
- **muxed** files (video + audio, e.g. X progressive MP4, TikTok H.264 renditions),
- **video-only** streams (X HLS video variants, TikTok HEVC renditions on Short Drama),
- **audio-only** streams (X HLS audio, TikTok's separate "music" track).

`selection.build_options` builds **one option per resolution** (labelled by the short side, so 720×1280 is "720p"). For each resolution it picks the best candidate (MP4-compatible first, then highest bitrate, then fewest streams), where a candidate is a muxed file, or a video-only stream paired with the best audio-only stream. Nothing is upscaled; options only exist for resolutions the source really has.

Per option it records:

| Field | Meaning |
|---|---|
| `requires_merge` | a separate audio stream will be combined |
| `audio_converted` | the audio isn't AAC/ALAC/AC-3/E-AC-3 and will be converted to AAC |
| `fallback_audio_format_id` | separate audio to add if the "muxed" stream turns out to have no audio |
| `downloadable`, `too_large`, `note` | MP4 feasibility, size limit, human explanation |

**Best Available** = the highest downloadable option *with audio* when the source has audio. A higher rendition with no usable audio is never chosen as best.

### Audio stream selection rules

| Source | Separate audio used? | Why |
|---|---|---|
| X (HLS audio-only) | Yes | It is the post's audio by construction |
| TikTok Videos tab, `music.playUrl` | **No** (v1.6) | Can be a licensed song or differ from the video's audio (measured r = 0.27 on one "original sound" video) |
| Short Drama, `music.original: true` | Yes | Measured to match the episodes' built-in audio (r = 0.969–0.977, equal length, 4 episodes) |
| Short Drama, music not marked original | No | No evidence it is the episode's audio |

### When metadata lies about audio

yt-dlp labels every TikTok `bitrateInfo` stream "acodec: aac" unless the URL path ends in `/media-video-hvc1/`. TikTok varies the URL form between requests, so the same video-only HEVC stream is sometimes labelled "has AAC" (seen live on all 52 episodes of a series in one listing). MediaLab therefore:

1. keeps a trusted separate track as `fallback_audio_format_id`;
2. after downloading, probes the video: if it has no audio track, downloads the fallback and combines it (`jobs.py`);
3. passes `expect_audio=True` to `assemble_mp4` when the source promised audio (explicit codec) or a fallback exists. A file without audio then fails with `audio_missing` instead of being saved silently.

## 2. Single-file processing (`MediaProcessor.assemble_mp4`)

1. **Probe inputs** (`ffprobe -v error -print_format json -show_format -show_streams <file>`).
2. **Compatibility:** video must be H.264, HEVC or AV1 (never re-encoded; otherwise `incompatible_format`). Audio must be in `APPLE_MP4_AUDIO` (copied) or `CONVERTIBLE_AUDIO` (MP3, MP2, Opus, Vorbis, FLAC, PCM → AAC).
3. **Mux** (representative command for the reported Short Drama case: HEVC video + separate MP3):

   ```bash
   ffmpeg -nostdin -hide_banner -loglevel error -y \
     -i video.mp4 -i audio.mp3 -map 0:v:0 -map 1:a:0 \
     -c:v copy -tag:v hvc1 \
     -c:a aac -b:a 192k \
     -movflags +faststart -f mp4 output.mp4
   ```
   - `-c:v copy`: the video bitstream is untouched (verified byte-identical in testing).
   - `-tag:v hvc1`: Apple players only play HEVC in MP4 with the `hvc1` sample entry.
   - AAC/ALAC/AC-3/E-AC-3 audio uses `-c:a copy` instead; a single muxed file uses `-map 0:v:0 -map 0:a:0?`.
   - `+faststart` puts the index first so Safari can start playback while streaming.
4. **Validate the output** (`validate_output`):
   - has video; has audio when the source had audio (`audio_missing`);
   - audio codec is Apple-playable (`mp4_compatibility`);
   - when combining separate streams: audio/video durations within max(1 s, 5 %) and start times within 0.5 s (`av_sync_failed`);
   - the audio decodes and isn't silent: `ffmpeg -i output.mp4 -map 0:a:0 -af volumedetect -vn -sn -f null -`, max volume must exceed −70 dB; if not, the source audio is measured too: a genuinely silent source is accepted and flagged (`audio_silent_source`), otherwise `audio_conversion_failed`/`audio_missing`.

### Why AAC conversion (QuickTime/AVFoundation)

FFmpeg happily writes MP3 into MP4 (object type `0x6B`), and FFmpeg/VLC/Chromium play it. **AVFoundation (used by QuickTime, Safari and Quick Look) ignores such a track entirely.** In v1.3/v1.4 the 720p Short Drama files were therefore silent in QuickTime although FFprobe listed an audio stream and FFmpeg measured −19.4 dB. AVFoundation listed only the `hvc1` track. After conversion to AAC, AVFoundation decodes the audio at the same level (−19.4 dBFS), confirmed by ear in QuickTime by the user. Conversion costs one lossy audio generation (192 kb/s AAC from 128 kb/s MP3); video is never touched.

**Lesson:** FFprobe recognising a stream proves neither that a given player will play it nor that it contains the right sound. During development, outputs were decoded with AVFoundation (`AVAssetReader`) and spot-checked by ear; see [TESTING.md](TESTING.md#audio-verification).

## 3. ZIP packaging (`packaging.build_zip`)

- Entries are the episode MP4s exactly as single downloads would produce them, named `"<Series> - E01.mp4"` in ascending episode order.
- `ZIP_STORED` (video doesn't compress further), streamed in 1 MiB chunks with `force_zip64=True` (archives may exceed 4 GB); never held in memory.
- A `MediaLab manifest.txt` is added when episodes were omitted (included list + reason per missing episode).
- After writing, `zipfile.testzip()` verifies every entry's CRC; only then are the episode files deleted (so a failure can be retried without re-downloading).
- Archive name: `"<Series> - E01-E10.zip"`, `"… - E01, E03, E05.zip"`, `"… - E01-E40 (12 episodes).zip"`, `"… - Complete Series.zip"` (only if every series episode is included), with `" (partial, 8 of 10)"` when episodes were omitted.

## 4. MP4 merging (`packaging.merge_mp4`)

### 4.1 Planning (batch level)

With Best Available, the batch first analyses every selected episode and picks the **highest rendition all of them offer** (same short side and video codec family), then downloads every episode at that rendition. Within one series, renditions at one quality are encoded identically (identical codec configuration/extradata observed for HEVC 720p and H.264 576p across episodes), so they can be joined by stream copy.

### 4.2 Stream-copy compatibility check (`copy_incompatibility`)

All inputs must match on: video codec, profile, width, height, pixel format, frame rate, video time base, video codec configuration (extradata hash), audio codec, profile, sample rate, channels and audio configuration. Additionally, each input's audio/video lengths must be within 0.5 s, streams must start at ~0, video must be H.264/HEVC and audio Apple-playable, and either all or none have audio.

**Copy path:**
```bash
# concat.txt: file '/…/job-batch-<id>/E0001.mp4' (one line per episode, MediaLab's own paths)
ffmpeg -progress pipe:1 -nostats -nostdin -hide_banner -loglevel error -y \
  -f concat -safe 0 -i concat.txt -map 0:v:0 -map 0:a:0 -c copy -tag:v hvc1 \
  -movflags +faststart -f mp4 output.mp4
```
Near-instant (≈3 s including verification for 5½ min of 1080p HEVC).

### 4.3 Normalisation path

Used when any check fails. Per input *n* with video length *d*:

```text
[n:v:0]scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2,setsar=1,
       fps=F,format=yuv420p,trim=duration=d,setpts=PTS-STARTPTS[vn];
[n:a:0]aresample=SR:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=SR:channel_layouts=stereo,
       apad=whole_dur=d,atrim=duration=d,asetpts=PTS-STARTPTS[an]        # or anullsrc for a silent episode
[v0][a0][v1][a1]…concat=n=N:v=1:a=1[v][a]
```
```bash
ffmpeg … -filter_complex "<graph>" -map "[v]" -map "[a]" \
  -c:v libx264 -preset fast -crf 20 -profile:v high -pix_fmt yuv420p -tag:v avc1 \
  -c:a aac -b:a 192k -movflags +faststart -f mp4 output.mp4
```
- **W×H** = the smallest input width and height (never upscaled; larger episodes scaled down, aspect kept with padding).
- **F** = the highest input frame rate.
- **SR** = the common sample rate, or 48 kHz if inputs differ; stereo.
- Each episode's audio is padded/trimmed to **its own video length**, so audio can't drift into the next episode.
- Requires `libx264`; without it the merge fails with a clear `transcode_failed` (suggesting ZIP).
- Cost: ≈23 s for 5½ min of 720p on Apple silicon; CPU-bound, cancellable.

### 4.4 Merge verification (`verify_merged`)

1. FFprobe: video present and H.264/HEVC; audio present if any input had audio, Apple-playable.
2. Duration = sum of episode lengths (tolerance 1 s + 0.1 s per episode); audio length ≈ video length.
3. Full decode, no errors allowed: `ffmpeg -nostdin -hide_banner -v error -i output.mp4 -f null -` (time limit scales with the video's length).
4. **Per-episode audio:** for every episode whose source was audible, the output's audio inside that episode's segment (minus 0.25 s at each edge) must exceed −70 dB: `ffmpeg -i output.mp4 -map 0:a:0 -af "atrim=start=S:end=E,volumedetect" -vn -f null -`.

## 5. Running FFmpeg

- Single-file steps (probe, assemble, audio checks) run through `MediaProcessor.run`: `Popen` polled every 0.2 s against `MEDIALAB_FFMPEG_TIMEOUT_SECONDS` and, since v1.9, against the job's cancel event (`MediaProcessor.cancellable`), so cancelling a job kills its FFmpeg/FFprobe during muxing, audio conversion and the final checks.
- Merge steps use `run_ffmpeg`: `Popen` with `-progress pipe:1` for progress, a stderr reader thread, and a **watchdog** that kills FFmpeg on cancel or timeout every 0.2 s regardless of output (v1.6; previously a stalled FFmpeg could ignore both).
- Never a shell; absolute paths; only MediaLab-generated file names.

## 6. Quality and performance trade-offs

| Choice | Quality | Speed | Notes |
|---|---|---|---|
| Video stream copy | identical to source | instant | Default everywhere |
| MP3 → AAC 192k | one lossy audio generation | fast | Required for Apple players |
| Merge by stream copy | identical | instant | Needs identical renditions (planning) |
| Merge with libx264 CRF 20 | visually close, not identical | CPU-bound | Only when episodes differ |

## 6.1 Bulk downloads (X / TikTok, v1.9)

- **Quality preference** (`best`, `1080p`, `720p`, `480p`) per batch: the exact resolution, else the next lower, else the closest higher (`choose_option(above="closest")`); with-audio options preferred, so Best Available is never a video-only stream when an audio one exists. Each item is then an ordinary job: the same muxing, AAC conversion and audio verification as a single download.
- **ZIP:** one MP4 per video, stored uncompressed, named `NN - <author> - <text> [<post id>] <res>.mp4` with `NN` the position in the pasted list (zero-padded), so names never collide and the order is kept. The archive is CRC-checked before delivery; a partial ZIP adds `MediaLab manifest.txt` (titles and reasons, no links). A single successful video is delivered as a plain MP4. No merged output for unrelated videos.
- **Separate files:** each video is delivered as soon as it is ready (two unsaved at most, as for Short Drama).

## 7. Cleanup

Job folders are removed in `finally`; batch folders after delivery, cancellation or expiry; delivered files immediately; unsaved files after the retention period; everything stale at startup. Merge and ZIP inputs are deleted only after the output verified. See [ARCHITECTURE.md](ARCHITECTURE.md#9-browser-delivery-and-temporary-storage).
