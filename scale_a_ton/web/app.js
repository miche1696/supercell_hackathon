const dom = {
  timerValue: document.getElementById("timer-value"),
  scoreValue: document.getElementById("score-value"),
  heartsRow: document.getElementById("hearts-row"),
  rulesPanel: document.getElementById("rules-panel"),
  rulesList: document.getElementById("rules-list"),
  minCard: document.getElementById("min-card"),
  maxCard: document.getElementById("max-card"),
  minValue: document.getElementById("min-value"),
  maxValue: document.getElementById("max-value"),
  boundaryHint: document.getElementById("boundary-hint"),
  answerInput: document.getElementById("answer-input"),
  sendButton: document.getElementById("send-button"),
  restartButton: document.getElementById("restart-button"),
  ambientVolumeSlider: document.getElementById("ambient-volume-slider"),
  ambientVolumeValue: document.getElementById("ambient-volume-value"),
  ambientMuteButton: document.getElementById("ambient-mute-button"),
  speechText: document.getElementById("speech-text"),
  resultBanner: document.getElementById("result-banner"),
  scaleArea: document.getElementById("scale-area"),
  scalePlate: document.getElementById("scale-plate"),
  scaleNeedle: document.getElementById("scale-needle"),
  scaleBox: document.getElementById("scale-box"),
  scaleWeightDisplay: document.getElementById("scale-weight-display"),
  scaleWeightValue: document.getElementById("scale-weight-value"),
  itemLayer: document.getElementById("item-layer"),
  usedObjectsFloor: document.getElementById("used-objects-floor"),
  countdownOverlay: document.getElementById("countdown-overlay"),
  pauseOverlay: document.getElementById("pause-overlay"),
  winOverlay: document.getElementById("win-overlay"),
  gameoverOverlay: document.getElementById("gameover-overlay"),
  gameoverScore: document.getElementById("gameover-score"),
};

const state = {
  backend: null,
  phase: "boot", // boot | countdown | waiting_input | evaluating | verdict | paused | game_over
  phaseBeforePause: null,
  paused: false,
  timeRemaining: 60,
  timerWarningShown: new Set(),
  countdownSecondsShown: new Set(),
  lastTimerDisplay: null,
  needleAnimating: false,
  needleAnimId: null,
  weightAnimId: null,
  displayedWeightG: 0,
  activeItemEl: null,
  usedSuccessKeys: new Set(),
  ambientAudio: null,
  ambientUnlockArmed: false,
  ambientVolume: 1,
  ambientMuted: false,
  plateHitAudio: null,
  speechTypingTimer: null,
  speechTypingToken: 0,
};

const HEART_FULL = "/assets/full_heart.png";
const HEART_EMPTY = "/assets/empty_heart.png";
const AMBIENT_SOUND_SRC = "/assets/sounds/sc-hackathon-song-with-ambience_256.mp3";
const AMBIENT_OUTPUT_SCALE = 0.2;
const PLATE_HIT_SOUND_SRC = "/assets/sounds/HIT-tommi.wav";
const PLATE_HIT_VOLUME = 0.06;
const ITEM_FRAME_SIZE_PX = 140;
const USED_ITEM_TILE_SIZE_PX = 120;
const USED_ITEM_TILE_SCALE = 0.82;
const USED_ITEM_FRAME_SIZE_PX = Math.round(USED_ITEM_TILE_SIZE_PX * USED_ITEM_TILE_SCALE);
// Crop a little from each frame edge (5% per side = 10% total) to hide seam artifacts.
const FALL_ITEM_EDGE_TRIM_RATIO = 0.18;
const USED_ITEM_EDGE_TRIM_RATIO = 0.05;
const SPRITE_FRAME_EDGE_TRIM_RATIO = FALL_ITEM_EDGE_TRIM_RATIO;
const VERDICT_NEEDLE_ANGLE_DEG = 30;
const SPEECH_TYPEWRITER_START_DELAY_MS = 90;
const SPEECH_TYPEWRITER_CHAR_DELAY_MS = 42;
const SPEECH_TYPEWRITER_LINE_BREAK_DELAY_MS = 190;
const SPEECH_TYPEWRITER_PUNCT_DELAY_MS = 140;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function sanitizeEdgeTrimRatio(edgeTrimRatio) {
  const numeric = Number(edgeTrimRatio);
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  return clamp(numeric, 0, 0.24);
}

function getSpriteSheetZoom(edgeTrimRatio = SPRITE_FRAME_EDGE_TRIM_RATIO) {
  const trim = sanitizeEdgeTrimRatio(edgeTrimRatio);
  return 1 / (1 - trim * 2);
}

function applySpriteSheetSizing(el, frameSizePx = ITEM_FRAME_SIZE_PX, edgeTrimRatio = SPRITE_FRAME_EDGE_TRIM_RATIO) {
  const zoom = getSpriteSheetZoom(edgeTrimRatio);
  const sheetSize = frameSizePx * 2 * zoom;
  el.style.backgroundSize = `${sheetSize}px ${sheetSize}px`;
}

function ensureAmbientAudio() {
  if (!state.ambientAudio) {
    const audio = new Audio(AMBIENT_SOUND_SRC);
    audio.loop = true;
    audio.preload = "auto";
    state.ambientAudio = audio;
  }
  applyAmbientSettings();
  return state.ambientAudio;
}

function applyAmbientSettings() {
  if (!state.ambientAudio) {
    return;
  }
  state.ambientAudio.volume = clamp(state.ambientVolume, 0, 1) * AMBIENT_OUTPUT_SCALE;
  state.ambientAudio.muted = !!state.ambientMuted;
}

function refreshAmbientControls() {
  if (dom.ambientVolumeSlider) {
    dom.ambientVolumeSlider.value = String(Math.round(clamp(state.ambientVolume, 0, 1) * 100));
  }
  if (dom.ambientVolumeValue) {
    dom.ambientVolumeValue.textContent = `${Math.round(clamp(state.ambientVolume, 0, 1) * 100)}%`;
  }
  if (dom.ambientMuteButton) {
    dom.ambientMuteButton.textContent = state.ambientMuted ? "UNMUTE" : "MUTE";
    dom.ambientMuteButton.setAttribute("aria-pressed", state.ambientMuted ? "true" : "false");
  }
}

function tryPlayAmbientFromInteraction() {
  const audio = ensureAmbientAudio();
  if (!audio.paused) {
    return;
  }

  const playPromise = audio.play();
  if (playPromise && typeof playPromise.catch === "function") {
    playPromise.catch(() => {
      armAmbientUnlockFromGesture();
    });
  }
}

function onAmbientVolumeChange(rawValue) {
  const numeric = Number(rawValue);
  if (!Number.isFinite(numeric)) {
    return;
  }

  state.ambientVolume = clamp(numeric / 100, 0, 1);
  if (state.ambientVolume > 0 && state.ambientMuted) {
    state.ambientMuted = false;
  }

  applyAmbientSettings();
  refreshAmbientControls();
  tryPlayAmbientFromInteraction();
}

function onAmbientMuteToggle() {
  state.ambientMuted = !state.ambientMuted;
  applyAmbientSettings();
  refreshAmbientControls();
  if (!state.ambientMuted) {
    tryPlayAmbientFromInteraction();
  }
}

function armAmbientUnlockFromGesture() {
  if (state.ambientUnlockArmed) {
    return;
  }
  state.ambientUnlockArmed = true;

  const handler = () => {
    window.removeEventListener("pointerdown", handler);
    window.removeEventListener("keydown", handler);

    const audio = ensureAmbientAudio();
    applyAmbientSettings();
    const playPromise = audio.play();
    if (playPromise && typeof playPromise.then === "function") {
      playPromise
        .then(() => {
          state.ambientUnlockArmed = false;
        })
        .catch(() => {
          // Some environments still block autoplay; re-arm for a later gesture.
          state.ambientUnlockArmed = false;
          armAmbientUnlockFromGesture();
        });
      return;
    }
    state.ambientUnlockArmed = false;
  };

  window.addEventListener("pointerdown", handler, { once: true });
  window.addEventListener("keydown", handler, { once: true });
}

function playAmbientLoopFromStart() {
  const audio = ensureAmbientAudio();
  audio.loop = true;
  applyAmbientSettings();
  audio.currentTime = 0;

  const playPromise = audio.play();
  if (playPromise && typeof playPromise.catch === "function") {
    playPromise.catch(() => {
      armAmbientUnlockFromGesture();
    });
  }
}

function ensurePlateHitAudio() {
  if (!state.plateHitAudio) {
    const audio = new Audio(PLATE_HIT_SOUND_SRC);
    audio.preload = "auto";
    state.plateHitAudio = audio;
  }
  state.plateHitAudio.volume = clamp(PLATE_HIT_VOLUME, 0, 1);
  return state.plateHitAudio;
}

function playPlateHitSound() {
  const audio = ensurePlateHitAudio();
  if (!audio.paused) {
    audio.currentTime = 0;
  }
  const playPromise = audio.play();
  if (playPromise && typeof playPromise.catch === "function") {
    playPromise.catch(() => {
      // Non-critical SFX; ignore playback rejections in restricted environments.
    });
  }
}

function formatClosestWeightFromG(weightG) {
  const safeG = Math.max(0, Math.round(Number(weightG) || 0));
  if (safeG < 1000) {
    return `${safeG.toLocaleString()}g`;
  }

  const kg = safeG / 1000;
  if (kg < 1000) {
    const kgText = kg.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 3 });
    return `${kgText}kg`;
  }

  const tons = safeG / 1000000;
  const tonsText = tons.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 3 });
  const tonUnit = tons === 1 ? "ton" : "tons";
  return `${tonsText}${tonUnit}`;
}

function formatRange(g) {
  return formatClosestWeightFromG(g);
}

function flashClass(el, className, durationMs = 900) {
  if (!el) {
    return;
  }
  el.classList.remove(className);
  void el.offsetWidth;
  el.classList.add(className);
  setTimeout(() => {
    el.classList.remove(className);
  }, durationMs);
}

function snapshotBackendState() {
  if (!state.backend) {
    return null;
  }
  return {
    min_g: state.backend.min_g,
    max_g: state.backend.max_g,
    active_rules: Array.isArray(state.backend.active_rules) ? [...state.backend.active_rules] : [],
  };
}

function diffRules(previousRules, nextRules) {
  const prev = Array.isArray(previousRules) ? previousRules : [];
  const next = Array.isArray(nextRules) ? nextRules : [];
  const prevSet = new Set(prev);
  const nextSet = new Set(next);
  return {
    added: next.filter((rule) => !prevSet.has(rule)),
    removed: prev.filter((rule) => !nextSet.has(rule)),
  };
}

function setSpeech(text) {
  if (state.speechTypingTimer !== null) {
    clearTimeout(state.speechTypingTimer);
    state.speechTypingTimer = null;
  }

  state.speechTypingToken += 1;
  const typingToken = state.speechTypingToken;
  const normalized = (text || "").trim();
  if (!normalized) {
    dom.speechText.textContent = "...";
    dom.speechText.classList.remove("is-typing");
    return;
  }

  const message = normalized.split(/\n+/).slice(0, 2).join("\n");
  dom.speechText.textContent = "";
  dom.speechText.classList.add("is-typing");

  let cursor = 0;
  const renderNextChar = () => {
    if (typingToken !== state.speechTypingToken) {
      return;
    }

    if (cursor >= message.length) {
      dom.speechText.classList.remove("is-typing");
      state.speechTypingTimer = null;
      return;
    }

    cursor += 1;
    dom.speechText.textContent = message.slice(0, cursor);

    const currentChar = message[cursor - 1];
    let delay = SPEECH_TYPEWRITER_CHAR_DELAY_MS;
    if (currentChar === "\n") {
      delay = SPEECH_TYPEWRITER_LINE_BREAK_DELAY_MS;
    } else if (/[.,!?]/.test(currentChar)) {
      delay = SPEECH_TYPEWRITER_PUNCT_DELAY_MS;
    }

    state.speechTypingTimer = setTimeout(renderNextChar, delay);
  };

  state.speechTypingTimer = setTimeout(renderNextChar, SPEECH_TYPEWRITER_START_DELAY_MS);
}

function setResultBanner(label, isPass) {
  dom.resultBanner.textContent = label;
  dom.resultBanner.classList.remove("hidden", "correct", "wrong");
  dom.resultBanner.classList.add(isPass ? "correct" : "wrong");
}

function hideResultBanner() {
  dom.resultBanner.classList.add("hidden");
  dom.resultBanner.classList.remove("correct", "wrong");
}

function setNeedleAngle(deg) {
  dom.scaleNeedle.style.transform = `translate(-50%, -50%) rotate(${deg}deg)`;
}

function triggerScalePlateBump() {
  if (!dom.scalePlate) {
    return;
  }
  dom.scalePlate.classList.remove("impact-bump");
  void dom.scalePlate.offsetWidth;
  dom.scalePlate.classList.add("impact-bump");
}

function triggerScaleBoxShake() {
  if (!dom.scaleBox) {
    return;
  }
  dom.scaleBox.classList.remove("is-shaking");
  void dom.scaleBox.offsetWidth;
  dom.scaleBox.classList.add("is-shaking");
}

function startNeedleOscillation() {
  if (state.needleAnimating) {
    return;
  }
  state.needleAnimating = true;

  const animate = (ts) => {
    if (!state.needleAnimating) {
      return;
    }

    if (!state.paused) {
      const angle = Math.sin(ts / 110) * 25;
      setNeedleAngle(angle);
    }

    state.needleAnimId = requestAnimationFrame(animate);
  };

  state.needleAnimId = requestAnimationFrame(animate);
}

function stopNeedleOscillation(finalAngle) {
  state.needleAnimating = false;
  if (state.needleAnimId !== null) {
    cancelAnimationFrame(state.needleAnimId);
    state.needleAnimId = null;
  }
  dom.scaleNeedle.style.transition = "transform 260ms ease-out";
  setNeedleAngle(finalAngle);
  setTimeout(() => {
    dom.scaleNeedle.style.transition = "";
  }, 280);
}

function setWeightDisplayState(mode) {
  dom.scaleWeightDisplay.classList.remove("idle", "good", "bad");
  if (mode === "good" || mode === "bad") {
    dom.scaleWeightDisplay.classList.add(mode);
    return;
  }
  dom.scaleWeightDisplay.classList.add("idle");
}

function setWeightDisplayValue(weightG) {
  const safe = Math.max(0, Math.round(Number(weightG) || 0));
  state.displayedWeightG = safe;
  dom.scaleWeightValue.textContent = formatClosestWeightFromG(safe);
}

function stopWeightAnimation() {
  if (state.weightAnimId !== null) {
    cancelAnimationFrame(state.weightAnimId);
    state.weightAnimId = null;
  }
}

function animateWeightTo(targetWeightG, durationMs = 850) {
  stopWeightAnimation();
  const from = state.displayedWeightG;
  const to = Math.max(0, Math.round(Number(targetWeightG) || 0));

  if (durationMs <= 0 || from === to) {
    setWeightDisplayValue(to);
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    const start = performance.now();
    const step = (ts) => {
      const progress = Math.min((ts - start) / durationMs, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = Math.round(from + (to - from) * eased);
      setWeightDisplayValue(value);

      if (progress < 1) {
        state.weightAnimId = requestAnimationFrame(step);
      } else {
        state.weightAnimId = null;
        resolve();
      }
    };
    state.weightAnimId = requestAnimationFrame(step);
  });
}

function setItemFrame(el, frameNumber, frameSizePx = ITEM_FRAME_SIZE_PX, edgeTrimRatio = SPRITE_FRAME_EDGE_TRIM_RATIO) {
  const normalizedFrame = [1, 2, 3, 4].includes(frameNumber) ? frameNumber : 4;
  const col = normalizedFrame === 2 || normalizedFrame === 4 ? 1 : 0;
  const row = normalizedFrame === 3 || normalizedFrame === 4 ? 1 : 0;
  const trim = sanitizeEdgeTrimRatio(edgeTrimRatio);
  const zoom = getSpriteSheetZoom(trim);
  const inset = frameSizePx * trim;
  const x = -((col * frameSizePx + inset) * zoom);
  const y = -((row * frameSizePx + inset) * zoom);
  el.style.backgroundPosition = `${x.toFixed(3)}px ${y.toFixed(3)}px`;
}

function spawnItem(assetUrl) {
  clearActiveItem();
  triggerScaleBoxShake();

  const el = document.createElement("div");
  el.className = "item-sprite";
  el.style.backgroundImage = `url('${assetUrl}')`;
  applySpriteSheetSizing(el, ITEM_FRAME_SIZE_PX, FALL_ITEM_EDGE_TRIM_RATIO);
  el.style.left = "50%";
  const scaleAreaTop = dom.scaleArea.getBoundingClientRect().top;
  const offscreenStartTop = -Math.ceil(scaleAreaTop + 180);
  el.style.top = `${offscreenStartTop}px`;
  el.style.transform = "translateX(-50%)";
  setItemFrame(el, 1, ITEM_FRAME_SIZE_PX, FALL_ITEM_EDGE_TRIM_RATIO);

  dom.itemLayer.appendChild(el);
  state.activeItemEl = el;
  return el;
}

function clearActiveItem() {
  if (state.activeItemEl) {
    state.activeItemEl.remove();
    state.activeItemEl = null;
  }
}

function normalizeUsedKey(name) {
  return String(name || "")
    .trim()
    .toLowerCase();
}

function addUsedObject(canonicalName, assetUrl) {
  if (!dom.usedObjectsFloor) {
    return;
  }

  const key = normalizeUsedKey(canonicalName);
  if (!key || state.usedSuccessKeys.has(key)) {
    return;
  }
  state.usedSuccessKeys.add(key);

  const displayName = String(canonicalName || key).replace(/_/g, " ");
  const card = document.createElement("div");
  card.className = "used-item";

  const sprite = document.createElement("div");
  sprite.className = "used-item-sprite";
  sprite.style.setProperty("--used-item-scale", `${USED_ITEM_TILE_SCALE}`);
  sprite.title = displayName;
  sprite.setAttribute("aria-label", displayName);

  const spriteFrame = document.createElement("div");
  spriteFrame.className = "used-item-sprite-frame";
  spriteFrame.style.backgroundImage = `url('${assetUrl}')`;
  applySpriteSheetSizing(spriteFrame, USED_ITEM_FRAME_SIZE_PX, USED_ITEM_EDGE_TRIM_RATIO);
  setItemFrame(spriteFrame, 4, USED_ITEM_FRAME_SIZE_PX, USED_ITEM_EDGE_TRIM_RATIO);

  sprite.appendChild(spriteFrame);

  const label = document.createElement("div");
  label.className = "used-item-label";
  label.textContent = displayName;

  card.appendChild(sprite);
  card.appendChild(label);
  dom.usedObjectsFloor.appendChild(card);
}

function resetUsedObjects() {
  state.usedSuccessKeys.clear();
  if (dom.usedObjectsFloor) {
    dom.usedObjectsFloor.innerHTML = "";
  }
}

async function animateDropSequence(el) {
  // Ensure one rendered frame at the off-screen start position.
  el.style.transition = "none";
  void el.offsetHeight;
  await new Promise((resolve) => requestAnimationFrame(resolve));

  // 1 -> falling
  el.style.transition = "top 900ms linear";
  el.style.top = "210px";
  await sleep(860);

  // 3 -> touching floor
  el.style.transition = "top 150ms ease-out";
  el.style.top = "210px";
  setItemFrame(el, 3, ITEM_FRAME_SIZE_PX, FALL_ITEM_EDGE_TRIM_RATIO);
  triggerScalePlateBump();
  playPlateHitSound();
  await sleep(150);

  // 4 -> standby
  setItemFrame(el, 4, ITEM_FRAME_SIZE_PX, FALL_ITEM_EDGE_TRIM_RATIO);

  // Tiny settle bounce
  el.style.transition = "top 120ms ease-out";
  el.style.top = "204px";
  await sleep(120);
  el.style.transition = "top 120ms ease-in";
  el.style.top = "214px";
  await sleep(120);
}

function renderLives(lives) {
  dom.heartsRow.innerHTML = "";
  const configured = state.backend?.config?.start_lives ?? 3;
  const total = Math.max(configured, 1);

  for (let i = 0; i < total; i += 1) {
    const img = document.createElement("img");
    img.className = "heart-icon";
    img.src = i < lives ? HEART_FULL : HEART_EMPTY;
    img.alt = i < lives ? "full heart" : "empty heart";
    dom.heartsRow.appendChild(img);
  }
}

function renderRules(rules, previousRules = null) {
  dom.rulesList.innerHTML = "";
  const delta = diffRules(previousRules, rules);

  if (!rules || rules.length === 0) {
    const li = document.createElement("li");
    li.className = "rule-none";
    li.textContent = "be anything (for now)";
    dom.rulesList.appendChild(li);
  } else {
    const addedSet = new Set(delta.added);
    for (const rule of rules) {
      const li = document.createElement("li");
      li.textContent = rule;
      if (addedSet.has(rule)) {
        li.classList.add("rule-added");
      }
      dom.rulesList.appendChild(li);
    }
  }

  if (previousRules !== null && (delta.added.length > 0 || delta.removed.length > 0)) {
    flashClass(dom.rulesPanel, "changed");
  }
  return delta;
}

function updatePrompt(previousState = null, ruleDelta = { added: [], removed: [] }) {
  const minG = state.backend?.min_g ?? 1;
  const maxG = state.backend?.max_g ?? 1000000000;
  dom.minValue.textContent = formatRange(minG);
  dom.maxValue.textContent = formatRange(maxG);

  if (!previousState) {
    dom.boundaryHint.textContent = "Submit one object name.";
    return;
  }

  const minChanged = previousState.min_g !== minG;
  const maxChanged = previousState.max_g !== maxG;
  if (minChanged) {
    flashClass(dom.minCard, "changed");
  }
  if (maxChanged) {
    flashClass(dom.maxCard, "changed");
  }

  const messages = [];
  if (minChanged) {
    messages.push(`MIN -> ${formatRange(minG)}`);
  }
  if (maxChanged) {
    messages.push(`MAX -> ${formatRange(maxG)}`);
  }
  if (ruleDelta.added.length > 0) {
    messages.push(`+ Rule: ${ruleDelta.added.join(", ")}`);
  }
  if (ruleDelta.removed.length > 0) {
    messages.push(`- Rule: ${ruleDelta.removed.join(", ")}`);
  }
  if (messages.length === 0) {
    messages.push("No boundary update this turn.");
  }

  dom.boundaryHint.textContent = messages.join(" | ");
}

function updateHudFromBackend(previousState = null) {
  if (!state.backend) {
    return;
  }

  dom.scoreValue.textContent = String(state.backend.score ?? 0);
  renderLives(state.backend.lives ?? 0);
  const ruleDelta = renderRules(state.backend.active_rules ?? [], previousState?.active_rules ?? null);
  updatePrompt(previousState, ruleDelta);
}

function updateTimerDisplay() {
  const shown = Math.ceil(state.timeRemaining);
  if (state.lastTimerDisplay === shown) {
    return;
  }

  state.lastTimerDisplay = shown;
  dom.timerValue.textContent = String(shown);

  if (shown <= 10) {
    dom.timerValue.style.color = "#ff8f8f";
  } else {
    dom.timerValue.style.color = "";
  }

  if (shown <= 10 && shown > 0 && !state.timerWarningShown.has(shown)) {
    state.timerWarningShown.add(shown);
    if (shown === 10) {
      setSpeech("Time warning! 10 seconds left.");
    }
  }

  if (shown <= 5 && shown > 0 && !state.countdownSecondsShown.has(shown)) {
    state.countdownSecondsShown.add(shown);
    flashCountdown(shown);
  }
}

function disableInput(disabled) {
  dom.answerInput.disabled = disabled;
  dom.sendButton.disabled = disabled;
}

function showPause(show) {
  dom.pauseOverlay.classList.toggle("hidden", !show);
}

function showGameOver(reason) {
  state.phase = "game_over";
  state.paused = false;
  state.phaseBeforePause = null;
  disableInput(true);
  stopNeedleOscillation(0);
  stopWeightAnimation();
  setWeightDisplayValue(0);
  setWeightDisplayState("idle");
  clearActiveItem();
  hideResultBanner();
  dom.winOverlay.classList.add("hidden");
  dom.gameoverOverlay.classList.add("hidden");

  const score = state.backend?.score ?? 0;
  if (reason === "demo_win") {
    dom.winOverlay.classList.remove("hidden");
    setSpeech("You won the demo.");
    return;
  }

  dom.gameoverScore.textContent = `Score: ${score}`;
  dom.gameoverOverlay.classList.remove("hidden");

  if (reason === "timer") {
    setSpeech("Time is up.");
  } else if (reason === "end_command") {
    setSpeech("Run ended by command.");
  } else {
    setSpeech("No more lives.");
  }
}

async function flashCountdown(value) {
  dom.countdownOverlay.textContent = String(value);
  dom.countdownOverlay.classList.remove("hidden");
  await sleep(300);
  if (state.phase !== "game_over") {
    dom.countdownOverlay.classList.add("hidden");
  }
}

async function runStartCountdown() {
  state.phase = "countdown";
  for (const v of [3, 2, 1]) {
    dom.countdownOverlay.textContent = String(v);
    dom.countdownOverlay.classList.remove("hidden");
    await sleep(650);
  }
  dom.countdownOverlay.classList.add("hidden");
  state.phase = "waiting_input";
  disableInput(false);
  dom.answerInput.focus();
}

async function apiStart() {
  const res = await fetch("/api/start", { method: "POST" });
  const data = await res.json();
  if (!data.ok) {
    throw new Error("Failed to start game");
  }
  if (data.trace_id) {
    console.debug("trace_id(start):", data.trace_id);
  }
  return data.state;
}

async function apiSubmit(inputText) {
  const res = await fetch("/api/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_text: inputText }),
  });
  return res.json();
}

async function handleSubmit() {
  if (state.phase !== "waiting_input" || state.paused) {
    return;
  }

  const inputText = dom.answerInput.value.trim();
  if (!inputText) {
    setSpeech("Type one item to continue.");
    return;
  }

  clearActiveItem();
  setWeightDisplayValue(0);
  setWeightDisplayState("idle");

  state.phase = "evaluating";
  disableInput(true);
  hideResultBanner();

  const startTs = performance.now();
  const response = await apiSubmit(inputText);
  if (response.trace_id) {
    console.debug("trace_id(submit):", response.trace_id);
  }

  if (!response.ok) {
    setSpeech("Backend error.");
    state.phase = "waiting_input";
    disableInput(false);
    return;
  }

  const result = response.result;
  const previousState = snapshotBackendState();

  if (result.type === "empty_input") {
    setSpeech(result.message || "Type one item.");
    state.phase = "waiting_input";
    disableInput(false);
    return;
  }

  if (result.type === "duplicate_input") {
    state.backend = result.state || state.backend;
    updateHudFromBackend(previousState);
    const duplicateMessage = String(result.message || "").trim();
    if (duplicateMessage.toLowerCase().startsWith("word already used")) {
      setSpeech(duplicateMessage);
    } else if (duplicateMessage) {
      setSpeech(`Word already used. ${duplicateMessage}`);
    } else {
      setSpeech("Word already used. Try a different item.");
    }
    state.phase = "waiting_input";
    disableInput(false);
    dom.answerInput.focus();
    return;
  }

  if (result.type === "end_command") {
    state.backend = result.state;
    updateHudFromBackend(previousState);
    showGameOver("end_command");
    return;
  }

  if (result.type === "game_over") {
    state.backend = result.state;
    updateHudFromBackend(previousState);
    showGameOver(state.backend?.game_over_reason || "no_lives");
    return;
  }

  const itemUrl = result?.item_asset?.asset_url || "/assets/cat.png";
  const itemEl = spawnItem(itemUrl);
  await animateDropSequence(itemEl);

  startNeedleOscillation();
  const measuredWeightG = Math.max(0, Math.round(Number(result.weight_g) || 0));
  const weightRisePromise = animateWeightTo(measuredWeightG, 950);
  const minEvalMs = Math.max(3000, Math.floor((state.backend?.config?.evaluation_min_seconds || 3) * 1000));
  const elapsed = performance.now() - startTs;
  if (elapsed < minEvalMs) {
    await sleep(minEvalMs - elapsed);
  }
  await weightRisePromise;

  stopNeedleOscillation(result.pass ? VERDICT_NEEDLE_ANGLE_DEG : -VERDICT_NEEDLE_ANGLE_DEG);
  setWeightDisplayState(result.pass ? "good" : "bad");

  state.backend = result.state;
  updateHudFromBackend(previousState);

  const speech = (result.ui_answer || result.reason || "").trim();
  setSpeech(speech);
  setResultBanner(result.ruling || (result.pass ? "CORRECT" : "WRONG"), !!result.pass);
  if (result.pass) {
    addUsedObject(result.canonical_name, itemUrl);
  }

  state.phase = "verdict";
  dom.answerInput.value = "";

  await sleep(1100);

  setWeightDisplayState("idle");
  hideResultBanner();

  if (state.backend?.game_over) {
    showGameOver(state.backend.game_over_reason || "no_lives");
    return;
  }

  if (state.timeRemaining <= 0) {
    showGameOver("timer");
    return;
  }

  state.phase = "waiting_input";
  disableInput(false);
  dom.answerInput.focus();
}

function togglePause() {
  if (state.phase === "game_over" || state.phase === "boot" || state.phase === "countdown") {
    return;
  }

  state.paused = !state.paused;
  showPause(state.paused);

  if (state.paused) {
    state.phaseBeforePause = state.phase;
    disableInput(true);
    state.phase = "paused";
    return;
  }

  if (!state.paused) {
    if (state.backend?.game_over) {
      return;
    }

    const restorePhase = state.phaseBeforePause || "waiting_input";
    state.phase = restorePhase;
    state.phaseBeforePause = null;
    disableInput(state.phase !== "waiting_input");
    if (state.phase === "waiting_input") {
      dom.answerInput.focus();
    }
  }
}

async function restartGame() {
  dom.winOverlay.classList.add("hidden");
  dom.gameoverOverlay.classList.add("hidden");
  state.timerWarningShown.clear();
  state.countdownSecondsShown.clear();
  state.lastTimerDisplay = null;
  state.paused = false;
  state.phaseBeforePause = null;
  showPause(false);
  clearActiveItem();
  resetUsedObjects();
  hideResultBanner();
  stopWeightAnimation();
  setWeightDisplayState("idle");
  setWeightDisplayValue(0);
  setNeedleAngle(0);

  state.backend = await apiStart();
  state.timeRemaining = state.backend.config?.timer_seconds ?? 60;
  updateHudFromBackend();
  updateTimerDisplay();
  setSpeech("Get ready.");
  playAmbientLoopFromStart();

  await runStartCountdown();
}

function startTimerLoop() {
  let prevTs = performance.now();

  const loop = (ts) => {
    const delta = (ts - prevTs) / 1000;
    prevTs = ts;

    if (!state.paused && state.phase === "waiting_input") {
      state.timeRemaining = clamp(state.timeRemaining - delta, 0, 9999);
      updateTimerDisplay();

      if (state.timeRemaining <= 0) {
        showGameOver("timer");
      }
    }

    requestAnimationFrame(loop);
  };

  requestAnimationFrame(loop);
}

function wireEvents() {
  dom.sendButton.addEventListener("click", handleSubmit);
  dom.answerInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      handleSubmit();
    }
  });

  dom.restartButton.addEventListener("click", restartGame);
  dom.ambientVolumeSlider.addEventListener("input", (ev) => {
    onAmbientVolumeChange(ev.target.value);
  });
  dom.ambientMuteButton.addEventListener("click", onAmbientMuteToggle);

  window.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      ev.preventDefault();
      togglePause();
    }
  });
}

async function boot() {
  wireEvents();
  disableInput(true);
  resetUsedObjects();
  refreshAmbientControls();
  applyAmbientSettings();
  ensurePlateHitAudio();
  state.backend = await apiStart();
  state.timeRemaining = state.backend.config?.timer_seconds ?? 60;

  updateHudFromBackend();
  updateTimerDisplay();
  setNeedleAngle(0);
  setWeightDisplayState("idle");
  setWeightDisplayValue(0);
  setSpeech("Get ready.");
  playAmbientLoopFromStart();

  startTimerLoop();
  await runStartCountdown();
}

boot().catch((err) => {
  console.error(err);
  setSpeech("Startup failed. Check server logs.");
});
