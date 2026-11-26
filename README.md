# Auto Reels Captions CLI (Gemini + FFmpeg ASS)

Open-source CLI to burn **CapCut / Reels / TikTok-style dynamic word-highlighted subtitles** and **640×640 Telegram video circles («кружочки»)** onto any MP4/MOV video — zero monthly subscription, zero center watermarks.

## 👉 Don't want to install Python, FFmpeg, or manage API keys?
**Try the ready-to-use Telegram bot without any setup (2 free videos):**  
➡️ **[Open @railway_robot in Telegram](https://t.me/railway_robot?start=github)**

## Why this exists
- CapCut moved Auto Captions behind CapCut Pro.
- Most web captioners add watermarks or cap free exports.
- This script uses `gemini-3.5-transcribe` word-level timestamps (`100ms` precision across 85+ languages) + `FFmpeg/libass` to generate crisp animated `.ass` subtitles and optional `.srt` exports locally.

## Features
- **3 built-in styles:** `tiktok` (yellow active word pop), `neon` (neon green highlight), `clean` (subtle boxed captions).
- **1-command Video Circle (`--circle`):** crops center 1:1 `640×640` formatted for Telegram video notes with safe circular subtitle margins.
- **`.SRT` export (`--srt`):** saves standard `.srt` alongside the rendered video.

## Requirements
- Python 3.11+
- `ffmpeg` and `ffprobe` on `PATH` (with `libass` enabled, standard in Linux/macOS/Windows full builds)
- Free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)

## Quick Start
```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your_api_key"

# Burn Reels/Shorts style subtitles + save .srt
python cli_subtitles.py video.mp4 --style tiktok --srt

# Convert to 640x640 Telegram video circle with Neon captions
python cli_subtitles.py video.mp4 --circle --style neon
```
