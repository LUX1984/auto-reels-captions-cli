from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import time


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoMeta:
    width: int
    height: int
    duration: float
    has_audio: bool


async def _run_cmd(args: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise MediaError("FFmpeg/FFprobe timeout")
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


async def ffprobe_video(path: Path) -> VideoMeta:
    rc, out, err = await _run_cmd(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        timeout=30,
    )
    if rc != 0:
        raise MediaError(f"Не удалось прочитать видеофайл: {err[:200]}")

    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise MediaError(f"Повреждённые метаданные видео: {exc}") from exc

    streams = data.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v_stream:
        raise MediaError("В файле не найдена видеодорожка.")

    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    width = int(v_stream.get("width") or 0)
    height = int(v_stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise MediaError("Некорректное разрешение видео.")

    # Respect rotation metadata if present
    rotation = 0
    for tag in (v_stream.get("tags") or {}).items():
        if tag[0].lower() == "rotate":
            try:
                rotation = int(tag[1])
            except ValueError:
                pass
    for sd in v_stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rotation = int(sd["rotation"])
            except (TypeError, ValueError):
                pass
    if abs(rotation) in {90, 270}:
        width, height = height, width

    dur_raw = v_stream.get("duration") or (data.get("format") or {}).get("duration") or 0
    try:
        duration = float(dur_raw)
    except (TypeError, ValueError):
        duration = 0.0

    return VideoMeta(width=width, height=height, duration=duration, has_audio=has_audio)


async def extract_audio_mp3(video_path: Path, audio_path: Path) -> str:
    """Extract 16kHz mono MP3 audio and return its SHA256 hex digest."""
    rc, _, err = await _run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "48k",
            str(audio_path),
        ],
        timeout=60,
    )
    if rc != 0 or not audio_path.exists() or audio_path.stat().st_size == 0:
        raise MediaError(f"Не удалось извлечь аудиодорожку: {err[-250:]}")
    return hashlib.sha256(audio_path.read_bytes()).hexdigest()


def detect_best_font() -> str:
    """Pick an installed Cyrillic-capable bold sans font on Linux."""
    candidates = [
        ("Montserrat", "/usr/share/fonts/truetype/montserrat"),
        ("Roboto", "/usr/share/fonts/truetype/roboto"),
        ("Ubuntu", "/usr/share/fonts/truetype/ubuntu"),
        ("DejaVu Sans", "/usr/share/fonts/truetype/dejavu"),
    ]
    for name, folder in candidates:
        if Path(folder).exists():
            return name
    return "DejaVu Sans"


async def render_video(
    *,
    input_path: Path,
    out_path: Path,
    ass_path: Path | None = None,
    is_circle: bool = False,
) -> None:
    """Render subtitled video or 640x640 Telegram Video Note (low-RAM 1-thread tuned)."""
    job_dir = out_path.parent
    filters: list[str] = []
    if is_circle:
        filters.append("scale=640:640:force_original_aspect_ratio=increase,crop=640:640")
    else:
        filters.append("scale='min(720,iw)':-2:flags=bilinear")

    if ass_path is not None:
        # Run ffmpeg with cwd=job_dir so relative filename needs zero escaping
        filters.append(f"ass={ass_path.name}")

    cmd = [
        "ffmpeg",
        "-y",
        "-threads",
        "1",
        "-i",
        str(input_path.resolve()),
    ]
    if is_circle:
        cmd.extend(["-t", "60"])
    cmd.extend(
        [
            "-vf",
            ",".join(filters),
            "-c:v",
            "libx264",
            "-preset",
            "superfast",
            "-crf",
            "24" if is_circle else "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k" if is_circle else "128k",
            "-movflags",
            "+faststart",
            str(out_path.resolve()),
        ]
    )

    rc, _, err = await _run_cmd(cmd, cwd=job_dir, timeout=180)
    if rc != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise MediaError(f"Ошибка рендера FFmpeg: {err[-300:]}")


def compute_output_resolution(meta: VideoMeta, is_circle: bool) -> tuple[int, int]:
    if is_circle:
        return 640, 640
    if meta.width > 720:
        scaled_h = int(round(meta.height * (720 / meta.width)))
        if scaled_h % 2 != 0:
            scaled_h += 1
        return 720, scaled_h
    w = meta.width if meta.width % 2 == 0 else meta.width + 1
    h = meta.height if meta.height % 2 == 0 else meta.height + 1
    return w, h


def cleanup_old_workdirs(work_dir: Path, max_age_sec: int = 1200) -> int:
    """Remove stale temp job directories to prevent disk fill-up."""
    if not work_dir.exists():
        return 0
    now = time.time()
    removed = 0
    for child in work_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            if now - child.stat().st_mtime > max_age_sec:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            pass
    return removed
