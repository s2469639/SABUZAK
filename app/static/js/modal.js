document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-modal-open]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var modal = document.getElementById(btn.dataset.modalOpen);
      if (modal) openModal(modal);
    });
  });

  document.querySelectorAll(".modal-overlay").forEach(function (overlay) {
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay || e.target.closest("[data-modal-close]")) {
        closeModal(overlay);
      }
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    document.querySelectorAll(".modal-overlay.open").forEach(closeModal);
  });

  function openModal(modal) {
    modal.classList.add("open");
    var firstInput = modal.querySelector("input, textarea");
    if (firstInput) firstInput.focus();
  }

  function closeModal(modal) {
    modal.classList.remove("open");
  }

  window.SabuzakModal = { open: openModal, close: closeModal };
});
