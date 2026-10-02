export async function readJsonResponse(response) {
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

export function createClientId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function initials(name) {
  const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
  return (parts.slice(-2).map(part => part[0]?.toUpperCase() || "").join("") || "?").slice(0, 2);
}

export function formatClock(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit" }).format(date);
}

export function shortPreview(value, max = 90) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

export function normalizeMessage(message) {
  return {
    ...message,
    id: message?.id == null ? null : Number(message.id),
    client_id: message?.client_id ? String(message.client_id) : null,
    school_id: message?.school_id == null ? null : Number(message.school_id),
    user_id: message?.user_id == null ? null : Number(message.user_id),
    reply_to_id: message?.reply_to_id == null ? null : Number(message.reply_to_id),
    content: String(message?.content || ""),
    user_name: String(message?.user_name || "Tài khoản đã xóa"),
    edited_at: message?.edited_at || null,
    deleted_at: message?.deleted_at || null,
    pending: Boolean(message?.pending),
    failed: Boolean(message?.failed),
    reply: message?.reply ? {
      ...message.reply,
      id: Number(message.reply.id),
      user_name: String(message.reply.user_name || "Tài khoản đã xóa"),
      content: String(message.reply.content || ""),
      deleted: Boolean(message.reply.deleted)
    } : null
  };
}
