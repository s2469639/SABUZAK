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

  // 모바일에서 화면 왼쪽 가장자리를 오른쪽으로 스와이프하면 사이드바가
  // 당겨져 나오고, 열린 상태에서 사이드바를 왼쪽으로 스와이프하면 닫힌다.
  var sidebarEl = document.querySelector(".sidebar");
  var EDGE_ZONE = 24;
  var SWIPE_THRESHOLD = 50;
  var touchStartX = 0;
  var touchStartY = 0;
  var tracking = false;

  document.addEventListener("touchstart", function (e) {
    if (!isMobile()) return;
    var t = e.touches[0];
    var isOpen = layout.classList.contains("sidebar-mobile-open");
    var withinEdge = t.clientX <= EDGE_ZONE;
    var onSidebar = sidebarEl && sidebarEl.contains(e.target);
    if (!isOpen && !withinEdge) return;
    if (isOpen && !onSidebar) return;
    touchStartX = t.clientX;
    touchStartY = t.clientY;
    tracking = true;
  }, { passive: true });

  document.addEventListener("touchmove", function (e) {
    if (!tracking) return;
    var t = e.touches[0];
    // 세로 스크롤 의도면(위아래로 더 많이 움직이면) 스와이프 제스처를 포기한다
    if (Math.abs(t.clientY - touchStartY) > Math.abs(t.clientX - touchStartX)) {
      tracking = false;
    }
  }, { passive: true });

  document.addEventListener("touchend", function (e) {
    if (!tracking) return;
    tracking = false;
    var t = e.changedTouches[0];
    var dx = t.clientX - touchStartX;
    var isOpen = layout.classList.contains("sidebar-mobile-open");
    if (!isOpen && dx > SWIPE_THRESHOLD) {
      openMobileSidebar();
    } else if (isOpen && dx < -SWIPE_THRESHOLD) {
      closeMobileSidebar();
    }
  }, { passive: true });
});
