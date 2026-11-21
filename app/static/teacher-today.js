(() => {
  const panel = document.getElementById("teacherToday");
  const picker = document.getElementById("teacherTodaySelect");
  const dateLabel = document.getElementById("teacherTodayDate");
  const result = document.getElementById("teacherTodayResult");
  const dateFormat = new Intl.DateTimeFormat("vi-VN", {
    timeZone: "UTC",
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
  const storageKey = `smart_tkb_today_teacher:${panel.dataset.userId}:${data.project.id}`;
  let selectedId = "";
  try {
    selectedId = localStorage.getItem(storageKey) || "";
  } catch {
    // The selector still works when the browser blocks storage.
  }

  function normalizeName(name) {
    return String(name || "").normalize("NFC").trim().replace(/\s+/g, " ").toLocaleLowerCase("vi-VN");
  }

  function updatePicker() {
    const teachers = [...data.teachers].sort((a, b) => a.name.localeCompare(b.name, "vi"));
    if (!teachers.some(teacher => String(teacher.id) === selectedId)) {
      const accountName = normalizeName(panel.dataset.userName);
      const matches = teachers.filter(teacher => normalizeName(teacher.name) === accountName);
      selectedId = matches.length === 1 ? String(matches[0].id) : "";
    }
    picker.replaceChildren(new Option("Chọn giáo viên", ""));
    picker.options[0].disabled = true;
    for (const teacher of teachers) {
      const shortName = teacher.short_name;
      const label = shortName && shortName !== teacher.name ? `${teacher.name} (${shortName})` : teacher.name;
      picker.add(new Option(label, String(teacher.id)));
    }
    picker.value = selectedId;
    picker.disabled = teachers.length === 0;
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function render() {
    const date = new Date(`${dateLabel.dateTime}T00:00:00Z`);
    dateLabel.textContent = dateFormat.format(date);
    const weekday = (date.getUTCDay() + 6) % 7;
    const { days, sessions, periods } = data.project;
    const firstSlot = weekday * sessions * periods;
    const nextDaySlot = firstSlot + sessions * periods;
    const assignments = new Map(data.assignments
      .filter(assignment => String(assignment.teacher_id) === selectedId)
      .map(assignment => [assignment.id, assignment]));
    const lessons = weekday < days ? data.lessons
      .filter(lesson => lesson.slot >= firstSlot && lesson.slot < nextDaySlot && assignments.has(lesson.assignment_id))
      .sort((a, b) => a.slot - b.slot) : [];

    result.replaceChildren();
    if (!lessons.length) {
      let message = "Giáo viên này không có tiết dạy hôm nay.";
      if (weekday >= days) message = "Bộ thời khóa biểu này không có tiết học hôm nay.";
      else if (picker.disabled) message = "Bộ thời khóa biểu này chưa có giáo viên.";
      else if (!selectedId) message = "Chọn giáo viên để xem các tiết dạy hôm nay.";
      result.append(element("p", message, "teacher-today-message muted"));
      return;
    }

    let lastSession = -1;
    let list;
    for (const lesson of lessons) {
      const offset = lesson.slot - firstSlot;
      const session = Math.floor(offset / periods);
      if (session !== lastSession) {
        lastSession = session;
        const group = element("div");
        if (sessions > 1) group.append(element("h3", session === 0 ? "Buổi sáng" : "Buổi chiều", "teacher-today-session"));
        list = element("ol", "", "teacher-today-list");
        list.setAttribute("role", "list");
        group.append(list);
        result.append(group);
      }
      const assignment = assignments.get(lesson.assignment_id);
      const row = element("li");
      const lessonInfo = element("div");
      lessonInfo.append(element("strong", assignment.subject_name), element("small", assignment.class_name, "muted"));
      row.append(element("span", `Tiết ${offset % periods + 1}`, "teacher-today-period"), lessonInfo);
      list.append(row);
    }
  }

  picker.addEventListener("change", () => {
    selectedId = picker.value;
    try {
      localStorage.setItem(storageKey, selectedId);
    } catch {
      // The selection still applies to the current page.
    }
    render();
  });
  window.addEventListener("schedule-data-updated", event => {
    if (event.detail?.revoked) {
      panel.hidden = true;
      picker.replaceChildren();
      result.replaceChildren();
      return;
    }
    updatePicker();
    render();
  });
  window.addEventListener("vietnam-date-changed", event => {
    if (panel.hidden || event.detail === dateLabel.dateTime) return;
    dateLabel.dateTime = event.detail;
    render();
  });

  updatePicker();
  render();
})();
