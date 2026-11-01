"use strict";
// Saved only for the current signed-in account, through the application's DB.
// Changing a file never removes saved rules without explicit confirmation.
let scheduleAuditSavedProfile = null;
let scheduleAuditLimitsDirty = false;
let scheduleAuditLimitsNotice = "";
let scheduleAuditSavedBusy = false;
let weeklyCatalogPromptCancel = null;

function weeklyCatalogFromReport(report) {
  const records = {classes: new Map(), subjects: new Map(), teachers: new Map()};
  const insert = (kind, raw) => {
    const label = kind === "subjects" ? weeklyCanonicalSubject(raw) : String(raw || "").trim();
    if (!label) return;
    if (kind === "teachers" && scheduleAuditIsUnknownTeacher(label)) return;
    if (kind === "subjects" && scheduleAuditIsUnknownSubject(label)) return;
    const key = kind === "subjects" ? weeklySubjectCode(label) : scheduleAuditEntityKey(label);
    if (key && !records[kind].has(key)) records[kind].set(key, label);
  };
  for (const cls of report?.viewer?.classes || []) insert("classes", cls.name);
  for (const cell of report?.viewer?.cells || []) {
    insert("classes", cell.class_name);
    insert("teachers", cell.teacher_name);
  }
  records.subjects = weeklyImportedSubjectNames(report);
  return Object.fromEntries(Object.entries(records).map(([type, map]) => [type,
    [...map.values()].sort((a,b) => a.localeCompare(b,"vi",{numeric:true}))]));
}
function weeklyCatalogChanges(previous, next) {
  const changes = {};
  for (const type of ["classes", "subjects", "teachers"]) {
    const normalize = names => {
      return new Map(names.map(name => [type === "subjects" ? weeklySubjectCode(name) : scheduleAuditEntityKey(name), name]));
    };
    const before = normalize(previous?.[type] || []);
    const after = normalize(next?.[type] || []);
    changes[type] = {
      removed: [...before].filter(([key]) => !after.has(key)).map(([,name]) => name),
      added: [...after].filter(([key]) => !before.has(key)).map(([,name]) => name)
    };
  }
  return changes;
}
function weeklyChangesExist(changes) {
  return Object.values(changes).some(x => x.added.length || x.removed.length);
}
function weeklyRowKey(type, row) {
  const key = scheduleAuditEntityKey;
  if (type === "class_subject") return `${String(row.grade || "").trim()}|${weeklySubjectCode(row.subject)}`;
  return `${key(row.teacher)}|${key(row.class_name)}|${weeklySubjectCode(row.subject)}`;
}
// Detect incompatible quotas in old drafts that used multiple names for one
// subject. Such values must be reviewed before a canonicalized draft is saved.
function weeklySavedAliasConflicts(saved) {
  const conflicts = [];
  for (const type of WEEKLY_LIMIT_TYPES) {
    const groups = new Map();
    for (const row of saved?.[type] || []) {
      if (!weeklyHasPeriods(row.periods)) continue;
      const key = weeklyRowKey(type, row);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    }
    for (const rows of groups.values()) {
      if (new Set(rows.map(row => Number(row.periods))).size > 1) {
        const first = rows[0];
        const place = type === "class_subject" ? `khối ${first.grade}` : `${first.teacher} - ${first.class_name}`;
        conflicts.push(`${place}, ${rows.map(row => `${row.subject}: ${row.periods} tiết`).join(" / ")}`);
      }
    }
  }
  return conflicts;
}
function weeklyRawSubjectLabel(value) {
  return String(value || "").normalize("NFC").trim().toLocaleLowerCase("vi-VN")
    .replace(/\s+/g, " ").replace(/\s*\(\s*/g, "(").replace(/\s*\)\s*/g, ")");
}
function weeklyMergeLimits(saved, generated, catalog, removeMissing, previousCatalog = null) {
  const kept = {}, subjects = new Set(catalog.subjects.map(weeklySubjectCode)),
    teachers = new Set(catalog.teachers.map(scheduleAuditEntityKey)),
    classes = new Set(catalog.classes.map(scheduleAuditEntityKey)),
    grades = new Set(catalog.classes.map(x => (String(x).match(/^(1[0-2]|[1-9])[a-z]/i) || [])[1]).filter(Boolean));
  const currentSubjectLabels = new Map((catalog.subjects || [])
    .map(name => [weeklySubjectCode(name), name]));
  const valid = (type, row) => !removeMissing || (
    type === "class_subject" ? subjects.has(weeklySubjectCode(row.subject)) && grades.has(String(row.grade || "").trim()) :
    teachers.has(scheduleAuditEntityKey(row.teacher)) &&
    subjects.has(weeklySubjectCode(row.subject)) && classes.has(scheduleAuditEntityKey(row.class_name)));
  for (const type of WEEKLY_LIMIT_TYPES) {
    const rows = new Map();
    for (const source of saved?.[type] || []) {
      const targetLabel = currentSubjectLabels.get(weeklySubjectCode(source.subject));
      const row = {...source, subject:weeklyCanonicalSubject(targetLabel || source.subject),
                   periods:source.periods ?? ""};
      if (!valid(type, row)) continue;
      const key = weeklyRowKey(type, row);
      const existing = rows.get(key);
      const sourceExact = weeklyRawSubjectLabel(source.subject) === weeklyRawSubjectLabel(targetLabel);
      if (!existing) {
        rows.set(key, {...row, _exact:sourceExact});
      } else {
        // An explicitly entered quota beats a blank one; among conflicting
        // values prefer the official subject label from the school catalog.
        const filled = weeklyHasPeriods(row.periods), oldFilled = weeklyHasPeriods(existing.periods);
        if ((filled && !oldFilled) || (filled === oldFilled && sourceExact && !existing._exact))
          rows.set(key, {...row, _exact:sourceExact});
      }
    }
    for (const source of generated?.[type] || []) {
      const key = weeklyRowKey(type, source);
      if (!rows.has(key)) rows.set(key, {...source, subject:weeklyCanonicalSubject(source.subject), periods:source.periods ?? ""});
    }
    kept[type] = [...rows.values()].map(({_exact, ...row}) => row);
  }
  return kept;
}
function weeklyCountRemovedRows(saved, updated) {
  let amount = 0;
  for (const type of WEEKLY_LIMIT_TYPES) {
    const next = new Map();
    for (const row of updated?.[type] || []) {
      const key = weeklyRowKey(type, row);
      next.set(key, (next.get(key) || 0) + 1);
    }
    for (const row of saved?.[type] || []) {
      const key = weeklyRowKey(type, row), keep = next.get(key) || 0;
      if (keep) next.set(key, keep - 1);
      else amount++;
    }
  }
  return amount;
}
function weeklyChangeList(title, values) {
  if (!values.length) return "";
  return `<p><b>${esc(title)} (${values.length}):</b> ${values.slice(0, 18).map(esc).join(", ")}${values.length > 18 ? ` và ${values.length - 18} mục khác` : ""}</p>`;
}
function promptWeeklyCatalogReplace(changes, removedCount, conflicts = []) {
  const titles = {classes: "Lớp", subjects: "Môn", teachers: "Giáo viên"};
  const detail = Object.entries(changes).map(([type, x]) =>
    weeklyChangeList(`${titles[type]} không còn trong TKB mới`, x.removed) +
    weeklyChangeList(`${titles[type]} mới`, x.added)).join("");
  return new Promise(resolve => {
    weeklyCatalogPromptCancel?.();
    const overlay = document.createElement("div");
    overlay.id = "weeklyCatalogDialog";
    overlay.className = "weekly-catalog-overlay";
    overlay.innerHTML = `<div class="weekly-catalog-dialog" role="dialog" aria-modal="true" aria-labelledby="weeklyCatalogTitle">
      <h2 id="weeklyCatalogTitle">TKB mới khác dữ liệu định mức đã lưu</h2>
      <p>Hệ thống đã kiểm tra trùng lịch của file mới. Danh sách lớp, môn hoặc giáo viên có thay đổi:</p>
      <div class="weekly-catalog-diff">${detail}</div>
      ${conflicts.length ? `<p class="weekly-catalog-warning"><b>Cùng một môn đang có nhiều mức tiết khác nhau (${conflicts.length}):</b> ${conflicts.slice(0, 10).map(esc).join("; ")}. Kiểm tra trước khi xác nhận.</p>` : ""}
      <p><b>Nếu xác nhận thay thế:</b> giữ nguyên số tiết đã nhập của mục còn tồn tại, thêm mục mới với ngưỡng trống và xóa hoặc gộp ${removedCount} dòng định mức không còn phù hợp (bao gồm tên môn trùng).</p>
      <p class="weekly-catalog-warning">Hãy bảo đảm TKB mới đã có đủ các lớp và môn trước khi tiếp tục. Chỉ số tiết đã khai báo được cập nhật; danh sách chính của trường không bị xóa.</p>
      <div class="weekly-catalog-actions">
        <button type="button" class="btn ghost" data-decision="keep">Giữ ngưỡng cũ</button>
        <button type="button" class="btn" data-decision="replace">Xác nhận thay thế và xóa mục cũ</button>
      </div>
    </div>`;
    let completed = false;
    const finish = (accepted) => {
      if (completed) return;
      completed = true;
      weeklyCatalogPromptCancel = null;
      document.removeEventListener("keydown", onKey);
      overlay.remove();
      resolve(accepted);
    };
    weeklyCatalogPromptCancel = () => finish(false);
    const onKey = event => { if (event.key === "Escape") finish(false); };
    overlay.querySelector('[data-decision="keep"]').addEventListener("click", () => finish(false));
    overlay.querySelector('[data-decision="replace"]').addEventListener("click", () => finish(true));
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    overlay.querySelector('[data-decision="keep"]').focus();
  });
}
async function weeklyStoreProfile(limits, catalog, revision) {
  const response = await fetch("/api/schedule-audit/limits", {
    method: "PUT", headers: operationHeaders({"Content-Type": "application/json"}),
    body: JSON.stringify({limits, catalog, revision})
  });
  const result = await readAuditResponse(response);
  if (!response.ok || !result.ok) throw new Error(auditErrorMessage(result, response.status, "Không thể lưu số tiết. Hãy thử lại."));
  return result.profile;
}
async function restoreSavedWeeklyLimits(report, runId) {
  const response = await fetch("/api/schedule-audit/limits", {headers: operationHeaders()});
  const data = await readAuditResponse(response);
  if (runId !== scheduleAuditRunId || report !== scheduleAuditLastReport) return;
  if (!response.ok || !data.ok) throw new Error(auditErrorMessage(data, response.status, "Không lấy được số tiết đã lưu. Hãy thử lại."));
  const newCatalog = weeklyCatalogFromReport(report);
  const proposed = weeklyMakeLimitDraft(report);
  const profile = data.profile;
  scheduleAuditSavedProfile = profile;
  if (!profile) {
    scheduleAuditWorkloadLimits = weeklyNormalizeLimitDraft(proposed);
    scheduleAuditLimitsNotice = "Bạn chưa lưu số tiết quy định. Hãy nhập số tiết và bấm Lưu để dùng lại ở các lần kiểm tra sau.";
    return;
  }
  const diff = weeklyCatalogChanges(profile.catalog, newCatalog);
  const conflicts = weeklySavedAliasConflicts(profile.limits);
  const conflictWarning = conflicts.length
    ? `Cảnh báo: ${conflicts.length} định mức cũ của cùng một môn khác số tiết. ` +
      `Hãy kiểm tra lại các dòng: ${conflicts.slice(0, 4).join("; ")}. ` +
      `Hệ thống ưu tiên tên đang dùng trên TKB, chưa tự lưu thay đổi này.`
    : "";
  if (!weeklyChangesExist(diff)) {
    scheduleAuditWorkloadLimits = weeklyMergeLimits(profile.limits, proposed, newCatalog, false);
    scheduleAuditLimitsNotice = conflictWarning || "Đã lấy số tiết bạn lưu trước đó. Những tên khác nhau của cùng một môn đã được nhận diện chung.";
    scheduleAuditLimitsDirty = !!conflicts.length;
    return;
  }
  const updated = weeklyMergeLimits(profile.limits, proposed, newCatalog, true, profile.catalog);
  const toRemove = weeklyCountRemovedRows(profile.limits, updated);
  const confirmed = await promptWeeklyCatalogReplace(diff, toRemove, conflicts);
  if (runId !== scheduleAuditRunId || report !== scheduleAuditLastReport) return;
  if (!confirmed) {
    scheduleAuditWorkloadLimits = weeklyMergeLimits(profile.limits, proposed, newCatalog, false);
    scheduleAuditLimitsNotice = conflictWarning || "Đã giữ thông tin đã lưu. Không có môn, giáo viên hoặc số tiết nào bị xóa.";
    scheduleAuditLimitsDirty = !!conflicts.length;
    return;
  }
  try {
    scheduleAuditSavedProfile = await weeklyStoreProfile(updated, newCatalog, profile.revision);
    scheduleAuditWorkloadLimits = weeklyMergeLimits(scheduleAuditSavedProfile.limits, proposed, newCatalog, false);
    scheduleAuditLimitsDirty = false;
    scheduleAuditLimitsNotice = (conflicts.length ? `Đã thay thế với ${conflicts.length} định mức cần kiểm tra lại. ` : "") +
      `Đã cập nhật bộ ngưỡng theo TKB mới, xóa ${toRemove} dòng cũ; các mức còn phù hợp vẫn được giữ lại.`;
  } catch (error) {
    scheduleAuditWorkloadLimits = updated;
    scheduleAuditLimitsDirty = true;
    scheduleAuditLimitsNotice = "Chưa lưu được thay đổi. Hãy bấm Lưu số tiết để thử lại.";
    scheduleAuditWorkloadError = error.message || "Không thể lưu số tiết. Hãy thử lại.";
  }
}
async function saveScheduleAuditWorkloadLimits() {
  if (!scheduleAuditWorkloadLimits || !scheduleAuditLastReport || scheduleAuditSavedBusy) return;
  scheduleAuditSavedBusy = true;
  scheduleAuditWorkloadError = "";
  const current = scheduleAuditLastReport, editId = scheduleAuditWorkloadCheckId;
  const catalog = weeklyCatalogFromReport(current);
  try {
    const saved = await weeklyStoreProfile(weeklyNormalizeLimitDraft(scheduleAuditWorkloadLimits), catalog, scheduleAuditSavedProfile?.revision || 0);
    if (current !== scheduleAuditLastReport) return;
    scheduleAuditSavedProfile = saved;
    scheduleAuditLimitsDirty = editId !== scheduleAuditWorkloadCheckId;
    scheduleAuditLimitsNotice = scheduleAuditLimitsDirty ? "Đã lưu phiên bản trước; bạn còn thay đổi chưa được lưu." : "Đã lưu số tiết. Khi kiểm tra TKB khác, bạn có thể dùng lại những số tiết này.";
  } catch (error) {
    scheduleAuditWorkloadError = error.message || "Không thể lưu số tiết. Hãy thử lại.";
  } finally {
    scheduleAuditSavedBusy = false;
    if (current === scheduleAuditLastReport) redrawScheduleAuditWorkload();
  }
}

// Reset the quota editor, not the timetable and not the school's master data.
// Persist only after an explicit confirmation; on failure retain existing data.
async function clearAllScheduleAuditWorkloadLimits() {
  const report = scheduleAuditLastReport;
  if (!report || !scheduleAuditWorkloadLimits || scheduleAuditSavedBusy) return;
  const enteredClasses = (scheduleAuditWorkloadLimits.class_subject || []).filter(x => weeklyHasPeriods(x.periods)).length;
  const enteredAssignments = (scheduleAuditWorkloadLimits.assignments || []).filter(x => weeklyHasPeriods(x.periods)).length;
  const message = `Xóa toàn bộ định mức đã khai báo?\n\n` +
    `• ${enteredClasses} ô số tiết theo khối/môn\n` +
    `• ${enteredAssignments} phân công giáo viên đã nhập tiết\n\n` +
    `Dữ liệu sẽ bị xóa khỏi tài khoản. Danh sách môn, lớp và giáo viên nhận diện từ TKB vẫn được giữ để nhập lại. File TKB và kết quả kiểm tra trùng lịch không bị xóa.`;
  if (!window.confirm(message)) return;
  const cleared = weeklyMakeLimitDraft(report);
  const revision = scheduleAuditSavedProfile?.revision || 0;
  const editId = ++scheduleAuditWorkloadCheckId;
  // Invalidate an in-flight workload check without leaving its busy flag stuck.
  scheduleAuditWorkloadBusy = false;
  scheduleAuditSavedBusy = true;
  scheduleAuditWorkloadError = '';
  redrawScheduleAuditWorkload();
  try {
    const profile = await weeklyStoreProfile(cleared, weeklyCatalogFromReport(report), revision);
    if (report !== scheduleAuditLastReport) return;
    scheduleAuditSavedProfile = profile;
    if (editId !== scheduleAuditWorkloadCheckId) {
      scheduleAuditLimitsDirty = true;
      scheduleAuditLimitsNotice = 'Đã đặt lại dữ liệu lưu; bạn còn thay đổi mới chưa lưu trên màn hình.';
      return;
    }
    scheduleAuditWorkloadLimits = weeklyNormalizeLimitDraft(cleared);
    scheduleAuditWorkloadOpen = true;
    scheduleAuditTeacherOpen = false;
    scheduleAuditLimitsDirty = false;
    scheduleAuditLimitsNotice = 'Đã xóa tất cả số tiết và phân công tự thêm trong bộ định mức đã lưu. Bạn có thể nhập lại từ đầu.';
    report.workload = null;
  } catch (error) {
    if (report !== scheduleAuditLastReport) return;
    scheduleAuditWorkloadError = error.message || 'Không xóa được dữ liệu đã lưu.';
    scheduleAuditLimitsNotice = 'Chưa xác nhận được việc xóa. Hãy tải lại trang để kiểm tra số tiết đã lưu trước khi thử lại.';
    scheduleAuditWorkloadOpen = true;
  } finally {
    scheduleAuditSavedBusy = false;
    if (report === scheduleAuditLastReport) redrawScheduleAuditWorkload();
  }
}
