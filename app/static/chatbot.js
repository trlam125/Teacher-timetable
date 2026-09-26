(() => {
  async function readChatbotResponse(response) {
    const raw = await response.text();
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch (error) {
      const statusLabel = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
      if (!response.ok)
        return { detail: `Máy chủ trả về lỗi ${statusLabel} nhưng phản hồi không phải JSON hợp lệ.` };
      const invalid = new Error(`Phản hồi chatbot không hợp lệ (${statusLabel}).`);
      invalid.cause = error;
      invalid.isInvalidServerResponse = true;
      throw invalid;
    }
  }

  const projectId = window.CHATBOT_PROJECT_ID;
  const form = document.querySelector("#chatForm");
  if (!form || !projectId) return;

  const input = document.querySelector("#chatInput");
  const fileInput = document.querySelector("#chatFile");
  const messages = document.querySelector("#chatMessages");
  const sendButton = document.querySelector("#sendChat");
  const filePreview = document.querySelector("#filePreview");
  const fileName = document.querySelector("#fileName");
  const removeFile = document.querySelector("#removeFile");
  const clearChat = document.querySelector("#clearChat");
  const popup = document.querySelector("#chatbotPopup");
  const fab = document.querySelector("#chatbotFab");
  const closeButton = document.querySelector("#chatbotClose");
  const minimizeButton = document.querySelector("#chatbotMinimize");
  const popupStatus = document.querySelector(".chatbot-popup-status");
  const pageStatus = document.querySelector(".chatbot-status");
  const history = [];
  let documentContext = [];

  let requestVersion = 0;
  let activeController = null;
  let activeModel =
    String(window.CHATBOT_PRIMARY_MODEL || "gemini-3.7-flash").trim() ||
    "gemini-3.7-flash";

  const escapeHtml = (value) =>
    String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  function setConnectionState(connected) {
    const status = popupStatus || pageStatus;
    if (!status) return;
    status.classList.toggle("is-ready", connected);
    status.classList.toggle("is-offline", !connected);
    status.textContent = connected
      ? "Sẵn sàng hỗ trợ"
      : "Không thể kết nối tới chatbot";
  }

  function renderInline(text) {
    let source = String(text ?? "");
    const protectedParts = [];
    const protect = (html) => {
      const token = `@@INLINE_${protectedParts.length}@@`;
      protectedParts.push(html);
      return token;
    };

    source = source.replace(/<br\s*\/?>/gi, () => protect("<br>"));
    source = source.replace(/`([^`\n]+)`/g, (_, code) =>
      protect(`<code>${escapeHtml(code)}</code>`),
    );
    source = source.replace(
      /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
      (_, label, url) => {
        return protect(
          `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`,
        );
      },
    );

    let safe = escapeHtml(source);
    safe = safe.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    safe = safe.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
    safe = safe.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    safe = safe.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");

    protectedParts.forEach((html, index) => {
      safe = safe.replaceAll(`@@INLINE_${index}@@`, html);
    });
    return safe;
  }

  function splitTableRow(line) {
    let value = String(line).trim();
    if (value.startsWith("|")) value = value.slice(1);
    if (value.endsWith("|") && !value.endsWith("\\|"))
      value = value.slice(0, -1);

    const cells = [];
    let cell = "";
    for (let index = 0; index < value.length; index += 1) {
      const char = value[index];
      const next = value[index + 1];
      if (char === "\\" && next === "|") {
        cell += "|";
        index += 1;
      } else if (char === "|") {
        cells.push(cell.trim());
        cell = "";
      } else {
        cell += char;
      }
    }
    cells.push(cell.trim());
    return cells;
  }

  function isTableSeparator(line) {
    const cells = splitTableRow(line);
    return (
      cells.length > 0 && cells.every((cell) => /^:?-{2,}:?$/.test(cell.trim()))
    );
  }

  function tableAlignment(separatorCell) {
    const value = separatorCell.trim();
    if (value.startsWith(":") && value.endsWith(":")) return "center";
    if (value.endsWith(":")) return "right";
    return "left";
  }

  function renderTable(headerLine, separatorLine, bodyLines) {
    const headers = splitTableRow(headerLine);
    const separators = splitTableRow(separatorLine);
    const alignments = headers.map((_, index) =>
      tableAlignment(separators[index] || "---"),
    );
    const rows = bodyLines.map(splitTableRow);

    const head = headers
      .map(
        (cell, index) =>
          `<th class="align-${alignments[index]}">${renderInline(cell)}</th>`,
      )
      .join("");

    const body = rows
      .map((row) => {
        const cells = headers
          .map(
            (_, index) =>
              `<td class="align-${alignments[index]}">${renderInline(row[index] || "")}</td>`,
          )
          .join("");
        return `<tr>${cells}</tr>`;
      })
      .join("");

    return `<div class="message-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function listIndent(raw) {
    return raw.replace(/\t/g, "    ").length;
  }

  function parseListItem(line) {
    const match = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.+)$/);
    if (!match) return null;
    const ordered = /^\d/.test(match[2]);
    return {
      indent: listIndent(match[1]),
      type: ordered ? "ol" : "ul",
      start: ordered ? Number.parseInt(match[2], 10) : null,
      content: match[3],
    };
  }

  function renderListSequence(items, startIndex, baseIndent) {
    let index = startIndex;
    let html = "";

    while (index < items.length && items[index].indent === baseIndent) {
      const type = items[index].type;
      const start =
        type === "ol" &&
          Number.isFinite(items[index].start) &&
          items[index].start > 1
          ? ` start="${items[index].start}"`
          : "";
      html += `<${type}${start}>`;

      while (index < items.length) {
        const item = items[index];
        if (
          item.indent < baseIndent ||
          item.indent > baseIndent ||
          item.type !== type
        )
          break;

        html += `<li>${renderInline(item.content)}`;
        index += 1;

        while (index < items.length && items[index].indent > baseIndent) {
          const nestedIndent = items[index].indent;
          const nested = renderListSequence(items, index, nestedIndent);
          html += nested.html;
          index = nested.index;
        }
        html += "</li>";
      }
      html += `</${type}>`;
    }

    return { html, index };
  }

  function renderListItems(items) {
    if (!items.length) return "";
    let index = 0;
    let html = "";
    while (index < items.length) {
      const rendered = renderListSequence(items, index, items[index].indent);
      html += rendered.html;
      if (rendered.index <= index) break;
      index = rendered.index;
    }
    return html;
  }

  function isListContinuationBoundary(lines, index) {
    const trimmed = String(lines[index] || "").trim();
    if (!trimmed) return false;
    if (/^@@CODEBLOCK_\d+@@$/.test(trimmed)) return true;
    if (
      /^(#{1,3})\s+/.test(trimmed) ||
      /^---+$/.test(trimmed) ||
      /^>\s?/.test(trimmed)
    )
      return true;
    return (
      index + 1 < lines.length &&
      lines[index].includes("|") &&
      isTableSeparator(lines[index + 1])
    );
  }

  function collectListBlock(lines, startIndex) {
    const items = [];
    let index = startIndex;

    while (index < lines.length) {
      const parsed = parseListItem(lines[index]);
      if (parsed) {
        items.push(parsed);
        index += 1;
        continue;
      }

      const trimmed = String(lines[index] || "").trim();
      if (!trimmed) {
        let nextIndex = index + 1;
        while (
          nextIndex < lines.length &&
          !String(lines[nextIndex] || "").trim()
        )
          nextIndex += 1;
        if (nextIndex < lines.length && parseListItem(lines[nextIndex])) {
          index = nextIndex;
          continue;
        }
        break;
      }

      if (!items.length || isListContinuationBoundary(lines, index)) break;

      // Smaller models sometimes wrap a long list item onto a new physical line
      // without repeating the list marker. Keep that text inside the same <li>.
      items[items.length - 1].content += ` ${trimmed}`;
      index += 1;
    }

    return { html: renderListItems(items), index };
  }

  function renderMarkdown(markdown) {
    const source = String(markdown || "").replace(/\r\n?/g, "\n");
    const codeBlocks = [];
    const protectedSource = source.replace(
      /```[^\n]*\n?([\s\S]*?)```/g,
      (_, code) => {
        const token = `@@CODEBLOCK_${codeBlocks.length}@@`;
        codeBlocks.push(
          `<pre><code>${escapeHtml(code.replace(/\n$/, ""))}</code></pre>`,
        );
        return `\n${token}\n`;
      },
    );

    const lines = protectedSource.split("\n");
    const out = [];
    let paragraph = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      out.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
      paragraph = [];
    };

    for (let index = 0; index < lines.length;) {
      const raw = lines[index];
      const line = raw.trimEnd();
      const trimmed = line.trim();

      if (!trimmed) {
        flushParagraph();
        index += 1;
        continue;
      }

      if (/^@@CODEBLOCK_\d+@@$/.test(trimmed)) {
        flushParagraph();
        out.push(trimmed);
        index += 1;
        continue;
      }

      if (
        index + 1 < lines.length &&
        line.includes("|") &&
        isTableSeparator(lines[index + 1])
      ) {
        flushParagraph();
        const bodyLines = [];
        let bodyIndex = index + 2;
        while (bodyIndex < lines.length) {
          const candidate = lines[bodyIndex];
          if (
            !candidate.trim() ||
            !candidate.includes("|") ||
            parseListItem(candidate)
          )
            break;
          bodyLines.push(candidate);
          bodyIndex += 1;
        }
        out.push(renderTable(line, lines[index + 1], bodyLines));
        index = bodyIndex;
        continue;
      }

      const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        const level = heading[1].length;
        out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }

      if (/^---+$/.test(trimmed)) {
        flushParagraph();
        out.push("<hr>");
        index += 1;
        continue;
      }

      if (parseListItem(line)) {
        flushParagraph();
        const rendered = collectListBlock(lines, index);
        out.push(rendered.html);
        index = rendered.index;
        continue;
      }

      const quote = trimmed.match(/^>\s?(.*)$/);
      if (quote) {
        flushParagraph();
        const quoteLines = [];
        while (index < lines.length) {
          const current = lines[index].trim().match(/^>\s?(.*)$/);
          if (!current) break;
          quoteLines.push(current[1]);
          index += 1;
        }
        out.push(
          `<blockquote>${renderInline(quoteLines.join(" "))}</blockquote>`,
        );
        continue;
      }

      paragraph.push(trimmed);
      index += 1;
    }

    flushParagraph();
    let html = out.join("");
    codeBlocks.forEach((block, index) => {
      html = html.replaceAll(`@@CODEBLOCK_${index}@@`, block);
    });
    return html;
  }

  let isChatbotAnimating = false;

  function setPopup(open) {
    if (!popup || !fab) return;
    popup.classList.toggle("is-open", open);
    popup.setAttribute("aria-hidden", String(!open));
    fab.setAttribute("aria-expanded", String(open));
    fab.classList.toggle("is-glowing", open);
    if (open) {
      document.getElementById("generalChatFab")?.classList.remove("is-glowing");
      requestAnimationFrame(() => input?.focus());
    }
  }

  function closeChatbotWithoutUndock() {
    if (!popup?.classList.contains("is-open")) return;
    if (window.FabMotion?.alignPopupToFab) {
      window.FabMotion.alignPopupToFab(popup, fab);
    }
    setPopup(false);
  }

  function getChatbotDockDeltaY() {
    const generalFab = document.getElementById("generalChatFab");
    if (!generalFab) return -64;
    const generalRect = generalFab.getBoundingClientRect();
    const fabRect = fab.getBoundingClientRect();
    const delta = generalRect.top - fabRect.top;
    return Math.round(delta) || -64;
  }

  function getChatbotTrail() {
    let trail = document.getElementById("chatbotTrail");
    if (!trail && fab) {
      trail = document.createElement("div");
      trail.id = "chatbotTrail";
      trail.className = "fab-trail-container chatbot-trail";
      trail.setAttribute("aria-hidden", "true");
      trail.innerHTML = `
        <div class="circle trail t4"></div>
        <div class="circle trail t3"></div>
        <div class="circle trail t2"></div>
        <div class="circle trail t1"></div>
      `;
      fab.insertAdjacentElement("beforebegin", trail);
    }
    return trail;
  }

  function dockUpChatbot(onTop = true) {
    return new Promise((resolve) => {
      const generalFab = document.getElementById("generalChatFab");
      if (!generalFab) {
        resolve();
        return;
      }

      const delta = getChatbotDockDeltaY();
      fab.style.setProperty("--cb-dock-y", `${delta}px`);
      const trail = getChatbotTrail();
      if (trail) {
        trail.style.setProperty("--cb-dock-y", `${delta}px`);
      }

      if (fab.classList.contains("is-docked")) {
        if (onTop) fab.classList.add("is-on-top");
        else fab.classList.remove("is-on-top");
        resolve();
        return;
      }

      if (onTop) fab.classList.add("is-on-top");
      else fab.classList.remove("is-on-top");

      fab.classList.remove("is-hidden", "is-sliding-down");
      if (trail) trail.classList.remove("is-sliding-down");

      void fab.offsetWidth;
      if (trail) void trail.offsetWidth;

      fab.classList.add("is-sliding-up");
      if (trail) trail.classList.add("is-sliding-up");

      let resolved = false;
      const done = () => {
        if (resolved) return;
        resolved = true;
        fab.removeEventListener("animationend", onEnd);
        clearTimeout(timer);
        fab.classList.remove("is-sliding-up");
        if (trail) trail.classList.remove("is-sliding-up");
        fab.classList.add("is-docked");
        resolve();
      };
      const onEnd = (e) => {
        if (e.target === fab && (e.animationName === "cb-move-up" || !e.animationName)) done();
      };
      fab.addEventListener("animationend", onEnd);
      const timer = setTimeout(done, 680);
    });
  }

  function dockDownChatbot() {
    return new Promise((resolve) => {
      const generalFab = document.getElementById("generalChatFab");
      const trail = getChatbotTrail();
      if (!generalFab || !fab.classList.contains("is-docked")) {
        fab.classList.remove("is-docked", "is-on-top", "is-sliding-up", "is-sliding-down");
        if (trail) trail.classList.remove("is-sliding-up", "is-sliding-down");
        resolve();
        return;
      }

      fab.classList.remove("is-hidden", "is-docked", "is-sliding-up");
      if (trail) trail.classList.remove("is-sliding-up");

      void fab.offsetWidth;
      if (trail) void trail.offsetWidth;

      fab.classList.add("is-sliding-down");
      if (trail) trail.classList.add("is-sliding-down");

      let resolved = false;
      const done = () => {
        if (resolved) return;
        resolved = true;
        fab.removeEventListener("animationend", onEnd);
        clearTimeout(timer);
        fab.classList.remove("is-on-top", "is-sliding-down");
        if (trail) trail.classList.remove("is-sliding-down");
        resolve();
      };
      const onEnd = (e) => {
        if (e.target === fab && (e.animationName === "cb-move-down" || !e.animationName)) done();
      };
      fab.addEventListener("animationend", onEnd);
      const timer = setTimeout(done, 680);
    });
  }

  async function openChatbotPopup() {
    if (isChatbotAnimating || popup?.classList.contains("is-open")) return;
    isChatbotAnimating = true;

    // Đóng hướng dẫn nếu đang mở mà không cần undock
    if (window.ContextHelpTour?.isOpen?.()) {
      if (window.ContextHelpTour.closeWithoutUndock) {
        window.ContextHelpTour.closeWithoutUndock();
      } else {
        window.ContextHelpTour.close(false);
      }
    }

    // Đóng khung chat chung nếu đang mở mà không cần undock
    if (window.GeneralChat?.isOpen?.()) {
      if (window.GeneralChat.closeWithoutUndock) {
        window.GeneralChat.closeWithoutUndock();
      } else {
        await window.GeneralChat.close();
      }
    }

    const generalFab = document.getElementById("generalChatFab");
    const helpFab = document.getElementById("helpTourFab");
    generalFab?.classList.remove("is-on-top", "is-glowing");
    helpFab?.classList.remove("is-on-top", "is-glowing");

    if (window.FabMotion) {
      fab?.classList.add("is-glowing");
      await window.FabMotion.open(fab, popup, {
        onOpened: () => {
          popup.setAttribute("aria-hidden", "false");
          fab?.setAttribute("aria-expanded", "true");
          requestAnimationFrame(() => input?.focus());
        }
      });
    } else {
      if (window.FabMotion?.alignPopupToFab) {
        window.FabMotion.alignPopupToFab(popup, fab);
      }
      fab?.classList.add("is-on-top");
      if (generalFab) {
        if (window.GeneralChat?.dockDown) {
          await window.GeneralChat.dockDown(false);
        }
      }
      setPopup(true);
    }

    isChatbotAnimating = false;
  }

  async function closeChatbotPopup() {
    if (isChatbotAnimating || !popup?.classList.contains("is-open")) return;
    isChatbotAnimating = true;

    if (window.FabMotion) {
      fab?.classList.remove("is-glowing");
      fab?.setAttribute("aria-expanded", "false");
      await window.FabMotion.close(fab, popup);
      popup.setAttribute("aria-hidden", "true");
    } else {
      if (window.FabMotion?.alignPopupToFab) {
        window.FabMotion.alignPopupToFab(popup, fab);
      }
      setPopup(false);
      fab?.classList.remove("is-on-top");
      if (window.GeneralChat?.dockUp) {
        await window.GeneralChat.dockUp();
      }
    }

    isChatbotAnimating = false;
  }

  window.toggleChatbotPopup = () =>
    popup?.classList.contains("is-open") ? closeChatbotPopup() : openChatbotPopup();

  window.ChatbotAssistant = {
    isOpen: () => popup?.classList.contains("is-open"),
    open: openChatbotPopup,
    close: closeChatbotPopup,
    closeWithoutUndock: closeChatbotWithoutUndock,
  };

  const handle = document.querySelector("#chatbotSheetHandle");
  handle?.addEventListener("click", () => closeChatbotPopup());
  fab?.addEventListener("click", () =>
    popup?.classList.contains("is-open") ? closeChatbotPopup() : openChatbotPopup()
  );
  closeButton?.addEventListener("click", () => closeChatbotPopup());
  minimizeButton?.addEventListener("click", () => closeChatbotPopup());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && popup?.classList.contains("is-open"))
      closeChatbotPopup();
  });
  document.addEventListener("click", (event) => {
    const generalFab = event.target.closest?.("#generalChatFab");
    const helpFab = event.target.closest?.("#helpTourFab");
    if ((generalFab || helpFab) && popup?.classList.contains("is-open")) {
      closeChatbotWithoutUndock();
    }
  }, true);

  function addMessage(role, content, extraClass = "") {
    const article = document.createElement("article");
    article.className = `chat-message ${role} ${extraClass}`.trim();
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = role === "assistant" ? "AI" : "Bạn";
    const body = document.createElement("div");
    body.className = "message-body";
    if (
      role === "assistant" &&
      !extraClass.includes("error") &&
      !extraClass.includes("chat-loading")
    ) {
      body.innerHTML = renderMarkdown(content);
    } else {
      body.textContent = content;
    }
    article.append(avatar, body);
    messages.appendChild(article);
    messages.scrollTop = messages.scrollHeight;
    return article;
  }


  function updateFilePreview() {
    const files = [...fileInput.files];
    filePreview.hidden = !files.length;
    fileName.textContent = files.length
      ? files
        .map((file) => `${file.name} · ${(file.size / 1024).toFixed(1)} KB`)
        .join(" · ")
      : "";
  }

  fileInput.addEventListener("change", () => {
    const files = [...fileInput.files];
    const allowedExtensions = [".docx", ".xlsx", ".csv", ".pdf"];
    const hasUnsupportedFile = files.some((file) => {
      const name = file.name.toLowerCase();
      return !allowedExtensions.some((extension) => name.endsWith(extension));
    });
    if (files.length > 3) {
      fileInput.value = "";
      addMessage("assistant", "Chỉ được đính kèm tối đa 3 tệp.", "error");
    } else if (hasUnsupportedFile) {
      fileInput.value = "";
      addMessage(
        "assistant",
        "Chỉ hỗ trợ tệp Word (.docx), Excel (.xlsx), CSV hoặc PDF.",
        "error",
      );
    } else if (files.some((file) => file.size > 5 * 1024 * 1024)) {
      fileInput.value = "";
      addMessage("assistant", "Mỗi tệp không được vượt quá 5 MB.", "error");
    } else if (
      files.reduce((total, file) => total + file.size, 0) >
      12 * 1024 * 1024
    ) {
      fileInput.value = "";
      addMessage(
        "assistant",
        "Tổng dung lượng tệp không được vượt quá 12 MB.",
        "error",
      );
    }
    updateFilePreview();
  });

  removeFile.addEventListener("click", () => {
    fileInput.value = "";
    updateFilePreview();
  });

  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.prompt;
      input.focus();
    });
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  clearChat.addEventListener("click", () => {
    requestVersion += 1;
    activeController?.abort();
    activeController = null;
    history.length = 0;
    documentContext = [];
    messages
      .querySelectorAll(
        ".chat-message.user,.chat-message.assistant:not(:first-child),.chat-loading",
      )
      .forEach((item) => item.remove());
    fileInput.value = "";
    updateFilePreview();
    sendButton.disabled = !window.CHATBOT_ENABLED;
    input.focus();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = input.value.trim();
    if (!prompt || sendButton.disabled) return;
    if (!window.CHATBOT_ENABLED) {
      setConnectionState(false);
      addMessage(
        "assistant",
        "Chatbot đang tạm ngừng hoặc chưa được cấu hình trên máy chủ.",
        "error",
      );
      return;
    }

    const selectedFiles = [...fileInput.files];
    const attachmentText = selectedFiles.length
      ? `\n\n📎 ${selectedFiles.map((file) => file.name).join(", ")}`
      : "";
    addMessage("user", `${prompt}${attachmentText}`);
    input.value = "";
    sendButton.disabled = true;
    const loading = addMessage(
      "assistant",
      "Đang đọc dữ liệu và phân tích…",
      "chat-loading",
    );

    const payload = new FormData();
    payload.append("message", prompt);
    payload.append("history_json", JSON.stringify(history.slice(-8)));
    payload.append("document_context_json", JSON.stringify(documentContext));
    payload.append("preferred_model", activeModel);
    selectedFiles.forEach((file) => payload.append("files", file));

    // Tệp đã được chụp vào FormData, nên xóa ngay khỏi bộ soạn thảo sau khi bấm Gửi.
    // File objects trong selectedFiles/FormData vẫn còn nguyên cho request hiện tại.
    fileInput.value = "";
    updateFilePreview();

    const currentVersion = ++requestVersion;
    const controller = new AbortController();
    activeController = controller;
    let timedOut = false;
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 150000);

    try {
      const response = await fetch(`/api/projects/${projectId}/chatbot`, {
        method: "POST",
        body: payload,
        signal: controller.signal,
        headers: {
          "X-Skip-Operation-Status": "1",
        },
      });
      const result = await readChatbotResponse(response);
      if (currentVersion !== requestVersion) return;

      loading.remove();
      if (!response.ok) {
        if (response.status === 401) {
          window.location.href = "/login";
          return;
        }
        setConnectionState(true);
        addMessage(
          "assistant",
          result.detail ||
          result.message ||
          `Máy chủ chatbot trả về lỗi HTTP ${response.status}.`,
          "error",
        );
        return;
      }

      setConnectionState(true);
      if (result.model_used) activeModel = String(result.model_used);
      if (Array.isArray(result.document_context))
        documentContext = result.document_context;
      addMessage("assistant", result.answer);
      history.push(
        { role: "user", content: prompt },
        { role: "assistant", content: result.answer },
      );
      if (history.length > 8) history.splice(0, history.length - 8);
    } catch (error) {
      if (currentVersion !== requestVersion) return;
      loading.remove();
      if (error?.name === "AbortError" && !timedOut) return;
      if (error?.isInvalidServerResponse) {
        setConnectionState(true);
        addMessage(
          "assistant",
          error.message || "Máy chủ chatbot trả về phản hồi không hợp lệ.",
          "error",
        );
      } else {
        setConnectionState(false);
        addMessage(
          "assistant",
          "Không thể kết nối tới chatbot. Vui lòng thử lại sau.",
          "error",
        );
      }
    } finally {
      window.clearTimeout(timeoutId);
      if (currentVersion === requestVersion) {
        activeController = null;
        sendButton.disabled = false;
        input.focus();
      }
    }
  });
})();

/* ==========================================================================
   3D SOCCER BALL MASCOT CONTROLLER (Trang trí Quả bóng đá 3D tương tác)
   - Truncated Icosahedron 3D Geometry (12 ngũ giác đen + 20 lục giác trắng)
   - Real-time 3D lighting, specular reflections & leather texture
   - Non-slip rolling physics following the chatbot border patrol
   - Free 3D drag/flick rotation with momentum
   - Interactive high kick / juggle with celebratory soccer quotes
   ========================================================================== */
function initSoccerBall3D() {
  const ballContainer =
    document.querySelector("#chatbotPet") ||
    document.querySelector(".chatbot-border-ball") ||
    document.querySelector(".chatbot-border-pet");
  if (!ballContainer || ballContainer.dataset.soccerBallInitialized) return;
  ballContainer.dataset.soccerBallInitialized = "true";

  const bubble =
    ballContainer.querySelector("#petBubble") ||
    ballContainer.querySelector(".ball-bubble") ||
    ballContainer.querySelector(".pet-bubble");
  const bubbleText = bubble ? bubble.querySelector(".pet-bubble-text") : null;
  const bubbleIcon = bubble ? bubble.querySelector(".pet-bubble-icon") : null;
  const canvas = ballContainer.querySelector("#chatbotBallCanvas") || ballContainer.querySelector("canvas");

  const soccerQuotes = [
    { icon: "⚽", text: "Vào ooo!" },
    { icon: "🎯", text: "Siêu phẩm!" },
    { icon: "🔥", text: "Sút cực căng!" },
    { icon: "✨", text: "Tâng bóng điệu nghệ!" },
    { icon: "🌟", text: "AI sẵn sàng kiến tạo!" },
    { icon: "🏆", text: "Bàn thắng vàng!" },
    { icon: "⚡", text: "Pha bóng đỉnh cao!" },
    { icon: "🥇", text: "Đỉnh nóc kịch trần!" },
  ];

  let bubbleTimeout = null;
  let quoteIndex = 0;

  function triggerKick(e) {
    if (e) {
      e.stopPropagation();
    }
    ballContainer.classList.remove("is-kicking", "is-petting");
    void ballContainer.offsetWidth;
    ballContainer.classList.add("is-kicking", "is-petting");

    // Add extra spin impulse on kick
    angularVelocityX += (Math.random() - 0.5) * 0.15;
    angularVelocityY += 0.35 + Math.random() * 0.15;

    setTimeout(() => {
      ballContainer.classList.remove("is-kicking", "is-petting");
    }, 720);

    // Show football emotion reaction bubble
    if (bubble && bubbleText && bubbleIcon) {
      const q = soccerQuotes[quoteIndex % soccerQuotes.length];
      quoteIndex++;
      bubbleIcon.textContent = q.icon;
      bubbleText.textContent = q.text;
      bubble.classList.add("is-active");

      clearTimeout(bubbleTimeout);
      bubbleTimeout = setTimeout(() => {
        bubble.classList.remove("is-active");
      }, 2400);
    }
  }

  ballContainer.addEventListener("click", triggerKick);
  ballContainer.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      triggerKick(e);
    }
  });

  // --- 3D GEOMETRY GENERATOR: Truncated Icosahedron (32 Faces) ---
  const phi = (1 + Math.sqrt(5)) / 2;
  const icoRaw = [];
  for (const s1 of [-1, 1]) {
    for (const s2 of [-1, 1]) {
      icoRaw.push([0, s1, s2 * phi]);
      icoRaw.push([s1, s2 * phi, 0]);
      icoRaw.push([s1 * phi, 0, s2]);
    }
  }
  function norm(v) {
    const l = Math.hypot(...v) || 1;
    return [v[0] / l, v[1] / l, v[2] / l];
  }
  const icoNorm = icoRaw.map(norm);

  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function cross(a, b) {
    return [
      a[1] * b[2] - a[2] * b[1],
      a[2] * b[0] - a[0] * b[2],
      a[0] * b[1] - a[1] * b[0]
    ];
  }

  const neighbors = Array.from({ length: 12 }, () => []);
  for (let i = 0; i < 12; i++) {
    for (let j = 0; j < 12; j++) {
      if (i !== j) {
        const d2 = (icoNorm[i][0] - icoNorm[j][0]) ** 2 +
          (icoNorm[i][1] - icoNorm[j][1]) ** 2 +
          (icoNorm[i][2] - icoNorm[j][2]) ** 2;
        if (d2 < 1.25) neighbors[i].push(j);
      }
    }
  }

  for (let i = 0; i < 12; i++) {
    const n = icoNorm[i];
    const refJ = neighbors[i][0];
    const refVec = norm(cross(n, [icoNorm[refJ][0] - n[0], icoNorm[refJ][1] - n[1], icoNorm[refJ][2] - n[2]]));
    const upVec = norm(cross(refVec, n));
    neighbors[i].sort((a, b) => {
      const va = [icoNorm[a][0] - n[0], icoNorm[a][1] - n[1], icoNorm[a][2] - n[2]];
      const vb = [icoNorm[b][0] - n[0], icoNorm[b][1] - n[1], icoNorm[b][2] - n[2]];
      return Math.atan2(dot(va, upVec), dot(va, refVec)) - Math.atan2(dot(vb, upVec), dot(vb, refVec));
    });
  }

  function interp(v1, v2, t) {
    return norm([
      v1[0] * (1 - t) + v2[0] * t,
      v1[1] * (1 - t) + v2[1] * t,
      v1[2] * (1 - t) + v2[2] * t
    ]);
  }

  const faces = [];
  // 12 Pentagons
  for (let i = 0; i < 12; i++) {
    const poly = neighbors[i].map(j => interp(icoNorm[i], icoNorm[j], 0.36));
    const c = norm(poly.reduce((acc, v) => [acc[0] + v[0] / 5, acc[1] + v[1] / 5, acc[2] + v[2] / 5], [0, 0, 0]));
    faces.push({ type: "pentagon", verts: poly, center: c });
  }

  // 20 Hexagons
  for (let i = 0; i < 12; i++) {
    for (const j of neighbors[i]) {
      for (const m of neighbors[j]) {
        if (neighbors[i].includes(m) && i < j && j < m) {
          const e1 = [icoNorm[j][0] - icoNorm[i][0], icoNorm[j][1] - icoNorm[i][1], icoNorm[j][2] - icoNorm[i][2]];
          const e2 = [icoNorm[m][0] - icoNorm[i][0], icoNorm[m][1] - icoNorm[i][1], icoNorm[m][2] - icoNorm[i][2]];
          const ccw = dot(cross(e1, e2), icoNorm[i]) > 0;
          const tri = ccw ? [i, j, m] : [i, m, j];
          const poly = [
            interp(icoNorm[tri[0]], icoNorm[tri[1]], 0.36),
            interp(icoNorm[tri[1]], icoNorm[tri[0]], 0.36),
            interp(icoNorm[tri[1]], icoNorm[tri[2]], 0.36),
            interp(icoNorm[tri[2]], icoNorm[tri[1]], 0.36),
            interp(icoNorm[tri[2]], icoNorm[tri[0]], 0.36),
            interp(icoNorm[tri[0]], icoNorm[tri[2]], 0.36)
          ];
          const c = norm(poly.reduce((acc, v) => [acc[0] + v[0] / 6, acc[1] + v[1] / 6, acc[2] + v[2] / 6], [0, 0, 0]));
          faces.push({ type: "hexagon", verts: poly, center: c });
        }
      }
    }
  }

  // --- 3D ROTATION MATRIX UTILITIES ---
  let rotMat = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1]
  ];

  function makeRotationMatrix(axis, angle) {
    const [x, y, z] = axis;
    const c = Math.cos(angle);
    const s = Math.sin(angle);
    const t = 1 - c;
    return [
      [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
      [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
      [t * x * z - s * y, t * y * z + s * x, t * z * z + c]
    ];
  }

  function multMat(a, b) {
    const res = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    for (let i = 0; i < 3; i++) {
      for (let j = 0; j < 3; j++) {
        res[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j];
      }
    }
    return res;
  }

  function multVec(m, v) {
    return [
      m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
      m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
      m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2]
    ];
  }

  // Initial stylish tilt
  rotMat = multMat(makeRotationMatrix([1, 0, 0], 0.2), rotMat);
  rotMat = multMat(makeRotationMatrix([0, 1, 0], 0.35), rotMat);

  let angularVelocityX = 0;
  let angularVelocityY = 0;
  let isDragging = false;
  let lastPointerX = 0;
  let lastPointerY = 0;
  let lastBallScreenX = null;
  let lastTimestamp = performance.now();

  // Pointer drag to spin ball freely
  ballContainer.addEventListener("pointerdown", (e) => {
    isDragging = true;
    lastPointerX = e.clientX;
    lastPointerY = e.clientY;
    angularVelocityX = 0;
    angularVelocityY = 0;
    ballContainer.setPointerCapture?.(e.pointerId);
  });

  ballContainer.addEventListener("pointermove", (e) => {
    if (!isDragging) return;
    const dx = e.clientX - lastPointerX;
    const dy = e.clientY - lastPointerY;
    lastPointerX = e.clientX;
    lastPointerY = e.clientY;

    const speed = Math.hypot(dx, dy);
    if (speed > 0.1) {
      angularVelocityX = (dy / speed) * Math.min(speed * 0.025, 0.4);
      angularVelocityY = (dx / speed) * Math.min(speed * 0.025, 0.4);

      const axis = norm([dy, dx, 0]);
      const angle = speed * 0.05;
      rotMat = multMat(makeRotationMatrix(axis, angle), rotMat);
    }
  });

  function stopDrag(e) {
    if (isDragging) {
      isDragging = false;
      try {
        ballContainer.releasePointerCapture?.(e.pointerId);
      } catch (_) { }
    }
  }

  ballContainer.addEventListener("pointerup", stopDrag);
  ballContainer.addEventListener("pointercancel", stopDrag);

  // --- CANVAS RENDERING LOOP ---
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  // High-DPI support (Display size tương ứng quả bóng 20px)
  const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
  const displaySize = 42;
  canvas.width = Math.round(displaySize * dpr);
  canvas.height = Math.round(displaySize * dpr);

  const lightDir = norm([-0.45, -0.65, 0.61]); // Spotlight shining from top-left

  function render(time) {
    const dt = Math.min((time - lastTimestamp) / 1000, 0.1);
    lastTimestamp = time;

    // Track physical translation of the ball to rotate in sync with patrol!
    const currentRect = ballContainer.getBoundingClientRect();
    const currentScreenX = currentRect.left;

    if (lastBallScreenX !== null && !isDragging) {
      const deltaX = currentScreenX - lastBallScreenX;
      // Rolling angle theta = deltaX / radius (bán kính quả bóng hiện tại là ~10px)
      if (Math.abs(deltaX) > 0.05) {
        const rollAngle = (deltaX / 10);
        // Roll axis is perpendicular to motion: [0, 1, 0] with slight 3D pitch tilt
        const rollAxis = norm([0.15, 1, 0]);
        rotMat = multMat(makeRotationMatrix(rollAxis, rollAngle), rotMat);
      } else {
        // Idle gentle rotation when resting
        const idleRot = makeRotationMatrix([0.3, 1, 0.2], 0.3 * dt);
        rotMat = multMat(idleRot, rotMat);
      }
    }
    lastBallScreenX = currentScreenX;

    // Inertial spin from drag/kick
    if (!isDragging && (Math.abs(angularVelocityX) > 0.001 || Math.abs(angularVelocityY) > 0.001)) {
      const spinSpeed = Math.hypot(angularVelocityX, angularVelocityY);
      if (spinSpeed > 0.001) {
        const axis = norm([angularVelocityX, angularVelocityY, 0]);
        rotMat = multMat(makeRotationMatrix(axis, spinSpeed), rotMat);
      }
      angularVelocityX *= 0.94;
      angularVelocityY *= 0.94;
    }

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const cx = canvas.width / 2;
    const cy = canvas.height / 2;
    const radius = (canvas.width / 2) - (2 * dpr);

    // Save state and clip to sphere circle
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.clip();

    // Base sphere background
    ctx.fillStyle = "#e2e8f0";
    ctx.fill();

    // Project and collect visible faces
    const visibleFaces = [];
    for (let f = 0; f < faces.length; f++) {
      const face = faces[f];
      const normRot = multVec(rotMat, face.center);

      // Backface culling: cull faces pointing away
      if (normRot[2] <= -0.05) continue;

      const projectedVerts = face.verts.map(v => {
        const vRot = multVec(rotMat, v);
        return {
          x: cx + vRot[0] * radius,
          y: cy - vRot[1] * radius,
          z: vRot[2]
        };
      });

      visibleFaces.push({
        type: face.type,
        normal: normRot,
        depth: normRot[2],
        verts: projectedVerts
      });
    }

    // Sort visible faces back to front (Painter's algorithm)
    visibleFaces.sort((a, b) => a.depth - b.depth);

    // Draw faces
    for (let i = 0; i < visibleFaces.length; i++) {
      const item = visibleFaces[i];
      const n = item.normal;
      const diffuse = Math.max(0.12, dot(n, lightDir));
      const halfZ = Math.max(0, (n[2] + lightDir[2]) / 2);
      const specular = Math.pow(Math.max(0, dot(n, lightDir)), 8) * 0.35;

      ctx.beginPath();
      ctx.moveTo(item.verts[0].x, item.verts[0].y);
      for (let v = 1; v < item.verts.length; v++) {
        ctx.lineTo(item.verts[v].x, item.verts[v].y);
      }
      ctx.closePath();

      if (item.type === "pentagon") {
        // Black / dark charcoal pentagon with specular shine
        const lum = Math.floor(18 + diffuse * 32 + specular * 100);
        ctx.fillStyle = `rgb(${lum}, ${lum + 2}, ${lum + 6})`;
        ctx.fill();
        ctx.lineWidth = 0.8 * dpr;
        ctx.strokeStyle = "rgba(15, 23, 42, 0.85)";
        ctx.stroke();
      } else {
        // High-grade white/cream leather hexagon with ambient occlusion
        const r = Math.floor(205 + diffuse * 45 + specular * 50);
        const g = Math.floor(212 + diffuse * 40 + specular * 50);
        const b = Math.floor(222 + diffuse * 32 + specular * 50);
        ctx.fillStyle = `rgb(${Math.min(255, r)}, ${Math.min(255, g)}, ${Math.min(255, b)})`;
        ctx.fill();
        ctx.lineWidth = 0.7 * dpr;
        ctx.strokeStyle = "rgba(71, 85, 105, 0.45)";
        ctx.stroke();
      }
    }

    // Inner 3D spherical shadow (Ambient Occlusion along rim)
    const rimGrad = ctx.createRadialGradient(cx, cy, radius * 0.65, cx, cy, radius);
    rimGrad.addColorStop(0, "rgba(15, 23, 42, 0)");
    rimGrad.addColorStop(0.8, "rgba(15, 23, 42, 0.22)");
    rimGrad.addColorStop(1, "rgba(15, 23, 42, 0.55)");
    ctx.fillStyle = rimGrad;
    ctx.fill();

    // Specular gloss glint on upper-left
    const glossGrad = ctx.createRadialGradient(
      cx - radius * 0.32,
      cy - radius * 0.32,
      radius * 0.05,
      cx - radius * 0.32,
      cy - radius * 0.32,
      radius * 0.65
    );
    glossGrad.addColorStop(0, "rgba(255, 255, 255, 0.75)");
    glossGrad.addColorStop(0.35, "rgba(255, 255, 255, 0.2)");
    glossGrad.addColorStop(1, "rgba(255, 255, 255, 0)");
    ctx.fillStyle = glossGrad;
    ctx.fill();

    ctx.restore();

    animFrameId = requestAnimationFrame(render);
  }

  let animFrameId = requestAnimationFrame(render);

  // Pause rendering when page is hidden to save battery & CPU
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (animFrameId) cancelAnimationFrame(animFrameId);
      animFrameId = null;
    } else {
      if (!animFrameId) {
        lastTimestamp = performance.now();
        animFrameId = requestAnimationFrame(render);
      }
    }
  });
}

// Backward compatibility alias: initLivingPet3D delegates to initSoccerBall3D
const initLivingPet3D = initSoccerBall3D;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initSoccerBall3D);
} else {
  initSoccerBall3D();
}

