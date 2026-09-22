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
        resultsBox.scrollIntoView({ behavior: "smooth", block: "start" });
      });
  }

  document.querySelectorAll(".continent-card").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".continent-card").forEach(function (b) {
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
  });

  function submitFilter(form, overrides) {
    overrides = overrides || {};
    var box = form.closest(".expo-results");
    var baseUrl = box.dataset.partialUrl;

    var params = new URLSearchParams();
    var foodCheckbox = form.querySelector('input[name="food_only"]');
    var searchInput = form.querySelector('input[name="search"]');

    if (foodCheckbox && foodCheckbox.checked) params.set("food_only", "1");
    if (searchInput && searchInput.value.trim()) params.set("search", searchInput.value.trim());

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
