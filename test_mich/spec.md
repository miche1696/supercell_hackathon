# Bribe the Scale (Solo) - Product Spec

## 1. Purpose
A single-player weight-guessing survival game where the player must keep answering valid items under changing constraints before time expires.

## 2. Core Concept
Each turn, the game asks for one item that fits:
- a weight range `[MIN, MAX]` (in grams)
- zero to three active micro-rules

Player submits one noun phrase. The judge interprets it, estimates weight, and returns pass/fail.

Game ends when:
- timer reaches `0`
- lives reach `0`
- player enters the stop command (`time`, case-insensitive)

## 3. Configurable Settings (Code-Level)
All settings must be configurable in code.

- `timer_seconds` (default: `60`)
- `start_lives` (default: `3`)
- `start_min_weight_g` (default: `1`)
- `start_max_weight_g` (default: `10_000_000`)  // 10,000 kg
- `max_rules` (default: `3`)
- `rule_add_min_turn` (default: `3`)
- `max_shrink_factor` (default: `0.1`)
- `minimum_enlarge_factor` (default: `10`)
- `max_progression_actions_per_turn` (default: `2`)
- `end_command` (default: `time`)
- `evaluation_min_seconds` (default: `3.0`)
- `timer_warning_seconds` (default: `10`)
- `countdown_last_seconds` (default: `5`)

## 4. Timer Behavior
- Timer is a real countdown.
- Timer decreases only while player is deciding/typing.
- Timer pauses while judge/LLM is responding.
- Timer pauses during verdict animations.
- Timer keeps running if browser tab loses focus.
- `Esc` pauses timer, animations, and input.

## 5. Turn Flow
1. Render turn header with lives, score, prompt, and rules.
2. Read one player input.
3. If input is empty/whitespace, ask again (no life loss, no timer/state penalty beyond normal waiting time).
4. If input matches end command (trimmed, case-insensitive exact match on `time`), end game.
5. Start evaluation phase (minimum 3 seconds).
6. Judge evaluates input and returns structured verdict.
7. Apply deterministic pass/fail checks.
8. If pass:
   - award points
   - register canonical object class in used set
   - apply progression updates
9. If fail:
   - decrement lives by 1
   - keep constraints unchanged
10. Continue until game over.

## 6. Input Interpretation Rules

### 6.1 Canonical Object Class (No Repeats)
- Accepted answers are tracked by canonical object class.
- Repeat is invalid even if quantity changes.
- Canonicalization behavior:
  - strip quantity and units
  - ignore minor adjectives
  - keep subtype if it changes category (`boat` vs `rowboat`)
  - meaningful personalization can define a new category (`dog with weighted vest`, `phone taped to a brick`)

### 6.2 Default Quantity and Meaning
- If no quantity is specified, assume quantity `1`.
- If plural form is used without count, interpret as one unit (`apples` -> one apple).
- Use the most common interpretation.

### 6.3 Default Average for Variable Objects
- If object is variable but has a stable commonly assumed average, use that average.
- Unknown weights should still be estimated from a common-person intuition.
- Do not fail only because exact weight varies.

## 7. Realness Policy
Allowed:
- real objects
- coherent, imaginable physical configurations/personalizations
- fictional objects if physically coherent enough to estimate

Rejected:
- gibberish
- paradox objects (`square circle`)
- impossible magic-only arbitrary-weight exploits

## 8. Anti-Cheat Policy

### 8.1 Explicit Measure Ban
Explicit mass/volume quantities in player input are not allowed.

Always reject examples:
- `1 kg of flour`
- `500 ml of water`
- `2 lbs of sand`

### 8.2 Bulk Material Rule
Bulk materials without count are invalid.

Reject examples:
- `flour`
- `water`
- `sand`

### 8.3 Allowed Quantity Form
Count-based quantities are allowed.

Allow examples:
- `3 AA batteries`
- `box of 12 pencils`
- `10 grains of rice`

### 8.4 Trick Phrasing
Reject self-referential or exact-target phrasing.

Reject example:
- `an object that weighs exactly 9.99 kg`

## 9. Rule System

### 9.1 Rule Allowlist (max 3, each <= 4 words)
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

Definitions:
- `Fits in hand` means typical adult hand.
- `Household item` means globally common household usage.

### 9.2 Rule Constraints
- Never exceed 3 active rules.
- Never add contradictory rules.
- Rules can persist across multiple turns.
- New rules can be added only from turn 3 onward.
- If rules are already at max and LLM proposes adding a rule, skip adding (no replacement).

## 10. Deterministic Pass/Fail
Fail the answer if any condition is true:
- not real
- bulk/quantity clarification needed
- explicit mass/volume quantity used
- trick/self-referential phrasing used
- canonical object class already used
- estimated weight outside `[MIN, MAX]`
- active rule predicate fails

Otherwise pass.

## 11. Difficulty Progression
After each correct answer, LLM may propose up to 2 progression actions.

Allowed actions:
- tighten range: `MAX = MAX * max_shrink_factor` (nice rounding)
- raise minimum: `MIN = MIN * minimum_enlarge_factor` (nice rounding)
- add one rule (if legal and slot available)
- hold constraints unchanged

Guardrails:
- Do not allow contradictory rules.
- If proposed bounds are invalid (`MIN >= MAX`), auto-fallback to previous bounds and hold.

Example ladder guidance for LLM pacing:
- `1g - 10000kg`
- `1g - 1000kg`
- `1kg - 1000kg` (x2 turns)
- `1kg - 1000kg + rule1`
- `1kg - 100kg + rule1`
- `1kg - 10kg + rule1` (x2 turns)
- `1kg - 10kg + rule1 + rule2`
- `1kg - 10kg + rule1 + rule2 + rule3` (x2 turns)

On wrong answers:
- lives decrease
- constraints remain unchanged

## 12. Scoring
- Default: `+1` per correct answer
- High-difficulty bonus: `+3` instead of `+1` when either:
  - `MAX <= 1 kg` (`<= 1000 g`), or
  - at least 2 active rules

Display total score only.

## 13. Frontend Integration Contract
Each turn should emit a frontend-safe verdict payload with at least:
- `canonical_name`
- `weight_g`
- `pass`

Optional display fields:
- `reason`
- `why`
- `notes`
- `rule_fail`
- `ui_answer`  // roast/funny mascot message, max 2 lines in UI
- `fallback_mode`  // true when malformed-double fallback was used

Intended frontend behavior:
- item spawns above a weighing scale
- stylized gravity drop / landing animation
- indicator shows result (green pass, red fail)

## 14. Output Format (Terminal Debug)
Per turn, print exactly:

```
TURN N
Lives: <icons-or-text> Score: S
Prompt: Name something that weighs between [MIN] and [MAX].
Rules: [Rule 1] [Rule 2] [Rule 3]
Reply with ONE item.
```

If no rules:

```
Rules: None
```

After reply, print:

```
Ruling: Correct / Wrong
Canonical object class: ...
Interpreted meaning: ... (only when needed)
Estimated weight: ... (g or kg)
Why: <one short sentence>
Notes: ... (only when needed)
```

## 15. Error Handling
If judge output is malformed:
- retry once
- if still malformed:
  - treat the turn as correct
  - apply score/progression/visuals as normal correct turn
  - use fallback `weight_g = round((MIN + MAX) / 2)` for UI/frontend

## 16. Non-Functional Constraints
- The game must remain deterministic at validation step.
- Pass/fail must rely on structured fields and code checks, not freeform text.
- Configuration must allow easy tuning for hackathon demos.
- Evaluation phase must feel intentional (minimum 3 seconds).
