const DEFAULT_RENDER_URL = "https://teacher-timetable-lam.onrender.com";

function cleanBaseUrl(value) {
  try {
    const url = new URL(String(value || "").trim());
    if (url.protocol !== "https:") return null;
    return url.origin + url.pathname.replace(/\/+$/, "");
  } catch {
    return null;
  }
}

export default async function handler(request, response) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.setHeader("Allow", "GET, HEAD");
    return response.status(405).json({ ready: false, error: "Method not allowed" });
  }

  response.setHeader("Cache-Control", "no-store, max-age=0");
  response.setHeader("CDN-Cache-Control", "no-store");

  const target = cleanBaseUrl(process.env.RENDER_URL || DEFAULT_RENDER_URL);
  if (!target) {
    return response.status(500).json({ ready: false, error: "Invalid RENDER_URL" });
  }

  const healthPath = (process.env.RENDER_HEALTH_PATH || "/health").trim();
  const safeHealthPath = healthPath.startsWith("/") ? healthPath : "/health";
  const healthUrl = `${target}${safeHealthPath}${safeHealthPath.includes("?") ? "&" : "?"}launcher=${Date.now()}`;
  const timeoutMs = Math.min(55000, Math.max(5000, Number(process.env.RENDER_WAKE_TIMEOUT_MS) || 50000));
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const upstream = await fetch(healthUrl, {
      method: "GET",
      cache: "no-store",
      redirect: "follow",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": "Smart-TKB-Vercel-Launcher/1.0",
      },
    });

    if (!upstream.ok) {
      return response.status(503).json({ ready: false, status: upstream.status });
    }

    let body = null;
    try {
      body = await upstream.json();
    } catch {
      body = null;
    }

    if (body && body.status !== "ok") {
      return response.status(503).json({ ready: false });
    }

    return response.status(200).json({ ready: true, target });
  } catch (error) {
    const reason = error?.name === "AbortError" ? "wake_timeout" : "upstream_unreachable";
    return response.status(503).json({ ready: false, reason });
  } finally {
    clearTimeout(timeout);
  }
}

export const config = {
  maxDuration: 60,
};
