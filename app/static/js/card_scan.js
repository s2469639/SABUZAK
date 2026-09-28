document.addEventListener("DOMContentLoaded", function () {
  var form = document.getElementById("scan-card-form");
  var input = document.getElementById("scan-card-input");
  var cameraBtn = document.getElementById("scan-camera-btn");
  var fileBtn = document.getElementById("scan-file-btn");
  var hint = document.getElementById("scan-bar-hint");
  if (!form || !input || !cameraBtn || !fileBtn) return;

  // 카메라 버튼: capture 속성을 붙여서 열면 모바일에서 바로 촬영 화면으로 간다.
  // 파일 버튼: capture 없이 열어서 보통의 파일/사진첩 선택창이 뜨게 한다.
  // (input 하나를 공유해서, 두 버튼이 같은 name="card_image"로 중복 제출되는 걸 방지)
  cameraBtn.addEventListener("click", function () {
    input.setAttribute("capture", "environment");
    input.click();
  });

  fileBtn.addEventListener("click", function () {
    input.removeAttribute("capture");
    input.click();
  });

  input.addEventListener("change", function () {
    if (!input.files || !input.files.length) return;
    cameraBtn.disabled = true;
    fileBtn.disabled = true;
    if (hint) hint.textContent = "명함을 인식하고 있어요...";
    form.requestSubmit ? form.requestSubmit() : form.submit();
  });
});
