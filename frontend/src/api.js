/**
 * API helper — wraps fetch with cookie credentials, Render/backend URL support,
 * and JSON parsing. Uses relative /api locally (Vite proxy) or
 * VITE_API_URL / VITE_RENDER_URL / VITE_BACKEND_URL when configured.
 */
export const BACKEND_ORIGIN = (
  import.meta.env.VITE_API_URL ||
  import.meta.env.VITE_RENDER_URL ||
  import.meta.env.VITE_BACKEND_URL ||
  ""
)
  .trim()
  .replace(/\/+$/, "");

const BASE = `${BACKEND_ORIGIN}/api`;

export function apiUrl(path = "") {
  const clean = String(path).replace(/^\/+/, "");
  return clean ? `${BASE}/${clean}` : BASE;
}

export function resolveMediaUrl(url) {
  if (!url) return "";
  if (/^(https?:|data:|blob:)/i.test(url)) return url;
  if (url.startsWith("/")) return `${BACKEND_ORIGIN}${url}`;
  return `${BACKEND_ORIGIN}/${url}`;
}

export function wsUrl(path = "live") {
  const clean = String(path).replace(/^\/+/, "");
  if (BACKEND_ORIGIN) {
    const wsOrigin = BACKEND_ORIGIN.replace(/^http/i, "ws");
    return `${wsOrigin}/api/${clean}`;
  }
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${location.host}/api/${clean}`;
}

export async function apiFetch(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    credentials: "include", // Always send cookies (session cookie)
    ...options,
  });

  if (response.status === 204) return null;

  let body;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const message =
      typeof body?.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`;
    throw new Error(message);
  }

  return body;
}

export function apiGet(path) {
  return apiFetch(path);
}

export function apiPost(path, data) {
  if (data instanceof FormData) {
    return apiFetch(path, { method: "POST", body: data });
  }
  return apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function apiDelete(path) {
  return apiFetch(path, { method: "DELETE" });
}

export function apiPut(path, data) {
  if (data instanceof FormData) {
    return apiFetch(path, { method: "PUT", body: data });
  }
  return apiFetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
