from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class WordTiming:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Phrase:
    words: tuple[WordTiming, ...]
    start: float
    end: float


def parse_offset_seconds(value: str | float | int | None) -> float:
    """Parse Gemini duration strings such as '0.200s' or '1s' into seconds."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    cleaned = str(value).strip().lower()
    if cleaned.endswith("s"):
        cleaned = cleaned[:-1]
    try:
        return max(0.0, float(cleaned))
    except ValueError:
        return 0.0


def extract_word_timings(annotations: list[dict] | None) -> list[WordTiming]:
    """Convert Gemini `word_info` annotations into monotonic WordTiming items."""
    if not annotations:
        return []
    result: list[WordTiming] = []
    last_end = 0.0
    for ann in annotations:
        if ann.get("type") != "word_info":
            continue
        text = str(ann.get("text", "")).strip()
        if not text:
            continue
        start = parse_offset_seconds(ann.get("start_offset"))
        end = parse_offset_seconds(ann.get("end_offset"))
        if start < last_end:
            start = last_end
        if end <= start:
            end = start + 0.18
        result.append(WordTiming(text=text, start=start, end=end))
        last_end = end
    return result


def group_words_into_phrases(
    words: list[WordTiming],
    max_words: int = 3,
    max_chars: int = 20,
    max_pause: float = 0.45,
) -> list[Phrase]:
    """Group word timings into punchy mobile-friendly phrases."""
    if not words:
        return []
    phrases: list[Phrase] = []
    buf: list[WordTiming] = []

    def flush() -> None:
        if buf:
            phrases.append(Phrase(words=tuple(buf), start=buf[0].start, end=buf[-1].end))
            buf.clear()

    for w in words:
        if buf:
            prev = buf[-1]
            pause = w.start - prev.end
            cur_chars = sum(len(x.text) for x in buf) + len(buf) + len(w.text)
            ends_sentence = prev.text.endswith((".", "!", "?", "…", ",", ";", ":"))
            if pause > max_pause or len(buf) >= max_words or cur_chars > max_chars or ends_sentence:
                flush()
        buf.append(w)

    flush()
    return phrases


def _format_ass_time(seconds: float) -> str:
    total_cs = max(0, round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _format_srt_time(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _escape_ass(text: str) -> str:
    text = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return re.sub(r"\s+", " ", text).strip()


def _style_config(style: str, width: int, height: int, is_circle: bool) -> dict[str, object]:
    short_side = min(width, height)
    if is_circle:
        font_size = 38
        margin_v = 104
        margin_lr = 92
    elif height > width:
        font_size = max(34, min(68, int(short_side * 0.058)))
        margin_v = int(height * 0.20)
        margin_lr = max(48, int(width * 0.07))
    else:
        font_size = max(30, min(58, int(short_side * 0.062)))
        margin_v = int(height * 0.10)
        margin_lr = max(60, int(width * 0.08))

    if style == "neon":
        return {
            "font_size": font_size,
            "margin_v": margin_v,
            "margin_lr": margin_lr,
            "primary": "&H00FFFFFF",
            "highlight": "&H0066FF55&",  # BGR neon green
            "outline_color": "&H00000000",
            "back_color": "&H90000000",
            "border_style": 1,
            "outline": 4,
            "shadow": 2,
            "bold": -1,
            "upper": True,
            "pop": True,
        }
    if style == "clean":
        return {
            "font_size": max(28, int(font_size * 0.88)),
            "margin_v": margin_v,
            "margin_lr": margin_lr,
            "primary": "&H00FFFFFF",
            "highlight": "&H00FFD24C&",  # BGR warm gold
            "outline_color": "&H88000000",
            "back_color": "&H88000000",
            "border_style": 3,
            "outline": 8,
            "shadow": 0,
            "bold": -1,
            "upper": False,
            "pop": False,
        }
    # Default: tiktok
    return {
        "font_size": font_size,
        "margin_v": margin_v,
        "margin_lr": margin_lr,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000E5FF&",  # BGR vivid yellow
        "outline_color": "&H00000000",
        "back_color": "&H80000000",
        "border_style": 1,
        "outline": 5,
        "shadow": 2,
        "bold": -1,
        "upper": True,
        "pop": True,
    }


def generate_ass(
    phrases: list[Phrase],
    width: int,
    height: int,
    style: str = "tiktok",
    is_circle: bool = False,
    watermark_text: str | None = None,
    font_name: str = "DejaVu Sans",
    total_duration: float = 180.0,
) -> str:
    """Build an ASS subtitle script with active-word highlighting and safe margins."""
    cfg = _style_config(style, width, height, is_circle)
    wm_size = 20 if is_circle else max(20, min(30, int(min(width, height) * 0.028)))
    wm_align = 3
    wm_margin_v = 68 if is_circle else max(28, int(height * 0.04))
    wm_margin_r = 135 if is_circle else max(24, int(width * 0.035))

    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            (
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
                "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
                "MarginL, MarginR, MarginV, Encoding"
            ),
            (
                f"Style: Default,{font_name},{cfg['font_size']},{cfg['primary']},&H000000FF,"
                f"{cfg['outline_color']},{cfg['back_color']},{cfg['bold']},0,0,0,100,100,0,0,"
                f"{cfg['border_style']},{cfg['outline']},{cfg['shadow']},2,"
                f"{cfg['margin_lr']},{cfg['margin_lr']},{cfg['margin_v']},1"
            ),
            (
                f"Style: Watermark,{font_name},{wm_size},&H22FFFFFF,&H000000FF,"
                f"&H55000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,1,{wm_align},"
                f"20,{wm_margin_r},{wm_margin_v},1"
            ),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    events: list[str] = []
    if watermark_text:
        wm_end = max(1.0, total_duration + 2.0)
        events.append(
            f"Dialogue: 1,0:00:00.00,{_format_ass_time(wm_end)},Watermark,,0,0,0,,{_escape_ass(watermark_text)}"
        )

    for idx, phrase in enumerate(phrases):
        words = phrase.words
        next_phrase_start = phrases[idx + 1].start if idx + 1 < len(phrases) else phrase.end + 0.25
        for wi, w in enumerate(words):
            seg_start = w.start
            if wi + 1 < len(words):
                seg_end = max(seg_start + 0.06, words[wi + 1].start)
            else:
                seg_end = min(max(w.end + 0.14, seg_start + 0.18), next_phrase_start)

            rendered_tokens: list[str] = []
            for ti, tok in enumerate(words):
                txt = _escape_ass(tok.text.upper() if cfg["upper"] else tok.text)
                if ti == wi:
                    if cfg["pop"]:
                        rendered_tokens.append(
                            f"{{\\c{cfg['highlight']}\\fscx108\\fscy108}}{txt}{{\\r}}"
                        )
                    else:
                        rendered_tokens.append(f"{{\\c{cfg['highlight']}}}{txt}{{\\r}}")
                else:
                    rendered_tokens.append(txt)
            line = " ".join(rendered_tokens)
            events.append(
                f"Dialogue: 0,{_format_ass_time(seg_start)},{_format_ass_time(seg_end)},Default,,0,0,0,,{line}"
            )

    return header + "\n" + "\n".join(events) + "\n"


def generate_srt(phrases: list[Phrase]) -> str:
    """Build a standard SRT file from grouped phrases."""
    blocks: list[str] = []
    for i, p in enumerate(phrases, start=1):
        text = " ".join(w.text for w in p.words)
        blocks.append(f"{i}\n{_format_srt_time(p.start)} --> {_format_srt_time(p.end)}\n{text}\n")
    return "\n".join(blocks)
