(function () {
  "use strict";
  const params = new URLSearchParams(location.search);
  const root = document.documentElement;
  if (params.get("font")) root.style.setProperty("--font-size", params.get("font") + "px");
  if (params.get("bottom")) root.style.setProperty("--bottom", params.get("bottom") + "%");
  if (params.get("color")) root.style.setProperty("--text", params.get("color"));
  if (params.get("bg")) root.style.setProperty("--panel", params.get("bg"));

  const lines = document.getElementById("lines");
  const label = document.getElementById("ai-label");
  const conn = document.getElementById("conn");
  const defaultLabel = label.textContent;
  const timers = new Map();
  let socket = null;
  let retry = 0;
  let config = { max_lines: 2 };

  function remove(id) {
    const node = document.getElementById("cap-" + id);
    if (node) node.remove();
    if (timers.has(id)) {
      clearTimeout(timers.get(id));
      timers.delete(id);
    }
  }

  function show(message) {
    label.style.display = message.ai_label === false ? "none" : "";
    label.textContent = message.ai_label_text || defaultLabel;
    remove(message.id);
    const box = document.createElement("div");
    box.className = "line";
    box.id = "cap-" + message.id;
    if (message.speaker) {
      const speaker = document.createElement("span");
      speaker.className = "speaker";
      speaker.textContent = message.speaker;
      box.appendChild(speaker);
    }
    box.appendChild(document.createTextNode(message.text || ""));
    lines.appendChild(box);
    const limit = Math.max(1, Number(config.max_lines) || 2);
    while (lines.children.length > limit) {
      const first = lines.firstChild;
      if (first && first.id) timers.delete(first.id.replace("cap-", ""));
      lines.removeChild(first);
    }
    const hold = Math.max(800, Number(message.hold_ms) || 3200);
    timers.set(message.id, setTimeout(function () { remove(message.id); }, hold));
  }

  function handle(message) {
    switch (message.type) {
      case "caption.show": show(message); break;
      case "caption.hide": remove(message.id); break;
      case "caption.clear":
        lines.innerHTML = "";
        timers.forEach(clearTimeout);
        timers.clear();
        break;
      case "hello":
        if (message.payload) config = message.payload;
        break;
      default: break;
    }
  }

  function connect() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = protocol + "//" + location.host + "/ws/live/overlay";
    conn.textContent = "字幕连接中…";
    conn.classList.add("offline");
    socket = new WebSocket(url);
    socket.onopen = function () {
      retry = 0;
      conn.textContent = "";
      conn.classList.remove("offline");
    };
    socket.onmessage = function (event) {
      try { handle(JSON.parse(event.data)); } catch (error) { /* ignore malformed frame */ }
    };
    socket.onerror = function () {
      try { socket.close(); } catch (error) { /* noop */ }
    };
    socket.onclose = function () {
      conn.textContent = "字幕连接断开，正在重连…";
      conn.classList.add("offline");
      retry = Math.min(retry + 1, 6);
      setTimeout(connect, 500 * retry);
    };
  }

  connect();
})();
