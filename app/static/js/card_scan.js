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
  var bulkBtn = document.getElementById("scan-bulk-btn");
  var bulkHint = document.getElementById("scan-bulk-hint");
  if (!bulkForm || !bulkInput || !bulkBtn) return;

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
    bulkBtn.disabled = true;
    if (bulkHint) bulkHint.textContent = "명함 " + bulkInput.files.length + "장을 인식하고 있어요...";
    bulkForm.requestSubmit ? bulkForm.requestSubmit() : bulkForm.submit();
  });
});