function bulkEntityToolbar(type) {
  return `<div class="entity-bulk-toolbar" data-bulk-toolbar="${type}"><span class="entity-bulk-count"><b data-bulk-count>0</b> mục được chọn</span><button class="btn btn-danger entity-bulk-delete" type="button" onclick="deleteSelectedEntities('${type}',this)" disabled>Xóa đã chọn</button></div>`;
}
function bulkEntityHeader(type) {
  return `<th class="entity-select-col"><input class="entity-select-all" type="checkbox" aria-label="Chọn tất cả" onchange="toggleAllEntityRows('${type}',this.checked)"></th>`;
}
function bulkEntityCell(type, id) {
  return `<td class="entity-select-col"><input class="entity-row-select" type="checkbox" data-entity-id="${Number(id)}" aria-label="Chọn mục này" onchange="syncEntityBulkControls('${type}')"></td>`;
}
function bulkEntityTableShell(type, tableHtml) {
  return `<div class="entity-table-shell" data-bulk-table="${type}">${bulkEntityToolbar(type)}${tableHtml}</div>`;
}
function table(rows, cols, type) {
  if (!rows.length) return '<div class="empty-state">Chưa có dữ liệu.</div>';
  const canEdit = ["department", "subject", "teacher", "grade", "class"].includes(type);
  const tableHtml = `<table class="data-table"><thead><tr>${bulkEntityHeader(type)}${cols.map((c) => `<th>${c[0]}</th>`).join("")}<th class="entity-actions-col"></th></tr></thead><tbody>${rows.map((r) => `<tr>${bulkEntityCell(type, r.id)}${cols.map((c) => `<td>${esc(typeof c[1] === "function" ? c[1](r) : r[c[1]])}</td>`).join("")}<td class="entity-actions-cell"><div class="entity-row-actions">${canEdit ? `<button class="action-link" onclick="openEntityEdit('${type}',${r.id})">Sửa</button>` : `<span class="action-link-placeholder"></span>`}<button class="danger-link" onclick="delEntity('${type}',${r.id},this)">Xóa</button></div></td></tr>`).join("")}</tbody></table>`;
  return bulkEntityTableShell(type, tableHtml);
}
function entityBulkRoot(type) {
  return document.querySelector(`[data-bulk-table="${type}"]`);
}
function selectedEntityIds(type) {
  const root = entityBulkRoot(type);
  if (!root) return [];
  return [...root.querySelectorAll(".entity-row-select:checked")]
    .map((input) => Number(input.dataset.entityId || 0))
    .filter((id) => id > 0);
}
function syncEntityBulkControls(type) {
  const root = entityBulkRoot(type);
  if (!root) return;
  const boxes = [...root.querySelectorAll(".entity-row-select")];
  const selected = boxes.filter((input) => input.checked);
  const master = root.querySelector(".entity-select-all");
  const count = root.querySelector("[data-bulk-count]");
  const button = root.querySelector(".entity-bulk-delete");
  if (master) {
    master.checked = boxes.length > 0 && selected.length === boxes.length;
    master.indeterminate = selected.length > 0 && selected.length < boxes.length;
  }
  if (count) count.textContent = String(selected.length);
  if (button) {
    const label = selected.length ? `Xóa đã chọn (${selected.length})` : "Xóa đã chọn";
    button.disabled = selected.length === 0;
    button.dataset.actionIdleLabel = label;
    if (button.dataset.actionState !== "loading") button.textContent = label;
  }
}
function toggleAllEntityRows(type, checked) {
  const root = entityBulkRoot(type);
  if (!root) return;
  root
    .querySelectorAll(".entity-row-select")
    .forEach((input) => (input.checked = Boolean(checked)));
  syncEntityBulkControls(type);
}
async function deleteSelectedEntities(type, button) {
  const ids = selectedEntityIds(type);
  if (!ids.length) return;

  if (type !== "assignment") {
    const confirmed = await confirmAction(
      `Xóa ${ids.length} mục đã chọn? Mục đang được sử dụng sẽ được giữ lại.`,
      { confirmText: `Xóa ${ids.length} mục` },
    );
    if (!confirmed) return;
  }

  setInlineActionState(button, "loading", {
    idle: button.dataset.actionIdleLabel || "Xóa đã chọn",
    loading: type === "assignment" ? "Đang kiểm tra..." : "Đang xóa...",
  });

  try {
    let confirmation = null;
    for (let attemptIndex = 0; attemptIndex < 3; attemptIndex++) {
      const body = { type, ids, ...(confirmation || {}) };
      const r = await fetch(`/api/projects/${PROJECT_ID}/entities/bulk`, {
        method: "DELETE",
        headers: operationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
      });
      const result = await readApiResponse(r);

      if (type === "assignment" && !r.ok && result?.requires_confirmation) {
        const confirmed = await confirmAction(
          result.message || `Xóa ${ids.length} phân công đã chọn?`,
          {
            title: "Xác nhận xóa phân công",
            confirmText: `Xóa ${Number(result.assignment_count || ids.length)} phân công`,
          },
        );
        if (!confirmed) {
          setInlineActionState(button, "idle", {
            idle: button.dataset.actionIdleLabel || "Xóa đã chọn",
          });
          return;
        }
        confirmation = {
          confirm_assignment_cascade: true,
          confirmed_lesson_ids: Array.isArray(result.lesson_ids) ? result.lesson_ids : [],
          confirmed_fixed_lesson_ids: Array.isArray(result.fixed_lesson_ids)
            ? result.fixed_lesson_ids
            : [],
        };
        setInlineActionState(button, "loading", {
          idle: button.dataset.actionIdleLabel || "Xóa đã chọn",
          loading: "Đang xóa...",
        });
        continue;
      }

      if (!r.ok) {
        setInlineActionState(
          button,
          "error",
          { idle: button.dataset.actionIdleLabel || "Xóa đã chọn", error: "Không thể xóa" },
          2200,
        );
        showToast(
          apiErrorMessage(result, "Không thể xóa các mục đã chọn."),
          "error",
          4800,
        );
        return;
      }
      setInlineActionState(button, "success", {
        idle: button.dataset.actionIdleLabel || "Xóa đã chọn",
        success: `Đã xóa ${Number(result.deleted || ids.length)} mục`,
      });
      showToast(
        result.message || `Đã xóa ${Number(result.deleted || ids.length)} mục.`,
        Array.isArray(result.skipped) && result.skipped.length ? "warning" : "delete",
        4800,
      );
      await wait(500);
      await refreshAfterSuccessfulMutation();
      return;
    }
    throw new Error("Dữ liệu lịch thay đổi trong lúc xác nhận. Hãy thử xóa lại.");
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: button.dataset.actionIdleLabel || "Xóa đã chọn", error: "Chưa hoàn tất" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 4800);
  }
}
