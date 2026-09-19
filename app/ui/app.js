/* Jev Voice Decision — page logic. No network access from here; everything goes through window.pywebview.api. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = { labels: null, thresholds: null, busy: false };

  // ---- stage flow: which card is "active" right now --------------------------
  const STAGE_TO_CARD = { idle: null, listening: "card-input", transcribing: "card-transcript",
                          deciding: "card-jev", complete: "card-action", error: null };
  const CARD_ORDER = ["card-input", "card-transcript", "card-jev", "card-action"];

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
    $("transcript-status").textContent = stage === "transcribing" ? "文字起こし中…" : "";
    $("input-status").textContent = stage === "deciding" ? "Jev が判断中…" : "";
  }
  window.jvd = { setStage };

  // ---- rendering ----------------------------------------------------------------
  function percent(value) { return `${Math.round(value * 100)}%`; }

  function renderBars(container, rows) {
    container.innerHTML = "";
    rows.forEach((row) => {
      const el = document.createElement("div");
      el.className = "bar-row" + (row.selected ? " selected" : "");
      el.innerHTML = `<span class="bar-label"></span><div class="bar-track"><div class="bar-fill"></div></div><span class="bar-value"></span>`;
      el.querySelector(".bar-label").textContent = row.label;
      el.querySelector(".bar-value").textContent = percent(row.value);
      container.appendChild(el);
      requestAnimationFrame(() => { el.querySelector(".bar-fill").style.width = percent(row.value); });
    });
  }

  function renderDecisions(d) {
    const L = state.labels;
    const intentRows = L.intent_ids.map((id) => ({
      label: L.intent[id], value: d.intent.probabilities[id] ?? 0, selected: id === d.intent.selected,
    }));
    renderBars($("intent-bars"), intentRows);
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

  // ---- actions ----------------------------------------------------------------
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
      const result = await window.pywebview.api.decide(text);
      if (!result.ok) {
        setStage("error");
        showBanner(result.error_message || "Jevから判断を取得できませんでした");
        return;
      }
      $("transcript").textContent = result.transcript;
      renderDecisions(result.decisions);
      renderAction(result);
      setStage("complete");
      renderHistory(await window.pywebview.api.history());
    } catch (_error) {
      setStage("error");
      showBanner("Jevから判断を取得できませんでした");
    } finally {
      state.busy = false;
      $("decide").disabled = false;
    }
  }

  async function init() {
    const status = await window.pywebview.api.status();
    state.labels = status.labels;
    state.thresholds = status.thresholds;
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
    $("decide").addEventListener("click", decide);
    $("input-text").addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") decide();
    });
    setStage("idle");
  }

  window.addEventListener("pywebviewready", () => { init().catch(() => showBanner("初期化に失敗しました")); });
})();
