"use strict";
const scheduleAuditInput = $("#scheduleAuditFile"),
  scheduleAuditDropzone = $("#scheduleAuditDropzone");
if (scheduleAuditInput)
  scheduleAuditInput.addEventListener("change", () => {
    const file = scheduleAuditInput.files?.[0] || null;
    if (file) selectScheduleAuditFile(file);
  });
if (scheduleAuditDropzone) {
  let dragDepth = 0;
  scheduleAuditDropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      scheduleAuditInput?.click();
    }
  });
  scheduleAuditDropzone.addEventListener("dragenter", (event) => {
    event.preventDefault();
    dragDepth += 1;
    scheduleAuditDropzone.classList.add("is-dragging");
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  });
  scheduleAuditDropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    scheduleAuditDropzone.classList.add("is-dragging");
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  });
  scheduleAuditDropzone.addEventListener("dragleave", (event) => {
    event.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) scheduleAuditDropzone.classList.remove("is-dragging");
  });
  scheduleAuditDropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dragDepth = 0;
    scheduleAuditDropzone.classList.remove("is-dragging");
    const files = Array.from(event.dataTransfer?.files || []);
    if (files.length > 1) {
      clearScheduleAuditFile(false);
      renderScheduleAuditError("Mỗi lần chỉ kiểm tra 1 file.");
      return;
    }
    const file = files[0];
    if (file) selectScheduleAuditFile(file);
  });
}
document.addEventListener("dragover", (event) => {
  if (Array.from(event.dataTransfer?.types || []).includes("Files"))
    event.preventDefault();
});
document.addEventListener("drop", (event) => {
  if (!Array.from(event.dataTransfer?.types || []).includes("Files")) return;
  if (event.target?.closest?.("#scheduleAuditDropzone")) return;
  event.preventDefault();
});

window.addEventListener(
  "resize",
  () => requestAnimationFrame(syncScheduleAuditBottomScroller),
  { passive: true },
);
