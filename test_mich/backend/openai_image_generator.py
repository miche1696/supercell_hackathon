from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from backend.tracing import trace_event, trace_span


class OpenAIImageGeneratorError(Exception):
    pass


def _read_key_from_dotenv(project_root: Path) -> Optional[str]:
    dotenv_path = project_root / ".env"
    if not dotenv_path.exists():
        return None

    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key not in {"OPENAI_KEY", "OPENAI_API_KEY"}:
            continue
        if value and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]
        return value.strip() or None
    return None


class OpenAIImageGenerator:
    API_URL = "https://api.openai.com/v1/images/generations"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-image-1.5",
        timeout_seconds: float = 60.0,
        size: str = "1024x1024",
        quality: Optional[str] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.size = size
        self.quality = quality

    @classmethod
    def from_env(cls, project_root: Path, model: str = "gpt-image-1.5") -> Optional["OpenAIImageGenerator"]:
        api_key = os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API_KEY") or _read_key_from_dotenv(project_root)
        if not api_key:
            return None
        configured_model = os.getenv("OPENAI_IMAGE_MODEL") or model
        configured_size = os.getenv("OPENAI_IMAGE_SIZE") or "1024x1024"
        configured_quality = os.getenv("OPENAI_IMAGE_QUALITY")
        return cls(
            api_key=api_key,
            model=configured_model,
            size=configured_size,
            quality=(configured_quality or "high"),
        )

    @staticmethod
    def _normalize_subject(subject: str) -> str:
        text = str(subject or "").replace("_", " ").strip()
        text = re.sub(r"\s+", " ", text)
        return text or "object"

    def build_sprite_prompt(self, subject: str) -> str:
        item_name = self._normalize_subject(subject)
        return (
            "Create a single pixel-art sprite sheet containing exactly 4 frames arranged in a 2x2 grid.\n"
            "The final output image must be perfectly square (1:1 aspect ratio).\n"
            "Each of the 4 frame cells must also be square and equal in size.\n"
            f"Each frame must depict the same pixel-art {item_name} asset at the exact same scale, orientation, "
            "and color palette, with no stylistic variation between frames.\n"
            "Art style:\n"
            "Clean 16-bit / retro pixel art\n"
            "Crisp, square pixels (no anti-aliasing, no blur)\n"
            "Limited color palette (game-ready)\n"
            "Clear silhouette suitable for a 2D game\n"
            "Sprite requirements:\n"
            "Transparent background\n"
            "The subject is centered vertically and horizontally in each frame\n"
            "The subject size and proportions are identical across all 4 frames\n"
            "Keep the entire subject visible inside an imaginary square bounding box in every frame\n"
            "Do not stretch the subject; if it is naturally wide/tall, use transparent padding to keep square framing\n"
            "No camera movement, no zoom, no rotation\n"
            "Animation states in this exact 2x2 layout:\n"
            "Top-left (Frame 1) – Falling: slightly above final ground position, subtle downward motion implied\n"
            "Top-right (Frame 2) – Transition: closer to the ground, minor squash or anticipation of landing\n"
            "Bottom-left (Frame 3) – Landing: touching the ground, slight squash for impact\n"
            "Bottom-right (Frame 4) – Idle / Static: fully landed, neutral resting pose\n"
            "Pose & motion rules:\n"
            "Motion is subtle and believable\n"
            "Only vertical position and slight squash/stretch change\n"
            "No limb repositioning between frames unless minimal and consistent\n"
            "Technical constraints:\n"
            "Sprite sheet must be evenly spaced\n"
            "No text, no UI, no shadows outside the sprite\n"
            "No background elements\n"
            "Designed for seamless looping between frames 1 -> 2 -> 3 -> 4 -> 3 -> 2\n"
            "Overall goal:\n"
            f"A professional, game-ready pixel-art falling animation of a {item_name}, suitable for direct import "
            "into a 2D game engine."
        )

    def _decode_generation_response(self, response_obj: Dict) -> bytes:
        data = response_obj.get("data")
        if not isinstance(data, list) or not data:
            raise OpenAIImageGeneratorError("Image API response missing data")

        first = data[0]
        if not isinstance(first, dict):
            raise OpenAIImageGeneratorError("Image API response has invalid data entry")

        b64_payload = first.get("b64_json")
        if isinstance(b64_payload, str) and b64_payload.strip():
            try:
                return base64.b64decode(b64_payload)
            except Exception as exc:
                raise OpenAIImageGeneratorError(f"Invalid b64_json payload: {exc}") from exc

        image_url = first.get("url")
        if isinstance(image_url, str) and image_url:
            try:
                with urllib.request.urlopen(image_url, timeout=self.timeout_seconds) as response:
                    return response.read()
            except Exception as exc:
                raise OpenAIImageGeneratorError(f"Failed to download generated image URL: {exc}") from exc

        raise OpenAIImageGeneratorError("Image API response missing both b64_json and url")

    def generate_sprite_sheet(self, subject: str, trace_id: Optional[str] = None) -> bytes:
        prompt = self.build_sprite_prompt(subject)
        with trace_span(
            "openai_image_generator",
            "generate_sprite_sheet",
            trace_id=trace_id,
            model=self.model,
            size=self.size,
            quality=self.quality,
            subject=self._normalize_subject(subject),
        ):
            payload = {
                "model": self.model,
                "prompt": prompt,
                "size": self.size,
                "background": "transparent",
                "output_format": "png",
            }
            if self.quality:
                payload["quality"] = self.quality

            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                self.API_URL,
                method="POST",
                data=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )

            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise OpenAIImageGeneratorError(f"OpenAI image HTTP error {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                raise OpenAIImageGeneratorError(f"OpenAI image connection error: {exc}") from exc
            except TimeoutError as exc:
                raise OpenAIImageGeneratorError("OpenAI image request timed out") from exc

            try:
                response_obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise OpenAIImageGeneratorError(f"OpenAI image non-JSON response: {exc}") from exc

            trace_event(
                "openai_image_generator",
                "generate_sprite_sheet.response_shape",
                trace_id=trace_id,
                top_keys=sorted(response_obj.keys()) if isinstance(response_obj, dict) else [],
                data_len=(len(response_obj.get("data", [])) if isinstance(response_obj, dict) else 0),
                background=(response_obj.get("background") if isinstance(response_obj, dict) else None),
                size=(response_obj.get("size") if isinstance(response_obj, dict) else None),
                quality=(response_obj.get("quality") if isinstance(response_obj, dict) else None),
            )

            if not isinstance(response_obj, dict):
                raise OpenAIImageGeneratorError("OpenAI image response must be a JSON object")

            image_bytes = self._decode_generation_response(response_obj)
            if not image_bytes:
                raise OpenAIImageGeneratorError("Generated image is empty")
            return image_bytes
