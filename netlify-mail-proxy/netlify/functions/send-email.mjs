import crypto from "node:crypto";
import nodemailer from "nodemailer";

function envBool(name, fallback = false) {
  const value = process.env[name];
  if (value == null || value === "") return fallback;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

function envInt(name, fallback) {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isFinite(value) ? value : fallback;
}

function safeEqual(left, right) {
  const a = Buffer.from(left ?? "", "utf8");
  const b = Buffer.from(right ?? "", "utf8");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function isEmail(value) {
  return (
    typeof value === "string" &&
    value.length <= 320 &&
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
  );
}

function json(data, status = 200, extraHeaders = {}) {
  return Response.json(data, {
    status,
    headers: {
      "Cache-Control": "no-store",
      ...extraHeaders,
    },
  });
}

let transporter;
let transporterKey = "";

function getTransporter() {
  const smtpHost = process.env.SMTP_HOST || "smtp.gmail.com";
  const smtpPort = envInt("SMTP_PORT", 587);
  const smtpSecure = envBool("SMTP_SSL", smtpPort === 465);
  const smtpStartTls = envBool("SMTP_STARTTLS", !smtpSecure);
  const smtpTimeoutMs = Math.max(
    5000,
    envInt("SMTP_TIMEOUT_SECONDS", 30) * 1000,
  );
  const smtpUser = process.env.SMTP_USER || "";
  const smtpPassword = process.env.SMTP_PASSWORD || "";

  const key = JSON.stringify({
    smtpHost,
    smtpPort,
    smtpSecure,
    smtpStartTls,
    smtpTimeoutMs,
    smtpUser,
    smtpPassword,
  });

  if (!transporter || transporterKey !== key) {
    transporter = nodemailer.createTransport({
      host: smtpHost,
      port: smtpPort,
      secure: smtpSecure,
      requireTLS: !smtpSecure && smtpStartTls,
      auth: {
        user: smtpUser,
        pass: smtpPassword,
      },
      connectionTimeout: smtpTimeoutMs,
      greetingTimeout: smtpTimeoutMs,
      socketTimeout: smtpTimeoutMs,
    });
    transporterKey = key;
  }

  return transporter;
}

export default async (request) => {
  if (request.method !== "POST") {
    return json(
      { ok: false, error: "Method not allowed" },
      405,
      { Allow: "POST" },
    );
  }

  const expectedSecret = process.env.MAIL_API_SECRET || "";
  const authHeader = request.headers.get("authorization") || "";
  const providedSecret = authHeader.startsWith("Bearer ")
    ? authHeader.slice("Bearer ".length).trim()
    : "";

  if (!expectedSecret || !safeEqual(providedSecret, expectedSecret)) {
    return json({ ok: false, error: "Unauthorized" }, 401);
  }

  if (!process.env.SMTP_USER || !process.env.SMTP_PASSWORD) {
    console.error("SMTP_USER or SMTP_PASSWORD is missing");
    return json({ ok: false, error: "Mail server is not configured" }, 500);
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "Invalid JSON" }, 400);
  }

  const to = typeof body?.to === "string" ? body.to.trim() : "";
  const subject = typeof body?.subject === "string" ? body.subject.trim() : "";
  const text = typeof body?.text === "string" ? body.text : "";

  if (!isEmail(to)) {
    return json({ ok: false, error: "Invalid recipient" }, 400);
  }
  if (!subject || subject.length > 200) {
    return json({ ok: false, error: "Invalid subject" }, 400);
  }
  if (!text || text.length > 20000) {
    return json({ ok: false, error: "Invalid email body" }, 400);
  }

  const fromEmail = (process.env.SMTP_FROM || process.env.SMTP_USER).trim();
  const fromName = (process.env.EMAIL_FROM_NAME || "Smart TKB").trim() || "Smart TKB";

  try {
    const info = await getTransporter().sendMail({
      from: `${fromName} <${fromEmail}>`,
      to,
      subject,
      text,
    });

    console.log(`Email accepted for ${to}; messageId=${info.messageId}`);
    return json({ ok: true, messageId: info.messageId });
  } catch (error) {
    console.error("SMTP send failed", error);
    return json({ ok: false, error: "SMTP send failed" }, 502);
  }
};

export const config = {
  path: "/api/send-email",
};
