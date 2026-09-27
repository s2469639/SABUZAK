document.addEventListener("DOMContentLoaded", function () {
  var layout = document.getElementById("layout-root");
  var toggle = document.getElementById("sidebar-toggle");
  if (!layout || !toggle) return;

  var STORAGE_KEY = "sabuzak-sidebar-collapsed";

  if (localStorage.getItem(STORAGE_KEY) === "1") {
    layout.classList.add("sidebar-collapsed");
  }

  toggle.addEventListener("click", function () {
    var collapsed = layout.classList.toggle("sidebar-collapsed");
    localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
  });
});
