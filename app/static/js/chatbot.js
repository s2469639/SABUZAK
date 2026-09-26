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

  fab.addEventListener("click", function () {
    panel.hidden ? open() : close();
  });
  closeBtn.addEventListener("click", close);

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
