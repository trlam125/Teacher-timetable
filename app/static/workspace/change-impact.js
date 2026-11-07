/* Project-scoped previews, confirmed edits and recovery. No preview writes to live data. */
let postScheduleEditing = false;
let projectChangeInFlight = false;

function setPostScheduleEditing(enabled) {
  postScheduleEditing = Boolean(enabled);
  const toggle = document.getElementById("postScheduleEditToggle");
  if (toggle) toggle.checked = postScheduleEditing;
  const hint = document.getElementById("postScheduleEditHint");
  if (hint) hint.textContent = postScheduleEditing
    ? "Đã bật chỉnh sửa. Bạn sẽ xem ảnh hưởng và xác nhận trước khi lưu."
    : "Xem trước ảnh hưởng trước khi áp dụng thay đổi.";
}

function changeSlotLabel(slot) {
  const periods = Number(data.project.periods || 5), sessions = Number(data.project.sessions || 2);
  const day = Math.floor(Number(slot) / (periods * sessions));
  const session = Math.floor((Number(slot) % (periods * sessions)) / periods);
  return `${day === 6 ? "Chủ nhật" : `Thứ ${day + 2}`} · ${sessions > 1 ? (session === 0 ? "Sáng · " : "Chiều · ") : ""}Tiết ${Number(slot) % periods + 1}`;
}

function changeDisplayValue(value, field) {
  const name = (table, id) => (data[table] || []).find(row => Number(row.id) === Number(id))?.name || "—";
  if (Array.isArray(value)) return value.map(row => {
    if (typeof row !== "object") return String(row);
    const labels = [];
    if (row.grade_id) labels.push(name("grades", row.grade_id));
    if (row.teacher_id) labels.push(name("teachers", row.teacher_id));
    if (row.subject_id) labels.push(name("subjects", row.subject_id));
    if (row.periods_per_week) labels.push(`${row.periods_per_week} tiết/tuần`);
    if (row.block_mode) labels.push(row.block_mode === "required_double" ? "Tiết đôi bắt buộc" : row.block_mode === "preferred_double" ? "Ưu tiên tiết đôi" : "Tiết đơn");
    return labels.join(" · ");
  }).join("; ") || "Trống";
  if (field === "Tiết tránh" || field === "Khóa lịch") {
    try { return JSON.parse(value).map(changeSlotLabel).join(", ") || "Không có"; } catch { return String(value); }
  }
  if (field === "Chế độ tiết") return value === "required_double" ? "Tiết đôi bắt buộc" : value === "preferred_double" ? "Ưu tiên tiết đôi" : "Tiết đơn";
  return String(value ?? "—");
}

function impactTable(headers, rows) {
  return `<div class="change-impact-table"><table><thead><tr>${headers.map(value => `<th>${esc(value)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(value => `<td>${esc(String(value ?? ""))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function renderChangeImpact(report, request, syncApply) {
  const totals = report.totals || {};
  const actions = {to_tray: "Đưa về kho", surplus: "Bỏ tiết dư", deleted: "Xóa cùng phân công"};
  let html = "";
  if (report.can_apply) {
    html += `<div class="change-impact-stats"><span>Phân công cập nhật: <b>${Number(totals.assignments_updated || 0)}</b></span><span>Phân công xóa: <b>${Number(totals.assignments_deleted || 0)}</b></span><span>Giữ: <b>${Number(totals.kept || 0)} tiết liên quan</b></span>${Object.entries(actions).map(([key, label]) => `<span>${label}: <b>${Number(totals[key] || 0)} tiết / ${Number(totals.blocks?.[key] || 0)} cụm</b></span>`).join("")}<span>Kho sau thay đổi: <b>${Number(totals.tray_after || 0)} tiết</b></span></div>`;
    if (!report.changed) html += "<p>Không có thay đổi cần lưu.</p>";
  }
  for (const blocker of report.blockers || []) {
    html += `<div class="change-impact-blocker">${esc(blocker.message || "Chưa thể áp dụng.")}</div>`;
    if (blocker.lessons?.length) html += impactTable(["Lớp", "Môn", "Giáo viên", "Tiết được bảo vệ"], blocker.lessons.map(row => [row.class_name, row.subject_name, row.teacher_name, changeSlotLabel(row.slot)]));
    for (const assignment of blocker.assignments || []) {
      const teachers = assignment.allow_transfer ? (data.teachers || []).filter(row => Number(row.id) !== Number(assignment.teacher_id) && (row.subject_ids || []).includes(Number(assignment.subject_id))) : [];
      html += `<label class="change-impact-resolution"><span>${esc(assignment.class_name)} · ${esc(assignment.subject_name)}</span><select data-change-resolution="${Number(assignment.id)}"><option value="">Chọn cách xử lý</option>${teachers.map(row => `<option value="${Number(row.id)}">Chuyển sang ${esc(row.name)}</option>`).join("")}<option value="delete">Xóa phân công và các tiết liên quan</option></select></label>`;
    }
    if (blocker.reason === "protected_lessons" || /cố định|ghim/i.test(blocker.message || "")) html += "<p>Quay lại lịch để bỏ cố định các tiết liên quan, rồi mở lại mục sửa.</p>";
    if (/chương trình/i.test(blocker.message || "") && request.kind === "assignment") html += '<p>Số tiết/chế độ được quản lý theo chương trình khối. Hãy sửa ở bảng “Số tiết bắt buộc theo khối – môn” và xem ảnh hưởng tới toàn khối.</p>';
  }
  if (report.changes?.length) html += "<h3>Nội dung thay đổi</h3>" + impactTable(["Đối tượng", "Nội dung", "Trước", "Sau"], report.changes.map(row => [row.object, row.field, changeDisplayValue(row.before, row.field), changeDisplayValue(row.after, row.field)]));
  if (report.assignments?.some(row => row.action === "delete")) html += "<h3>Phân công sẽ xóa</h3>" + impactTable(["Lớp", "Môn", "Giáo viên"], report.assignments.filter(row => row.action === "delete").map(row => [row.class_name, row.subject_name, row.teacher_name]));
  if (report.lesson_actions?.length) html += "<h3>Tiết bị ảnh hưởng</h3>" + impactTable(["Lớp", "Môn", "Giáo viên", "Vị trí", "Xử lý", "Lý do"], report.lesson_actions.map(row => [row.class_name, row.subject_name, row.teacher_name, changeSlotLabel(row.slot), actions[row.action], row.reason]));
  if (report.removal_candidates?.length) {
    html += '<h3>Chọn cụm tiết bỏ khi giảm tiết</h3><p>Bỏ chọn để giữ cụm tiết, chọn để bỏ. Tiết đôi được gỡ cả cụm; phần còn cần dạy sẽ trở về kho tiết chưa xếp. Sau khi đổi lựa chọn, bấm “Tính lại ảnh hưởng”.</p>';
    html += report.removal_candidates.map(row => `<label class="change-impact-block"><input type="checkbox" data-change-remove="${Number(row.assignment_id)}" data-lesson-ids="${row.lesson_ids.map(Number).join(",")}" ${row.selected ? "checked" : ""} ${row.protected ? "disabled" : ""}><span>${esc(row.class_name)} · ${esc(row.subject_name)} · ${esc(row.slots.map(changeSlotLabel).join("; "))}${row.protected ? " (Đã cố định)" : ""}</span></label>`).join("");
  }
  for (const warning of report.warnings || []) html += `<p>${esc(warning)}</p>`;
  if (report.changed && report.can_apply) html += "<p>Bản dự phòng sẽ được lưu trước khi áp dụng. Các tiết cố định được bảo vệ.</p>";
  if ((data.lessons || []).length && report.requires_edit_mode && report.changed && !postScheduleEditing) html += '<label class="change-impact-block"><input id="changeEnableEditing" type="checkbox"> Cho phép chỉnh sửa sau xếp lịch cho lần làm việc này</label>';
  document.getElementById("changeImpactBody").innerHTML = html;
  document.getElementById("changeEnableEditing")?.addEventListener("change", event => {
    setPostScheduleEditing(event.target.checked);
    syncApply();
  });
}

async function projectChangeRequest(path, payload) {
  const response = await fetch(`/api/projects/${PROJECT_ID}/changes${path}`, {
    method: "POST", headers: operationHeaders({"Content-Type": "application/json"}), body: JSON.stringify(payload),
  });
  return {response, result: await readApiResponse(response)};
}

async function runProjectChange(originalRequest) {
  if (projectChangeInFlight) throw new Error("Đang có thay đổi chờ xác nhận. Hãy hoàn tất hoặc hủy trước.");
  projectChangeInFlight = true;
  const request = JSON.parse(JSON.stringify(originalRequest));
  let preview;
  try {
    preview = await projectChangeRequest("/preview", request);
    if (!preview.response.ok) return {...preview, cancelled: false};
    if (preview.result.can_apply && !preview.result.changed) return {response: preview.response, result: {ok: true, message: "Không có thay đổi."}, cancelled: true};
    if (preview.result.can_apply && !preview.result.requires_edit_mode) {
      const outcome = await projectChangeRequest("/apply", {request, impact_token: preview.result.impact_token});
      return {...outcome, cancelled: false};
    }
    const dialog = document.getElementById("changeImpactDialog"), apply = document.getElementById("changeImpactApply"), recalculate = document.getElementById("changeImpactRecalculate"), cancel = document.getElementById("changeImpactCancel"), status = document.getElementById("changeImpactStatus");
    let report = preview.result, busy = false, previewDirty = false, selectionRevision = 0;
    const syncApply = () => { apply.disabled = busy || previewDirty || !report.can_apply || !report.changed || (report.requires_edit_mode && (data.lessons || []).length > 0 && !postScheduleEditing); };
    const render = () => {renderChangeImpact(report, request, syncApply);syncApply();};
    render();
    status.textContent = "";
    dialog.showModal();
    return await new Promise(resolve => {
      const cleanup = () => {apply.onclick = null;recalculate.onclick = null;cancel.onclick = null;dialog.oncancel = null;dialog.onclose = null;dialog.onchange = null;};
      const finish = outcome => {cleanup();dialog.close();resolve(outcome);};
      const cancelled = () => finish({...preview, cancelled: true});
      cancel.onclick = () => {if (!busy) cancelled();};
      dialog.oncancel = event => {event.preventDefault();if (!busy) cancelled();};
      dialog.onclose = () => {cleanup();resolve({...preview, cancelled: true});};
      dialog.onchange = event => {
        if (event.target.matches("[data-change-resolution], [data-change-remove]")) {
          previewDirty = true;
          selectionRevision += 1;
          syncApply();
          status.textContent = "Lựa chọn đã đổi. Hãy tính lại ảnh hưởng trước khi áp dụng.";
        }
      };
      let busyControls = [];
      const setBusy = value => {
        if (value && !busy) {
          busyControls = [...dialog.querySelectorAll("[data-change-resolution], [data-change-remove], #changeEnableEditing")].map(control => [control, control.disabled]);
          busyControls.forEach(([control]) => {control.disabled = true;});
        } else if (!value) {
          busyControls.forEach(([control, disabled]) => {control.disabled = disabled;});
          busyControls = [];
        }
        busy = value;cancel.disabled = value;recalculate.disabled = value;syncApply();
      };
      recalculate.onclick = async () => {
        if (busy) return;
        for (const select of dialog.querySelectorAll("[data-change-resolution]")) {
          if (select.value) (request.resolutions ||= {})[select.dataset.changeResolution] = select.value;
          else if (request.resolutions) delete request.resolutions[select.dataset.changeResolution];
        }
        const checks = [...dialog.querySelectorAll("[data-change-remove]")];
        if (checks.length) {
          request.remove_lesson_ids = {};
          for (const check of checks.filter(check => check.checked && !check.disabled)) {
            (request.remove_lesson_ids[check.dataset.changeRemove] ||= []).push(...check.dataset.lessonIds.split(",").map(Number));
          }
        }
        const revision = selectionRevision;
        previewDirty = true;
        setBusy(true);status.textContent = "Đang tính lại ảnh hưởng...";
        try {
          const outcome = await projectChangeRequest("/preview", request);
          if (!outcome.response.ok) {status.textContent = apiErrorMessage(outcome.result, "Không thể xem trước.");return;}
          if (revision !== selectionRevision) {
            status.textContent = "Lựa chọn đã đổi trong lúc tính. Hãy tính lại ảnh hưởng trước khi áp dụng.";
            return;
          }
          report = outcome.result;previewDirty = false;render();status.textContent = "Đã tính lại ảnh hưởng theo lựa chọn hiện tại.";
        } catch (error) {status.textContent = requestFailureMessage(error);} finally {setBusy(false);}
      };
      apply.onclick = async () => {
        if (busy || previewDirty || apply.disabled) return;
        setBusy(true);status.textContent = "Đang áp dụng thay đổi...";
        try {
          const outcome = await projectChangeRequest("/apply", {request, impact_token: report.impact_token});
          if (outcome.response.ok) {
            if (outcome.result.undone) outcome.result.message = "Thay đổi này đã được áp dụng và hoàn tác trước đó. Dữ liệu hiện tại được giữ nguyên.";
            finish({...outcome, cancelled: false});return;
          }
          status.textContent = apiErrorMessage(outcome.result, "Không thể áp dụng.");
          if (outcome.result.reason === "impact_stale") {
            report.can_apply = false;
            status.textContent += " Quay lại chỉnh sửa và tải dữ liệu mới, hoặc tính lại ảnh hưởng nếu mục đang sửa chưa thay đổi.";
          }
        } catch (error) {
          status.textContent = "Chưa xác định được kết quả do mất kết nối. Bấm Áp dụng lại để kiểm tra; hệ thống không áp dụng trùng.";
        } finally {setBusy(false);}
      };
    });
  } finally {projectChangeInFlight = false;}
}

async function openProjectChangeHistory() {
  const dialog = document.getElementById("projectChangeHistoryDialog"), body = document.getElementById("projectChangeHistoryBody");
  if (!dialog.open) dialog.showModal();
  body.textContent = "Đang tải bản dự phòng...";
  try {
    const response = await fetch(`/api/projects/${PROJECT_ID}/changes`, {headers: operationHeaders()});
    const result = await readApiResponse(response);
    if (!response.ok) {body.textContent = apiErrorMessage(result, "Không thể tải bản dự phòng.");return;}
    body.innerHTML = result.items.length ? result.items.map(row => `<article class="project-change-entry"><b>${esc(row.title)}</b> · <time>${esc(new Date(row.created_at).toLocaleString("vi-VN", {timeZone: "Asia/Ho_Chi_Minh"}))}</time> · ${esc(row.actor_name || "")}<p>${esc(row.message)}</p>${row.undone_at ? "<span>Đã hoàn tác</span>" : row.can_undo ? `<button type="button" class="btn ghost" data-undo-change="${esc(row.id)}">Hoàn tác thay đổi này</button>` : "<span>Đã có thay đổi tiếp theo; không thể phục hồi đè lên dữ liệu hiện tại.</span>"}</article>`).join("") : "<p>Chưa có bản dự phòng từ các lần chỉnh sửa.</p>";
    body.querySelectorAll(".project-change-entry").forEach((entry, index) => {
      const button = document.createElement("button"), detail = document.createElement("div");
      button.type = "button";button.className = "btn ghost";button.textContent = "Xem chi tiết";
      detail.hidden = true;
      entry.append(button, detail);
      button.addEventListener("click", async () => {
        if (detail.dataset.loaded) {detail.hidden = !detail.hidden;return;}
        button.disabled = true;
        try {
          const response = await fetch(`/api/projects/${PROJECT_ID}/changes/${encodeURIComponent(result.items[index].id)}`, {headers: operationHeaders()});
          const payload = await readApiResponse(response);
          if (!response.ok) {showToast(apiErrorMessage(payload, "Không thể tải chi tiết."), "error");return;}
          const audit = payload.audit || {}, labels = {to_tray: "Đưa về kho", surplus: "Bỏ tiết dư", deleted: "Xóa cùng phân công"};
          detail.innerHTML = (audit.changes?.length ? '<h3>Nội dung thay đổi</h3>' + impactTable(["Đối tượng", "Nội dung", "Trước", "Sau"], audit.changes.map(row => [row.object, row.field, changeDisplayValue(row.before, row.field), changeDisplayValue(row.after, row.field)])) : '')
            + (audit.lesson_actions?.length ? '<h3>Tiết bị ảnh hưởng</h3>' + impactTable(["Lớp", "Môn", "Giáo viên", "Vị trí", "Xử lý", "Lý do"], audit.lesson_actions.map(row => [row.class_name, row.subject_name, row.teacher_name, changeSlotLabel(row.slot), labels[row.action], row.reason])) : '');
          if (!detail.innerHTML) detail.textContent = "Bản ghi này chưa có chi tiết thay đổi.";
          detail.dataset.loaded = "true";detail.hidden = false;
        } catch (error) {showToast(requestFailureMessage(error), "error");}
        finally {button.disabled = false;}
      });
    });
    body.querySelectorAll("[data-undo-change]").forEach(button => button.addEventListener("click", async () => {
      if (!(await confirmUndoInHistory(button))) return;
      button.disabled = true;
      try {
        const outcome = await projectChangeRequest(`/${encodeURIComponent(button.dataset.undoChange)}/undo`, {});
        if (!outcome.response.ok) {showToast(apiErrorMessage(outcome.result, "Không thể hoàn tác."), "error", 6500);button.disabled = false;return;}
        showToast(outcome.result.message, "success", 6000);
        autoAssignmentDrafts.clear();autoGradeDrafts.clear();
        await refreshAfterSuccessfulMutation();
        await openProjectChangeHistory();
      } catch (error) {showToast(requestFailureMessage(error), "error");button.disabled = false;}
    }));
  } catch (error) {body.textContent = requestFailureMessage(error);}
}

function confirmUndoInHistory(button) {
  const panel = document.createElement("div");
  panel.innerHTML = '<p>Phục hồi dữ liệu trước lần thay đổi này? Phân công và lịch sẽ trở về trạng thái trong bản dự phòng.</p><div class="row"><button type="button" class="btn" data-confirm-undo>Phục hồi</button><button type="button" class="btn ghost" data-cancel-undo>Hủy</button></div>';
  button.hidden = true;
  button.after(panel);
  const dialog = button.closest("dialog");
  return new Promise(resolve => {
    const finish = confirmed => {dialog.removeEventListener("close", onClose);panel.remove();button.hidden = false;resolve(confirmed);};
    const onClose = () => finish(false);
    dialog.addEventListener("close", onClose, {once: true});
    panel.querySelector("[data-confirm-undo]").onclick = () => finish(true);
    panel.querySelector("[data-cancel-undo]").onclick = () => finish(false);
  });
}

function updateWithImpactPreview(url, payload) {
  const assignment = url.match(/\/assignments\/(\d+)$/), entity = url.match(/\/entity\/([^/]+)\/(\d+)$/);
  if (!assignment && !entity) throw new Error("Thao tác sửa chưa được hỗ trợ.");
  return runProjectChange({kind: assignment ? "assignment" : "entity", entity_type: assignment ? "assignment" : entity[1],
    entity_id: Number(assignment ? assignment[1] : entity[2]), expected_token: payload.expected_token,
    values: payload.data || payload});
}
