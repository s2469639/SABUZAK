document.addEventListener("DOMContentLoaded", function () {
  // 페이지 안에 제품명+HS코드 자동완성 쌍이 여러 개 있을 수 있다 (제품 등록 폼,
  // 대시보드/수정 모달 등) - .form-row 안에 .hs-autocomplete-field가 2개(제품명, HS코드)
  // 들어있는 구조를 찾아서 각각 독립적으로 연결한다.
  document.querySelectorAll(".form-row").forEach(function (row) {
    var fields = row.querySelectorAll(".hs-autocomplete-field");
    if (fields.length < 2) return;
    wireAutocomplete(fields[0], fields[1]);
  });

  function wireAutocomplete(nameField, hsField) {
    var nameInput = nameField.querySelector("input");
    var hsInput = hsField.querySelector("input");
    var nameDropdown = nameField.querySelector(".hs-autocomplete-dropdown");
    var hsDropdown = hsField.querySelector(".hs-autocomplete-dropdown");
    if (!nameInput || !hsInput || !nameDropdown || !hsDropdown) return;

    var debounceTimer = null;

    function search(query, dropdown) {
      if (query.trim().length < 1) {
        dropdown.hidden = true;
        dropdown.innerHTML = "";
        return;
      }
      fetch("/mypage/hscode-search?q=" + encodeURIComponent(query))
        .then(function (res) { return res.json(); })
        .then(function (items) {
          renderDropdown(items, dropdown);
        });
    }

    function renderDropdown(items, dropdown) {
      if (!items.length) {
        dropdown.hidden = true;
        dropdown.innerHTML = "";
        return;
      }
      dropdown.innerHTML = items
        .map(function (item) {
          return (
            '<div class="hs-autocomplete-item" data-hscode="' +
            item.hscode +
            '" data-name="' +
            (item.name_ko || "") +
            '">' +
            '<span class="hs-autocomplete-code">' + item.hscode + "</span>" +
            '<span class="hs-autocomplete-name">' + (item.name_ko || "") + "</span>" +
            "</div>"
          );
        })
        .join("");
      dropdown.hidden = false;

      dropdown.querySelectorAll(".hs-autocomplete-item").forEach(function (el) {
        el.addEventListener("click", function () {
          hsInput.value = el.dataset.hscode;
          if (!nameInput.value.trim()) {
            nameInput.value = el.dataset.name;
          }
          nameDropdown.hidden = true;
          hsDropdown.hidden = true;
        });
      });
    }

    function onInput(input, dropdown) {
      input.addEventListener("input", function () {
        clearTimeout(debounceTimer);
        var value = input.value;
        debounceTimer = setTimeout(function () {
          search(value, dropdown);
        }, 250);
      });
    }

    onInput(nameInput, nameDropdown);
    onInput(hsInput, hsDropdown);

    document.addEventListener("click", function (e) {
      if (!nameInput.contains(e.target) && !nameDropdown.contains(e.target)) {
        nameDropdown.hidden = true;
      }
      if (!hsInput.contains(e.target) && !hsDropdown.contains(e.target)) {
        hsDropdown.hidden = true;
      }
    });
  }

  // 제품 수정 모달: "수정" 버튼을 누른 행의 데이터로 모달 폼을 채우고,
  // 그 제품의 수정 URL로 폼 action을 맞춘다 (모달 하나를 모든 행이 공유).
  var editModal = document.getElementById("edit-product-modal");
  if (editModal) {
    var editForm = document.getElementById("edit-product-form");
    var editName = document.getElementById("edit-name");
    var editHsCode = document.getElementById("edit-hs_code");
    var editBrand = document.getElementById("edit-brand");
    var editProductForm = document.getElementById("edit-product_form");
    var editIngredients = document.getElementById("edit-ingredients");
    var editTargetPrice = document.getElementById("edit-target_price");
    var editCertifications = document.getElementById("edit-certifications");
    var editStrengths = document.getElementById("edit-strengths");

    document.querySelectorAll("[data-edit-product]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        editForm.action = btn.dataset.editUrl;
        editName.value = btn.dataset.editName;
        editHsCode.value = btn.dataset.editHscode;
        editBrand.value = btn.dataset.editBrand || "";
        editProductForm.value = btn.dataset.editProductForm || "";
        editIngredients.value = btn.dataset.editIngredients || "";
        editTargetPrice.value = btn.dataset.editTargetPrice || "";
        editCertifications.value = btn.dataset.editCertifications || "";
        editStrengths.value = btn.dataset.editStrengths || "";
      });
    });
  }
});
