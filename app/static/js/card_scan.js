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

  function syncInputFiles() {
    var dt = new DataTransfer();
    staged.forEach(function (file) { dt.items.add(file); });
    bulkInput.files = dt.files;
  }

  function renderPreview() {
    bulkPreview.innerHTML = "";
    staged.forEach(function (file, idx) {
      var thumb = document.createElement("div");
      thumb.className = "scan-bulk-thumb";

  // 모바일에서 여러 장을 고르려면 capture가 없어야 한다
  // (capture가 있으면 갤러리 대신 카메라가 열려서 한 장만 찍힘).
  // HTML에 뭐가 붙어 있든 여기서 확실하게 맞춰 둔다.
  bulkInput.removeAttribute("capture");
  bulkInput.multiple = true;
  bulkInput.setAttribute("accept", "image/*");

  bulkBtn.addEventListener("click", function () {
    bulkInput.click();
  });

  bulkInput.addEventListener("change", function () {
    if (!bulkInput.files || !bulkInput.files.length) return;
    for (var i = 0; i < bulkInput.files.length && staged.length < MAX_BULK_CARDS; i++) {
      staged.push(bulkInput.files[i]);
    }
    if (staged.length >= MAX_BULK_CARDS && bulkHint) {
      bulkHint.textContent = "최대 " + MAX_BULK_CARDS + "장까지 담을 수 있어요.";
    }
    syncInputFiles();
    renderPreview();
  });

  bulkForm.addEventListener("submit", function () {
    bulkAddBtn.disabled = true;
    bulkSubmitBtn.disabled = true;
    if (bulkHint) bulkHint.textContent = "명함 " + staged.length + "장을 인식하고 있어요...";
  });
});