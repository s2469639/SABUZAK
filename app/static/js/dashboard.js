document.addEventListener("DOMContentLoaded", function () {
  var resultsBox = document.getElementById("continent-results");
  if (!resultsBox) return;

  var activeContinentBtn = null;

  function loadPartial(url) {
    fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (res) { return res.text(); })
      .then(function (html) {
        resultsBox.innerHTML = html;
        resultsBox.hidden = false;
        var card = document.querySelector(".dash-map-card");
        if (card) {
          var top = window.scrollY + card.getBoundingClientRect().bottom;
          window.scrollTo({ top: top, behavior: "smooth" });
        } else {
          resultsBox.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
  }

  document.querySelectorAll(".legend-chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".legend-chip").forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });
      activeContinentBtn = btn;
      loadPartial(btn.dataset.url);
    });
  });

  // 결과 영역은 매번 새로 렌더링되므로 이벤트 위임으로 처리
  resultsBox.addEventListener("submit", function (e) {
    var form = e.target.closest("[data-filter-form]");
    if (!form) return;
    e.preventDefault();
    submitFilter(form);
  });

  resultsBox.addEventListener("click", function (e) {
    var pageLink = e.target.closest("a.page-link");
    if (pageLink) {
      e.preventDefault();
      loadPartial(pageLink.getAttribute("href"));
      return;
    }

    var resetBtn = e.target.closest("[data-filter-reset]");
    if (resetBtn) {
      var form = resetBtn.closest("[data-filter-form]");
      var baseUrl = resultsBox.querySelector(".expo-results").dataset.partialUrl;
      loadPartial(baseUrl);
      return;
    }

    var tagBtn = e.target.closest("[data-keyword-tag]");
    if (tagBtn) {
      var isActive = tagBtn.classList.contains("active");
      var form = tagBtn.closest(".expo-results").querySelector("[data-filter-form]");
      submitFilter(form, { keyword_tag: isActive ? "" : tagBtn.dataset.keywordTag });
      return;
    }

    // "상세 필터" 토글: 식품여부/규모/참관대상 체크박스는 기본으로 접어둬서
    // 검색창까지만 보이게 하고, 필요할 때만 펼친다.
    var advToggle = e.target.closest("[data-filter-advanced-toggle]");
    if (advToggle) {
      var advBox = advToggle.closest("form").querySelector("[data-filter-advanced]");
      if (advBox) {
        var willShow = advBox.hidden;
        advBox.hidden = !willShow;
        advToggle.setAttribute("aria-expanded", String(willShow));
      }
      return;
    }
  });

  // 정렬 셀렉트는 필터 폼 안에 있지 않아도 되니(레이아웃상 키워드 태그 줄 옆에 있음),
  // 값이 바뀌면 그 즉시(버튼 없이) 다시 불러온다.
  resultsBox.addEventListener("change", function (e) {
    var sortSelect = e.target.closest('select[name="sort"]');
    if (!sortSelect) return;
    var form = sortSelect.closest(".expo-results").querySelector("[data-filter-form]");
    submitFilter(form);
  });

  function submitFilter(form, overrides) {
    overrides = overrides || {};
    var box = form.closest(".expo-results");
    var baseUrl = box.dataset.partialUrl;

    var params = new URLSearchParams();
    var foodCheckbox = form.querySelector('input[name="food_only"]');
    var searchInput = form.querySelector('input[name="search"]');
    var sortSelect = box.querySelector('select[name="sort"]');
    var dateFromInput = form.querySelector('input[name="date_from"]');
    var dateToInput = form.querySelector('input[name="date_to"]');

    if (foodCheckbox && foodCheckbox.checked) params.set("food_only", "1");
    if (searchInput && searchInput.value.trim()) params.set("search", searchInput.value.trim());
    if (sortSelect && sortSelect.value && sortSelect.value !== "asc") {
      params.set("sort", sortSelect.value);
    }
    if (dateFromInput && dateFromInput.value) params.set("date_from", dateFromInput.value);
    if (dateToInput && dateToInput.value) params.set("date_to", dateToInput.value);

    form.querySelectorAll('input[name="scale"]:checked').forEach(function (cb) {
      params.append("scale", cb.value);
    });
    form.querySelectorAll('input[name="audience_type"]:checked').forEach(function (cb) {
      params.append("audience_type", cb.value);
    });

    var currentTag = "";
    var activeTagBtn = box.querySelector(".keyword-filter-tag.active");
    if (activeTagBtn) currentTag = activeTagBtn.dataset.keywordTag;
    if ("keyword_tag" in overrides) {
      currentTag = overrides.keyword_tag;
    }
    if (currentTag) params.set("keyword_tag", currentTag);

    var qs = params.toString();
    loadPartial(baseUrl + (qs ? "?" + qs : ""));
  }
});
