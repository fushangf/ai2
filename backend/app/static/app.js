const canvas = document.getElementById("drawingCanvas");
const ctx = canvas.getContext("2d");
const listenStatus = document.getElementById("listenStatus");
const transcript = document.getElementById("transcript");
const planSummary = document.getElementById("planSummary");
const latency = document.getElementById("latency");
const thinking = document.getElementById("thinking");
const thinkingTitle = document.getElementById("thinkingTitle");
const thinkingNote = document.getElementById("thinkingNote");
const voiceOrb = document.getElementById("voiceOrb");
const sceneInfo = document.getElementById("sceneInfo");
const dslOutput = document.getElementById("dslOutput");
const permissionOverlay = document.getElementById("permissionOverlay");
const permissionButton = document.getElementById("permissionButton");
const providerBadge = document.getElementById("providerBadge");
const modelBadge = document.getElementById("modelBadge");
const taskStatus = document.getElementById("taskStatus");
const progressFill = document.getElementById("progressFill");
const progressText = document.getElementById("progressText");
const activityLog = document.getElementById("activityLog");
const promptBufferEl = document.getElementById("promptBuffer");
const routeBadge = document.getElementById("routeBadge");
const routeReason = document.getElementById("routeReason");
const silenceCountdown = document.getElementById("silenceCountdown");
const countdownFill = document.getElementById("countdownFill");
const audioLevelFill = document.getElementById("audioLevelFill");
const planSteps = document.getElementById("planSteps");
const userIdentity = document.getElementById("userIdentity");
const logoutButton = document.getElementById("logoutButton");
const asrConfidence = document.getElementById("asrConfidence");
const preflightStatus = document.getElementById("preflightStatus");
const interactionModeEl = document.getElementById("interactionMode");

const state = {
  background: { mode: "solid", color1: "#ffffff", color2: "#ffffff", direction: "vertical" },
  objects: [],
};

let undoStack = [];
let redoStack = [];
let recognition = null;
let shouldListen = true;
let recognizing = false;
let pausedForSpeech = false;
let busy = false;
let restartTimer = null;
let lastFinalText = "";
let lastFinalAt = 0;
let currentRequestController = null;
let jobCounter = 0;
let activeJobToken = 0;
let currentJobBaseState = null;
let stopRequested = false;
let voiceMode = "idle"; // idle | dictating | busy_stop | paused
let dictationBuffer = [];
let lastInterimControlAt = 0;
let dictationSilenceTimer = null;
let silenceCountdownTicker = null;
let silenceDeadline = 0;
let lastVoiceActivityAt = 0;
let audioContext = null;
let audioAnalyser = null;
let audioStream = null;
let vadAnimationFrame = null;
let vadNoiseFloor = 0.012;
let lastVadMarkAt = 0;
let lastPrompt = "";
let animationDelayScale = 1;
let dictationVersion = 0;
let lastAcceptedChunk = "";
let lastAcceptedChunkAt = 0;
let recognitionErrorCount = 0;
let recognitionBackoffMs = 320;
let lastRecognitionConfidence = null;
let interactionMode = "draw_v1";
let voiceConversationHistory = [];
const MAX_VOICE_CHAT_HISTORY = 12;
const AUTO_FINISH_MS = 3000;
const REQUEST_TIMEOUT_MS = 55000;
const RECOVERY_KEY_PREFIX = "voice_draw_recovery_v2";

function getAuth() {
  const raw = localStorage.getItem("voice_draw_auth");
  if (!raw) return null;
  try { return JSON.parse(raw); } catch (_) { return null; }
}

function authHeaders(extra = {}) {
  const auth = getAuth();
  return auth ? { Authorization: `Bearer ${auth.token}`, ...extra } : extra;
}

function logout() {
  localStorage.removeItem("voice_draw_auth");
  window.location.href = "/login";
}

logoutButton?.addEventListener("click", logout);

function clearDictationSilenceTimer() {
  if (dictationSilenceTimer) {
    clearTimeout(dictationSilenceTimer);
    dictationSilenceTimer = null;
  }
  if (silenceCountdownTicker) {
    clearInterval(silenceCountdownTicker);
    silenceCountdownTicker = null;
  }
  silenceDeadline = 0;
  if (silenceCountdown) silenceCountdown.textContent = "—";
  if (countdownFill) countdownFill.style.width = "0%";
}

function updateSilenceCountdown() {
  if (!silenceDeadline || voiceMode !== "dictating" || !dictationText()) {
    if (silenceCountdown) silenceCountdown.textContent = voiceMode === "dictating" ? "等待内容" : "—";
    if (countdownFill) countdownFill.style.width = "0%";
    return;
  }
  const remaining = Math.max(0, silenceDeadline - Date.now());
  if (silenceCountdown) silenceCountdown.textContent = `${(remaining / 1000).toFixed(1)} 秒`;
  if (countdownFill) countdownFill.style.width = `${Math.max(0, Math.min(100, (1 - remaining / AUTO_FINISH_MS) * 100))}%`;
}

function scheduleAutoFinish(reason = "检测到 3 秒静默，已自动开始绘图") {
  if (voiceMode !== "dictating" || busy || !dictationText()) return;
  if (dictationSilenceTimer) clearTimeout(dictationSilenceTimer);
  const scheduledVersion = dictationVersion;
  silenceDeadline = Date.now() + AUTO_FINISH_MS;
  updateSilenceCountdown();
  if (!silenceCountdownTicker) silenceCountdownTicker = setInterval(updateSilenceCountdown, 80);
  dictationSilenceTimer = setTimeout(() => {
    const quietFor = Date.now() - lastVoiceActivityAt;
    const stable = scheduledVersion === dictationVersion;
    if (voiceMode === "dictating" && !busy && dictationText() && stable && quietFor >= AUTO_FINISH_MS - 120) {
      finishDictation(reason);
    } else if (voiceMode === "dictating" && dictationText()) {
      scheduleAutoFinish(reason);
    }
  }, AUTO_FINISH_MS + 40);
}

function markVoiceActivity() {
  if (voiceMode !== "dictating" || busy) return;
  lastVoiceActivityAt = Date.now();
  dictationVersion += 1;
  if (dictationText()) scheduleAutoFinish();
}

async function initializeAudioVAD(silentFailure = false) {
  if (audioAnalyser && audioStream) return true;
  if (!navigator.mediaDevices?.getUserMedia) return false;
  try {
    audioStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaStreamSource(audioStream);
    audioAnalyser = audioContext.createAnalyser();
    audioAnalyser.fftSize = 1024;
    audioAnalyser.smoothingTimeConstant = 0.72;
    source.connect(audioAnalyser);
    const data = new Uint8Array(audioAnalyser.fftSize);

    const sample = () => {
      if (!audioAnalyser) return;
      audioAnalyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const value of data) {
        const normalized = (value - 128) / 128;
        sum += normalized * normalized;
      }
      const rms = Math.sqrt(sum / data.length);
      const visual = Math.min(100, Math.max(2, rms * 650));
      if (audioLevelFill) audioLevelFill.style.width = `${visual}%`;
      const threshold = Math.max(0.016, vadNoiseFloor * 2.2 + 0.006);
      if (rms > threshold) {
        const now = Date.now();
        if (now - lastVadMarkAt > 140) {
          lastVadMarkAt = now;
          markVoiceActivity();
        }
      } else {
        vadNoiseFloor = vadNoiseFloor * 0.985 + rms * 0.015;
      }
      vadAnimationFrame = requestAnimationFrame(sample);
    };
    sample();
    logEvent("自适应语音活动检测 VAD 已启动", "success");
    return true;
  } catch (error) {
    if (!silentFailure) logEvent(`VAD 初始化失败：${error.message || "未授权"}`, "warn");
    return false;
  }
}

function deepClone(value) { return JSON.parse(JSON.stringify(value)); }
function snapshot() { return deepClone(state); }
function trimHistory() { if (undoStack.length > 40) undoStack = undoStack.slice(-40); }
function commitHistory(previousState) { undoStack.push(deepClone(previousState)); trimHistory(); redoStack = []; }
function restore(s) { state.background = deepClone(s.background); state.objects = deepClone(s.objects); render(); }

function recoveryStorageKey() {
  const auth = getAuth();
  const identity = auth?.user?.id || auth?.user?.username || "anonymous";
  return `${RECOVERY_KEY_PREFIX}_${identity}`;
}

function persistLocalRecovery(reason = "自动保存") {
  try {
    localStorage.setItem(recoveryStorageKey(), JSON.stringify({
      version: 2,
      savedAt: Date.now(),
      reason,
      lastPrompt,
      scene: snapshot(),
    }));
  } catch (_) {
    // localStorage may be unavailable in hardened browser modes; drawing still works.
  }
}

function restoreLocalRecovery(announce = false) {
  try {
    const raw = localStorage.getItem(recoveryStorageKey());
    if (!raw) {
      if (announce) speak("没有找到可恢复的现场");
      return false;
    }
    const saved = JSON.parse(raw);
    if (!saved?.scene || !Array.isArray(saved.scene.objects)) throw new Error("恢复数据格式无效");
    restore(saved.scene);
    lastPrompt = saved.lastPrompt || lastPrompt;
    logEvent(`已恢复本机现场：${saved.reason || "自动保存"}`, "success");
    if (announce) speak("已恢复上次中断前的绘图现场");
    return true;
  } catch (error) {
    localStorage.removeItem(recoveryStorageKey());
    if (announce) speak("恢复现场失败");
    return false;
  }
}

function nowStamp() {
  return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function logEvent(text, level = "info") {
  const item = document.createElement("li");
  item.className = `log-item ${level}`;
  item.textContent = `${nowStamp()} · ${text}`;
  activityLog.prepend(item);
  while (activityLog.children.length > 12) activityLog.removeChild(activityLog.lastChild);
}

function setTaskStatus(text) {
  taskStatus.textContent = text;
}

function setProgress(completed = 0, total = 0, label = "等待任务") {
  const ratio = total > 0 ? Math.min(1, completed / total) : 0;
  progressFill.style.width = `${Math.round(ratio * 100)}%`;
  progressText.textContent = label;
}

function renderPlanSteps(steps = []) {
  if (!planSteps) return;
  planSteps.innerHTML = "";
  const items = steps.length ? steps : ["等待语音任务"];
  items.slice(0, 10).forEach((step) => {
    const li = document.createElement("li");
    li.textContent = step;
    planSteps.appendChild(li);
  });
}

function setRouteInfo(source = "pending", reason = "") {
  if (source === "local") routeBadge.textContent = "本地低延迟";
  else if (source === "ai") routeBadge.textContent = "AI 复杂规划";
  else if (source === "cache") routeBadge.textContent = "验证缓存命中";
  else if (source === "voice_v2") routeBadge.textContent = "语音交流 V2";
  else routeBadge.textContent = "待判断";
  routeBadge.classList.toggle("local-route", source === "local");
  routeBadge.classList.toggle("ai-route", source === "ai");
  routeBadge.classList.toggle("cache-route", source === "cache");
  routeBadge.classList.toggle("voice-v2-route", source === "voice_v2");
  if (routeReason) routeReason.textContent = reason || "系统会自动选择本地快速通道、已验证缓存、AI 复杂规划或语音交流模型 V2。";
}

function updateInteractionModeUI() {
  if (!interactionModeEl) return;
  interactionModeEl.textContent = interactionMode === "chat_v2" ? "交流 V2" : "绘图 V1";
}

function setInteractionMode(mode, announce = false) {
  interactionMode = mode === "chat_v2" ? "chat_v2" : "draw_v1";
  updateInteractionModeUI();
  const message = interactionMode === "chat_v2"
    ? "已切换到语音交流模型 V2，说开始后自然说话，静默三秒我会直接回复。"
    : "已切换回绘图模式，说开始后描述画面，静默三秒自动绘图。";
  planSummary.textContent = message;
  if (interactionMode === "chat_v2") {
    setRouteInfo("voice_v2", "当前处于语音交流模型 V2，不修改画布，只进行语音问答。")
  } else {
    setRouteInfo("pending", "当前处于绘图模式，系统会自动选择本地快速通道、已验证缓存或 AI 复杂规划通道。");
  }
  logEvent(message, "info");
  if (announce) speak(message);
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function colorOr(value, fallback) {
  if (!value || typeof value !== "string") return fallback;
  return value;
}

function drawBackground() {
  const bg = state.background || {};
  if (bg.mode === "linear_gradient") {
    let gradient;
    if (bg.direction === "horizontal") gradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
    else if (bg.direction === "diagonal") gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    else gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
    gradient.addColorStop(0, colorOr(bg.color1, "#ffffff"));
    gradient.addColorStop(1, colorOr(bg.color2, "#ffffff"));
    ctx.fillStyle = gradient;
  } else {
    ctx.fillStyle = colorOr(bg.color1, "#ffffff");
  }
  ctx.fillRect(0, 0, canvas.width, canvas.height);
}

function pointsCenter(points) {
  if (!points?.length) return { x: 0, y: 0 };
  const sum = points.reduce((a, p) => ({ x: a.x + p.x, y: a.y + p.y }), { x: 0, y: 0 });
  return { x: sum.x / points.length, y: sum.y / points.length };
}

function anchorFor(shape) {
  switch (shape.type) {
    case "circle":
    case "ellipse":
    case "arc":
      return { x: shape.cx, y: shape.cy };
    case "rect":
      return { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 };
    case "line":
      return { x: (shape.x1 + shape.x2) / 2, y: (shape.y1 + shape.y2) / 2 };
    case "polygon":
    case "polyline":
      return pointsCenter(shape.points);
    case "bezier":
      return { x: (shape.p0.x + shape.p3.x) / 2, y: (shape.p0.y + shape.p3.y) / 2 };
    case "text":
      return { x: shape.x, y: shape.y };
    default:
      return { x: 0, y: 0 };
  }
}

function roundRectPath(x, y, width, height, radius) {
  const r = Math.min(Math.max(radius || 0, 0), width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function applyStyle(shape) {
  ctx.globalAlpha = shape.opacity ?? 1;
  ctx.fillStyle = colorOr(shape.fill, "transparent");
  ctx.strokeStyle = colorOr(shape.stroke, "#111827");
  ctx.lineWidth = shape.stroke_width ?? 2;
}

function fillAndStroke(shape, canFill = true) {
  if (canFill && shape.fill && shape.fill !== "transparent" && (shape.opacity ?? 1) > 0) ctx.fill();
  if (shape.stroke && shape.stroke !== "transparent" && (shape.stroke_width ?? 0) > 0) ctx.stroke();
}

function drawShape(shape) {
  ctx.save();
  applyStyle(shape);
  const anchor = anchorFor(shape);
  const tx = shape._tx || 0;
  const ty = shape._ty || 0;
  const scale = shape._scale || 1;
  const rotation = ((shape.rotation || 0) + (shape._rotation || 0)) * Math.PI / 180;
  ctx.translate(anchor.x + tx, anchor.y + ty);
  ctx.rotate(rotation);
  ctx.scale(scale, scale);
  ctx.translate(-anchor.x, -anchor.y);

  if (shape.type === "circle") {
    ctx.beginPath();
    ctx.arc(shape.cx, shape.cy, shape.r, 0, Math.PI * 2);
    fillAndStroke(shape);
  } else if (shape.type === "ellipse") {
    ctx.beginPath();
    ctx.ellipse(shape.cx, shape.cy, shape.rx, shape.ry, 0, 0, Math.PI * 2);
    fillAndStroke(shape);
  } else if (shape.type === "rect") {
    roundRectPath(shape.x, shape.y, shape.width, shape.height, shape.radius);
    fillAndStroke(shape);
  } else if (shape.type === "line") {
    ctx.lineCap = shape.line_cap || "round";
    ctx.beginPath();
    ctx.moveTo(shape.x1, shape.y1);
    ctx.lineTo(shape.x2, shape.y2);
    fillAndStroke(shape, false);
  } else if (shape.type === "polygon" || shape.type === "polyline") {
    ctx.lineCap = shape.line_cap || "round";
    ctx.lineJoin = shape.line_join || "round";
    ctx.beginPath();
    shape.points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
    if (shape.type === "polygon") ctx.closePath();
    fillAndStroke(shape, shape.type === "polygon");
  } else if (shape.type === "bezier") {
    ctx.lineCap = shape.line_cap || "round";
    ctx.beginPath();
    ctx.moveTo(shape.p0.x, shape.p0.y);
    ctx.bezierCurveTo(shape.p1.x, shape.p1.y, shape.p2.x, shape.p2.y, shape.p3.x, shape.p3.y);
    fillAndStroke(shape, false);
  } else if (shape.type === "arc") {
    ctx.beginPath();
    ctx.arc(shape.cx, shape.cy, shape.r, shape.start_angle * Math.PI / 180, shape.end_angle * Math.PI / 180, !!shape.counterclockwise);
    fillAndStroke(shape, false);
  } else if (shape.type === "text") {
    ctx.font = `${shape.font_size || 28}px ${shape.font_family || "sans-serif"}`;
    ctx.textAlign = shape.align || "center";
    ctx.textBaseline = shape.baseline || "middle";
    if (shape.fill && shape.fill !== "transparent") ctx.fillText(shape.text, shape.x, shape.y);
    if (shape.stroke && shape.stroke !== "transparent" && (shape.stroke_width || 0) > 0) ctx.strokeText(shape.text, shape.x, shape.y);
  }
  ctx.restore();
}

function render() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawBackground();
  [...state.objects].sort((a, b) => (a.z_index || 0) - (b.z_index || 0)).forEach(drawShape);
  const groups = new Set(state.objects.map(o => o.group_id).filter(Boolean));
  sceneInfo.textContent = `当前 ${state.objects.length} 个图元，${groups.size} 个语义对象`;
}

function targetMatches(shape, op) {
  return (op.target_ids || []).includes(shape.id) || (shape.group_id && (op.target_group_ids || []).includes(shape.group_id));
}

function applyOperation(op) {
  if (op.op === "clear") {
    state.objects = [];
    state.background = { mode: "solid", color1: "#ffffff", color2: "#ffffff", direction: "vertical" };
  } else if (op.op === "background") {
    state.background = deepClone(op);
    delete state.background.op;
  } else if (op.op === "create") {
    const shape = deepClone(op.shape);
    const existingIndex = state.objects.findIndex(item => item.id === shape.id);
    if (existingIndex >= 0) state.objects[existingIndex] = shape;
    else state.objects.push(shape);
  } else if (op.op === "delete") {
    state.objects = state.objects.filter(shape => !targetMatches(shape, op));
  } else if (op.op === "recolor") {
    state.objects.forEach(shape => {
      if (!targetMatches(shape, op)) return;
      if (op.fill !== null && op.fill !== undefined) shape.fill = op.fill;
      if (op.stroke !== null && op.stroke !== undefined) shape.stroke = op.stroke;
    });
  } else if (op.op === "transform") {
    state.objects.forEach(shape => {
      if (!targetMatches(shape, op)) return;
      shape._tx = (shape._tx || 0) + (op.dx || 0);
      shape._ty = (shape._ty || 0) + (op.dy || 0);
      shape._scale = (shape._scale || 1) * (op.scale || 1);
      shape._rotation = (shape._rotation || 0) + (op.rotation_delta || 0);
    });
  }
}

function bboxFor(shape) {
  const a = anchorFor(shape);
  if (shape.type === "circle" || shape.type === "arc") return [shape.cx - shape.r, shape.cy - shape.r, shape.r * 2, shape.r * 2];
  if (shape.type === "ellipse") return [shape.cx - shape.rx, shape.cy - shape.ry, shape.rx * 2, shape.ry * 2];
  if (shape.type === "rect") return [shape.x, shape.y, shape.width, shape.height];
  if (shape.type === "line") return [Math.min(shape.x1, shape.x2), Math.min(shape.y1, shape.y2), Math.abs(shape.x2 - shape.x1), Math.abs(shape.y2 - shape.y1)];
  if (shape.points?.length) {
    const xs = shape.points.map(p => p.x);
    const ys = shape.points.map(p => p.y);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
  }
  return [a.x - 20, a.y - 20, 40, 40];
}

function sceneSummary() {
  return {
    background: deepClone(state.background),
    objects: state.objects.slice(-220).map(shape => ({
      id: shape.id,
      group_id: shape.group_id || "",
      label: shape.label || "",
      type: shape.type,
      bbox: bboxFor(shape),
      fill: shape.fill || "",
      stroke: shape.stroke || "",
      tags: shape.tags || [],
    })),
  };
}

function updateAsrConfidence(confidence, label = "") {
  if (!asrConfidence) return;
  if (typeof confidence !== "number" || !Number.isFinite(confidence) || confidence <= 0) {
    asrConfidence.textContent = label || "浏览器未提供";
    return;
  }
  const percent = Math.round(confidence * 100);
  asrConfidence.textContent = `${percent}%${label ? ` · ${label}` : ""}`;
}

function selectBestRecognitionAlternative(result) {
  const alternatives = Array.from(result || []).map(item => ({
    text: String(item.transcript || "").trim(),
    confidence: Number(item.confidence || 0),
  })).filter(item => item.text);
  if (!alternatives.length) return { text: "", confidence: 0, alternatives: [] };

  const domainWords = /(开始|停止|撤销|重做|清空|保存|绘图|画|移动|放大|缩小|旋转|删除|颜色|左|右|上|下|作品|自检)/;
  const scored = alternatives.map((item, index) => {
    const compact = compactVoiceText(item.text);
    let score = item.confidence > 0 ? item.confidence : 0.48 - index * 0.025;
    if (domainWords.test(compact)) score += 0.22;
    if (compact.length >= 6) score += 0.08;
    if (/^(嗯|啊|哦|呃|那个|然后|就是)$/.test(compact)) score -= 0.45;
    return { ...item, score };
  }).sort((a, b) => b.score - a.score);
  return {
    text: scored[0].text,
    confidence: scored[0].confidence,
    alternatives: alternatives.map(item => item.text),
  };
}

function isMeaningfulDictationChunk(text, confidence = 0) {
  const cleaned = cleanDictationText(text);
  const compact = compactVoiceText(cleaned);
  if (!compact || /^(嗯|啊|哦|呃|那个|然后|接着|就是|这个|那个那个)$/.test(compact)) return false;
  const meaningfulLength = (compact.match(/[\u4e00-\u9fffA-Za-z0-9]/g) || []).length;
  if (meaningfulLength < 2) return false;
  // Some browsers always report 0 confidence. Only reject when a real low value is supplied.
  if (confidence > 0 && confidence < 0.28 && meaningfulLength < 7) return false;
  return true;
}

function compactVoiceText(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[\s，。！？、,.!?；;：:"'“”‘’（）()【】\[\]<>《》]/g, "")
    .replace(/开使|开识|开市|开驶|凯始|开始吧|开始了/g, "开始")
    .replace(/完必|玩毕|完币|完闭|完毕了|说完了|说完啦|描述完毕|描述完成|结束描述|结束了/g, "完毕")
    .replace(/停址|廷止|停止了|停下|停一下|别画了|不要画了|取消绘图|取消当前任务|终止任务/g, "停止");
}

function hasStartCommand(texts) {
  return texts.some(t => {
    const c = compactVoiceText(t);
    return c === "开始" || c.includes("开始画") || c.includes("开始绘画") || c.includes("开始创作") || c.includes("开始记录") || c.includes("开始描述") || c.startsWith("开始");
  });
}

function hasFinishCommand(texts) {
  return texts.some(t => {
    const c = compactVoiceText(t);
    return c === "完毕" || c.includes("完毕") || c.includes("开始画吧") || c.includes("可以画了") || c.includes("画吧") || c.includes("好了开始画");
  });
}

function hasStopCommand(texts) {
  return texts.some(t => {
    const c = compactVoiceText(t);
    return c === "停" || c === "停止" || c.includes("停止") || c.includes("停止绘图") || c.includes("停止绘制") || c.includes("取消") || c.includes("终止");
  });
}

function textAfterStart(text) {
  const raw = String(text || "").trim();
  const idx = raw.search(/开始|开使|开识|开市|开驶|凯始/);
  if (idx < 0) return "";
  return raw.slice(idx).replace(/^(开始|开使|开识|开市|开驶|凯始)[，。！？、\s]*(画|绘制|创作|描述|记录)?[，。！？、\s]*/i, "").trim();
}

function textBeforeFinish(text) {
  const raw = String(text || "").trim();
  const m = raw.search(/完毕|完必|玩毕|完币|完闭|说完了|说完啦|结束描述|描述完毕|描述完成|可以画了|画吧/);
  if (m < 0) return raw;
  return raw.slice(0, m).trim();
}

function cleanDictationText(text) {
  return String(text || "")
    .replace(/^(开始|开使|开识|开市|开驶|凯始)[，。！？、\s]*(画|绘制|创作|描述|记录)?[，。！？、\s]*/i, "")
    .replace(/[，。！？、\s]*(完毕|完必|玩毕|完币|完闭|说完了|说完啦|结束描述|描述完毕|描述完成|可以画了|画吧)$/i, "")
    .trim();
}

function dictationText() {
  return dictationBuffer.join("，").replace(/[，、\s]+$/g, "").trim();
}

function updatePromptBuffer() {
  const text = dictationText();
  const idleHint = interactionMode === "chat_v2" ? "尚未开始交流" : "尚未开始记录";
  const dictatingHint = interactionMode === "chat_v2" ? "正在记录交流内容，3 秒静默将自动回复" : "正在记录，3 秒静默将自动开始绘图";
  promptBufferEl.textContent = text || (voiceMode === "dictating" ? dictatingHint : idleHint);
}

function setVoiceMode(mode, reason = "") {
  voiceMode = mode;
  voiceOrb.classList.toggle("recording", mode === "dictating");
  if (mode === "idle") {
    clearDictationSilenceTimer();
    setTaskStatus(interactionMode === "chat_v2" ? "待机：请说“开始”进行交流" : "待机：请说“开始”");
    setListeningUI(interactionMode === "chat_v2" ? "待机中，只等待“开始”进入交流" : "待机中，只等待“开始”", "idle");
    if (reason) logEvent(reason, "info");
  } else if (mode === "dictating") {
    setTaskStatus(interactionMode === "chat_v2" ? "正在记录交流内容" : "正在记录绘画描述");
    setListeningUI(interactionMode === "chat_v2" ? "正在记录，静默 3 秒自动回复" : "正在记录，静默 3 秒自动开始绘图", "listening");
    if (reason) logEvent(reason, "success");
  } else if (mode === "busy_stop") {
    clearDictationSilenceTimer();
    setTaskStatus(interactionMode === "chat_v2" ? "语音交流模型 V2 正在回复" : "AI 正在绘制");
    setListeningUI(interactionMode === "chat_v2" ? "回复生成中，仅监听“停止”" : "绘制中，仅监听“停止”", "thinking");
  } else if (mode === "paused") {
    clearDictationSilenceTimer();
    setTaskStatus("语音暂停中");
    setListeningUI("监听已暂停", "idle");
  }
  updatePromptBuffer();
}

function speak(text) {
  if (!("speechSynthesis" in window) || !text) return;
  pausedForSpeech = true;
  if (recognition && recognizing) {
    try { recognition.abort(); } catch (_) {}
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1.08;
  const resume = () => {
    pausedForSpeech = false;
    scheduleRecognition(350);
  };
  utterance.onend = resume;
  utterance.onerror = resume;
  speechSynthesis.cancel();
  speechSynthesis.speak(utterance);
}

function setListeningUI(text, mode = "idle") {
  listenStatus.textContent = text;
  voiceOrb.classList.toggle("listening", mode === "listening");
  voiceOrb.classList.toggle("thinking", mode === "thinking");
}

function scheduleRecognition(delay = 500) {
  clearTimeout(restartTimer);
  restartTimer = setTimeout(startRecognitionSafe, delay);
}

function startRecognitionSafe() {
  if (!recognition || recognizing || pausedForSpeech || !shouldListen) return;
  try {
    recognition.start();
  } catch (_) {
    scheduleRecognition(800);
  }
}

function pauseListeningForTenSeconds() {
  shouldListen = false;
  clearTimeout(restartTimer);
  clearDictationSilenceTimer();
  if (recognition && recognizing) {
    try { recognition.abort(); } catch (_) {}
  }
  setVoiceMode("paused");
  logEvent("已暂停语音监听 10 秒", "warn");
  setTimeout(() => {
    shouldListen = true;
    setVoiceMode("idle", "已自动恢复到待机状态");
    scheduleRecognition(220);
  }, 10000);
}

function undo() {
  if (!undoStack.length) return speak("没有可以撤销的操作");
  redoStack.push(snapshot());
  restore(undoStack.pop());
  persistLocalRecovery("撤销后自动保存");
  logEvent("已撤销上一步", "success");
  speak("已撤销");
}

function redo() {
  if (!redoStack.length) return speak("没有可以重做的操作");
  undoStack.push(snapshot());
  restore(redoStack.pop());
  persistLocalRecovery("重做后自动保存");
  logEvent("已重做上一步", "success");
  speak("已重做");
}

function clearScene() {
  const previous = snapshot();
  commitHistory(previous);
  state.objects = [];
  state.background = { mode: "solid", color1: "#ffffff", color2: "#ffffff", direction: "vertical" };
  render();
  persistLocalRecovery("清空画布后自动保存");
  logEvent("画布已清空", "warn");
  speak("画布已清空");
}

function saveImage() {
  const a = document.createElement("a");
  a.download = `ai-voice-drawing-${Date.now()}.png`;
  a.href = canvas.toDataURL("image/png");
  a.click();
  logEvent("图片已导出为 PNG", "success");
  speak("图片已保存");
}

async function saveArtwork() {
  if (!state.objects.length) {
    speak("当前画布还是空的，暂时不能保存作品");
    return;
  }
  try {
    const title = lastPrompt ? lastPrompt.slice(0, 36) : `语音绘画作品 ${nowStamp()}`;
    const response = await fetch("/api/artworks", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ title, scene: snapshot() }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "保存作品失败");
    logEvent(`作品已保存到账号：${data.title}`, "success");
    speak("作品已保存到你的账号");
  } catch (error) {
    logEvent(`保存作品失败：${error.message}`, "error");
    speak(`保存作品失败，${error.message}`);
  }
}

async function loadLatestArtwork() {
  try {
    const response = await fetch("/api/artworks/latest", { headers: authHeaders() });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "读取作品失败");
    const previous = snapshot();
    restore(data.scene);
    commitHistory(previous);
    logEvent(`已恢复作品：${data.title}`, "success");
    speak(`已打开上一次保存的作品，${data.title}`);
  } catch (error) {
    logEvent(`打开作品失败：${error.message}`, "warn");
    speak(error.message || "还没有保存过作品");
  }
}

async function announceArtworkCount() {
  try {
    const response = await fetch("/api/artworks?limit=100", { headers: authHeaders() });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "读取作品列表失败");
    speak(`你一共保存了 ${data.artworks?.length || 0} 幅作品`);
  } catch (error) {
    speak(error.message || "读取作品数量失败");
  }
}

function speakHelp() {
  const text = "你可以说开始后描述画面，静默三秒自动绘图。还可以说撤销、重做、清空画布、保存图片、保存作品、打开上次作品、重复上次描述和停止。也可以说进入交流模式，切到语音交流模型 V2，和我自然对话。";
  planSummary.textContent = text;
  renderPlanSteps(["说开始并描述画面", "静默 3 秒自动提交", "继续用自然语言编辑", "说停止可中断并回滚"]);
  speak(text);
}

async function runSystemPreflight(announce = true) {
  if (preflightStatus) {
    preflightStatus.textContent = "检测中";
    preflightStatus.classList.remove("preflight-ok", "preflight-warn");
  }
  try {
    const response = await fetch("/api/preflight");
    const data = await response.json();
    const browserSpeech = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
    const microphoneReady = !!audioAnalyser;
    const allReady = !!data.ok && browserSpeech && microphoneReady;
    if (preflightStatus) {
      preflightStatus.textContent = allReady ? "全部就绪" : "需要处理";
      preflightStatus.classList.toggle("preflight-ok", allReady);
      preflightStatus.classList.toggle("preflight-warn", !allReady);
    }
    const details = [
      `后端${data.checks?.backend?.ok ? "正常" : "异常"}`,
      `数据库${data.checks?.database?.ok ? "正常" : "异常"}`,
      `AI${data.checks?.ai?.ok ? "已配置" : "未配置"}`,
      `语音识别${browserSpeech ? "可用" : "不可用"}`,
      `麦克风${microphoneReady ? "就绪" : "未授权"}`,
    ];
    logEvent(`系统自检：${details.join("，")}`, allReady ? "success" : "warn");
    if (announce) speak(allReady ? "系统自检通过，比赛演示环境已就绪" : `系统自检完成，${details.join("，")}`);
    return allReady;
  } catch (error) {
    if (preflightStatus) {
      preflightStatus.textContent = "后端不可达";
      preflightStatus.classList.add("preflight-warn");
    }
    logEvent(`系统自检失败：${error.message}`, "error");
    if (announce) speak("系统自检失败，请检查后端服务");
    return false;
  }
}

function validatePlanForClient(plan) {
  if (!plan || !Array.isArray(plan.operations) || plan.operations.length < 1 || plan.operations.length > 220) {
    throw new Error("Drawing DSL 操作数量不合法");
  }
  const allowedOps = new Set(["clear", "background", "create", "delete", "recolor", "transform"]);
  const allowedShapes = new Set(["circle", "ellipse", "rect", "line", "polygon", "polyline", "bezier", "arc", "text"]);
  for (const op of plan.operations) {
    if (!allowedOps.has(op?.op)) throw new Error(`不支持的 Drawing DSL 操作：${op?.op || "未知"}`);
    if (op.op === "create") {
      if (!op.shape?.id || !allowedShapes.has(op.shape.type)) throw new Error("创建图元缺少安全的 id 或类型");
    }
  }
  return true;
}

function stopCurrentJob(feedback = "已停止当前绘制", shouldSpeak = true) {
  clearDictationSilenceTimer();
  if (!busy && !currentRequestController && voiceMode !== "dictating") return false;
  if (voiceMode === "dictating" && !busy) {
    dictationBuffer = [];
    transcript.textContent = "已取消本次描述，请重新说“开始”";
    planSummary.textContent = "本次绘画描述已取消";
    setVoiceMode("idle");
    logEvent("已取消语音描述", "warn");
    if (shouldSpeak) speak("已取消，请重新说开始");
    return true;
  }
  stopRequested = true;
  activeJobToken += 1;
  if (currentRequestController) {
    try { currentRequestController.abort(); } catch (_) {}
  }
  if (currentJobBaseState) restore(currentJobBaseState);
  currentRequestController = null;
  currentJobBaseState = null;
  busy = false;
  thinking.classList.add("hidden");
  setVoiceMode("idle");
  setProgress(0, 0, "当前任务已停止");
  planSummary.textContent = feedback;
  logEvent(feedback, "warn");
  if (shouldSpeak) speak(feedback);
  return true;
}

function handleLocalControl(text, alternatives = [text]) {
  const all = alternatives.length ? alternatives : [text];
  const primary = compactVoiceText(text);
  if (hasStopCommand(all) && (busy || voiceMode === "dictating")) {
    return stopCurrentJob(voiceMode === "dictating" ? "已取消当前绘画描述" : "已停止当前绘制", true);
  }
  if (/^(撤销|返回上一步|取消上一步)$/.test(primary)) { undo(); return true; }
  if (/^(重做|恢复上一步)$/.test(primary)) { redo(); return true; }
  if (/^(清空画布|全部清除|清除画布|新建画布)$/.test(primary)) { clearScene(); return true; }
  if (/^(保存作品|保存到账号|云端保存)$/.test(primary)) { saveArtwork(); return true; }
  if (/^(打开上次作品|恢复上次作品|加载上次作品)$/.test(primary)) { loadLatestArtwork(); return true; }
  if (/^(我的作品|作品数量|我有多少作品)$/.test(primary)) { announceArtworkCount(); return true; }
  if (/^(保存图片|导出图片|下载图片)$/.test(primary)) { saveImage(); return true; }
  if (/^(朗读状态|当前状态)$/.test(primary)) {
    speak(`${sceneInfo.textContent}，当前模式是${interactionMode === "chat_v2" ? "语音交流版本二" : "绘图版本一"}，当前执行路径是${routeBadge.textContent}`);
    return true;
  }
  if (/^(语音帮助|帮助|有哪些指令|使用说明)$/.test(primary)) { speakHelp(); return true; }
  if (/^(系统自检|检查系统|赛前检查|环境自检)$/.test(primary)) { runSystemPreflight(true); return true; }
  if (/^(恢复现场|恢复崩溃前画面|恢复本机画面|恢复上次现场)$/.test(primary)) { restoreLocalRecovery(true); return true; }
  if (/^(重复上次描述|重复上一个任务|再画一次|重复上次交流)$/.test(primary)) {
    if (!lastPrompt) speak(interactionMode === "chat_v2" ? "还没有可以重复的交流内容" : "还没有可以重复的绘画描述");
    else if (interactionMode === "chat_v2") sendToVoiceChatV2(lastPrompt);
    else sendToAI(lastPrompt);
    return true;
  }
  if (/^(进入交流模式|切换到交流模式|语音交流模式|交流模式|版本二|v2模式)$/.test(primary)) {
    setInteractionMode("chat_v2", true);
    return true;
  }
  if (/^(退出交流模式|切换到绘图模式|绘图模式|返回绘图|返回绘画模式)$/.test(primary)) {
    setInteractionMode("draw_v1", true);
    return true;
  }
  if (/^(清空交流记录|重置交流记录|清除交流记录)$/.test(primary)) {
    voiceConversationHistory = [];
    planSummary.textContent = "语音交流记录已清空";
    speak("语音交流记录已清空");
    return true;
  }
  if (/^(加快绘制|绘制快一点)$/.test(primary)) {
    animationDelayScale = Math.max(0.25, animationDelayScale * 0.7);
    speak("已加快绘制动画");
    return true;
  }
  if (/^(减慢绘制|绘制慢一点)$/.test(primary)) {
    animationDelayScale = Math.min(3, animationDelayScale * 1.35);
    speak("已减慢绘制动画");
    return true;
  }
  if (/^(停止监听|停止语音|暂停监听|暂停十秒)$/.test(primary)) {
    speak("语音监听将暂停十秒");
    setTimeout(pauseListeningForTenSeconds, 900);
    return true;
  }
  if (/^(继续监听|恢复监听)$/.test(primary)) {
    shouldListen = true;
    setVoiceMode("idle", "已恢复监听");
    scheduleRecognition();
    speak("已继续监听，请说开始");
    return true;
  }
  return false;
}

async function animateOperations(operations, token) {
  const total = operations?.length || 0;
  for (let i = 0; i < total; i++) {
    if (stopRequested || token !== activeJobToken) {
      if (currentJobBaseState) restore(currentJobBaseState);
      return false;
    }
    applyOperation(operations[i]);
    render();
    const label = total > 0 ? `正在绘制 ${i + 1} / ${total}` : "正在绘制";
    setProgress(i + 1, total, label);
    setTaskStatus("AI 正在绘制");
    await sleep((operations[i].op === "create" ? 42 : 24) * animationDelayScale);
  }
  return true;
}

async function sendToAI(text) {
  lastPrompt = text;
  const token = ++jobCounter;
  activeJobToken = token;
  stopRequested = false;
  busy = true;
  currentJobBaseState = snapshot();
  currentRequestController = new AbortController();
  setVoiceMode("busy_stop");

  thinking.classList.remove("hidden");
  thinkingTitle.textContent = "AI 正在构图并编译绘图指令…";
  thinkingNote.textContent = "绘画内容监听已结束；当前只响应“停止”。";
  setTaskStatus("AI 正在规划");
  setProgress(0, 0, "正在调用 AI 规划画面");
  planSummary.textContent = "正在判断使用本地快速通道还是 AI 复杂规划通道…";
  setRouteInfo("pending", "正在根据指令复杂度和当前场景自动选择执行路径。");
  renderPlanSteps(["解析语音意图", "选择执行路径", "生成并校验 Drawing DSL", "逐步绘制到画布"]);
  logEvent(`开始处理：${text}`, "info");
  let requestTimedOut = false;
  const requestTimeoutId = setTimeout(() => {
    requestTimedOut = true;
    try { currentRequestController?.abort(); } catch (_) {}
  }, REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch("/api/plan", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text, canvas: { width: canvas.width, height: canvas.height }, scene: sceneSummary() }),
      signal: currentRequestController.signal,
    });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        logout();
        return;
      }
      throw new Error(data.detail || "AI 请求失败");
    }
    if (token !== activeJobToken || stopRequested) return;
    validatePlanForClient(data.plan);

    planSummary.textContent = `${data.plan.plan_summary}${data.repair_attempted ? "（AI 输出已自动修复）" : ""}${data.cache_hit ? "（命中已验证缓存）" : ""}`;
    latency.textContent = `${data.server_total_ms || data.latency_ms} ms`;
    setRouteInfo(data.source, data.route_reason || "执行路径已确定");
    renderPlanSteps(data.plan.execution_steps || []);
    dslOutput.textContent = JSON.stringify({
      source: data.source,
      route_reason: data.route_reason,
      latency_ms: data.latency_ms,
      repair_attempted: data.repair_attempted,
      plan: data.plan,
    }, null, 2);
    thinkingTitle.textContent = data.source === "local"
      ? "本地快速编辑正在执行"
      : data.source === "cache"
        ? "已验证缓存正在快速复现"
        : (data.plan.title || "AI 正在绘图");
    thinkingNote.textContent = `正在逐步执行 ${data.operation_count || data.plan.operations.length} 条 Drawing DSL；如需取消，请说“停止”。`;

    const success = await animateOperations(data.plan.operations, token);
    if (!success || token !== activeJobToken || stopRequested) return;

    commitHistory(currentJobBaseState);
    currentJobBaseState = null;
    persistLocalRecovery("绘图完成后自动保存");
    setProgress(data.plan.operations.length, data.plan.operations.length, `绘制完成，共 ${data.plan.operations.length} 步`);
    logEvent(`${data.source === "local" ? "本地编辑" : "AI 绘制"}完成：${data.plan.title || "未命名方案"}`, "success");
    speak(data.plan.spoken_feedback || "绘图完成。继续创作请说开始");
  } catch (error) {
    if (currentJobBaseState) restore(currentJobBaseState);
    if (error?.name === "AbortError") {
      const message = requestTimedOut ? "AI 请求超时，画布已自动回滚" : "当前任务已中止，画布已回滚";
      planSummary.textContent = message;
      logEvent(message, requestTimedOut ? "error" : "warn");
      if (requestTimedOut) speak("AI 请求超时，画布已经安全回滚，请检查网络后重试");
    } else {
      planSummary.textContent = `${error.message}，画布已自动回滚`;
      logEvent(`绘图失败并已回滚：${error.message}`, "error");
      speak(`绘图失败，${error.message}，画布已经回滚`);
    }
  } finally {
    clearTimeout(requestTimeoutId);
    if (token === activeJobToken) {
      busy = false;
      currentRequestController = null;
      currentJobBaseState = null;
      thinking.classList.add("hidden");
      dictationBuffer = [];
      setVoiceMode("idle");
      if (!stopRequested && progressText.textContent === "正在调用 AI 规划画面") setProgress(0, 0, "等待任务");
      if (!pausedForSpeech) scheduleRecognition(350);
    }
  }
}

async function sendToVoiceChatV2(text) {
  lastPrompt = text;
  const token = ++jobCounter;
  activeJobToken = token;
  stopRequested = false;
  busy = true;
  currentJobBaseState = null;
  currentRequestController = new AbortController();
  setVoiceMode("busy_stop");

  thinking.classList.remove("hidden");
  thinkingTitle.textContent = "语音交流模型 V2 正在生成回复…";
  thinkingNote.textContent = "交流内容监听已结束；当前只响应“停止”。";
  setTaskStatus("语音交流模型 V2 正在回复");
  setProgress(0, 0, "正在生成语音回复");
  planSummary.textContent = "正在调用语音交流模型 V2…";
  setRouteInfo("voice_v2", "当前处于语音交流模型 V2，不修改画布，只进行自然语音交流。");
  renderPlanSteps(["整理最近交流上下文", "生成自然语言回复", "语音播报回复"]);
  logEvent(`开始交流：${text}`, "info");
  let requestTimedOut = false;
  const requestTimeoutId = setTimeout(() => {
    requestTimedOut = true;
    try { currentRequestController?.abort(); } catch (_) {}
  }, REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch("/api/voice-chat-v2", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text, history: voiceConversationHistory }),
      signal: currentRequestController.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        logout();
        return;
      }
      throw new Error(data.detail || "语音交流模型 V2 请求失败");
    }
    if (token !== activeJobToken || stopRequested) return;

    voiceConversationHistory = Array.isArray(data.history) ? data.history.slice(-MAX_VOICE_CHAT_HISTORY) : [];
    transcript.textContent = text;
    promptBufferEl.textContent = text;
    planSummary.textContent = data.answer;
    latency.textContent = `${data.latency_ms} ms`;
    dslOutput.textContent = JSON.stringify(data, null, 2);
    thinkingTitle.textContent = "语音交流模型 V2 已生成回复";
    thinkingNote.textContent = data.intent ? `交流意图：${data.intent}` : "自然语音交流回复已就绪";
    setProgress(1, 1, "交流回复完成");
    logEvent(`交流完成：${data.answer}`, "success");
    speak(data.spoken_feedback || data.answer || "交流完成");
    if (data.suggested_action === "switch_draw_mode") {
      setInteractionMode("draw_v1", false);
    }
  } catch (error) {
    if (error?.name === "AbortError") {
      const message = requestTimedOut ? "语音交流模型 V2 请求超时" : "当前交流已中止";
      planSummary.textContent = message;
      logEvent(message, requestTimedOut ? "error" : "warn");
      if (requestTimedOut) speak("语音交流超时，请稍后重试");
    } else {
      planSummary.textContent = error.message;
      logEvent(`交流失败：${error.message}`, "error");
      speak(`交流失败，${error.message}`);
    }
  } finally {
    clearTimeout(requestTimeoutId);
    if (token === activeJobToken) {
      busy = false;
      currentRequestController = null;
      thinking.classList.add("hidden");
      dictationBuffer = [];
      setVoiceMode("idle");
      if (!pausedForSpeech) scheduleRecognition(350);
    }
  }
}

function beginDictation(initialText = "", confidence = 0) {
  if (busy) return;
  dictationBuffer = [];
  dictationVersion += 1;
  lastAcceptedChunk = "";
  lastAcceptedChunkAt = 0;
  setVoiceMode("dictating", interactionMode === "chat_v2" ? "已听到“开始”，开始记录交流内容" : "已听到“开始”，开始记录绘画描述");
  transcript.textContent = interactionMode === "chat_v2" ? "已开始记录，请自然说话；静默 3 秒将自动回复" : "已开始记录，请描述画面；静默 3 秒将自动开始绘画";
  planSummary.textContent = interactionMode === "chat_v2" ? "正在记录交流内容，静默 3 秒后自动调用语音交流模型 V2" : "正在记录绘画描述，静默 3 秒后自动调用 AI";
  setProgress(0, 0, interactionMode === "chat_v2" ? "记录中：静默 3 秒自动回复" : "记录中：静默 3 秒自动开始绘图");
  const content = cleanDictationText(initialText);
  if (content) addDictationChunk(content, confidence);
  else {
    silenceCountdown.textContent = "等待内容";
    countdownFill.style.width = "0%";
  }
}

function addDictationChunk(text, confidence = 0) {
  const cleaned = cleanDictationText(text);
  if (!isMeaningfulDictationChunk(cleaned, confidence)) {
    logEvent(`忽略低信息量语音：${cleaned || "空白"}`, "warn");
    return false;
  }
  const now = Date.now();
  if (cleaned === lastAcceptedChunk && now - lastAcceptedChunkAt < 2600) {
    logEvent("已过滤重复语音片段", "info");
    return false;
  }
  lastAcceptedChunk = cleaned;
  lastAcceptedChunkAt = now;
  dictationBuffer.push(cleaned);
  const combined = dictationText();
  transcript.textContent = cleaned;
  planSummary.textContent = interactionMode === "chat_v2" ? "已记录，继续交流；静默 3 秒自动回复" : "已记录，继续描述；静默 3 秒自动开始绘图";
  updatePromptBuffer();
  updateAsrConfidence(confidence, confidence > 0.72 ? "清晰" : confidence > 0 ? "可用" : "未提供");
  logEvent(`记录描述：${cleaned}`, "info");
  if (combined.length > 1500) {
    finishDictation("描述较长，已自动开始绘图");
    return true;
  }
  markVoiceActivity();
  return true;
}

async function finishDictation(reason = interactionMode === "chat_v2" ? "检测到 3 秒静默，已自动开始交流回复" : "检测到 3 秒静默，已自动开始绘图") {
  clearDictationSilenceTimer();
  const prompt = dictationText();
  if (!prompt) {
    planSummary.textContent = "没有记录到绘画内容，请重新说“开始”后描述画面";
    logEvent("未记录到有效绘画内容", "warn");
    dictationBuffer = [];
    setVoiceMode("idle");
    speak("没有听到绘画内容，请重新说开始");
    return;
  }
  transcript.textContent = interactionMode === "chat_v2" ? "准备回复" : "准备绘图";
  promptBufferEl.textContent = prompt;
  planSummary.textContent = reason;
  logEvent(reason, "success");
  if (interactionMode === "chat_v2") await sendToVoiceChatV2(prompt);
  else await sendToAI(prompt);
}

async function handleIdleFinalText(text, alternatives, confidence = 0) {
  if (handleLocalControl(text, alternatives)) return;

  if (hasStartCommand(alternatives)) {
    const after = textAfterStart(text);
    beginDictation(after, confidence);
    if (after && hasFinishCommand([after, text])) {
      const before = textBeforeFinish(after);
      dictationBuffer = [];
      if (cleanDictationText(before)) addDictationChunk(before, confidence);
      await finishDictation("检测到结束口令，已开始绘图");
    }
    return;
  }

  const c = compactVoiceText(text);
  if (c.startsWith("画") || c.includes("画一") || c.includes("绘制")) {
    transcript.textContent = text;
    planSummary.textContent = interactionMode === "chat_v2" ? "请先说“开始”再进行语音交流，静默 3 秒后我会自动回复。" : "为避免误触发和消耗 token，请先说“开始”，描述完成后保持静默 3 秒。";
    logEvent("忽略未唤醒的绘画内容：请先说“开始”", "warn");
  }
}

async function handleDictationFinalText(text, alternatives, confidence = 0) {
  if (hasStopCommand(alternatives)) {
    stopCurrentJob("已取消当前绘画描述", true);
    return;
  }
  const compact = compactVoiceText(text);
  if (/^(立即绘图|马上绘图|现在画|开始执行)$/.test(compact)) {
    await finishDictation("收到立即绘图指令，开始执行");
    return;
  }
  if (/^(继续描述|我还没说完|不要提交)$/.test(compact)) {
    scheduleAutoFinish(interactionMode === "chat_v2" ? "继续交流结束，静默 3 秒后自动回复" : "继续描述结束，静默 3 秒后自动绘图");
    speak(interactionMode === "chat_v2" ? "好的，请继续说" : "好的，请继续描述");
    return;
  }
  if (hasFinishCommand(alternatives)) {
    const before = textBeforeFinish(text);
    if (cleanDictationText(before)) addDictationChunk(before, confidence);
    await finishDictation("检测到兼容结束口令，已开始绘图");
    return;
  }
  const afterStart = hasStartCommand(alternatives) ? textAfterStart(text) : text;
  addDictationChunk(afterStart, confidence);
}

async function handleFinalText(text, alternatives = [text], confidence = 0) {
  text = text.trim();
  const now = Date.now();
  if (!text || (text === lastFinalText && now - lastFinalAt < 1200)) return;
  lastFinalText = text;
  lastFinalAt = now;

  if (busy) {
    if (hasStopCommand(alternatives)) stopCurrentJob("已停止当前绘制", true);
    return;
  }

  if (voiceMode === "dictating") {
    await handleDictationFinalText(text, alternatives, confidence);
  } else {
    await handleIdleFinalText(text, alternatives, confidence);
  }
}

function initializeRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    setListeningUI("当前浏览器不支持语音识别", "idle");
    planSummary.textContent = "请使用新版 Chrome 或 Edge";
    setTaskStatus("浏览器不支持语音识别");
    logEvent("浏览器不支持 SpeechRecognition，请使用 Chrome 或 Edge", "error");
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 5;

  recognition.onstart = () => {
    recognizing = true;
    recognitionErrorCount = 0;
    recognitionBackoffMs = 320;
    if (busy) setListeningUI("绘制中，仅监听“停止”", "thinking");
    else if (voiceMode === "dictating") setListeningUI(interactionMode === "chat_v2" ? "正在记录，静默 3 秒自动回复" : "正在记录，静默 3 秒自动开始绘图", "listening");
    else setListeningUI("待机中，只等待“开始”", "idle");
    permissionOverlay.classList.add("hidden");
  };

  recognition.onend = () => {
    recognizing = false;
    if (shouldListen && !pausedForSpeech) scheduleRecognition(recognitionBackoffMs);
  };

  recognition.onerror = event => {
    recognizing = false;
    recognitionErrorCount += 1;
    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      permissionOverlay.classList.remove("hidden");
      setListeningUI("等待麦克风授权", "idle");
      setTaskStatus("等待授权");
      shouldListen = false;
      logEvent("麦克风权限未授予，等待手动授权", "warn");
      return;
    }

    if (voiceMode === "dictating") setListeningUI("正在记录，静默 3 秒自动开始绘图", "listening");
    else if (busy) setListeningUI("绘制中，仅监听“停止”", "thinking");
    else setListeningUI("待机中，只等待“开始”", "idle");

    recognitionBackoffMs = Math.min(5000, 320 * Math.pow(1.65, Math.min(recognitionErrorCount, 6)));
    if (event.error === "network" && recognitionErrorCount % 3 === 1) {
      logEvent("浏览器语音服务网络波动，正在自动重连", "warn");
    } else if (!['no-speech', 'aborted'].includes(event.error)) {
      logEvent(`语音识别暂时异常：${event.error}，正在恢复`, "warn");
    }
    if (shouldListen) scheduleRecognition(recognitionBackoffMs);
  };

  recognition.onresult = event => {
    let interim = "";
    const finalSegments = [];
    const allTexts = [];
    const confidenceParts = [];

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      const selected = selectBestRecognitionAlternative(result);
      allTexts.push(...selected.alternatives);
      if (result.isFinal) {
        if (selected.text) finalSegments.push(selected.text);
        if (selected.confidence > 0) confidenceParts.push({ confidence: selected.confidence, weight: Math.max(1, selected.text.length) });
      } else {
        interim += selected.text;
        if (selected.confidence > 0) updateAsrConfidence(selected.confidence, "识别中");
      }
    }

    if (busy && allTexts.length && hasStopCommand(allTexts)) {
      const now = Date.now();
      if (now - lastInterimControlAt > 700) {
        lastInterimControlAt = now;
        stopCurrentJob("已停止当前绘制", true);
      }
      return;
    }

    if (interim) {
      if (voiceMode === "dictating") {
        transcript.textContent = `记录中：${interim}`;
        markVoiceActivity();
      } else if (!busy && hasStartCommand([interim])) {
        transcript.textContent = "检测到“开始”…";
      }
    }

    if (finalSegments.length) {
      const primary = finalSegments.join("，");
      const totalWeight = confidenceParts.reduce((sum, item) => sum + item.weight, 0);
      const confidence = totalWeight
        ? confidenceParts.reduce((sum, item) => sum + item.confidence * item.weight, 0) / totalWeight
        : 0;
      lastRecognitionConfidence = confidence || null;
      updateAsrConfidence(confidence, confidence > 0.72 ? "清晰" : confidence > 0 ? "可用" : "未提供");
      handleFinalText(primary, allTexts.length ? allTexts : [primary], confidence);
    }
  };

  shouldListen = true;
  setVoiceMode("idle");
  startRecognitionSafe();
  setTimeout(() => {
    if (!recognizing) permissionOverlay.classList.remove("hidden");
  }, 1800);
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    providerBadge.textContent = `AI 服务：${data.provider_label || data.provider || "未知"}`;
    modelBadge.textContent = `绘图模型：${data.model || "未配置"} / 交流V2：${data.voice_chat_v2_model || data.model || "未配置"}`;
    if (!data.ai_configured) {
      logEvent("尚未配置 AI_API_KEY，请先填写 .env 文件", "warn");
      planSummary.textContent = "后端已启动，但尚未配置 AI_API_KEY。请先在 .env 中填入七牛云 Key。";
    } else {
      logEvent(`已连接 ${data.provider_label}，绘图模型 ${data.model}，语音交流 V2 模型 ${data.voice_chat_v2_model || data.model}`, "success");
    }
  } catch (_) {
    providerBadge.textContent = "AI 服务：连接失败";
    modelBadge.textContent = "模型：未知";
    logEvent("无法读取后端健康状态，请确认服务已启动", "error");
  }
}

async function tryCompetitionDemoLogin() {
  try {
    const response = await fetch("/api/demo-login", { method: "POST" });
    if (!response.ok) return null;
    const data = await response.json();
    localStorage.setItem("voice_draw_auth", JSON.stringify({ token: data.token, user: data.user }));
    logEvent("评委演示模式已自动登录", "success");
    return data;
  } catch (_) {
    return null;
  }
}

async function ensureUser() {
  let auth = getAuth();
  if (!auth) {
    const demo = await tryCompetitionDemoLogin();
    if (!demo) {
      logout();
      return null;
    }
    auth = getAuth();
  }
  const response = await fetch("/api/me", { headers: authHeaders() });
  if (!response.ok) {
    localStorage.removeItem("voice_draw_auth");
    const demo = await tryCompetitionDemoLogin();
    if (!demo) {
      logout();
      return null;
    }
    return ensureUser();
  }
  const user = await response.json();
  if (user.role === "admin") {
    window.location.href = "/admin/dashboard";
    return null;
  }
  userIdentity.textContent = `当前用户：${user.username} · 已使用 ${user.usage_count} 次`;
  return user;
}

permissionButton.addEventListener("click", async () => {
  shouldListen = true;
  await initializeAudioVAD(false);
  permissionOverlay.classList.add("hidden");
  logEvent("麦克风已授权，进入纯语音待机状态", "info");
  setVoiceMode("idle");
  startRecognitionSafe();
});

(async () => {
  const user = await ensureUser();
  if (!user) return;
  render();
  restoreLocalRecovery(false);
  renderPlanSteps();
  setRouteInfo();
  setProgress(0, 0, "等待你说“开始”");
  await loadHealth();
  await initializeAudioVAD(true);
  initializeRecognition();
  await runSystemPreflight(false);
})();

window.addEventListener("beforeunload", () => {
  persistLocalRecovery("页面关闭前自动保存");
  if (vadAnimationFrame) cancelAnimationFrame(vadAnimationFrame);
  audioStream?.getTracks?.().forEach(track => track.stop());
  try { recognition?.abort(); } catch (_) {}
});

updateInteractionModeUI();
