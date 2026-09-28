document.addEventListener("DOMContentLoaded", function () {
  // ---- 1장 촬영 (카메라) ----
  var form = document.getElementById("scan-card-form");
  var input = document.getElementById("scan-card-input");
  var cameraBtn = document.getElementById("scan-camera-btn");
  var hint = document.getElementById("scan-bar-hint");

  if (form && input && cameraBtn) {
    // capture 속성은 HTML에 고정으로 붙어 있어서(모바일에서 바로 촬영 화면으로 감),
    // 여기선 버튼을 누르면 그 input을 열어주기만 하면 된다.
    cameraBtn.addEventListener("click", function () {
      input.click();
    });

    input.addEventListener("change", function () {
      if (!input.files || !input.files.length) return;
      cameraBtn.disabled = true;
      if (hint) hint.textContent = "명함을 인식하고 있어요...";
      form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  }

  // ---- 여러 장 한번에 (갤러리) ----
  var bulkForm = document.getElementById("scan-bulk-form");
  var bulkInput = document.getElementById("scan-bulk-input");
  var bulkAddBtn = document.getElementById("scan-bulk-add-btn");
  var bulkSubmitBtn = document.getElementById("scan-bulk-submit-btn");
  var bulkCount = document.getElementById("scan-bulk-count");
  var bulkHint = document.getElementById("scan-bulk-hint");
  var bulkPreview = document.getElementById("scan-bulk-preview");
  if (!bulkForm || !bulkInput || !bulkAddBtn || !bulkSubmitBtn || !bulkPreview) return;

  var MAX_BULK_CARDS = 20;
  // 모바일에서 "명함 추가"를 누를 때마다 카메라로 한 장씩 찍거나 갤러리에서
  // 여러 장을 고를 수 있는데, 두 경우 다 여기 staged 배열에 계속 누적해서
  // 최종적으로 한 번에 전송한다. input.multiple 하나만 믿으면, 카메라로
  // 찍는 경우(태생적으로 한 장씩만 나옴) 매번 이전에 담은 파일들이 사라진다.
  var staged = [];

  // DataTransfer로 input.files를 바꿔 끼우는 건 구형 iOS Safari 등에서 안 될 수
  // 있어서, 안 되면 submit 때 fetch로 직접 보내는 쪽으로 넘어간다.
  function syncInputFiles() {
    try {
      var dt = new DataTransfer();
      staged.forEach(function (file) { dt.items.add(file); });
      bulkInput.files = dt.files;
      return bulkInput.files.length === staged.length;
    } catch (e) {
      return false;
    }
  }

  var previewUrls = [];

  function renderPreview() {
    previewUrls.forEach(function (url) { URL.revokeObjectURL(url); });
    previewUrls = [];
    bulkPreview.innerHTML = "";

    staged.forEach(function (file, idx) {
      var thumb = document.createElement("div");
      thumb.className = "scan-bulk-thumb";

      var img = document.createElement("img");
      var url = URL.createObjectURL(file);
      previewUrls.push(url);
      img.src = url;
      img.alt = file.name;
      thumb.appendChild(img);

      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.textContent = "×";
      removeBtn.setAttribute("aria-label", "삭제");
      removeBtn.addEventListener("click", function () {
        staged.splice(idx, 1);
        syncInputFiles();
        renderPreview();
      });
      thumb.appendChild(removeBtn);

      bulkPreview.appendChild(thumb);
    });

    if (bulkCount) bulkCount.textContent = String(staged.length);
    bulkSubmitBtn.hidden = staged.length === 0;
    bulkAddBtn.disabled = staged.length >= MAX_BULK_CARDS;
    if (bulkHint) {
      if (staged.length >= MAX_BULK_CARDS) {
        bulkHint.textContent = "최대 " + MAX_BULK_CARDS + "장까지 담을 수 있어요. 업로드 시작을 누르세요.";
      } else if (staged.length) {
        bulkHint.textContent = "총 " + staged.length + "장 담았어요. 더 추가하거나 업로드 시작을 누르세요.";
      } else {
        bulkHint.textContent = "사진을 한 장씩 찍거나 여러 장을 골라 \"명함 추가\"로 계속 담은 뒤, 업로드 시작을 누르세요 (최대 " + MAX_BULK_CARDS + "장)";
      }
    }
  }

  // 모바일에서 여러 장을 고르려면 capture가 없어야 한다
  // (capture가 있으면 갤러리 대신 카메라만 열려서 한 장씩만 찍힘).
  bulkInput.removeAttribute("capture");
  bulkInput.multiple = true;
  bulkInput.setAttribute("accept", "image/*");

  bulkAddBtn.addEventListener("click", function () {
    bulkInput.click();
  });

  bulkInput.addEventListener("change", function () {
    // 선택 창에서 취소하면 일부 브라우저는 input.files를 비워버리므로,
    // 새로 고른 게 없어도 담아둔 목록으로 다시 맞춰 둔다.
    if (bulkInput.files && bulkInput.files.length) {
      var picked = Array.prototype.slice.call(bulkInput.files);
      picked.forEach(function (file) {
        if (staged.length >= MAX_BULK_CARDS) return;
        if (staged.indexOf(file) !== -1) return;
        staged.push(file);
      });
    }
    syncInputFiles();
    renderPreview();
  });

  bulkForm.addEventListener("submit", function (event) {
    if (!staged.length) {
      event.preventDefault();
      return;
    }
    bulkAddBtn.disabled = true;
    bulkSubmitBtn.disabled = true;
    if (bulkHint) bulkHint.textContent = "명함 " + staged.length + "장을 인식하고 있어요...";

    if (syncInputFiles()) return; // 일반 폼 전송으로 진행

    // input.files를 바꿀 수 없는 브라우저: 담아둔 파일로 직접 전송
    event.preventDefault();
    var fd = new FormData();
    staged.forEach(function (file) { fd.append("card_images", file, file.name); });
    fetch(bulkForm.action, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (res) {
        if (res.redirected) {
          window.location.href = res.url;
          return null;
        }
        return res.text();
      })
      .then(function (html) {
        if (html === null) return;
        document.open();
        document.write(html);
        document.close();
      })
      .catch(function () {
        bulkAddBtn.disabled = staged.length >= MAX_BULK_CARDS;
        bulkSubmitBtn.disabled = false;
        if (bulkHint) bulkHint.textContent = "업로드에 실패했어요. 네트워크를 확인하고 다시 시도해주세요.";
      });
  });
});
