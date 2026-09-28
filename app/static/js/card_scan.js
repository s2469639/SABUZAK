document.addEventListener("DOMContentLoaded", function () {
  var form = document.getElementById("scan-card-form");
  var input = document.getElementById("scan-card-input");
  var cameraBtn = document.getElementById("scan-camera-btn");
  var hint = document.getElementById("scan-bar-hint");
  if (!form || !input || !cameraBtn) return;

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

  var bulkForm = document.getElementById("scan-bulk-form");
  var bulkInput = document.getElementById("scan-bulk-input");
  var bulkBtn = document.getElementById("scan-bulk-btn");
  var bulkHint = document.getElementById("scan-bulk-hint");
  if (!bulkForm || !bulkInput || !bulkBtn) return;

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
