/* 메일 첨부 버튼 공용 동작.
   첨부한 파일이 없으면 바로 파일 선택창, 한 개 이상 있으면 [첨부 파일 확인 / 새 파일 첨부] 메뉴.
   요소 id는 `${prefix}-btn|pop|input|picker|count|modal|list` 규칙을 따른다.
     - input : 서버로 실제 전송되는 <input type="file" name="attachments">
     - picker: 파일을 고르는 용도의 보이지 않는 input (고른 파일을 목록에 이어 붙인다)
   opts.saved: 서버에 이미 첨부돼 있는 파일 [{name, size, url, deleteFormId}] (없으면 생략) */
window.SabuzakAttach = (function () {
  function sizeLabel(n) {
    return n >= 1024 * 1024 ? (n / (1024 * 1024)).toFixed(1) + "MB" : Math.max(1, Math.round(n / 1024)) + "KB";
  }

  function el(tag, className, text) {
    var e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function init(opts) {
    var byId = function (suffix) { return document.getElementById(opts.prefix + "-" + suffix); };
    var btn = byId("btn"), pop = byId("pop"), formInput = byId("input"), picker = byId("picker");
    var countEl = byId("count"), modal = byId("modal"), listEl = byId("list");
    var saved = opts.saved || [];
    var files = [];

    function total() { return saved.length + files.length; }

    // 화면에서 관리하는 새 파일 목록을 실제 전송용 input에 반영
    function sync() {
      var dt = new DataTransfer();
      files.forEach(function (f) { dt.items.add(f); });
      formInput.files = dt.files;
      countEl.textContent = total() ? "(" + total() + ")" : "";
    }

    function renderList() {
      listEl.innerHTML = "";

      saved.forEach(function (a) {
        var li = el("li");
        var link = el("a", "", a.name);
        link.href = a.url;
        var del = el("button", "btn-chip btn-chip-danger", "삭제");
        del.type = "button";
        del.addEventListener("click", function () {
          var form = document.getElementById(a.deleteFormId);
          if (form) form.requestSubmit();
        });
        li.appendChild(link);
        li.appendChild(el("span", "attach-size", a.size));
        li.appendChild(del);
        listEl.appendChild(li);
      });

      files.forEach(function (f, i) {
        var li = el("li");
        var del = el("button", "btn-chip btn-chip-danger", "삭제");
        del.type = "button";
        del.addEventListener("click", function () {
          files.splice(i, 1);
          sync();
          if (!total()) { window.SabuzakModal.close(modal); return; }
          renderList();
        });
        li.appendChild(el("span", "", f.name));
        li.appendChild(el("span", "attach-size", sizeLabel(f.size) + (opts.pendingNote ? " · " + opts.pendingNote : "")));
        li.appendChild(del);
        listEl.appendChild(li);
      });
    }

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (!total()) { picker.click(); return; }
      pop.hidden = !pop.hidden;
    });

    pop.addEventListener("click", function (e) {
      var item = e.target.closest("[data-attach-action]");
      if (!item) return;
      pop.hidden = true;
      if (item.dataset.attachAction === "new") {
        picker.click();
      } else {
        renderList();
        window.SabuzakModal.open(modal);
      }
    });

    // 새로 고른 파일은 기존 목록에 이어 붙인다 (같은 파일은 중복 제외)
    picker.addEventListener("change", function () {
      Array.prototype.forEach.call(picker.files, function (f) {
        var dup = files.some(function (x) {
          return x.name === f.name && x.size === f.size && x.lastModified === f.lastModified;
        });
        if (!dup) files.push(f);
      });
      picker.value = "";
      sync();
    });

    document.addEventListener("click", function () { pop.hidden = true; });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") pop.hidden = true; });

    sync();
  }

  return { init: init };
})();
