from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from backend.tracing import trace_event, trace_span


class OpenAIJudgeError(Exception):
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


def _extract_json_object(text: str) -> Dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise OpenAIJudgeError("No JSON object found in model output")
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise OpenAIJudgeError(f"Invalid JSON from model: {exc}") from exc


class OpenAIJudge:
    API_URL = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, model: str = "gpt-5-mini", timeout_seconds: float = 25.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls, project_root: Path, model: str = "gpt-5-mini") -> Optional["OpenAIJudge"]:
        api_key = os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API_KEY") or _read_key_from_dotenv(project_root)
        if not api_key:
            return None
        return cls(api_key=api_key, model=model)

    def _build_system_prompt(self) -> str:
        return (
            "You are the game judge for 'Bribe the Scale'. "
            "Return ONE strict JSON object only, no markdown.\n\n"
            "Rules:\n"
            "- Interpret one user noun phrase.\n"
            "- If no quantity is specified, assume quantity 1.\n"
            "- Plural without count means one item.\n"
            "- Estimate weight by common-person intuition in grams.\n"
            "- Canonicalize to a stable canonical_name for no-repeat checks.\n"
            "- Mark cheating=true for explicit measure phrases (kg, g, lbs, ml, liters, etc.).\n"
            "- Mark cheating=true for bulk material entries without a clear container/object "
            "(e.g., flour, sand, sugar, water).\n"
            "- Example cheating inputs: '1 kg', '500g rice', 'flour'.\n"
            "- Example not cheating: clear object nouns like 'cat', 'bicycle', 'spoon', 'the golden gate bridge'.\n"
            "- Reject trick phrasings like exact-target self-reference.\n"
            "- Unknown items should still get a best estimate.\n"
            "- ui_answer should be short roast/funny style, max 2 lines.\n"
            "- progression_actions can include up to 2 actions.\n"
            "- Allowed progression action types: hold, shrink_max, raise_min, add_rule.\n"
            "- For add_rule, freely invent one new rule phrase.\n"
            "- turn_context.rule_examples are inspiration, NOT a fixed list.\n"
            "- New rules should be simple, clear, and quickly judgeable by common sense.\n"
            "- Keep each individual rule easy (usually 2-6 words); difficulty should come from combining rules.\n"
            "- Any add_rule text must read as a continuation of: 'The item must ...'.\n"
            "- Write rule text as a short verb phrase, not a noun label.\n"
            "- Good examples: 'be alive', 'have wheels', 'fit in one hand', "
            "'start with the letter B', 'be made of metal'.\n"
            "- Avoid fragments like 'alive' or 'metal object'.\n"
            "- For add_rule selection, IGNORE the latest input_text and previous submitted words.\n"
            "- Do not derive the new rule from recently guessed objects.\n"
            "- Just propose one generally useful, independent rule for the level.\n"
            "- Avoid obscure, niche, unsafe, hateful, sexual, or demeaning rule ideas.\n\n"
            "- A 'Howl's Moving Castle' is a reference to tokyo's author 'Hayao Miyazak' and should be considered as a tokyo flying object"
            "- Do NOT output a final pass/fail verdict.\n"
            "- Evaluate each active rule independently and output rule_checks.\n"
            "- rule_checks must include exactly one entry for each active rule.\n"
            "- Keep the rule text unchanged from active_rules when returning rule_checks.\n"
            "- Respect progression.hold_policy from turn context.\n"
            "- Use hold only when turn is greater than hold_policy.allowed_after_turn "
            "and hold_policy.current_span_g is less than or equal to hold_policy.thin_boundary_span_g.\n"
            "- If hold is not allowed yet, prefer shrink_max or raise_min.\n\n"
            "Output JSON keys:\n"
            "canonical_name: string\n"
            "interpreted_meaning: string\n"
            "estimated_weight_g: integer\n"
            "cheating: boolean\n"
            "cheating_reason: string or null\n"
            "rule_checks: array of objects with keys:\n"
            "  rule: string\n"
            "  ok: boolean\n"
            "  reason: string\n"
            "reason_short: string\n"
            "notes: string or null\n"
            "ui_answer: string or null\n"
            "progression_actions: array (max 2) of objects with keys:\n"
            "  type: one of hold|shrink_max|raise_min|add_rule\n"
            "  rule: string (required only for add_rule)\n"
        )

    @staticmethod
    def _extract_text_value(value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            candidate = value.get("value")
            if isinstance(candidate, str):
                return candidate
        return ""

    @classmethod
    def _collect_output_text(cls, response_obj: Dict) -> str:
        if isinstance(response_obj.get("output_text"), str) and response_obj["output_text"].strip():
            return response_obj["output_text"]

        output = response_obj.get("output", [])
        parts = []
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                for content in item.get("content", []) or []:
                    if not isinstance(content, dict):
                        continue
                    ctype = content.get("type")
                    if ctype in {"output_text", "text"}:
                        text = cls._extract_text_value(content.get("text"))
                        if isinstance(text, str) and text.strip():
                            parts.append(text)
                    elif ctype == "refusal":
                        refusal = cls._extract_text_value(content.get("refusal"))
                        if refusal.strip():
                            parts.append(refusal)
        return "\n".join(parts).strip()

    def judge(self, turn_context: Dict, trace_id: Optional[str] = None) -> Dict:
        with trace_span(
            "openai_judge",
            "judge",
            trace_id=trace_id,
            model=self.model,
            turn=turn_context.get("turn"),
            input_preview=str(turn_context.get("input_text", ""))[:120],
        ):
            payload = {
                "model": self.model,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": self._build_system_prompt()}]},
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": json.dumps(turn_context, ensure_ascii=False)}],
                    },
                ],
                "max_output_tokens": 1800,
                "reasoning": {"effort": "minimal"},
                "text": {"format": {"type": "json_object"}},
            }

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
                raise OpenAIJudgeError(f"OpenAI HTTP error {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                raise OpenAIJudgeError(f"OpenAI connection error: {exc}") from exc
            except TimeoutError as exc:
                raise OpenAIJudgeError("OpenAI request timed out") from exc

            try:
                response_obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise OpenAIJudgeError(f"OpenAI non-JSON response: {exc}") from exc

            output_items = response_obj.get("output") if isinstance(response_obj, dict) else None
            first_item = output_items[0] if isinstance(output_items, list) and output_items else {}
            content = first_item.get("content") if isinstance(first_item, dict) else []
            content_types = []
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict):
                        content_types.append(str(c.get("type")))

            trace_event(
                "openai_judge",
                "judge.response_shape",
                trace_id=trace_id,
                status=(response_obj.get("status") if isinstance(response_obj, dict) else None),
                incomplete_details=(response_obj.get("incomplete_details") if isinstance(response_obj, dict) else None),
                top_keys=sorted(response_obj.keys()) if isinstance(response_obj, dict) else [],
                output_len=(len(output_items) if isinstance(output_items, list) else 0),
                first_output_type=(first_item.get("type") if isinstance(first_item, dict) else None),
                content_types=content_types,
            )

            text = self._collect_output_text(response_obj)
            if not text:
                trace_event(
                    "openai_judge",
                    "judge.response_missing_text",
                    trace_id=trace_id,
                    level="ERROR",
                    response_preview=raw,
                )
                raise OpenAIJudgeError("OpenAI response had no text output")

            parsed = _extract_json_object(text)
            trace_event(
                "openai_judge",
                "judge.response_parsed",
                trace_id=trace_id,
                keys=sorted(parsed.keys()),
                output_chars=len(text),
            )
            return parsed
