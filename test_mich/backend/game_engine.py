from __future__ import annotations

import math
import random
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.openai_judge import OpenAIJudge
from backend.tracing import trace_event, trace_span


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\s_-]", " ", value.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    return cleaned.replace(" ", "_")


def singularize(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("ses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def nice_round_weight(value: float) -> int:
    if value <= 1:
        return 1
    exponent = int(math.floor(math.log10(value)))
    magnitude = 10 ** exponent
    normalized = value / magnitude

    if normalized < 1.5:
        nice = 1
    elif normalized < 3.5:
        nice = 2
    elif normalized < 7.5:
        nice = 5
    else:
        nice = 10
    return max(1, int(nice * magnitude))


class AssetPipeline:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.assets_dir = project_root / "assets"
        self.generated_dir = self.assets_dir / "generated"
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.placeholder_source = self.assets_dir / "cat.png"

    def _scan_asset_index(self) -> Dict[str, str]:
        index: Dict[str, str] = {}
        for file_path in self.assets_dir.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if file_path.name.startswith("."):
                continue
            rel = file_path.relative_to(self.project_root).as_posix()
            public_url = "/" + rel
            key = slugify(file_path.stem)
            if key and key not in index:
                index[key] = public_url
        return index

    def resolve_or_generate(self, canonical_name: str, trace_id: Optional[str] = None) -> Dict[str, str]:
        index = self._scan_asset_index()
        canonical_slug = slugify(canonical_name)

        if canonical_slug in index:
            trace_event(
                "assets",
                "resolve_or_generate.hit_exact",
                trace_id=trace_id,
                canonical_name=canonical_name,
                asset_url=index[canonical_slug],
            )
            return {
                "source": "existing",
                "asset_url": index[canonical_slug],
                "asset_slug": canonical_slug,
            }

        tokens = [singularize(t) for t in canonical_slug.split("_") if t]
        for token in tokens:
            if token in index:
                trace_event(
                    "assets",
                    "resolve_or_generate.hit_token",
                    trace_id=trace_id,
                    canonical_name=canonical_name,
                    token=token,
                    asset_url=index[token],
                )
                return {
                    "source": "existing",
                    "asset_url": index[token],
                    "asset_slug": token,
                }

        fallback_slug = canonical_slug or "unknown_item"
        generated_name = f"item_{fallback_slug}.png"
        generated_path = self.generated_dir / generated_name

        if not generated_path.exists():
            if self.placeholder_source.exists():
                shutil.copyfile(self.placeholder_source, generated_path)
                trace_event(
                    "assets",
                    "resolve_or_generate.generated_copy",
                    trace_id=trace_id,
                    canonical_name=canonical_name,
                    generated_path=str(generated_path),
                    source_path=str(self.placeholder_source),
                )
            else:
                raise FileNotFoundError("Missing assets/cat.png placeholder for generation pipeline")
        else:
            trace_event(
                "assets",
                "resolve_or_generate.generated_cache_hit",
                trace_id=trace_id,
                canonical_name=canonical_name,
                generated_path=str(generated_path),
            )

        rel = generated_path.relative_to(self.project_root).as_posix()
        return {
            "source": "generated",
            "asset_url": "/" + rel,
            "asset_slug": fallback_slug,
        }


@dataclass
class GameConfig:
    timer_seconds: int = 60
    start_lives: int = 3
    start_min_weight_g: int = 1
    start_max_weight_g: int = 10_000_000
    max_rules: int = 3
    rule_add_min_turn: int = 3
    max_shrink_factor: float = 0.2
    minimum_enlarge_factor: float = 5.0
    max_progression_actions_per_turn: int = 2
    end_command: str = "time"
    evaluation_min_seconds: float = 3.0
    judge_model: str = "gpt-5-mini"
    hold_allowed_after_turn: int = 5
    hold_thin_boundary_span_g: int = 20_000
    min_max_lock_ratio: float = 100.0


@dataclass
class GameState:
    turn: int = 1
    score: int = 0
    lives: int = 3
    min_g: int = 1
    max_g: int = 10_000_000
    active_rules: List[str] = field(default_factory=list)
    used_input_keys: Set[str] = field(default_factory=set)
    used_canonical: Set[str] = field(default_factory=set)
    range_locked: bool = False
    game_over: bool = False
    game_over_reason: Optional[str] = None


class GameEngine:
    RULE_EXAMPLES = [
        "start with a consonant",
        "start with a vowel",
        "be alive",
        "be food",
        "fit in one hand",
        "have wheels",
        "be made of metal",
        "be a household item",
        "be found outdoors",
        "be used every day",
        "fit in a backpack",
        "be colorful",
    ]

    CONTRADICTIONS = {
        ("start with a consonant", "start with a vowel"),
        ("be alive", "be an object"),
        ("be food", "not be food"),
        ("Starts with consonant", "Starts with vowel"),
        ("Object, not alive", "Is alive"),
        ("Is food", "Not food"),
    }

    SUCCESS_LINES = [
        "Nice one.",
        "That works.",
        "Clean answer.",
        "Perfect fit.",
        "Good pick.",
        "You nailed it.",
        "Sharp move.",
        "Solid call.",
        "On target.",
        "Keep it coming.",
        "That passes.",
        "Good instincts.",
        "You got this.",
        "Clutch answer.",
        "Accurate.",
        "Very good.",
        "Right on.",
        "Great call.",
        "Locked in.",
        "Strong round.",
    ]

    ROAST_LINES = [
        "That guess was wild.",
        "Scale says nope.",
        "Did you even lift that?",
        "Bold. Incorrect, but bold.",
        "That item and this range are enemies.",
        "Your scale privileges are under review.",
        "You just fed chaos to the machine.",
        "Nice try, wrong planet.",
        "That answer tripped over itself.",
        "Range missed by a mile.",
        "I respect the confidence, not the result.",
        "That was a certified miss.",
        "Try again, but with gravity this time.",
        "Nope. The dial cried.",
        "You almost invented new physics.",
        "That answer needs a map.",
        "I asked for accurate, not adventurous.",
        "The scale is disappointed.",
        "That was aggressively wrong.",
        "A swing and a miss.",
        "Close... if we ignore reality.",
        "The range called security.",
        "This is why we test things.",
        "Your guess needs calibration.",
        "You gave the dial trust issues.",
        "Not even the mascot can defend that.",
        "That object said no thanks.",
        "Math did not agree.",
        "You rushed that one, huh?",
        "Respectfully: absolutely not.",
        "That was chaos in text form.",
        "You aimed. Somewhere.",
        "This scale has standards.",
        "Nope. Try less drama, more logic.",
        "That call was heavier than your odds.",
        "I admire the imagination.",
        "The answer was spicy, not correct.",
        "This guess is under investigation.",
        "That range remained undefeated.",
        "Reset and swing smarter.",
    ]

    def __init__(self, project_root: Path, config: Optional[GameConfig] = None) -> None:
        with trace_span("engine", "init", model=(config.judge_model if config else GameConfig().judge_model)):
            self.project_root = project_root
            self.config = config or GameConfig()
            self.rng = random.Random(42)
            self.asset_pipeline = AssetPipeline(project_root)

            self.openai_judge = OpenAIJudge.from_env(project_root=project_root, model=self.config.judge_model)
            if self.openai_judge is None:
                raise RuntimeError("OPENAI_KEY not found. Set OPENAI_KEY in .env or environment.")

            self.state = GameState(
                lives=self.config.start_lives,
                min_g=self.config.start_min_weight_g,
                max_g=self.config.start_max_weight_g,
            )
            trace_event(
                "engine",
                "init.ready",
                model=self.config.judge_model,
                timer_seconds=self.config.timer_seconds,
                start_lives=self.config.start_lives,
                start_min_g=self.config.start_min_weight_g,
                start_max_g=self.config.start_max_weight_g,
                min_max_lock_ratio=self.config.min_max_lock_ratio,
            )

    def reset(self) -> Dict:
        with trace_span("engine", "reset"):
            self.state = GameState(
                lives=self.config.start_lives,
                min_g=self.config.start_min_weight_g,
                max_g=self.config.start_max_weight_g,
            )
            trace_event(
                "engine",
                "reset.state_initialized",
                turn=self.state.turn,
                lives=self.state.lives,
                min_g=self.state.min_g,
                max_g=self.state.max_g,
            )
            return self.public_state()

    def public_state(self) -> Dict:
        return {
            "turn": self.state.turn,
            "score": self.state.score,
            "lives": self.state.lives,
            "min_g": self.state.min_g,
            "max_g": self.state.max_g,
            "active_rules": list(self.state.active_rules),
            "range_locked": self.state.range_locked,
            "game_over": self.state.game_over,
            "game_over_reason": self.state.game_over_reason,
            "config": {
                "timer_seconds": self.config.timer_seconds,
                "start_lives": self.config.start_lives,
                "end_command": self.config.end_command,
                "evaluation_min_seconds": self.config.evaluation_min_seconds,
                "judge_model": self.config.judge_model,
                "hold_allowed_after_turn": self.config.hold_allowed_after_turn,
                "hold_thin_boundary_span_g": self.config.hold_thin_boundary_span_g,
                "min_max_lock_ratio": self.config.min_max_lock_ratio,
            },
        }

    def submit(self, input_text: str, trace_id: Optional[str] = None) -> Dict:
        with trace_span(
            "engine",
            "submit",
            trace_id=trace_id,
            phase="entry",
            input_preview=str(input_text or "")[:120],
            turn=self.state.turn,
        ):
            if self.state.game_over:
                trace_event("engine", "submit.blocked_game_over", trace_id=trace_id, reason=self.state.game_over_reason)
                return {
                    "type": "game_over",
                    "message": "Game is already over. Start a new run.",
                    "state": self.public_state(),
                }

            raw = (input_text or "").strip()
            if not raw:
                trace_event("engine", "submit.empty_input", trace_id=trace_id)
                return {
                    "type": "empty_input",
                    "message": "Type one item to continue.",
                    "state": self.public_state(),
                }

            if raw.lower() == self.config.end_command:
                self.state.game_over = True
                self.state.game_over_reason = "end_command"
                trace_event("engine", "submit.end_command", trace_id=trace_id, command=self.config.end_command)
                return {
                    "type": "end_command",
                    "message": "Run ended by command.",
                    "state": self.public_state(),
                }

            raw_key = slugify(raw) or raw.lower()
            if raw_key in self.state.used_input_keys:
                trace_event(
                    "engine",
                    "submit.duplicate_raw_input",
                    trace_id=trace_id,
                    turn=self.state.turn,
                    raw_input=raw,
                    raw_key=raw_key,
                )
                return {
                    "type": "duplicate_input",
                    "message": f'Word already used: "{raw}". Try a different object.',
                    "canonical_name": raw,
                    "state": self.public_state(),
                }

            return self._run_turn(raw, trace_id=trace_id, raw_key=raw_key)

    def _run_turn(self, raw_input: str, trace_id: Optional[str] = None, raw_key: Optional[str] = None) -> Dict:
        with trace_span("engine", "run_turn", trace_id=trace_id, turn=self.state.turn, raw_input=raw_input):
            judge = None
            last_error: Optional[Exception] = None

            for attempt in range(1, 3):
                try:
                    trace_event("engine", "judge.attempt", trace_id=trace_id, attempt=attempt)
                    raw_judge = self.openai_judge.judge(self._build_turn_context(raw_input), trace_id=trace_id)
                    judge = self._normalize_judge_payload(raw_judge, raw_input)
                    self._validate_judge_payload(judge)
                    trace_event("engine", "judge.ok", trace_id=trace_id, attempt=attempt)
                    break
                except Exception as exc:
                    judge = None
                    last_error = exc
                    trace_event(
                        "engine",
                        "judge.error",
                        trace_id=trace_id,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        error=str(exc),
                        level="ERROR",
                    )

            if judge is None:
                error_msg = f"OpenAI judge failed after retry: {last_error}"
                trace_event("engine", "judge.failed_twice", trace_id=trace_id, error=error_msg, level="ERROR")
                raise RuntimeError(error_msg)

            canonical_name = judge["canonical_name"]
            canonical_key = slugify(canonical_name) or canonical_name.strip().lower() or slugify(raw_input)
            if canonical_key in self.state.used_canonical:
                trace_event(
                    "engine",
                    "submit.duplicate_canonical",
                    trace_id=trace_id,
                    turn=self.state.turn,
                    canonical_name=canonical_name,
                    canonical_key=canonical_key,
                )
                return {
                    "type": "duplicate_input",
                    "message": f'Word already used: "{canonical_name}". Try a different object.',
                    "canonical_name": canonical_name,
                    "state": self.public_state(),
                }
            self.state.used_canonical.add(canonical_key)
            effective_raw_key = raw_key or slugify(raw_input) or raw_input.lower().strip()
            if effective_raw_key:
                self.state.used_input_keys.add(effective_raw_key)

            weight_g = int(judge["estimated_weight_g"])
            asset = self.asset_pipeline.resolve_or_generate(canonical_name, trace_id=trace_id)
            evaluation = self._evaluate_submission(
                estimated_weight_g=weight_g,
                rule_checks=judge["rule_checks"],
                cheating=judge["cheating"],
                cheating_reason=judge.get("cheating_reason"),
            )
            passed = evaluation["passed"]
            rule_fail = evaluation["rule_fail"]
            reason = evaluation["reason"]
            notes = judge.get("notes")

            trace_event(
                "engine",
                "llm_judgment.done",
                trace_id=trace_id,
                canonical_name=canonical_name,
                estimated_weight_g=weight_g,
                reason_short_llm=judge.get("reason_short"),
                rule_fail=rule_fail,
                cheating=evaluation["cheating"],
                cheating_reason=evaluation["cheating_reason"],
                within_range=evaluation["within_range"],
                rules_ok=evaluation["rules_ok"],
                pass_computed=passed,
                failed_rules=evaluation["failed_rules"],
                active_rules=self.state.active_rules,
            )

            progression_actions: List[str] = []

            if passed:
                points = self._points_for_pass()
                self.state.score += points
                progression_actions = self._apply_progression(judge.get("progression_actions", []), trace_id=trace_id)
                ruling = "Correct"
                ui_answer = self._limit_two_lines(judge.get("ui_answer") or self._pick_success_line())
            else:
                self.state.lives -= 1
                ruling = "Wrong"
                ui_answer = self._limit_two_lines(judge.get("ui_answer") or self._pick_roast_line())

            self.state.turn += 1

            if self.state.lives <= 0:
                self.state.game_over = True
                self.state.game_over_reason = "no_lives"

            trace_event(
                "engine",
                "run_turn.result",
                trace_id=trace_id,
                ruling=ruling,
                passed=passed,
                score=self.state.score,
                lives=self.state.lives,
                min_g=self.state.min_g,
                max_g=self.state.max_g,
                progression_actions=progression_actions,
            )

            return {
                "type": "turn_result",
                "ruling": ruling,
                "pass": passed,
                "canonical_name": canonical_name,
                "interpreted_meaning": judge["interpreted_meaning"],
                "weight_g": weight_g,
                "reason": reason,
                "notes": notes,
                "rule_fail": rule_fail,
                "ui_answer": ui_answer,
                "fallback_mode": False,
                "progression_actions": progression_actions,
                "item_asset": {
                    "asset_url": asset["asset_url"],
                    "source": asset["source"],
                    "sprite_sheet": {"cols": 2, "rows": 2},
                },
                "state": self._finalize_state_if_needed(),
            }

    def _build_turn_context(self, raw_input: str) -> Dict[str, Any]:
        return {
            "input_text": raw_input,
            "turn": self.state.turn,
            "range_g": {"min": self.state.min_g, "max": self.state.max_g},
            "active_rules": list(self.state.active_rules),
            "used_canonical_count": len(self.state.used_canonical),
            "used_canonical": sorted(self.state.used_canonical),
            "rule_examples": list(self.RULE_EXAMPLES),
            "rule_design": {
                "goal": "maximize engagement with simple, fun constraints",
                "target_rule_word_count": "2-6 words",
                "prefer_broad_reusable_rules": True,
            },
            "progression": {
                "max_actions": self.config.max_progression_actions_per_turn,
                "rule_add_min_turn": self.config.rule_add_min_turn,
                "max_rules": self.config.max_rules,
                "max_shrink_factor": self.config.max_shrink_factor,
                "minimum_enlarge_factor": self.config.minimum_enlarge_factor,
                "hold_policy": {
                    "allowed_after_turn": self.config.hold_allowed_after_turn,
                    "thin_boundary_span_g": self.config.hold_thin_boundary_span_g,
                    "current_span_g": self._range_span_g(),
                },
            },
            "policy": {
                "plural_without_count_means_one": True,
                "estimate_unknown_anyway": True,
                "explicit_measure_banned": True,
            },
        }

    def _normalize_judge_payload(self, payload: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        canonical_raw = payload.get("canonical_name")
        if not isinstance(canonical_raw, str) or not canonical_raw.strip():
            canonical_raw = raw_input

        interpreted = payload.get("interpreted_meaning")
        if not isinstance(interpreted, str) or not interpreted.strip():
            interpreted = raw_input

        try:
            weight_g = int(round(float(payload.get("estimated_weight_g"))))
        except Exception as exc:
            raise ValueError("estimated_weight_g must be numeric") from exc

        progression_raw = payload.get("progression_actions")
        progression_actions = progression_raw if isinstance(progression_raw, list) else []

        rule_checks_raw = payload.get("rule_checks")
        if not isinstance(rule_checks_raw, list):
            raise ValueError("rule_checks must be a list")

        rule_checks: List[Dict[str, Any]] = []
        for entry in rule_checks_raw:
            if not isinstance(entry, dict):
                raise ValueError("rule_checks entries must be objects")

            rule_raw = entry.get("rule")
            if not isinstance(rule_raw, str) or not rule_raw.strip():
                raise ValueError("rule_checks.rule must be a non-empty string")

            ok_value = self._coerce_bool(entry.get("ok"), "rule_checks.ok")

            reason_raw = entry.get("reason")
            reason_text = reason_raw.strip() if isinstance(reason_raw, str) and reason_raw.strip() else ""

            rule_checks.append(
                {
                    "rule": rule_raw.strip(),
                    "ok": ok_value,
                    "reason": reason_text,
                }
            )

        cheating = self._coerce_bool(payload.get("cheating"), "cheating")
        cheating_reason_raw = payload.get("cheating_reason")
        cheating_reason = (
            cheating_reason_raw.strip()
            if isinstance(cheating_reason_raw, str) and cheating_reason_raw.strip()
            else None
        )

        return {
            "canonical_name": self._canonicalize(canonical_raw),
            "interpreted_meaning": interpreted.strip(),
            "estimated_weight_g": max(1, weight_g),
            "cheating": cheating,
            "cheating_reason": cheating_reason,
            "rule_checks": rule_checks,
            "reason_short": str(payload.get("reason_short", "Judged by LLM."))[:180],
            "notes": payload.get("notes"),
            "ui_answer": payload.get("ui_answer"),
            "progression_actions": progression_actions,
        }

    def _validate_judge_payload(self, payload: Dict[str, Any]) -> None:
        required = [
            "canonical_name",
            "interpreted_meaning",
            "estimated_weight_g",
            "cheating",
            "rule_checks",
            "reason_short",
            "progression_actions",
        ]
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(f"Malformed judge payload, missing: {missing}")

        checks = payload.get("rule_checks")
        if not isinstance(checks, list):
            raise ValueError("Malformed judge payload, rule_checks must be a list")

        checks_by_rule = {
            self._rule_key(str(entry.get("rule", "")))
            for entry in checks
            if isinstance(entry, dict)
        }
        missing_rule_checks = [rule for rule in self.state.active_rules if self._rule_key(rule) not in checks_by_rule]
        if missing_rule_checks:
            raise ValueError(f"Missing rule_checks for active rules: {missing_rule_checks}")

    def _coerce_bool(self, value: Any, field_name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "correct", "pass", "ok"}:
                return True
            if normalized in {"false", "no", "wrong", "fail", "ko"}:
                return False
        raise ValueError(f"{field_name} must be boolean-like")

    def _rule_key(self, value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _evaluate_submission(
        self,
        estimated_weight_g: int,
        rule_checks: List[Dict[str, Any]],
        cheating: bool,
        cheating_reason: Optional[str],
    ) -> Dict[str, Any]:
        within_range = self.state.min_g <= estimated_weight_g <= self.state.max_g

        checks_by_rule: Dict[str, Dict[str, Any]] = {}
        for entry in rule_checks:
            key = self._rule_key(entry.get("rule", ""))
            if key and key not in checks_by_rule:
                checks_by_rule[key] = entry

        failed_rules: List[Dict[str, str]] = []
        for rule in self.state.active_rules:
            check = checks_by_rule.get(self._rule_key(rule))
            if check is None:
                failed_rules.append({"rule": rule, "reason": "Rule evaluation missing from judge."})
                continue

            if not bool(check.get("ok")):
                detail = str(check.get("reason") or "Rule not satisfied.").strip()
                failed_rules.append({"rule": rule, "reason": detail})

        rules_ok = len(failed_rules) == 0
        passed = (not cheating) and within_range and rules_ok

        if cheating:
            reason = str(cheating_reason or "Cheating input: include only object names, no weight expression or bulk material.")
            rule_fail = "cheating"
        elif not within_range:
            reason = f"Estimated {estimated_weight_g} g is outside range {self.state.min_g}-{self.state.max_g} g."
            rule_fail = None
        elif failed_rules:
            first_fail = failed_rules[0]
            reason = f"Rule failed: {first_fail['rule']}."
            detail = first_fail.get("reason", "").strip()
            rule_fail = f"{first_fail['rule']}: {detail}" if detail else first_fail["rule"]
        else:
            reason = "Within range and all active rules satisfied."
            rule_fail = None

        return {
            "passed": passed,
            "reason": reason,
            "rule_fail": rule_fail,
            "cheating": cheating,
            "cheating_reason": cheating_reason,
            "within_range": within_range,
            "rules_ok": rules_ok,
            "failed_rules": failed_rules,
        }

    def _finalize_state_if_needed(self) -> Dict:
        if self.state.lives <= 0 and not self.state.game_over:
            self.state.game_over = True
            self.state.game_over_reason = "no_lives"
        return self.public_state()

    def _points_for_pass(self) -> int:
        if self.state.max_g <= 1000 or len(self.state.active_rules) >= 2:
            return 3
        return 1

    def _canonicalize(self, raw_input: str) -> str:
        text = raw_input.lower().strip()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        text = re.sub(r"^\d+\s+", "", text)
        text = re.sub(r"^(a|an|the)\s+", "", text)

        tokens = [t for t in text.split(" ") if t]
        tokens = [singularize(t) for t in tokens]

        canonical = "_".join(tokens).strip("_")
        return canonical or "unknown_item"

    def _pick_success_line(self) -> str:
        return self.rng.choice(self.SUCCESS_LINES)

    def _pick_roast_line(self) -> str:
        return self.rng.choice(self.ROAST_LINES)

    def _limit_two_lines(self, text: str) -> str:
        lines = str(text or "").splitlines()
        lines = [line.strip() for line in lines if line.strip()]
        if not lines:
            return "..."
        return "\n".join(lines[:2])

    def _is_contradictory(self, candidate: str, existing_rules: List[str]) -> bool:
        candidate_key = self._rule_key(candidate)
        existing_keys = {self._rule_key(rule) for rule in existing_rules}
        for a, b in self.CONTRADICTIONS:
            a_key = self._rule_key(a)
            b_key = self._rule_key(b)
            if (candidate_key == a_key and b_key in existing_keys) or (candidate_key == b_key and a_key in existing_keys):
                return True
        return False

    def _normalize_rule(self, rule: str) -> Optional[str]:
        normalized = re.sub(r"\s+", " ", str(rule or "").strip())
        normalized = normalized.strip(" .;:!?")
        if not normalized:
            return None

        if len(normalized) < 3 or len(normalized) > 64:
            return None

        words = normalized.split(" ")
        if len(words) > 8:
            return None

        lowered = normalized.lower()
        if lowered in {"none", "n/a", "same", "no rule"}:
            return None

        return normalized

    def _normalize_progression_actions(self, actions: List[Any]) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        for entry in actions[: self.config.max_progression_actions_per_turn]:
            if isinstance(entry, str):
                normalized.append({"type": entry.strip().lower()})
                continue

            if isinstance(entry, dict):
                action_type = str(entry.get("type", "")).strip().lower()
                if not action_type:
                    continue
                item: Dict[str, str] = {"type": action_type}
                if "rule" in entry and isinstance(entry.get("rule"), str):
                    item["rule"] = entry["rule"]
                normalized.append(item)

        if not normalized:
            normalized = [{"type": "hold"}]
        return normalized

    def _range_span_g(self) -> int:
        return max(0, self.state.max_g - self.state.min_g)

    def _lock_target_max_g(self) -> int:
        ratio_target = int(math.ceil(self.state.min_g * self.config.min_max_lock_ratio))
        return max(self.state.min_g + 1, ratio_target)

    def _should_lock_range(self) -> bool:
        return self.state.max_g <= self._lock_target_max_g()

    def _lock_range(self, trace_id: Optional[str] = None, source: str = "unknown") -> str:
        old_min = self.state.min_g
        old_max = self.state.max_g

        self.state.max_g = self._lock_target_max_g()
        self.state.range_locked = True

        trace_event(
            "engine",
            "progression.range_locked",
            trace_id=trace_id,
            source=source,
            min_max_lock_ratio=self.config.min_max_lock_ratio,
            old_min_g=old_min,
            old_max_g=old_max,
            locked_min_g=self.state.min_g,
            locked_max_g=self.state.max_g,
        )
        return f"lock_range:max={self.state.max_g}"

    def _hold_allowed_now(self) -> bool:
        return (
            self.state.turn > self.config.hold_allowed_after_turn
            and self._range_span_g() <= self.config.hold_thin_boundary_span_g
        )

    def _apply_progression(self, proposed_actions: List[Any], trace_id: Optional[str] = None) -> List[str]:
        old_min = self.state.min_g
        old_max = self.state.max_g
        old_rules = list(self.state.active_rules)

        actions = self._normalize_progression_actions(proposed_actions)
        applied: List[str] = []

        if not self.state.range_locked and self._should_lock_range():
            applied.append(self._lock_range(trace_id=trace_id, source="pre_progression"))

        trace_event(
            "engine",
            "progression.start",
            trace_id=trace_id,
            proposed_actions=proposed_actions,
            normalized_actions=actions,
            start_min=old_min,
            start_max=old_max,
            start_rules=old_rules,
        )

        for action in actions:
            action_type = action.get("type", "")

            if action_type == "hold":
                if self.state.range_locked:
                    applied.append("hold_skipped_range_locked")
                    continue

                if self._hold_allowed_now():
                    applied.append("hold")
                    continue

                span_before = self._range_span_g()
                new_max = nice_round_weight(self.state.max_g * self.config.max_shrink_factor)
                self.state.max_g = max(self.state.min_g + 1, new_max)
                applied.append("hold_replaced_with_shrink_max")
                trace_event(
                    "engine",
                    "progression.hold_replaced",
                    trace_id=trace_id,
                    turn=self.state.turn,
                    span_before_g=span_before,
                    span_after_g=self._range_span_g(),
                    hold_allowed_after_turn=self.config.hold_allowed_after_turn,
                    hold_thin_boundary_span_g=self.config.hold_thin_boundary_span_g,
                )
                continue

            if action_type == "shrink_max":
                if self.state.range_locked:
                    applied.append("shrink_max_skipped_range_locked")
                    continue

                new_max = nice_round_weight(self.state.max_g * self.config.max_shrink_factor)
                self.state.max_g = max(self.state.min_g + 1, new_max)
                applied.append("shrink_max")
                if self._should_lock_range():
                    applied.append(self._lock_range(trace_id=trace_id, source="shrink_max"))
                    break
                continue

            if action_type == "raise_min":
                if self.state.range_locked:
                    applied.append("raise_min_skipped_range_locked")
                    continue

                new_min = nice_round_weight(self.state.min_g * self.config.minimum_enlarge_factor)
                self.state.min_g = max(1, new_min)
                applied.append("raise_min")
                if self._should_lock_range():
                    applied.append(self._lock_range(trace_id=trace_id, source="raise_min"))
                    break
                continue

            if action_type == "add_rule":
                if self.state.turn < self.config.rule_add_min_turn:
                    applied.append("add_rule_skipped_too_early")
                    continue
                if len(self.state.active_rules) >= self.config.max_rules:
                    applied.append("add_rule_skipped_max_rules")
                    continue

                rule_candidate = action.get("rule", "")
                normalized_rule = self._normalize_rule(rule_candidate)
                if normalized_rule is None:
                    applied.append("add_rule_skipped_invalid_rule")
                    continue
                if normalized_rule in self.state.active_rules:
                    applied.append("add_rule_skipped_duplicate")
                    continue
                if self._is_contradictory(normalized_rule, self.state.active_rules):
                    applied.append("add_rule_skipped_contradiction")
                    continue

                self.state.active_rules.append(normalized_rule)
                applied.append(f"add_rule:{normalized_rule}")
                continue

            applied.append(f"unknown_action:{action_type}")

        if not self.state.range_locked and self._should_lock_range():
            applied.append(self._lock_range(trace_id=trace_id, source="post_progression"))

        if self.state.min_g >= self.state.max_g:
            self.state.min_g = old_min
            self.state.max_g = old_max
            self.state.active_rules = old_rules
            trace_event(
                "engine",
                "progression.invalid_bounds_fallback",
                trace_id=trace_id,
                restored_min=self.state.min_g,
                restored_max=self.state.max_g,
                restored_rules=self.state.active_rules,
                level="WARNING",
            )
            return ["hold_fallback_invalid_bounds"]

        trace_event(
            "engine",
            "progression.end",
            trace_id=trace_id,
            applied_actions=applied,
            end_min=self.state.min_g,
            end_max=self.state.max_g,
            end_rules=self.state.active_rules,
        )
        return applied if applied else ["hold"]
