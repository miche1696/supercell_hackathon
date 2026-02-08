# Frontend Direction (Hackathon Demo)

## 1. Goal
Build a cute retro-arcade desktop browser demo that is visually clear and stable:
`spawn -> drop -> weigh -> verdict -> next turn`.

Priorities:
- polish over complexity
- reliability over ambitious systems
- readable visuals for demo video

## 2. Recommended Stack (Fastest Reliable Path)
- Frontend: `Vite + JavaScript + PixiJS + GSAP`
- Backend judge/validator: `Python (FastAPI)`

Why JavaScript now:
- faster iteration under time pressure
- no TS typing overhead for initial delivery
- can migrate to TS later if needed

## 3. Rendering and Motion
- Do not use raytracing or heavy 3D.
- Use 2D/2.5D scene composition.
- Use stylized tweened physics (no heavy simulation required).

Drop sequence:
- spawn item above scale
- ease-in fall
- one small bounce
- settle

Needle sequence:
- fast swing
- overshoot
- settle at final angle

## 4. Fixed UX Decisions
- Desktop only.
- Single main scene + overlays.
- Start flow includes `3-2-1` countdown.
- Input submission: `Enter` + click button.
- Lives shown as hearts.
- Rules shown in side panel.
- Mascot on right side with speech bubble (max 2 lines).
- Only two outcomes: pass/fail (no yellow state).
- Evaluation phase lasts at least 3 seconds.
- Pause on `Esc` pauses timer, animations, input.

## 5. Layout Blueprint
- Top-left HUD: hearts, score, timer.
- Left panel: active rules (chips/list).
- Center stage: scale, item drop area, verdict banner.
- Bottom-center: input field + submit.
- Right panel: mascot sprite + speech bubble.
- Overlay layer: how-to-play, pause, game over, countdown.

## 6. State Machine
- `BOOT`
- `MENU_IDLE`
- `HOW_TO_PLAY_OVERLAY`
- `COUNTDOWN_3_2_1`
- `TURN_PROMPT`
- `WAITING_INPUT` (timer running)
- `JUDGE_EVALUATING` (timer paused, min 3s)
- `DROP_AND_WEIGH_ANIM`
- `VERDICT_DISPLAY`
- `TURN_TRANSITION`
- `PAUSED`
- `GAME_OVER`

## 7. Animation and Feedback Spec
Pass:
- needle reaches green zone
- center `CORRECT` pixel banner
- success SFX
- mascot success line (from fixed pool)

Fail:
- light red flash
- short screen shake
- crack SFX
- heart pop/loss animation
- center `WRONG` pixel banner
- fail SFX
- mascot roast line

Timer warning:
- warning sound starts at 10s
- visual urgency pulse
- explicit `5-4-3-2-1` countdown

## 8. Audio Plan
BGM:
- one looped retro arcade track

Required SFX:
- submit
- evaluation drum roll
- pass
- fail
- life lost
- timer warning
- game over

Accessibility:
- one global `Mute` toggle

## 9. Mascot Messaging
- Bubble hard limit: 2 lines.
- Tone: roast humor for errors.
- Content pools:
- 20 fixed success lines
- 40 fixed fail roast lines

Optional LLM line:
- Use `ui_answer` only if safe and <= 2 lines.
- Otherwise fallback to fixed line pool.

## 10. Asset Strategy for 8-Hour Delivery
Use a hybrid approach.

Do not block implementation on full asset completion.

Pipeline:
1. Build full game with placeholders first.
2. Lock sprite sizes/anchors/naming conventions.
3. Replace placeholders with final art in priority order.

Why:
- guarantees working demo even if asset generation is late
- avoids breaking layout from uncertain art dimensions
- lets you test readability and timing early

## 11. Asset Priority List
P0 (must-have before final record):
- background scene
- scale base + needle
- mascot idle sprite
- hearts UI states
- `CORRECT` banner
- `WRONG` banner
- generic fallback item sprite

P1 (high-value polish):
- particle sprites (dust/spark)
- button hover/press states
- extra mascot expressions

P2 (optional):
- expanded item sprite library
- environment variations

## 12. Any-Item Visual Pipeline
Goal: user can type any item and game always displays something.

Rule:
- Try pre-generated sprite by canonical slug first.
- If missing, use generic fallback sprite + item label text.

This guarantees the loop never breaks.

## 13. Naming and Art Consistency Rules
- Use one fixed canvas/pixel grid policy.
- Use one palette family across all assets.
- Keep single light direction for all sprites.
- Use consistent anchor points:
- items: bottom-center
- mascot: bottom-center
- scale: centered on platform

Recommended folders:
- `assets/ui/`
- `assets/mascot/`
- `assets/scale/`
- `assets/items/`
- `assets/items_fallback/`
- `assets/audio/`

## 14. Font and UI Style (Retro but Readable)
- Heading font: pixel arcade style
- Body/UI font: cleaner pixel-friendly font
- Keep high contrast for timer and verdict text.
- Avoid tiny pixel text for long explanations.

## 15. Backend-to-Frontend Contract (Minimum)
Required per evaluated turn:
- `canonical_name`
- `weight_g`
- `pass`

Optional:
- `reason`
- `why`
- `notes`
- `rule_fail`
- `ui_answer`
- `fallback_mode`

Frontend behavior on malformed-double fallback:
- show as correct
- use fallback weight from backend
- continue normal progression visuals

## 16. Technical Risk Controls
- Keep one scene, avoid scene switching complexity.
- Keep animation durations fixed and deterministic.
- Keep a strict timeout on evaluation display (minimum 3s, no hanging).
- Never block render loop on asset misses.
- Preload only P0 assets before start; lazy-load extras.

## 17. Deliverable Readiness Checklist
- full loop works with keyboard and button input
- countdown works
- pause/resume works
- timer warning + countdown works
- pass and fail visuals/audio work
- fallback sprite always works for unknown item asset
- game over screen shows final score
