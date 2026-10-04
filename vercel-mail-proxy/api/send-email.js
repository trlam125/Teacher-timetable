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

function parseRequestBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  if (typeof req.body === "string" && req.body.trim()) {
    return JSON.parse(req.body);
  }
  return {};
}

function isEmail(value) {
  return (
    typeof value === "string" &&
    value.length <= 320 &&
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
  );
}

const smtpHost = process.env.SMTP_HOST || "smtp.gmail.com";
const smtpPort = envInt("SMTP_PORT", 587);
const smtpSecure = envBool("SMTP_SSL", smtpPort === 465);
const smtpStartTls = envBool("SMTP_STARTTLS", !smtpSecure);
const smtpTimeoutMs = Math.max(5000, envInt("SMTP_TIMEOUT_SECONDS", 30) * 1000);

const transporter = nodemailer.createTransport({
  host: smtpHost,
  port: smtpPort,
  secure: smtpSecure,
  requireTLS: !smtpSecure && smtpStartTls,
  auth: {
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASSWORD,
  },
  connectionTimeout: smtpTimeoutMs,
  greetingTimeout: smtpTimeoutMs,
  socketTimeout: smtpTimeoutMs,
});

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "Method not allowed" });
  }

  const expectedSecret = process.env.MAIL_API_SECRET || "";
  const authHeader = req.headers.authorization || "";
  const providedSecret = authHeader.startsWith("Bearer ")
    ? authHeader.slice("Bearer ".length).trim()
    : "";

  if (!expectedSecret || !safeEqual(providedSecret, expectedSecret)) {
    return res.status(401).json({ ok: false, error: "Unauthorized" });
  }

  if (!process.env.SMTP_USER || !process.env.SMTP_PASSWORD) {
    console.error("SMTP_USER or SMTP_PASSWORD is missing");
    return res.status(500).json({ ok: false, error: "Mail server is not configured" });
  }

  let body;
  try {
    body = parseRequestBody(req);
  } catch {
    return res.status(400).json({ ok: false, error: "Invalid JSON" });
  }

  const to = typeof body.to === "string" ? body.to.trim() : "";
  const subject = typeof body.subject === "string" ? body.subject.trim() : "";
  const text = typeof body.text === "string" ? body.text : "";

  if (!isEmail(to)) {
    return res.status(400).json({ ok: false, error: "Invalid recipient" });
  }
  if (!subject || subject.length > 200) {
    return res.status(400).json({ ok: false, error: "Invalid subject" });
  }
  if (!text || text.length > 20000) {
    return res.status(400).json({ ok: false, error: "Invalid email body" });
  }

  const fromEmail = (process.env.SMTP_FROM || process.env.SMTP_USER).trim();
  const fromName = (process.env.EMAIL_FROM_NAME || "Smart TKB").trim() || "Smart TKB";

  try {
    const info = await transporter.sendMail({
      from: `${fromName} <${fromEmail}>`,
      to,
      subject,
      text,
    });

    console.log(`Email accepted for ${to}; messageId=${info.messageId}`);
    return res.status(200).json({ ok: true, messageId: info.messageId });
  } catch (error) {
    console.error("SMTP send failed", error);
    return res.status(502).json({ ok: false, error: "SMTP send failed" });
  }
}
