# Bribe the Scale (Solo) - Final Game Design (Demo Build)

## 1) Scope and Goal
- Build a polished, video-ready desktop-browser demo in a few hours.
- Keep the architecture simple and resilient.
- Prioritize clear gameplay loop: `input -> evaluate -> drop -> weigh -> verdict -> next turn`.

## 2) Final Product Decisions
- Session: one continuous run until game over.
- Game over triggers:
- timer reaches 0
- lives reaches 0
- player sends end command (`time`, case-insensitive, trimmed)
- Empty input: does not consume life, prompt again.
- Timer keeps running when tab is unfocused.
- Pause with `Esc`: pauses timer, animations, and input.
- Warning at 10 seconds, plus `5-4-3-2-1` countdown.
- Platform target: desktop browser demo only.
- Mobile support: not required.
- Visual style: cute retro arcade pixel hybrid.
- Physics style: stylized tweened drop (not heavy real physics).

## 3) Core Gameplay Rules
- Each turn asks for one item within `[MIN_G, MAX_G]` and active rules (0-3).
- Player submits one noun phrase.
- Judge returns structured interpretation and estimate.
- Deterministic validator decides final pass/fail.
- On pass:
- add score
- store canonical class in used set
- apply progression updates
- On fail:
- lose 1 life
- constraints unchanged

## 4) Canonicalization and Input Interpretation
- Canonical class is tracked for no-repeat logic.
- Canonicalization:
- strip quantity and explicit unit fragments
- collapse minor adjectives
- keep meaningful subtype changes
- keep meaningful personalization if physically coherent
- Quantity defaults to 1.
- Plural without count defaults to one (`apples` -> one apple).
- Unknown/variable objects: estimate anyway by common-person intuition.
- Fictional/coherent items allowed if physically interpretable.

## 5) Anti-Cheat and Validity
- Reject explicit mass/volume in player text.
- Reject bulk materials without count.
- Reject self-referential exact-target phrasing.
- Reject paradox/non-real objects.
- Reject repeated canonical class (only passed items are tracked).

## 6) Rule System
- Max active rules: 3.
- Add rules only from turn 3 onward.
- Never add contradictory rules.
- If already at max rules and LLM proposes add-rule: skip rule add (no replacement).
- Rule allowlist:
- Starts with consonant
- Starts with vowel
- Starts with [LETTER]
- Object, not alive
- Is alive
- Is food
- Not food
- Fits in hand
- Has wheels
- Made of metal
- Made of wood
- Household item

## 7) Difficulty Progression (LLM-Guided with Guardrails)
- LLM can apply up to 2 progression actions after a correct turn.
- Allowed actions:
- shrink max (`MAX_G = round(MAX_G * max_shrink_factor)`)
- raise min (`MIN_G = round(MIN_G * minimum_enlarge_factor)`)
- add one new non-contradictory rule (if slot available)
- hold
- Config defaults:
- `max_shrink_factor = 0.1`
- `minimum_enlarge_factor = 10`
- If LLM proposes invalid bounds (`MIN_G >= MAX_G`): backend auto-fallback to previous bounds and hold.
- No probabilistic constraints required; LLM has freedom, backend enforces safety.

## 8) Scoring
- Base score on pass: `+1`.
- High-difficulty score: `+3` instead of `+1` when:
- `MAX_G <= 1000`, or
- active rules >= 2
- Fail: `+0`.
- Show only total score.

## 9) Timer
- Real countdown from `timer_seconds` (default 60).
- Decreases only in `WAITING_INPUT`.
- Pauses in judge/evaluation and verdict animation phases.
- Keeps running when tab is unfocused.

## 10) Error Handling
- If judge output malformed: retry once.
- If second malformed:
- treat turn as fully correct (score/progression/visuals)
- synthesize fallback weight as midpoint:
- `weight_g = round((MIN_G + MAX_G) / 2)`
- use canonicalized user text as `canonical_name` if possible, else `"unknown_item"`

## 11) UI / Scene Layout
- Single main scene with overlays (simplest path).
- Regions:
- Top-left HUD: hearts, score, timer.
- Left side panel: current rules.
- Center: weighing scale + drop zone.
- Bottom-center: input field + submit button.
- Right: mascot character + speech bubble (2-line max).
- Center overlays: countdown, pause modal, game-over modal, pass/fail banners.

## 12) Game States (State Machine)
- `BOOT`
- `MENU_IDLE` (Start / How to Play)
- `HOW_TO_PLAY_OVERLAY`
- `COUNTDOWN_3_2_1`
- `TURN_PROMPT`
- `WAITING_INPUT` (timer running)
- `JUDGE_EVALUATING` (timer paused, minimum 3.0s)
- `DROP_AND_WEIGH_ANIM`
- `VERDICT_DISPLAY`
- `TURN_TRANSITION`
- `PAUSED`
- `GAME_OVER`

## 13) Turn Timeline (Per Submitted Input)
1. Player submits (`Enter` or button).
2. If command matches `time` (trim + case-insensitive): go `GAME_OVER`.
3. Start `JUDGE_EVALUATING` for at least 3.0 seconds (play drum roll).
4. Receive judge payload, run deterministic checks.
5. Spawn item sprite above scale.
6. Tween drop, bounce, settle.
7. Animate needle to interpreted weight.
8. Show verdict banner (`Correct`/`Wrong`) and mascot line.
9. Apply life/score/progression.
10. Move to next turn or game over.

## 14) Animation and Feedback
- Pass:
- needle lands in green zone
- center `CORRECT` pixel banner
- success SFX
- mascot uses random success line (non-AI list)
- Fail:
- light red flash
- brief camera/scene shake
- crack SFX
- one heart pop animation
- center `WRONG` pixel banner
- fail SFX
- mascot roast line (max 2 lines)
- Yellow zone: disabled (only pass/fail visuals).

## 15) Audio Design
- Looping retro arcade BGM.
- Required SFX:
- submit
- evaluation drum roll
- pass
- fail
- life lost
- timer warning
- game over
- Accessibility toggle required now:
- mute all audio

## 16) Mascot Dialogue Rules
- Bubble max: 2 lines.
- Tone: roast humor for errors.
- Pools:
- success lines: 20 fixed non-AI lines
- fail roast lines: 40 fixed lines
- Optional: if LLM returns `ui_answer`, use it only if <=2 lines and safe; else fallback to fixed pools.

## 17) Item Visual Pipeline (Any Input)
- Preferred: pre-generated sprite library keyed by canonical name slug.
- Fallback always available: generic crate/object silhouette + item text label.
- Runtime generation can be skipped for reliability.
- Evaluation phase has fixed minimum 3s so timing feels intentional.

## 18) Frontend Verdict Payload (Backend -> Frontend)
- Required:
- `canonical_name: string`
- `weight_g: number`
- `pass: boolean`
- Recommended optional:
- `reason: string`
- `why: string`
- `notes: string`
- `rule_fail: string | null`
- `ui_answer: string` (max 2 lines rendered)
- `fallback_mode: boolean` (true when malformed-double fallback applied)

## 19) Judge Contract (LLM -> Backend)
- LLM should return structured JSON only.
- Suggested fields:
- `canonical_name`
- `interpreted_meaning`
- `estimated_weight_g`
- `is_real`
- `needs_clarification`
- `used_explicit_measure`
- `used_trick_phrasing`
- `rule_checks` (map rule -> bool)
- `reason_short`
- `notes`
- `ui_answer`
- `progression_actions` (0..2 entries from allowed set)

## 20) Deterministic Backend Validation Order
1. End command check.
2. Empty input check.
3. Anti-cheat text checks (explicit measure, trick phrasing, bulk-without-count).
4. Realness check.
5. Canonical repeat check against passed set.
6. Weight in range check.
7. Rule predicate checks.
8. Final pass/fail decision.

## 21) End Command and Input Rules
- End command matcher:
- `normalized = input.trim().lower()`
- if `normalized == "time"` then stop.
- Empty input:
- no life lost
- show mascot prompt like `Type one item to continue.`

## 22) Progression Example Ladder (for LLM Guidance)
- Example target pacing:
- `1g - 10000kg`
- `1g - 1000kg`
- `1kg - 1000kg` (x2 turns)
- `1kg - 1000kg + rule1`
- `1kg - 100kg + rule1`
- `1kg - 10kg + rule1` (x2 turns)
- `1kg - 10kg + rule1 + rule2`
- `1kg - 10kg + rule1 + rule2 + rule3` (x2 turns)
- then continue with cautious min/max tightening while keeping solvable prompts.

## 23) LLM Prompting Rules for Progression Quality
- Keep rounds solvable by a normal player.
- Avoid abrupt impossible jumps.
- Prefer stability for 1-2 turns before adding new restriction.
- Never output contradictory rules.
- Max 2 progression actions per turn.
- If unsure, hold.

## 24) Quick Build Recommendation (8-Hour Delivery)
- Fast stack:
- Frontend: Vite + JavaScript + PixiJS + GSAP
- Backend: Python FastAPI service for LLM judge and deterministic validation
- Why:
- keeps Python where you are strongest
- gives polished arcade visuals quickly
- avoids heavy engine complexity

## 25) Minimum Asset Checklist
- 1 background scene
- 1 scale sprite (base + dial/needle parts)
- 1 mascot sprite (idle + talk mouth toggle optional)
- 2 center banners (`CORRECT`, `WRONG`)
- 3 heart states (full, pop anim frame, empty)
- fallback item sprite sheet (generic crate/object)
- optional pre-generated item sprite folder

## 26) Demo-Ready Acceptance Criteria
- Runs locally in desktop browser with no crashes.
- Full game loop completes with all end conditions.
- Timer behavior matches spec exactly.
- Pass/fail visuals and sounds fire reliably.
- LLM malformed-double fallback handled as correct with midpoint weight.
- At least one successful and one failed turn shown cleanly on video.

