(() => {
  const fab = document.getElementById("generalChatFab");
  const popup = document.getElementById("generalChatPopup");
  if (!fab || !popup) return;
  if (popup.dataset.realtimeInitialized === "true") return;

  const currentUser = {
    id: Number(popup.dataset.currentUserId),
    name: String(popup.dataset.currentUserName || ""),
    role: String(popup.dataset.currentUserRole || "")
  };
  if (!Number.isFinite(currentUser.id) || currentUser.id <= 0) return;
  popup.dataset.realtimeInitialized = "true";
  const closeButton = document.getElementById("generalChatClose");
  const unreadBadge = document.getElementById("generalChatUnread");
  const onlineText = document.getElementById("generalChatOnlineText");
  const schoolSelect = document.getElementById("generalChatSchoolSelect");
  const socketState = document.getElementById("generalChatSocketState");
  const messages = document.getElementById("generalChatMessages");
  const loading = document.getElementById("generalChatLoading");
  const typingLine = document.getElementById("generalChatTyping");
  const contextBar = document.getElementById("generalChatComposerContext");
  const contextTitle = document.getElementById("generalChatContextTitle");
  const contextText = document.getElementById("generalChatContextText");
  const contextCancel = document.getElementById("generalChatContextCancel");
  const form = document.getElementById("generalChatForm");
  const input = document.getElementById("generalChatInput");
  const sendButton = document.getElementById("generalChatSend");

  let socket = null;
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let historyLoaded = false;
  let historyLoading = false;
  let unread = 0;
  let typingTimer = null;
  let sentTyping = false;
  let replyTarget = null;
  let editTarget = null;
  const globalOnlineUsers = new Set();
  const roomOnlineUsers = new Set();
  const typingUsers = new Map();
  let activeSchoolId = null;
  let activeSchoolName = "";
  const renderedMessageIds = new Set();
  const messageStore = new Map();

  const isOpen = () => popup.classList.contains("is-open");
  const isSuperAdmin = () => String(currentUser.role || "") === "super_admin";

  async function readJsonResponse(response) {
    const raw = await response.text();
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch (error) {
      const statusLabel = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
      if (!response.ok)
        return { detail: `Máy chủ trả về lỗi ${statusLabel} nhưng phản hồi không phải JSON hợp lệ.` };
      const invalid = new Error(`Phản hồi chat từ máy chủ không hợp lệ (${statusLabel}).`);
      invalid.cause = error;
      throw invalid;
    }
  }

  function notifyChat(message, kind = "error") {
    if (window.OperationStatus?.notify) {
      window.OperationStatus.notify(message, kind);
      return;
    }
    const notice = document.createElement("div");
    notice.className = `general-chat-inline-notice is-${kind}`;
    notice.textContent = String(message || "Không thực hiện được thao tác chat.");
    popup.querySelector(".general-chat-header")?.insertAdjacentElement("afterend", notice);
    window.setTimeout(() => notice.remove(), 4200);
  }

  async function confirmChatDelete() {
    if (!window.OperationStatus?.confirm) {
      notifyChat("Không thể mở hộp xác nhận. Vui lòng tải lại trang rồi thử lại.", "error");
      return false;
    }
    return window.OperationStatus.confirm("Xóa tin nhắn này?", {
      title: "Xóa tin nhắn",
      confirmText: "Xóa",
    });
  }

  function setSocketState(state) {
    socketState.classList.remove("is-online", "is-offline");
    if (state === "online") {
      socketState.classList.add("is-online");
      socketState.setAttribute("aria-label", "Đã kết nối");
      socketState.title = "Đã kết nối realtime";
      sendButton.disabled = !activeSchoolId;
    } else if (state === "offline") {
      socketState.classList.add("is-offline");
      socketState.setAttribute("aria-label", "Mất kết nối");
      socketState.title = "Mất kết nối, đang thử kết nối lại";
      sendButton.disabled = true;
    } else {
      socketState.setAttribute("aria-label", "Đang kết nối");
      socketState.title = "Đang kết nối realtime";
      sendButton.disabled = true;
    }
  }

  function updateOnlineText(count) {
    if (!activeSchoolId) {
      onlineText.textContent = "Chưa được gán trường";
      return;
    }
    const safeCount = Number.isFinite(Number(count)) ? Number(count) : roomOnlineUsers.size;
    onlineText.textContent = `${safeCount} người đang online`;
  }

  function setUnread(value) {
    unread = Math.max(0, value);
    if (unread === 0) {
      unreadBadge.hidden = true;
      unreadBadge.textContent = "0";
      return;
    }
    unreadBadge.hidden = false;
    unreadBadge.textContent = unread > 99 ? "99+" : String(unread);
  }

  function resetRoomView() {
    historyLoaded = false;
    historyLoading = false;
    renderedMessageIds.clear();
    messageStore.clear();
    typingUsers.clear();
    roomOnlineUsers.clear();
    clearComposerContext();
    setUnread(0);
    messages.innerHTML = '<div id="generalChatLoading" class="general-chat-empty">Đang tải tin nhắn...</div>';
  }

  function joinActiveSchool() {
    if (!activeSchoolId) {
      updateOnlineText(0);
      input.disabled = true;
      sendButton.disabled = true;
      return;
    }
    input.disabled = false;
    if (socket?.readyState === WebSocket.OPEN) {
      sendJson({ type: "room_join", school_id: activeSchoolId });
    }
  }

  async function loadSchools() {
    try {
      const response = await fetch("/api/chat/schools", {
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
      });
      const data = await readJsonResponse(response);
      if (!response.ok) {
        throw new Error(
          data.message || data.detail || `Máy chủ chat trả về lỗi HTTP ${response.status}.`,
        );
      }
      const schools = Array.isArray(data.schools) ? data.schools : [];
      schoolSelect.innerHTML = "";
      if (!schools.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "Chưa được gán trường";
        schoolSelect.appendChild(option);
        schoolSelect.disabled = true;
        activeSchoolId = null;
        activeSchoolName = "";
        resetRoomView();
        messages.innerHTML = '<div class="general-chat-empty">Tài khoản chưa được gán trường nên chưa thể sử dụng chat chung.</div>';
        updateOnlineText(0);
        input.disabled = true;
        sendButton.disabled = true;
        return;
      }
      schoolSelect.disabled = schools.length <= 1;
      schools.forEach(school => {
        const option = document.createElement("option");
        option.value = String(school.id);
        option.textContent = school.name;
        schoolSelect.appendChild(option);
      });
      activeSchoolId = Number(data.default_school_id || schools[0].id);
      const active = schools.find(school => Number(school.id) === activeSchoolId) || schools[0];
      activeSchoolId = Number(active.id);
      activeSchoolName = String(active.name || "");
      schoolSelect.value = String(activeSchoolId);
      resetRoomView();
      joinActiveSchool();
      if (isOpen()) loadHistory();
    } catch (error) {
      schoolSelect.innerHTML = '<option value="">Không tải được danh sách trường</option>';
      schoolSelect.disabled = true;
      activeSchoolId = null;
      updateOnlineText(0);
      input.disabled = true;
      sendButton.disabled = true;
      notifyChat(
        error?.message || "Không thể tải danh sách trường cho chat chung.",
        "error",
      );
    }
  }

  schoolSelect?.addEventListener("change", () => {
    stopTyping();
    activeSchoolId = Number(schoolSelect.value) || null;
    activeSchoolName = schoolSelect.options[schoolSelect.selectedIndex]?.textContent || "";
    resetRoomView();
    joinActiveSchool();
    if (isOpen()) loadHistory();
  });

  let isChatAnimating = false;

  function getDockDeltaY() {
    const assistantFab = document.getElementById("chatbotFab");
    if (!assistantFab) return 64;
    if (fab.classList.contains("is-docked")) {
      const val = parseFloat(fab.style.getPropertyValue("--gc-dock-y"));
      if (Number.isFinite(val) && val > 0) return val;
    }
    const assistantRect = assistantFab.getBoundingClientRect();
    const fabRect = fab.getBoundingClientRect();
    const delta = assistantRect.top - fabRect.top;
    return Math.round(delta) || 64;
  }

  function closeGeneralChatWithoutUndock() {
    if (!isOpen()) return;
    popup.classList.remove("is-open");
    popup.setAttribute("aria-hidden", "true");
    fab.setAttribute("aria-expanded", "false");
    fab.classList.remove("is-glowing");
    closeAllMenus();
    stopTyping();
  }

  function getGeneralChatTrail() {
    let trail = document.getElementById("generalChatTrail");
    if (!trail && fab) {
      trail = document.createElement("div");
      trail.id = "generalChatTrail";
      trail.className = "fab-trail-container general-chat-trail";
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

  function dockDown(onTop = false) {
    return new Promise((resolve) => {
      const assistantFab = document.getElementById("chatbotFab");
      if (!assistantFab) {
        resolve();
        return;
      }

      const delta = getDockDeltaY();
      fab.style.setProperty("--gc-dock-y", `${delta}px`);
      const trail = getGeneralChatTrail();
      if (trail) {
        trail.style.setProperty("--gc-dock-y", `${delta}px`);
      }

      if (fab.classList.contains("is-docked")) {
        if (onTop) {
          fab.classList.add("is-on-top");
        } else {
          fab.classList.remove("is-on-top");
        }
        resolve();
        return;
      }

      if (onTop) {
        fab.classList.add("is-on-top");
      } else {
        fab.classList.remove("is-on-top");
      }
      fab.classList.remove("is-hidden", "is-sliding-up");
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
        fab.classList.remove("is-sliding-down");
        if (trail) trail.classList.remove("is-sliding-down");
        fab.classList.add("is-docked");
        resolve();
      };
      const onEnd = (e) => {
        if (e.target === fab && (e.animationName === "gc-move-down" || !e.animationName)) done();
      };
      fab.addEventListener("animationend", onEnd);
      const timer = setTimeout(done, 680);
    });
  }

  function dockUp() {
    return new Promise((resolve) => {
      const assistantFab = document.getElementById("chatbotFab");
      const trail = getGeneralChatTrail();
      if (!assistantFab || !fab.classList.contains("is-docked")) {
        fab.classList.remove("is-docked", "is-on-top", "is-sliding-down", "is-sliding-up");
        if (trail) trail.classList.remove("is-sliding-down", "is-sliding-up");
        resolve();
        return;
      }

      fab.classList.remove("is-hidden", "is-docked", "is-sliding-down");
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
        fab.classList.remove("is-on-top", "is-sliding-up");
        if (trail) trail.classList.remove("is-sliding-up");
        resolve();
      };
      const onEnd = (e) => {
        if (e.target === fab && (e.animationName === "gc-move-up" || !e.animationName)) done();
      };
      fab.addEventListener("animationend", onEnd);
      const timer = setTimeout(done, 680);
    });
  }

  async function closeAssistantPopup(keepDocked = false) {
    if (window.ChatbotAssistant?.isOpen?.()) {
      if (keepDocked && window.ChatbotAssistant?.closeWithoutUndock) {
        window.ChatbotAssistant.closeWithoutUndock();
      } else {
        await window.ChatbotAssistant.close();
      }
      return;
    }
    const assistantPopup = document.getElementById("chatbotPopup");
    const assistantFab = document.getElementById("chatbotFab");
    if (assistantPopup) {
      assistantPopup.classList.remove("is-open");
      assistantPopup.setAttribute("aria-hidden", "true");
    }
    if (assistantFab) {
      assistantFab.classList.remove("is-hidden");
      assistantFab.setAttribute("aria-expanded", "false");
    }
  }

  async function openPopup() {
    if (isChatAnimating || isOpen()) return;
    isChatAnimating = true;

    await closeAssistantPopup(true);

    const assistantFab = document.getElementById("chatbotFab");
    assistantFab?.classList.remove("is-glowing");

    if (window.FabMotion) {
      await window.FabMotion.open(fab, popup, {
        onOpened: () => {
          fab.classList.add("is-glowing");
          setUnread(0);
          loadHistory();
          requestAnimationFrame(() => input?.focus());
        }
      });
    } else {
      if (assistantFab) {
        await dockDown(true);
      }
      popup.classList.add("is-open");
      popup.setAttribute("aria-hidden", "false");
      fab.setAttribute("aria-expanded", "true");
      fab.classList.add("is-glowing");
      setUnread(0);
      loadHistory();
      requestAnimationFrame(() => input?.focus());
    }

    isChatAnimating = false;
  }

  async function closePopup() {
    if (isChatAnimating) return;
    if (!isOpen() && !fab.classList.contains("is-docked") && !fab.dataset.motionY) return;

    isChatAnimating = true;
    fab.classList.remove("is-glowing");
    closeAllMenus();
    stopTyping();

    if (window.FabMotion) {
      await window.FabMotion.close(fab, popup);
    } else {
      popup.classList.remove("is-open");
      popup.setAttribute("aria-hidden", "true");
      fab.setAttribute("aria-expanded", "false");
      await dockUp();
    }

    isChatAnimating = false;
  }

  window.GeneralChat = {
    isOpen,
    open: openPopup,
    close: closePopup,
    closeWithoutUndock: closeGeneralChatWithoutUndock,
    dockDown,
    dockUp,
    getFab: () => fab,
    getPopup: () => popup
  };

  fab.addEventListener("click", () => isOpen() ? closePopup() : openPopup());
  closeButton?.addEventListener("click", closePopup);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen() && !replyTarget && !editTarget) {
      closePopup();
    }
  });

  document.addEventListener("click", (event) => {
    const assistantFab = event.target.closest?.("#chatbotFab");
    if (assistantFab && isOpen()) closeGeneralChatWithoutUndock();
    if (!event.target.closest?.(".general-chat-message-actions")) closeAllMenus();
  }, true);

  function initials(name) {
    const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
    return (parts.slice(-2).map(part => part[0]?.toUpperCase() || "").join("") || "?").slice(0, 2);
  }

  function formatClock(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit" }).format(date);
  }

  function shortPreview(value, max = 90) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (text.length <= max) return text;
    return `${text.slice(0, max - 1)}…`;
  }

  function normalizeMessage(message) {
    return {
      ...message,
      id: Number(message?.id),
      school_id: message?.school_id == null ? null : Number(message.school_id),
      user_id: message?.user_id == null ? null : Number(message.user_id),
      reply_to_id: message?.reply_to_id == null ? null : Number(message.reply_to_id),
      content: String(message?.content || ""),
      user_name: String(message?.user_name || "Tài khoản đã xóa"),
      edited_at: message?.edited_at || null,
      deleted_at: message?.deleted_at || null,
      reply: message?.reply ? {
        ...message.reply,
        id: Number(message.reply.id),
        user_name: String(message.reply.user_name || "Tài khoản đã xóa"),
        content: String(message.reply.content || ""),
        deleted: Boolean(message.reply.deleted)
      } : null
    };
  }

  function closeAllMenus(exceptArticle = null) {
    messages.querySelectorAll(".general-chat-message.is-menu-open").forEach(article => {
      if (article !== exceptArticle) article.classList.remove("is-menu-open");
    });
  }

  function createActionButton(action, label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "general-chat-action-item";
    button.dataset.action = action;
    button.textContent = label;
    return button;
  }

  function buildActions(message, own) {
    if (message.deleted_at) return null;
    const wrapper = document.createElement("div");
    wrapper.className = "general-chat-message-actions";

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "general-chat-actions-trigger";
    trigger.setAttribute("aria-label", "Tùy chọn tin nhắn");
    trigger.setAttribute("aria-expanded", "false");
    trigger.textContent = "⋮";

    const menu = document.createElement("div");
    menu.className = "general-chat-actions-menu";
    menu.setAttribute("role", "menu");
    menu.appendChild(createActionButton("reply", "Trả lời"));
    if (own) menu.appendChild(createActionButton("edit", "Sửa"));
    if (own || isSuperAdmin()) menu.appendChild(createActionButton("delete", "Xóa"));

    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      const article = trigger.closest(".general-chat-message");
      const willOpen = !article.classList.contains("is-menu-open");
      closeAllMenus(article);
      article.classList.toggle("is-menu-open", willOpen);
      trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });

    wrapper.append(trigger, menu);
    return wrapper;
  }

  function createReplyPreview(reply) {
    if (!reply) return null;
    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "general-chat-reply-preview";
    preview.dataset.replyId = String(reply.id || "");
    const label = document.createElement("strong");
    label.textContent = `Trả lời ${reply.user_name || "Tài khoản đã xóa"}`;
    const content = document.createElement("span");
    content.textContent = reply.deleted ? "Tin nhắn đã bị xóa" : shortPreview(reply.content);
    preview.append(label, content);
    preview.addEventListener("click", () => scrollToMessage(reply.id));
    return preview;
  }

  function createFooter(message, own) {
    const footer = document.createElement("div");
    footer.className = "general-chat-message-footer";

    const parts = [];
    const time = formatClock(message.created_at);
    if (time) parts.push(time);
    if (own && !message.deleted_at) parts.push("✓ Đã gửi");
    if (message.edited_at && !message.deleted_at) parts.push("Đã chỉnh sửa");
    if (message.deleted_at) parts.push("Đã xóa");
    footer.textContent = parts.join(" · ");
    return footer;
  }

  function appendMessage(rawMessage, options = {}) {
    const message = normalizeMessage(rawMessage);
    const id = Number(message.id);
    if (id && renderedMessageIds.has(id)) return;
    if (id) renderedMessageIds.add(id);
    if (id) messageStore.set(id, message);

    document.getElementById("generalChatLoading")?.remove();
    const own = Number(message.user_id) === Number(currentUser.id);
    const article = document.createElement("article");
    article.className = `general-chat-message${own ? " is-own" : ""}${message.deleted_at ? " is-deleted" : ""}`;
    if (id) article.dataset.messageId = String(id);

    if (!own) {
      const avatar = document.createElement("div");
      avatar.className = "general-chat-message-avatar";
      avatar.textContent = initials(message.user_name);
      article.appendChild(avatar);
    }

    const card = document.createElement("div");
    card.className = "general-chat-message-card";

    const meta = document.createElement("div");
    meta.className = "general-chat-message-meta";
    const author = document.createElement("strong");
    author.textContent = own ? "Bạn" : message.user_name;
    meta.appendChild(author);
    const actions = buildActions(message, own);
    if (actions) meta.appendChild(actions);

    const replyPreview = createReplyPreview(message.reply);
    const body = document.createElement("div");
    body.className = "general-chat-message-body";
    body.textContent = message.deleted_at ? "Tin nhắn đã bị xóa" : message.content;

    const footer = createFooter(message, own);
    card.appendChild(meta);
    if (replyPreview) card.appendChild(replyPreview);
    card.append(body, footer);
    article.appendChild(card);
    messages.appendChild(article);

    if (!options.noScroll) messages.scrollTop = messages.scrollHeight;
  }

  function rerenderMessage(messageId) {
    const id = Number(messageId);
    const message = messageStore.get(id);
    const oldArticle = messages.querySelector(`[data-message-id="${id}"]`);
    if (!message || !oldArticle) return;

    const marker = document.createElement("span");
    oldArticle.before(marker);
    renderedMessageIds.delete(id);
    oldArticle.remove();
    appendMessage(message, { noScroll: true });
    const newArticle = messages.lastElementChild;
    marker.replaceWith(newArticle);
  }

  function updateReplyReferences(messageId, content, deleted = false) {
    const id = Number(messageId);
    messageStore.forEach(message => {
      if (Number(message.reply_to_id) !== id || !message.reply) return;
      message.reply.content = deleted ? "Tin nhắn đã bị xóa" : String(content || "");
      message.reply.deleted = Boolean(deleted);
      const article = messages.querySelector(`[data-message-id="${message.id}"]`);
      const previewText = article?.querySelector(`.general-chat-reply-preview[data-reply-id="${id}"] span`);
      if (previewText) previewText.textContent = deleted ? "Tin nhắn đã bị xóa" : shortPreview(content);
    });
  }

  function applyMessageUpdate(patch) {
    const id = Number(patch?.id);
    const message = messageStore.get(id);
    if (!message) return;
    message.content = String(patch.content || "");
    message.edited_at = patch.edited_at || message.edited_at;
    messageStore.set(id, message);
    rerenderMessage(id);
    updateReplyReferences(id, message.content, false);
    if (editTarget?.id === id) clearComposerContext();
  }

  function applyMessageDelete(data) {
    const id = Number(data?.message_id);
    const message = messageStore.get(id);
    if (!message) return;
    message.content = "Tin nhắn đã bị xóa";
    message.deleted_at = data.deleted_at || new Date().toISOString();
    messageStore.set(id, message);
    rerenderMessage(id);
    updateReplyReferences(id, "Tin nhắn đã bị xóa", true);
    if (replyTarget?.id === id || editTarget?.id === id) clearComposerContext();
  }

  function scrollToMessage(messageId) {
    const article = messages.querySelector(`[data-message-id="${Number(messageId)}"]`);
    if (!article) return;
    article.scrollIntoView({ behavior: "smooth", block: "center" });
    article.classList.add("is-highlighted");
    window.setTimeout(() => article.classList.remove("is-highlighted"), 1200);
  }

  function setComposerContext(mode, message) {
    const wasEditing = Boolean(editTarget);
    replyTarget = mode === "reply" ? message : null;
    editTarget = mode === "edit" ? message : null;
    contextBar.hidden = false;
    contextBar.classList.toggle("is-edit", mode === "edit");
    contextTitle.textContent = mode === "edit" ? "Sửa tin nhắn" : `Trả lời ${message.user_name || "Tài khoản đã xóa"}`;
    contextText.textContent = shortPreview(message.content, 120);
    if (mode === "edit") {
      input.value = message.content;
      autoSizeInput();
    } else if (wasEditing) {
      input.value = "";
      autoSizeInput();
    }
    input.focus();
  }

  function clearComposerContext() {
    replyTarget = null;
    editTarget = null;
    contextBar.hidden = true;
    contextBar.classList.remove("is-edit");
    contextTitle.textContent = "";
    contextText.textContent = "";
  }

  contextCancel?.addEventListener("click", () => {
    const wasEditing = Boolean(editTarget);
    clearComposerContext();
    if (wasEditing) {
      input.value = "";
      autoSizeInput();
    }
    input.focus();
  });

  messages.addEventListener("click", async (event) => {
    const actionButton = event.target.closest?.(".general-chat-action-item");
    if (!actionButton) return;
    event.preventDefault();
    event.stopPropagation();
    const article = actionButton.closest(".general-chat-message");
    const id = Number(article?.dataset.messageId);
    const message = messageStore.get(id);
    if (!message || message.deleted_at) return;
    closeAllMenus();

    if (actionButton.dataset.action === "reply") {
      setComposerContext("reply", message);
      return;
    }
    if (actionButton.dataset.action === "edit") {
      if (Number(message.user_id) !== Number(currentUser.id)) return;
      setComposerContext("edit", message);
      return;
    }
    if (actionButton.dataset.action === "delete") {
      const allowed = Number(message.user_id) === Number(currentUser.id) || isSuperAdmin();
      if (!allowed) return;
      if (!(await confirmChatDelete())) return;
      sendJson({ type: "chat_delete", school_id: activeSchoolId, message_id: id });
    }
  });

  async function loadHistory() {
    if (!activeSchoolId || historyLoaded || historyLoading) return;
    const requestedSchoolId = Number(activeSchoolId);
    historyLoading = true;
    try {
      const response = await fetch(`/api/chat/general/messages?school_id=${encodeURIComponent(requestedSchoolId)}&limit=50`, {
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
      });
      const data = await readJsonResponse(response);
      if (!response.ok) {
        throw new Error(
          data.message || data.detail || `Máy chủ chat trả về lỗi HTTP ${response.status}.`,
        );
      }
      if (requestedSchoolId !== Number(activeSchoolId)) return;
      document.getElementById("generalChatLoading")?.remove();
      const rows = Array.isArray(data.messages) ? data.messages : [];
      if (!rows.length) {
        const empty = document.createElement("div");
        empty.className = "general-chat-empty";
        empty.textContent = activeSchoolName ? `Chưa có tin nhắn trong ${activeSchoolName}.` : "Chưa có tin nhắn trong trường này.";
        empty.id = "generalChatNoMessages";
        messages.appendChild(empty);
      } else {
        rows.forEach(row => appendMessage(row, { noScroll: true }));
        messages.scrollTop = messages.scrollHeight;
      }
      historyLoaded = true;
    } catch (error) {
      const loadingNode = document.getElementById("generalChatLoading");
      if (loadingNode)
        loadingNode.textContent =
          error?.message || "Chưa tải được lịch sử chat. Hệ thống sẽ thử lại khi bạn mở chat.";
    } finally {
      historyLoading = false;
    }
  }

  function removeEmptyState() {
    document.getElementById("generalChatNoMessages")?.remove();
  }

  function formatLastSeen(value) {
    if (!value) return "Chưa có hoạt động";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Chưa có hoạt động";
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return "Vừa xong";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} phút trước`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} giờ trước`;
    if (seconds < 172800) return "Hôm qua";
    return new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
  }

  function renderPresenceRow(row, online, lastSeen) {
    row.classList.toggle("is-online", Boolean(online));
    const state = row.querySelector("[data-presence-state]");
    const detail = row.querySelector("[data-presence-last-seen]");
    if (lastSeen) row.dataset.lastSeen = lastSeen;
    if (state) state.textContent = online ? "Online" : "Offline";
    if (detail) detail.textContent = online ? "Đang hoạt động" : formatLastSeen(row.dataset.lastSeen || lastSeen);
  }

  function refreshAllPresenceRows() {
    document.querySelectorAll("[data-presence-user-id]").forEach(row => {
      const id = Number(row.dataset.presenceUserId);
      renderPresenceRow(row, globalOnlineUsers.has(id), row.dataset.lastSeen || "");
    });
  }

  function applyPresenceEvent(data) {
    const userId = Number(data.user_id);
    if (data.online) {
      globalOnlineUsers.add(userId);
    } else {
      globalOnlineUsers.delete(userId);
    }
    const row = document.querySelector(`[data-presence-user-id="${userId}"]`);
    if (row) renderPresenceRow(row, Boolean(data.online), data.last_seen || "");
  }

  function applySchoolPresenceEvent(data) {
    if (Number(data.school_id) !== Number(activeSchoolId)) return;
    const userId = Number(data.user_id);
    if (data.online) roomOnlineUsers.add(userId);
    else {
      roomOnlineUsers.delete(userId);
      typingUsers.delete(userId);
      renderTyping();
    }
    updateOnlineText(data.online_count);
  }

  function renderTyping() {
    const names = Array.from(typingUsers.values());
    if (!names.length) {
      typingLine.hidden = true;
      typingLine.textContent = "";
      return;
    }
    typingLine.hidden = false;
    typingLine.textContent = names.length === 1
      ? `${names[0]} đang nhập...`
      : `${names.slice(0, 2).join(", ")}${names.length > 2 ? ` và ${names.length - 2} người khác` : ""} đang nhập...`;
  }

  function sendJson(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(payload));
    return true;
  }

  function scheduleReconnect() {
    reconnectAttempt += 1;
    const delay = Math.min(10000, 800 * Math.pow(1.65, reconnectAttempt));
    clearTimeout(reconnectTimer);
    reconnectTimer = window.setTimeout(connect, delay);
  }

  function connect() {
    if (socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(socket.readyState)) return;
    clearTimeout(reconnectTimer);
    setSocketState("connecting");
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    try {
      socket = new WebSocket(`${scheme}://${location.host}/ws/realtime`);
    } catch (_) {
      socket = null;
      setSocketState("offline");
      scheduleReconnect();
      return;
    }

    socket.addEventListener("open", () => {
      reconnectAttempt = 0;
      globalOnlineUsers.add(Number(currentUser.id));
      refreshAllPresenceRows();
      setSocketState("online");
      sendJson({ type: "activity" });
    });

    socket.addEventListener("message", (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }

      if (data.type === "ready") {
        globalOnlineUsers.clear();
        (data.online_user_ids || []).forEach(id => globalOnlineUsers.add(Number(id)));
        refreshAllPresenceRows();
        joinActiveSchool();
        return;
      }

      if (data.type === "presence_sync") {
        globalOnlineUsers.clear();
        (data.online_user_ids || []).forEach(id => globalOnlineUsers.add(Number(id)));
        refreshAllPresenceRows();
        joinActiveSchool();
        return;
      }

      if (data.type === "presence") {
        applyPresenceEvent(data);
        return;
      }

      if (data.type === "room_ready") {
        if (Number(data.school_id) !== Number(activeSchoolId)) return;
        roomOnlineUsers.clear();
        (data.online_user_ids || []).forEach(id => roomOnlineUsers.add(Number(id)));
        updateOnlineText(data.online_count);
        return;
      }

      if (data.type === "school_presence") {
        applySchoolPresenceEvent(data);
        return;
      }

      if (data.type === "typing") {
        if (Number(data.school_id) !== Number(activeSchoolId)) return;
        const id = Number(data.user_id);
        if (data.typing) typingUsers.set(id, String(data.user_name || "Ai đó"));
        else typingUsers.delete(id);
        renderTyping();
        return;
      }

      if (data.type === "chat_message" && data.message) {
        if (Number(data.school_id ?? data.message.school_id) !== Number(activeSchoolId)) return;
        removeEmptyState();
        appendMessage(data.message);
        typingUsers.delete(Number(data.message.user_id));
        renderTyping();
        if (!isOpen() && Number(data.message.user_id) !== Number(currentUser.id)) {
          setUnread(unread + 1);
        }
        return;
      }

      if (data.type === "chat_message_updated" && data.message) {
        if (Number(data.school_id) !== Number(activeSchoolId)) return;
        applyMessageUpdate(data.message);
        return;
      }

      if (data.type === "chat_message_deleted") {
        if (Number(data.school_id) !== Number(activeSchoolId)) return;
        applyMessageDelete(data);
        return;
      }

      if (data.type === "chat_error") {
        notifyChat(data.message || "Không thực hiện được thao tác chat.", "error");
      }
    });

    socket.addEventListener("close", (event) => {
      setSocketState("offline");
      globalOnlineUsers.delete(Number(currentUser.id));
      roomOnlineUsers.delete(Number(currentUser.id));
      refreshAllPresenceRows();
      if (event.code === 4401) {
        onlineText.textContent = "Phiên đăng nhập đã hết hạn";
        return;
      }
      scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      try { socket.close(); } catch (_) { /* noop */ }
    });
  }

  function autoSizeInput() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 118)}px`;
  }

  function startTyping() {
    if (!activeSchoolId) return;
    if (!sentTyping) sentTyping = sendJson({ type: "typing", school_id: activeSchoolId, typing: true });
    clearTimeout(typingTimer);
    typingTimer = window.setTimeout(stopTyping, 1200);
  }

  function stopTyping() {
    clearTimeout(typingTimer);
    if (sentTyping && activeSchoolId) sendJson({ type: "typing", school_id: activeSchoolId, typing: false });
    sentTyping = false;
  }

  input.addEventListener("input", () => {
    autoSizeInput();
    if (input.value.trim()) startTyping(); else stopTyping();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && (replyTarget || editTarget)) {
      event.preventDefault();
      const wasEditing = Boolean(editTarget);
      clearComposerContext();
      if (wasEditing) {
        input.value = "";
        autoSizeInput();
      }
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;

    let sent = false;
    if (editTarget) {
      sent = sendJson({ type: "chat_edit", school_id: activeSchoolId, message_id: editTarget.id, content });
    } else {
      sent = sendJson({
        type: "chat_send",
        school_id: activeSchoolId,
        content,
        reply_to_id: replyTarget?.id || null
      });
    }
    if (!sent) return;

    input.value = "";
    autoSizeInput();
    clearComposerContext();
    stopTyping();
  });

  window.addEventListener("beforeunload", stopTyping);
  window.setInterval(() => {
    sendJson({ type: "activity" });
    document.querySelectorAll("[data-presence-user-id]").forEach(row => {
      const id = Number(row.dataset.presenceUserId);
      if (!globalOnlineUsers.has(id)) renderPresenceRow(row, false, row.dataset.lastSeen || "");
    });
  }, 60000);

  document.querySelectorAll("[data-presence-user-id].is-online").forEach(row => {
    const id = Number(row.dataset.presenceUserId);
    if (Number.isFinite(id)) globalOnlineUsers.add(id);
  });
  globalOnlineUsers.add(Number(currentUser.id));
  setSocketState("connecting");
  refreshAllPresenceRows();
  connect();
  loadSchools();
  window.__SMART_TKB_REALTIME_READY = true;
})();
