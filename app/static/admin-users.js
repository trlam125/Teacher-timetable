(() => {
  const openers = new WeakMap();
  const deleteConfirmation = document.getElementById("accountDeleteConfirmation");
  let pendingDeleteForm = null;

  document.addEventListener("click", event => {
    const opener = event.target.closest("[data-admin-dialog]");
    if (opener) {
      const dialog = document.getElementById(opener.dataset.adminDialog);
      if (!dialog || dialog.open) return;
      openers.set(dialog, opener);
      dialog.showModal();
      return;
    }

    const close = event.target.closest("[data-close-admin-dialog]");
    if (close) close.closest("dialog").close();
    if (event.target.closest("[data-delete-account]")) deleteConfirmation.close("delete");
  });

  document.querySelectorAll(".admin-detail-dialog").forEach(dialog => {
    dialog.addEventListener("close", () => openers.get(dialog)?.focus());
  });

  document.addEventListener("submit", event => {
    if (event.target.matches(".avatar-delete-form")) {
      const button = event.target.querySelector("[data-confirm-message]");
      if (button && !window.confirm(button.dataset.confirmMessage)) event.preventDefault();
      return;
    }
    if (!event.target.matches("[data-confirm-account-delete]")) return;
    event.preventDefault();
    if (deleteConfirmation.open) return;
    pendingDeleteForm = event.target;
    deleteConfirmation.returnValue = "";
    deleteConfirmation.showModal();
  });

  deleteConfirmation.addEventListener("close", () => {
    const form = pendingDeleteForm;
    pendingDeleteForm = null;
    if (deleteConfirmation.returnValue === "delete") form?.submit();
  });
})();
