(function () {
  var widget = document.getElementById("chatbot-widget");
  if (!widget) return;

  var fab = document.getElementById("chatbot-fab");
  var panel = document.getElementById("chatbot-panel");
  var closeBtn = document.getElementById("chatbot-close");
  var messagesBox = document.getElementById("chatbot-messages");
  var examplesBox = document.getElementById("chatbot-examples");
  var form = document.getElementById("chatbot-form");
  var input = document.getElementById("chatbot-input");

  var history = []; // [{role: 'user'|'assistant', content}]

  function open() {
    panel.hidden = false;
    fab.classList.add("is-open");
    input.focus();
  }
  function close() {
    panel.hidden = true;
    fab.classList.remove("is-open");
  }

  var suppressClick = false;
  fab.addEventListener("click", function () {
    if (suppressClick) { suppressClick = false; return; }
    panel.hidden ? open() : close();
  });
  closeBtn.addEventListener("click", close);

  // 아이콘을 드래그해서 화면 아무 곳(좌/우/위/아래)으로나 옮길 수 있게 한다.
  // 손을 떼면 가까운 쪽 가장자리(좌/우)로 스르륵 붙는다. 위치는 이 브라우저에만
  // 저장(localStorage)해서 새로고침해도 유지되지만, 다른 사람에게는 공유되지 않는다.
  var POS_KEY = "fairmate_chatbot_pos";
  var DRAG_THRESHOLD = 5;
  var EDGE_GAP = 12;

  function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }

  function updateOpenDirection(left, top) {
    var w = widget.offsetWidth;
    widget.classList.toggle("side-left", left + w / 2 < window.innerWidth / 2);
    widget.classList.toggle("open-below", top < 220);
  }

  function applyPosition(left, top, animate) {
    widget.style.transition = animate ? "left 0.28s ease, top 0.28s ease" : "none";
    widget.style.left = left + "px";
    widget.style.top = top + "px";
    widget.style.right = "auto";
    widget.style.bottom = "auto";
    updateOpenDirection(left, top);
  }

  function savePosition(left, top) {
    try { localStorage.setItem(POS_KEY, JSON.stringify({ left: left, top: top })); } catch (e) {}
  }

  function restorePosition() {
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(POS_KEY) || "null"); } catch (e) {}
    if (saved && typeof saved.left === "number" && typeof saved.top === "number") {
      var w = widget.offsetWidth || 58, h = widget.offsetHeight || 58;
      var left = clamp(saved.left, EDGE_GAP, window.innerWidth - w - EDGE_GAP);
      var top = clamp(saved.top, EDGE_GAP, window.innerHeight - h - EDGE_GAP);
      applyPosition(left, top, false);
    } else {
      var rect = widget.getBoundingClientRect();
      updateOpenDirection(rect.left, rect.top);
    }
  }

  var dragState = null;

  fab.addEventListener("pointerdown", function (e) {
    if (e.button !== undefined && e.button !== 0) return;
    var rect = widget.getBoundingClientRect();
    dragState = {
      startX: e.clientX, startY: e.clientY,
      originLeft: rect.left, originTop: rect.top,
      moved: false, pointerId: e.pointerId,
    };
  });

  fab.addEventListener("pointermove", function (e) {
    if (!dragState) return;
    var dx = e.clientX - dragState.startX;
    var dy = e.clientY - dragState.startY;
    if (!dragState.moved && Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
    if (!dragState.moved) {
      dragState.moved = true;
      fab.setPointerCapture(dragState.pointerId);
      panel.hidden = true;
      fab.classList.remove("is-open");
      widget.classList.add("dragging");
    }
    var w = widget.offsetWidth, h = widget.offsetHeight;
    var left = clamp(dragState.originLeft + dx, EDGE_GAP, window.innerWidth - w - EDGE_GAP);
    var top = clamp(dragState.originTop + dy, EDGE_GAP, window.innerHeight - h - EDGE_GAP);
    applyPosition(left, top, false);
  });

  function endDrag() {
    if (!dragState) return;
    widget.classList.remove("dragging");
    if (dragState.moved) {
      suppressClick = true;
      var rect = widget.getBoundingClientRect();
      var w = widget.offsetWidth, h = widget.offsetHeight;
      var snapLeft = (rect.left + w / 2 < window.innerWidth / 2) ? EDGE_GAP : window.innerWidth - w - EDGE_GAP;
      var top = clamp(rect.top, EDGE_GAP, window.innerHeight - h - EDGE_GAP);
      applyPosition(snapLeft, top, true);
      savePosition(snapLeft, top);
    }
    dragState = null;
  }
  fab.addEventListener("pointerup", endDrag);
  fab.addEventListener("pointercancel", endDrag);

  window.addEventListener("resize", function () {
    var rect = widget.getBoundingClientRect();
    var w = widget.offsetWidth, h = widget.offsetHeight;
    var left = clamp(rect.left, EDGE_GAP, window.innerWidth - w - EDGE_GAP);
    var top = clamp(rect.top, EDGE_GAP, window.innerHeight - h - EDGE_GAP);
    applyPosition(left, top, false);
  });

  restorePosition();

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // 답변에 포함된 URL(절대경로 http(s)://, 또는 /exhibitions, /mypage, /dashboard로
  // 시작하는 사이트 내부 경로)을 클릭 가능한 링크로 바꿔준다.
  function linkify(text) {
    var escaped = escapeHtml(text);
    return escaped.replace(
      /(https?:\/\/[^\s<]+|\/(?:exhibitions|mypage|dashboard)[^\s<]*)/g,
      function (url) {
        var trimmed = url.replace(/[.,)]+$/, "");
        return '<a href="' + trimmed + '" target="_blank" rel="noopener">' + trimmed + "</a>";
      }
    );
  }

  function addMessage(role, text) {
    var el = document.createElement("div");
    el.className = "chatbot-msg " + (role === "user" ? "chatbot-msg-user" : "chatbot-msg-bot");
    if (role === "user") {
      el.textContent = text;
    } else {
      el.innerHTML = linkify(text);
    }
    messagesBox.appendChild(el);
    messagesBox.scrollTop = messagesBox.scrollHeight;
    return el;
  }

  function send(text) {
    text = (text || "").trim();
    if (!text) return;

    if (examplesBox) { examplesBox.remove(); examplesBox = null; }

    addMessage("user", text);
    history.push({ role: "user", content: text });
    input.value = "";

    var loadingEl = addMessage("bot", "확인 중입니다...");
    loadingEl.classList.add("chatbot-msg-loading");

    fetch("/chatbot/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: history }),
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        loadingEl.classList.remove("chatbot-msg-loading");
        var reply = data.reply || data.error || "답변을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.";
        loadingEl.innerHTML = linkify(reply);
        history.push({ role: "assistant", content: reply });
      })
      .catch(function () {
        loadingEl.classList.remove("chatbot-msg-loading");
        loadingEl.innerHTML = linkify("네트워크 오류로 답변을 받지 못했습니다. 잠시 후 다시 시도해주세요.");
      });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    send(input.value);
  });

  document.querySelectorAll(".chatbot-example-btn").forEach(function (btn) {
    btn.addEventListener("click", function () { send(btn.textContent); });
  });
})();
