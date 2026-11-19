(function () {
  "use strict";
  const $ = function (id) { return document.getElementById(id); };
  const state = { status: null, records: [], selected: null, ws: null, retry: 0 };
  let toastTimer = null;

  function toast(message) {
    const node = $("toast");
    node.textContent = message;
    node.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.classList.remove("show"); }, 4200);
  }

  async function api(path, options) {
    const response = await fetch("/api/live" + path, options);
    let body = null;
    try { body = await response.json(); } catch (error) { body = null; }
    if (!response.ok) {
      throw new Error((body && (body.detail || body.message)) || ("HTTP " + response.status));
    }
    return body;
  }

  function post(path, payload) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    });
  }

  function send(message) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(message));
      return true;
    }
    toast("控制台连接未就绪，稍后再试。");
    return false;
  }

  function renderState(status) {
    state.status = status;
    const mode = status.mode || "idle";
    const badge = $("badge");
    badge.className = "badge " + (mode === "idle" ? "idle" : mode);
    badge.textContent = mode === "live" ? "直播中 · 真实音频" : (mode === "mock" ? "演示中 · 无 API 消耗" : "未启动");
    $("uptime").textContent = status.running ? ("已运行 " + Math.round(status.uptime_seconds) + " s") : "";
    $("btn-stop").disabled = !status.running;
    $("btn-live").disabled = status.running;
    $("btn-demo").disabled = status.running;

    const cfg = status.config || {};
    $("cfg-mic").checked = cfg.source_microphone !== false;
    $("cfg-sys").checked = !!cfg.source_system;
    $("cfg-label").checked = cfg.ai_label !== false;
    $("cfg-delay").value = cfg.publish_delay_ms || 0;
    $("cfg-hold").value = cfg.hold_ms || 3600;
    $("cfg-font").value = cfg.font_size || 34;
    $("delay-value").textContent = (cfg.publish_delay_ms || 0) + " ms";
    $("hold-value").textContent = (cfg.hold_ms || 3600) + " ms";
    $("font-value").textContent = (cfg.font_size || 34) + " px";
    $("overlay-url").value = (status.overlay_url || "") +
      "?font=" + (cfg.font_size || 34) + "&bottom=12";

    const devices = status.devices || {};
    fillDevices($("dev-mic"), devices.microphones || [], cfg.device_microphone, devices.default_microphone);
    fillDevices($("dev-sys"), devices.loopbacks || [], cfg.device_loopback, devices.default_loopback);
    $("device-hint").textContent = devices.hint || "";

    const m = status.metrics || {};
    const cap = m.caption || {};
    $("m-p50").textContent = cap.p50_ms ? cap.p50_ms + " ms" : "–";
    $("m-p95").textContent = cap.p95_ms ? cap.p95_ms + " ms" : "–";
    $("m-pub").textContent = cap.published || 0;
    $("m-frames").textContent = (m.frames_sent || 0) + " / " + (m.frames_gated || 0);
    $("m-sec").textContent = (m.asr_seconds || 0).toFixed(1);
    $("m-cost").textContent = "¥" + ((m.asr_seconds || 0) * 0.00033).toFixed(2);

    if (status.records) {
      state.records = status.records.slice();
      renderRecords();
    }
    if (status.last_error) toast("提示：" + status.last_error);
  }

  function fillDevices(select, items, chosen, fallback) {
    const wanted = chosen === null || chosen === undefined ? fallback : chosen;
    select.innerHTML = "";
    const auto = document.createElement("option");
    auto.value = "";
    auto.textContent = "自动选择" + (fallback !== null && fallback !== undefined ? "（默认设备）" : "");
    select.appendChild(auto);
    items.forEach(function (item) {
      const option = document.createElement("option");
      option.value = String(item.index);
      option.textContent = item.name + " · " + item.sample_rate + " Hz";
      if (String(wanted) === String(item.index)) option.selected = true;
      select.appendChild(option);
    });
  }

  function renderRecords() {
    const box = $("records");
    if (!state.records.length) {
      box.innerHTML = '<div class="empty">启动后这里会显示英文原句与中文译文。</div>';
      return;
    }
    box.innerHTML = "";
    state.records.slice(-60).forEach(function (record) {
      const node = document.createElement("div");
      node.className = "record" + (state.selected === record.id ? " active" : "");
      const en = document.createElement("div");
      en.className = "en";
      en.textContent = record.source_text || "";
      const zh = document.createElement("div");
      zh.className = "zh";
      zh.textContent = record.text || "";
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = new Date((record.created_at || Date.now() / 1000) * 1000).toLocaleTimeString();
      node.appendChild(en); node.appendChild(zh); node.appendChild(meta);
      node.addEventListener("click", function () {
        state.selected = record.id;
        renderRecords();
        $("selected").textContent = "已选中：" + (record.source_text || "");
      });
      box.appendChild(node);
    });
    box.scrollTop = box.scrollHeight;
  }

  function handle(message) {
    switch (message.type) {
      case "state":
        renderState(message.payload || {});
        break;
      case "caption.record":
        state.records.push(message.payload || {});
        renderRecords();
        break;
      case "caption.on_air":
        break;
      case "chat.answer":
        $("answer").textContent = message.answer || "";
        break;
      case "chat.error":
        $("answer").textContent = "问答失败：" + (message.message || "");
        break;
      case "notice":
        toast(message.text || "");
        break;
      case "summary":
        toast("已生成一段阶段小结（可在本机历史中查看）。");
        break;
      default:
        break;
    }
  }

  function connect() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(protocol + "//" + location.host + "/ws/live/console");
    state.ws = ws;
    ws.onopen = function () {
      state.retry = 0;
      ws.send(JSON.stringify({ type: "request_state" }));
    };
    ws.onmessage = function (event) {
      try { handle(JSON.parse(event.data)); } catch (error) { /* ignore malformed */ }
    };
    ws.onclose = function () {
      state.retry = Math.min(state.retry + 1, 6);
      setTimeout(connect, 500 * state.retry);
    };
    ws.onerror = function () { try { ws.close(); } catch (error) { /* noop */ } };
  }

  function currentConfig() {
    const parseDevice = function (id) {
      const value = $(id).value;
      return value === "" ? null : Number(value);
    };
    return {
      source_microphone: $("cfg-mic").checked,
      source_system: $("cfg-sys").checked,
      ai_label: $("cfg-label").checked,
      publish_delay_ms: Number($("cfg-delay").value),
      hold_ms: Number($("cfg-hold").value),
      font_size: Number($("cfg-font").value),
      device_microphone: parseDevice("dev-mic"),
      device_loopback: parseDevice("dev-sys")
    };
  }

  document.addEventListener("DOMContentLoaded", function () {
    ["cfg-delay", "cfg-hold", "cfg-font"].forEach(function (id) {
      $(id).addEventListener("input", function () {
        $("delay-value").textContent = $("cfg-delay").value + " ms";
        $("hold-value").textContent = $("cfg-hold").value + " ms";
        $("font-value").textContent = $("cfg-font").value + " px";
      });
    });

    $("btn-live").addEventListener("click", async function () {
      try {
        await post("/config", currentConfig());
        const result = await post("/start", { mock: false });
        renderState(result);
        toast("直播模式已启动。请把 OBS 叠层地址加入浏览器来源。");
      } catch (error) {
        toast("真实采集启动失败：" + error.message + "。可先用「演示模式」验证界面链路。");
      }
    });
    $("btn-demo").addEventListener("click", async function () {
      try {
        const result = await post("/start", { mock: true });
        renderState(result);
        toast("演示模式已启动，点击「注入演示」可生成英文字幕。");
      } catch (error) { toast("启动失败：" + error.message); }
    });
    $("btn-stop").addEventListener("click", async function () {
      try { renderState(await post("/stop", {})); } catch (error) { toast(error.message); }
    });
    $("btn-apply").addEventListener("click", async function () {
      try { renderState(await post("/config", currentConfig())); toast("设置已应用。"); }
      catch (error) { toast(error.message); }
    });
    $("btn-devices").addEventListener("click", async function () {
      try { renderState(await api("/devices?refresh=true")); toast("设备列表已刷新。"); }
      catch (error) { toast(error.message); }
    });
    $("btn-copy").addEventListener("click", function () {
      const value = $("overlay-url").value;
      navigator.clipboard.writeText(value).then(function () { toast("已复制 OBS 叠层地址。"); },
        function () { $("overlay-url").select(); toast("请手动复制选中的地址。"); });
    });
    $("btn-open-overlay").addEventListener("click", function () {
      window.open($("overlay-url").value, "_blank");
    });
    $("btn-hide").addEventListener("click", function () { send({ type: "hide" }); });
    $("btn-clear").addEventListener("click", function () { send({ type: "clear" }); });
    $("btn-recall").addEventListener("click", function () { send({ type: "recall", payload: {} }); });
    $("btn-resume").addEventListener("click", function () {
      send({ type: "resume" });
      toast("已恢复显示。");
    });
    $("btn-srt").addEventListener("click", function () { window.location.href = "/api/live/srt"; });
    $("btn-inject").addEventListener("click", async function () {
      const text = $("inject-en").value.trim();
      try {
        await post("/inject", { source_text: text, target_text: "" });
        $("inject-en").value = "";
      } catch (error) { toast(error.message); }
    });
    $("btn-ask").addEventListener("click", function () {
      const question = $("ask-input").value.trim();
      if (!question) { toast("请先输入问题。"); return; }
      const selected = state.records.find(function (item) { return item.id === state.selected; });
      send({
        type: "chat.ask",
        question: question,
        selected_text: selected ? selected.source_text : "",
        request_id: "console-" + Date.now()
      });
      $("answer").textContent = "思考中…";
    });
    $("ask-input").addEventListener("keydown", function (event) {
      if (event.key === "Enter") $("btn-ask").click();
    });

    connect();
  });
})();
