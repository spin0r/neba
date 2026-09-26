# aebn-vod-downloader

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/hyper440/aebn-vod-downloader/blob/main/colab.ipynb)

## Dependencies

- Python 3.8 or higher (supports Windows 7)
- FFmpeg in system PATH. On Windows 7, use the **essentials** build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (the full build requires Windows 10+)

## Installation

```
pip install https://github.com/hyper440/aebn-vod-downloader/archive/refs/heads/main.zip -U
```

Or

```
pip install git+https://github.com/hyper440/aebn-vod-downloader -U
```

### Example Usage With Arguments

```
aebndl https://*.aebn.com/*/movies/* --resolution 720 --scene 2
```

To download scene 2 in 720p resolution

## Arguments

| Flags | Argument                | Description                                                                                                                                                                                                                                                        |
| ----- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
|       | `URL`                   | URL of the movie or list.txt                                                                                                                                                                                                                                       |
| `-o`  | `--output_dir`          | Specify the output directory                                                                                                                                                                                                                                       |
| `-w`  | `--work_dir`            | Specify the work diretory to store downloaded temporary segments in                                                                                                                                                                                                |
| `-i`  | `--info`          | Print full movie and segment info without downloading                                                                                   |
| `-r`  | `--resolution`          | Desired video resolution by pixel height. If not found, the nearest lower resolution will be used. Use 0 to select the lowest available resolution. (default: highest available)                                                                                   |
| `-f`  | `--force-resolution`    | If the target resolution not available, exit with an error                                                                                                                                                                                                         |
| `-n`  | `--names`               | Include performer names in the output filename                                                                                                                                                                                                                     |
| `-nm`  | `--no-metadata`               | Disable adding title and chapter markers to the output video                                                                                                                                                                                                                     |
| `-s`  | `--scene`               | Download a single scene using the relevant scene number on AEBN                                                                                                                                                                                                    |
|       | `--split-scenes`        | Download and save each scene as a separate file                                                                                                                                                                                                                    |
| `-ss` | `--start-segment`       | Specify the start segment                                                                                                                                                                                                                                          |
| `-es` | `--end-segment`         | Specify the end segment                                                                                                                                                                                                                                            |
| `-p`  | `--proxy`               | Proxy to use (format: protocol://username:password@ip:port)                                                                                                                                                                                                        |
| `-pm` | `--proxy-metadata`      | Use proxies for metadata only, and not for downloading                                                                                                                                                                                                             |
| `-c`  | `--covers`              | Download front and back covers                                                                                                                                                                                                                                     |
|       | `--covers-only`         | Download only the front and back covers, skipping the movie                                                                                                                                                                                                        |
| `-ow` | `--overwrite`           | Overwrite existing audio and video segments and covers, if already present                                                                                                                                                                                        |
| `-ts` | `--target-stream`       | Download just video or just audio stream                                                                                                                                                                                                                           |
| `-ks` | `--keep-segments`       | Keep audio and video segments after downloading                                                                                                                                                                                                                    |
| `-kl` | `--keep-logs`           | Keep logs after successful exit                                                                                                                                                                                                                                    |
| `-ac` | `--aggressive-cleaning` | Delete segments instantly after a successful join into stream. By default, segments are deleted on success, after stream muxing. If you are really low on disk space, you can use this option, but in case of muxing error you would have to download it all again |
| `-t`  | `--threads`             | Threads for concurrent downloads(default=5)                                                                                                                                                                                                         |
| `-l`  | `--log-level`           | Set the logging level (default: INFO) Any level above INFO would also disable progress bars                                                                                                                                                                        |

## Telegram Bot

### Install with bot extras

```
pip install git+https://github.com/hyper440/aebn-vod-downloader -U --extra bot
# or locally
pip install -e ".[bot]"
```

### Configuration

Create `.env` file from `.env.example` or export env vars:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...  # from @BotFather
ALLOWED_USER_IDS=123456789            # optional, comma-separated; empty = allow all
AEBN_OUTPUT_DIR=./output_dir
AEBN_WORK_DIR=./work_dir
AEBN_PROXY=socks5://user:pass@ip:port # optional, same as CLI -p
MAX_CONCURRENT_DOWNLOADS=2
MAX_TELEGRAM_FILESIZE_MB=50           # 50 for hosted Bot API, 2000 for self-hosted
```

### Run

```
export TELEGRAM_BOT_TOKEN="123:ABC"
aebndl-bot
# or
python -m aebn_dl.bot
```

### Bot Commands

| Command | Description |
| ------- | ----------- |
| `/start`, `/help` | Show help |
| `/m3u8 <url>` / `/dash` / `/mpd` / `/manifest` | **Primary** — return direct DASH manifest URL (m3u8 equivalent) without downloading. Includes `ffmpeg`/`mpv` one-liners |
| `/info <url>` | Show title, studio, duration, resolutions, scenes + button to get m3u8 |
| `/covers <url>` | Download front/back covers only |
| `/dl <url> [720] [scene:2] [--covers] [--split-scenes]` | Optional full download (kept for completeness) |
| Paste URL directly | Auto-returns **m3u8/DASH URL** (no download) |

Works with **AEBN**, **AdultDVDEmpire / AdultEmpire**, and **Elegant Angel** links (same Empire backend).

## Web UI

A Calcast-style command-bar frontend that mirrors the bot, served on `$PORT`
(the bot serves it automatically in the background; standalone via `aebndl-web`):

```
pip install -e ".[bot]"        # web needs no extra deps (stdlib only)
WEB_PASSWORD=secret aebndl-web # optional password lock, else open
# open http://localhost:8000
```

- Paste any AEBN / ADE / Elegant Angel link → **Manifest** (per-resolution
  copy-to-clipboard links), **Info** (title, studio, duration, performers,
  scenes), **Covers** tabs. `Enter` fetches, click any row copies the link.
- **Cookies button**: paste Netscape cookie exports for `adultdvdempire.com`
  or `elegantangel.com`, with **Import** (file upload), **Export** (download
  `.txt`), Save in browser (`localStorage`, sent per-request) or Save to
  server (shared fallback, also used by the bot). Shows expiry + PPM balance.
- Recent links kept as history; optional `WEB_PASSWORD` env locks the UI
  behind a login view.

API (same-origin JSON): `POST /api/extract {url, mode, cookies}`,
`GET/POST/DELETE /api/cookies`, `GET /api/auth-check`, `POST /api/login`.

Inline buttons: `📄 Get m3u8 / DASH URL` (primary), per-resolution shortcuts, `Refresh m3u8`, `Show info`.

Manifest is fetched via `POST https://{type}.aebn.com/{type}/deliver` (`movieId`, `format=DASH`) → `content["url"]` (`aebn_dl/manifest_parser.py:92`), same as `Manifest._get_new_manifest_url()`. The bot runs `_blocking_m3u8()` in `ThreadPoolExecutor` and returns `manifest_url` + `base_stream_url` as code-block for easy copy.

### Docker example

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg
COPY . /app
WORKDIR /app
RUN pip install -e ".[bot]"
CMD ["aebndl-bot"]
```
