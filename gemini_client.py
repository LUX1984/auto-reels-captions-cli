from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
from pathlib import Path
import aiohttp
from aiohttp_socks import ProxyConnector

from subtitles import WordTiming, extract_word_timings


class GeminiQuotaError(RuntimeError):
    pass


class GeminiAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriptionResult:
    full_text: str
    words: list[WordTiming]
    raw_annotations: list[dict]


class GeminiTranscriber:
    BASE_URL = "https://generativelanguage.googleapis.com"
    MODEL = "gemini-3.5-transcribe"

    def __init__(self, api_key: str, timeout_sec: int = 90, proxy_url: str = "") -> None:
        self.api_key = api_key
        self.proxy_url = proxy_url.strip()
        self.timeout = aiohttp.ClientTimeout(total=timeout_sec)

    async def transcribe_audio(self, audio_path: Path, mime_type: str = "audio/mp3") -> TranscriptionResult:
        raw_bytes = audio_path.read_bytes()
        if not raw_bytes:
            raise GeminiAPIError("Empty audio file")

        connector = ProxyConnector.from_url(self.proxy_url, rdns=True) if self.proxy_url else None
        async with aiohttp.ClientSession(timeout=self.timeout, connector=connector) as session:
            if len(raw_bytes) <= 8 * 1024 * 1024:
                audio_part = {
                    "type": "audio",
                    "data": base64.b64encode(raw_bytes).decode("ascii"),
                    "mime_type": mime_type,
                }
            else:
                file_uri, uploaded_mime = await self._upload_file(session, raw_bytes, mime_type)
                audio_part = {
                    "type": "audio",
                    "uri": file_uri,
                    "mime_type": uploaded_mime,
                }

            payload = {
                "model": self.MODEL,
                "input": [audio_part],
                "generation_config": {
                    "transcription_config": {
                        "mode": {
                            "type": "verbatim",
                            "timestamp_granularities": ["word"],
                        }
                    }
                },
            }
            data = await self._post_interaction_with_retry(session, payload)

        full_text = ""
        raw_annotations: list[dict] = []
        for step in data.get("steps", []):
            for item in step.get("content", []):
                if item.get("type") == "text" or "text" in item:
                    if item.get("text"):
                        full_text += item["text"]
                    if item.get("annotations"):
                        raw_annotations.extend(item["annotations"])

        words = extract_word_timings(raw_annotations)
        return TranscriptionResult(
            full_text=full_text.strip(),
            words=words,
            raw_annotations=raw_annotations,
        )

    async def _post_interaction_with_retry(
        self,
        session: aiohttp.ClientSession,
        payload: dict,
        max_attempts: int = 3,
    ) -> dict:
        url = f"{self.BASE_URL}/v1beta/interactions"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        last_err = ""
        for attempt in range(max_attempts):
            async with session.post(url, headers=headers, json=payload) as resp:
                text = await resp.text()
                if resp.status == 200:
                    return json.loads(text)
                last_err = f"HTTP {resp.status}: {text[:300]}"
                if resp.status == 429:
                    if "limit: 0" in text:
                        raise GeminiQuotaError(last_err)
                    if attempt + 1 < max_attempts:
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue
                    raise GeminiQuotaError(last_err)
                if resp.status >= 500 and attempt + 1 < max_attempts:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise GeminiAPIError(last_err)
        raise GeminiAPIError(last_err)

    async def _upload_file(
        self,
        session: aiohttp.ClientSession,
        raw_bytes: bytes,
        mime_type: str,
    ) -> tuple[str, str]:
        start_headers = {
            "x-goog-api-key": self.api_key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(raw_bytes)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        }
        async with session.post(
            f"{self.BASE_URL}/upload/v1beta/files",
            headers=start_headers,
            json={"file": {"display_name": "subcircle_audio"}},
        ) as r:
            if r.status >= 400:
                raise GeminiAPIError(f"Files API start error {r.status}: {await r.text()}")
            upload_url = r.headers.get("X-Goog-Upload-URL")
            if not upload_url:
                raise GeminiAPIError("Missing X-Goog-Upload-URL")

        up_headers = {
            "Content-Length": str(len(raw_bytes)),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        }
        async with session.post(upload_url, headers=up_headers, data=raw_bytes) as r2:
            body2 = await r2.text()
            if r2.status >= 400:
                raise GeminiAPIError(f"Files API upload error {r2.status}: {body2}")
            info = json.loads(body2)
            file_obj = info.get("file", info)
            return file_obj["uri"], file_obj.get("mimeType", mime_type)
