document.addEventListener("DOMContentLoaded", function () {
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
