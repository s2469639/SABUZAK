document.addEventListener("DOMContentLoaded", function () {
  // "지금 실제 데이터 가져오기"(TRAINS 조회) 같은 버튼은 서버가 외부 API를
  // 불러오느라 몇 초씩 걸리는데, 그동안 화면에 아무 표시가 없으면 사용자가
  // "안 되나보다" 하고 계속 다시 눌러서 매번 이전 요청이 취소되고 처음부터
  // 다시 기다리는 문제가 있었다. 제출 즉시 버튼을 비활성화 + 문구를 바꿔서
  // 진행 중임을 보여주고, 중복 제출도 막는다.
  document.querySelectorAll("form.btn-loading-form").forEach(function (form) {
    form.addEventListener("submit", function () {
      var btn = form.querySelector("button[type=submit]");
      if (!btn || btn.disabled) return;
      btn.dataset.originalText = btn.textContent;
      btn.textContent = btn.dataset.loadingText || "처리 중...";
      btn.disabled = true;
    });
  });

  document.querySelectorAll(".tabs").forEach(function (tabs) {
    var buttons = tabs.querySelectorAll(".tab-btn");

    function activate(target) {
      var btn = tabs.querySelector('.tab-btn[data-tab="' + target + '"]');
      if (!btn) return;

      buttons.forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });

      tabs.querySelectorAll(".tab-panel").forEach(function (panel) {
        panel.hidden = panel.id !== "tab-" + target;
      });
    }

    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        activate(btn.dataset.tab);
      });
    });

    // 예: /exhibitions/detail/1#hscode 로 들어오면 HS코드 탭이 바로 보이도록
    var hashTab = window.location.hash.replace("#", "");
    if (hashTab) {
      activate(hashTab);
    }
  });
});
