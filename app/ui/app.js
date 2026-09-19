/* Jev Voice Decision — page logic. No network access from here; everything goes through window.pywebview.api. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = { labels: null, thresholds: null, busy: false, mode: "text", recording: false,
                  voiceAvailable: false, voiceState: "unconfigured" };

  // ---- stage flow: which card is "active" right now --------------------------
  const STAGE_TO_CARD = { idle: null, listening: "card-input", transcribing: "card-transcript",
                          deciding: "card-jev", complete: "card-action", error: null };
  const CARD_ORDER = ["card-input", "card-transcript", "card-jev", "card-action"];
  const STAGE_LABEL = { idle: "", listening: "聞き取り中…", transcribing: "文字起こし中…", deciding: "Jev が判断中…",
                        complete: "", error: "" };

  function setStage(stage) {
    const activeId = STAGE_TO_CARD[stage] || null;
    const activeIndex = CARD_ORDER.indexOf(activeId);
    CARD_ORDER.forEach((id, index) => {
      const card = $(id);
      card.classList.toggle("active", id === activeId);
      card.classList.toggle("done", activeIndex >= 0 && index < activeIndex);
    });
    document.querySelectorAll(".arrow").forEach((arrow, index) => {
      arrow.classList.toggle("active", activeIndex >= 0 && index < activeIndex);
    });
    $("transcript-status").textContent = stage === "transcribing" ? "端末内 STT で文字起こし中…" : "";
    $("input-status").textContent = stage === "deciding" ? STAGE_LABEL.deciding : "";
    if (state.mode === "voice") {
      if (stage === "listening") $("voice-state").textContent = STAGE_LABEL.listening;
      else if (stage === "transcribing" || stage === "deciding") $("voice-state").textContent = STAGE_LABEL[stage];
      else if (stage === "complete" || stage === "idle") $("voice-state").textContent = state.voiceState === "ready" ? "待機中" : voiceStateLabel();
    }
  }

  function setMeter(level) {
    const width = Math.min(100, Math.round(Math.sqrt(Math.max(0, level)) * 130));
    $("meter-fill").style.width = width + "%";
  }

  function voiceStateLabel() {
    switch (state.voiceState) {
      case "ready": return "待機中";
      case "starting": return "端末内 STT を準備中…（モデル読み込み）";
      case "error": return "端末内 STT を使えません";
      default: return "端末内 STT は未設定";
    }
  }

  function setVoiceState(voiceState, message) {
    state.voiceState = voiceState;
    $("rec-start").disabled = voiceState !== "ready" || state.recording;
    if (!state.recording) $("voice-state").textContent = voiceStateLabel();
    if (voiceState === "error" && message) showBanner(message);
  }
  window.jvd = { setStage, setMeter, setVoiceState };

  // ---- rendering ----------------------------------------------------------------
  function percent(value) { return `${Math.round(value * 100)}%`; }

  function renderBars(container, rows) {
    container.innerHTML = "";
    rows.forEach((row) => {
      const el = document.createElement("div");
      el.className = "bar-row" + (row.selected ? " selected" : "") + (row.cls ? " " + row.cls : "");
      el.innerHTML = `<span class="bar-label"></span><div class="bar-track"><div class="bar-fill"></div></div><span class="bar-value"></span>`;
      el.querySelector(".bar-label").textContent = row.label;
      el.querySelector(".bar-value").textContent = percent(row.value);
      container.appendChild(el);
      requestAnimationFrame(() => { el.querySelector(".bar-fill").style.width = percent(row.value); });
    });
  }

  function renderDecisions(d) {
    const L = state.labels;
    renderBars($("intent-bars"), L.intent_ids.map((id) => ({
      label: L.intent[id], value: d.intent.probabilities[id] ?? 0, selected: id === d.intent.selected, cls: "intent-" + id,
    })));
    $("intent-confidence").textContent = d.intent.confidence.toFixed(2);

    const yes = d.needs_response.probability_yes;
    renderBars($("needs-bars"), [
      { label: "YES", value: yes, selected: yes >= state.thresholds.needs_response },
      { label: "NO", value: 1 - yes, selected: yes < state.thresholds.needs_response },
    ]);

    const max = d.priority.max_level || 1;
    $("priority-marker").style.left = percent(Math.min(Math.max(d.priority.score, 0), max) / max);
    const levelRows = [];
    for (let level = 0; level <= max; level += 1) {
      const p = d.priority.probabilities[String(level)] ?? d.priority.probabilities[level] ?? 0;
      levelRows.push({ label: L.priority[level] ?? String(level), value: p, selected: false });
    }
    let best = 0;
    levelRows.forEach((row, index) => { if (row.value > levelRows[best].value) best = index; });
    levelRows[best].selected = true;
    renderBars($("priority-bars"), levelRows);
    $("priority-score").textContent = `${d.priority.score.toFixed(2)} / ${max}`;
    $("priority-confidence").textContent = d.priority.confidence.toFixed(2);

    const tokens = (d.input_tokens ?? "–") + " in / " + (d.output_tokens ?? "–") + " out";
    $("jev-meta").textContent = `model ${d.model} · ${Math.round(d.latency_ms)} ms · tokens ${tokens} · Jevの出力分布をそのまま表示しています`;
    $("jev-empty").hidden = true;
    $("jev-body").hidden = false;
  }

  function renderAction(result) {
    const L = state.labels;
    const a = result.action;
    const d = result.decisions;
    $("action-intent").textContent = a.hold ? "⚠ 判断保留" : L.intent[d.intent.selected];
    $("action-intent").className = "action-intent" + (a.hold ? "" : " tinted intent-" + d.intent.selected);
    $("action-label").textContent = L.action[a.action] || a.action;
    const badges = [];
    if (a.hold) badges.push(["hold", "confidence が demo threshold 未満"]);
    if (a.needs_response && !a.hold) badges.push(["reply", "返答が必要"]);
    if (a.highlight) badges.push(["highlight", "優先度 高 — 強調"]);
    $("action-badges").innerHTML = "";
    badges.forEach(([cls, text]) => {
      const b = document.createElement("span");
      b.className = "badge " + cls; b.textContent = text; $("action-badges").appendChild(b);
    });
    $("action-rules").innerHTML = "";
    a.rules.forEach((rule) => { const li = document.createElement("li"); li.textContent = rule; $("action-rules").appendChild(li); });
    $("card-action").classList.toggle("highlighted", !!a.highlight);
    $("action-empty").hidden = true;
    $("action-body").hidden = false;
  }

  function renderHistory(entries) {
    const ul = $("history");
    ul.innerHTML = "";
    entries.forEach((h) => {
      const li = document.createElement("li");
      li.className = h.highlight ? "highlight" : "";
      li.innerHTML = `<span class="h-time"></span><span class="h-text"></span><span class="h-action"></span>`;
      li.querySelector(".h-time").textContent = h.time_label;
      li.querySelector(".h-text").textContent = `「${h.transcript}」`;
      li.querySelector(".h-action").textContent = `${h.intent} → ${h.action}`;
      ul.appendChild(li);
    });
  }

  function showBanner(text) {
    const banner = $("banner");
    banner.textContent = text || "";
    banner.hidden = !text;
  }

  function resetOutputs() {
    $("jev-body").hidden = true; $("jev-empty").hidden = false;
    $("action-body").hidden = true; $("action-empty").hidden = false;
    $("card-action").classList.remove("highlighted");
  }

  async function showResult(result) {
    if (!result.ok) {
      setStage("error");
      showBanner(result.error_message || "Jevから判断を取得できませんでした");
      return;
    }
    $("transcript").textContent = result.transcript;
    $("transcript").classList.remove("placeholder");
    renderDecisions(result.decisions);
    renderAction(result);
    setStage("complete");
    renderHistory(await window.pywebview.api.history());
  }

  // ---- text mode ----------------------------------------------------------------
  async function decide() {
    if (state.busy) return;
    const text = $("input-text").value;
    if (!text.trim()) { showBanner("テキストを入力してください"); return; }
    state.busy = true;
    $("decide").disabled = true;
    showBanner("");
    resetOutputs();
    $("transcript").textContent = text.trim();
    $("transcript").classList.remove("placeholder");
    setStage("deciding");
    try {
      await showResult(await window.pywebview.api.decide(text));
    } catch (_error) {
      setStage("error");
      showBanner("Jevから判断を取得できませんでした");
    } finally {
      state.busy = false;
      $("decide").disabled = false;
    }
  }

  // ---- voice mode ---------------------------------------------------------------
  function setRecordingUi(recording) {
    state.recording = recording;
    $("rec-start").hidden = recording;
    $("rec-start").disabled = state.voiceState !== "ready" || recording;
    $("rec-stop").hidden = !recording;
    $("rec-cancel").hidden = !recording;
    $("card-input").classList.toggle("recording", recording);
  }

  let meterTimer = null;
  function startMeterPolling() {
    stopMeterPolling();
    meterTimer = setInterval(async () => {
      try {
        const m = await window.pywebview.api.meter_level();
        setMeter(m.level || 0);
        if (state.recording) $("voice-state").textContent = `${STAGE_LABEL.listening} ${m.seconds.toFixed(1)} 秒`;
      } catch (_error) { /* ignore transient bridge errors */ }
    }, 100);
  }
  function stopMeterPolling() {
    if (meterTimer !== null) { clearInterval(meterTimer); meterTimer = null; }
    setMeter(0);
  }

  async function startRecording() {
    if (state.busy || state.recording) return;
    showBanner("");
    const reply = await window.pywebview.api.start_listening();
    if (!reply.ok) { showBanner(reply.error_message || "マイクを開けませんでした"); return; }
    resetOutputs();
    $("transcript").textContent = "（話し終えたら「停止」を押してください）";
    $("transcript").classList.add("placeholder");
    setRecordingUi(true);
    setStage("listening");
    startMeterPolling();
  }

  async function stopRecording() {
    if (!state.recording || state.busy) return;
    state.busy = true;
    $("rec-stop").disabled = true;
    stopMeterPolling();
    setRecordingUi(false);
    setStage("transcribing");
    try {
      await showResult(await window.pywebview.api.stop_listening());
    } catch (_error) {
      setStage("error");
      showBanner("Jevから判断を取得できませんでした");
    } finally {
      state.busy = false;
      $("rec-stop").disabled = false;
    }
  }

  async function cancelRecording() {
    if (!state.recording) return;
    stopMeterPolling();
    await window.pywebview.api.cancel_listening();
    setRecordingUi(false);
    setStage("idle");
  }

  // ---- rapid demo: one real request at a time, rendered as it arrives ----
  const rapid = { running: false, stopRequested: false, finished: false };
  const RAPID_DWELL_MS = 160;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function setRapidUi() {
    const btn = $("rapid-btn");
    btn.classList.toggle("running", rapid.running);
    btn.textContent = rapid.running ? "停止" : (rapid.finished ? "もう一度見る" : "RAPID DEMO");
    $("decide").disabled = rapid.running;
    $("input-text").readOnly = rapid.running;
    $("mode-voice").disabled = rapid.running || !state.voiceAvailable;
  }

  function setRapidProgress(index, total) {
    $("rapid-progress").hidden = false;
    $("rapid-bar").hidden = false;
    $("rapid-progress").textContent = `${index} / ${total}`;
    $("rapid-bar-fill").style.width = total ? `${Math.round((index / total) * 100)}%` : "0%";
  }

  async function runRapidDemo() {
    const started = await window.pywebview.api.rapid_start();
    if (!started.ok) { showBanner(started.error_message || "Jevから判断を取得できませんでした"); return; }
    rapid.running = true; rapid.stopRequested = false; rapid.finished = false;
    state.busy = true;
    showBanner("");
    setRapidUi();
    setRapidProgress(0, started.total);
    try {
      while (!rapid.stopRequested) {
        setStage("deciding");
        const step = await window.pywebview.api.rapid_step();
        if (!("text" in step)) break;
        $("input-text").value = step.text;
        $("transcript").textContent = step.text;
        $("transcript").classList.remove("placeholder");
        setRapidProgress(step.index, step.total);
        if (step.result.ok) {
          renderDecisions(step.result.decisions);
          renderAction(step.result);
          setStage("complete");
        } else {
          resetOutputs();
          setStage("error");
          $("action-empty").textContent = step.result.error_message || "Jevから判断を取得できませんでした";
          $("action-empty").hidden = false;
        }
        if (step.done) break;
        await sleep(RAPID_DWELL_MS);
      }
    } finally {
      rapid.running = false; rapid.finished = true;
      state.busy = false;
      $("action-empty").textContent = "（Python の規則で決まったアクションがここに表示されます）";
      setRapidUi();
    }
  }

  async function onRapidButton() {
    if (rapid.running) {
      rapid.stopRequested = true;
      await window.pywebview.api.rapid_stop();
      return;
    }
    if (state.recording) return;
    await runRapidDemo();
  }

  function setMode(mode) {
    if (mode === "voice" && !state.voiceAvailable) return;
    if (state.recording || rapid.running) return;
    state.mode = mode;
    $("mode-text").classList.toggle("active", mode === "text");
    $("mode-voice").classList.toggle("active", mode === "voice");
    $("text-panel").hidden = mode !== "text";
    $("voice-panel").hidden = mode !== "voice";
    $("privacy-note").hidden = mode !== "voice";
    if (mode === "voice") $("voice-state").textContent = voiceStateLabel();
    setStage("idle");
  }

  async function init() {
    const status = await window.pywebview.api.status();
    state.labels = status.labels;
    state.thresholds = status.thresholds;
    state.voiceAvailable = !!status.voice_available;
    state.voiceState = status.voice_state || "unconfigured";
    $("mode-voice").disabled = !state.voiceAvailable;
    if (state.voiceAvailable) $("mode-voice").title = "";
    const examples = await window.pywebview.api.examples();
    const wrap = $("examples");
    examples.forEach((text) => {
      const chip = document.createElement("button");
      chip.type = "button"; chip.className = "chip"; chip.textContent = text;
      chip.addEventListener("click", () => { $("input-text").value = text; $("input-text").focus(); });
      wrap.appendChild(chip);
    });
    if (status.startup_error) showBanner(status.startup_error_message || "Jev クライアントを初期化できませんでした");
    else if (!status.api_key_present) showBanner("TypeSafe の API キーが設定されていません（環境変数 TYPESAFE_API_KEY）");
    else if (status.voice_state === "error" && status.voice_error_message) showBanner(status.voice_error_message);
    $("decide").addEventListener("click", decide);
    $("input-text").addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") decide();
    });
    $("mode-text").addEventListener("click", () => setMode("text"));
    $("mode-voice").addEventListener("click", () => setMode("voice"));
    $("rec-start").addEventListener("click", startRecording);
    $("rec-stop").addEventListener("click", stopRecording);
    $("rec-cancel").addEventListener("click", cancelRecording);
    $("rapid-btn").addEventListener("click", onRapidButton);
    setVoiceState(state.voiceState, "");
    setMode("text");
  }

  window.addEventListener("pywebviewready", () => { init().catch(() => showBanner("初期化に失敗しました")); });
})();
