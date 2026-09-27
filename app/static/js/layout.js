document.addEventListener("DOMContentLoaded", function () {
  var layout = document.getElementById("layout-root");
  var toggle = document.getElementById("sidebar-toggle");
  var mobileToggle = document.getElementById("mobile-sidebar-toggle");
  var backdrop = document.getElementById("sidebar-backdrop");
  if (!layout) return;

  var STORAGE_KEY = "sabuzak-sidebar-collapsed";
  var isMobile = function () {
    return window.matchMedia("(max-width: 768px)").matches;
  };

  if (!isMobile() && localStorage.getItem(STORAGE_KEY) === "1") {
    layout.classList.add("sidebar-collapsed");
  }

  function closeMobileSidebar() {
    layout.classList.remove("sidebar-mobile-open");
  }

  function openMobileSidebar() {
    layout.classList.add("sidebar-mobile-open");
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      if (isMobile()) {
        closeMobileSidebar();
        return;
      }
      var collapsed = layout.classList.toggle("sidebar-collapsed");
      localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    });
  }

  if (mobileToggle) {
    mobileToggle.addEventListener("click", openMobileSidebar);
  }

  if (backdrop) {
    backdrop.addEventListener("click", closeMobileSidebar);
  }

  layout.querySelectorAll(".sidebar nav a").forEach(function (link) {
    link.addEventListener("click", function () {
      if (isMobile()) closeMobileSidebar();
    });
  });

  window.addEventListener("resize", function () {
    if (!isMobile()) closeMobileSidebar();
  });
});
