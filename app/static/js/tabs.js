document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".tabs").forEach(function (tabs) {
    var buttons = tabs.querySelectorAll(".tab-btn");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var target = btn.dataset.tab;

        buttons.forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });

        tabs.querySelectorAll(".tab-panel").forEach(function (panel) {
          panel.hidden = panel.id !== "tab-" + target;
        });
      });
    });
  });
});
