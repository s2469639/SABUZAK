document.addEventListener("DOMContentLoaded", function () {
  var nameInput = document.getElementById("name");
  var hsInput = document.getElementById("hs_code");
  if (!nameInput || !hsInput) return;

  var nameDropdown = document.getElementById("name-autocomplete");
  var hsDropdown = document.getElementById("hs_code-autocomplete");

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
});
