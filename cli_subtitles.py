#!/usr/bin/env python3
"""Open-source CLI: Burn Reels/Shorts/TikTok dynamic subtitles onto any MP4 via Gemini 3.5 Transcribe + FFmpeg."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import tempfile

from gemini_client import GeminiTranscriber
from media import compute_output_resolution, detect_best_font, extract_audio_mp3, ffprobe_video, render_video
from subtitles import generate_ass, generate_srt, group_words_into_phrases


async def run_cli(args: argparse.Namespace) -> None:
    api_key = args.api_key or os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Set GEMINI_API_KEY or pass --api-key")

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SystemExit(f"Input video not found: {input_path}")

    out_path = Path(args.output).resolve() if args.output else input_path.with_name(f"{input_path.stem}_subtitled.mp4")
    meta = await ffprobe_video(input_path)
    if not meta.has_audio:
        raise SystemExit("Video has no audio track.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        audio_path = tmp_dir / "audio.mp3"
        await extract_audio_mp3(input_path, audio_path)

        transcriber = GeminiTranscriber(api_key)
        tr = await transcriber.transcribe_audio(audio_path)
        if not tr.words:
            raise SystemExit("No speech detected.")

        phrases = group_words_into_phrases(tr.words)
        out_w, out_h = compute_output_resolution(meta, args.circle)
        ass_path = tmp_dir / "subs.ass"
        ass_path.write_text(
            generate_ass(
                phrases,
                width=out_w,
                height=out_h,
                style=args.style,
                is_circle=args.circle,
                font_name=detect_best_font(),
                total_duration=meta.duration,
            ),
            encoding="utf-8",
        )
        local_out = tmp_dir / "out.mp4"
        await render_video(input_path=input_path, out_path=local_out, ass_path=ass_path, is_circle=args.circle)
        out_path.write_bytes(local_out.read_bytes())

        if args.srt:
            srt_path = out_path.with_suffix(".srt")
            srt_path.write_text(generate_srt(phrases), encoding="utf-8")
            print(f"Saved SRT: {srt_path}")
        print(f"Done: {out_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Burn dynamic Reels/Shorts/Circle subtitles with Gemini + FFmpeg")
    p.add_argument("input", help="Path to input video (MP4/MOV)")
    p.add_argument("-o", "--output", help="Output video path")
    p.add_argument("--style", choices=["tiktok", "neon", "clean"], default="tiktok", help="Subtitle preset style")
    p.add_argument("--circle", action="store_true", help="Crop 1:1 640x640 Telegram video note format")
    p.add_argument("--srt", action="store_true", help="Also export .srt file")
    p.add_argument("--api-key", help="Gemini API key (or set GEMINI_API_KEY)")
    asyncio.run(run_cli(p.parse_args()))


if __name__ == "__main__":
    main()
