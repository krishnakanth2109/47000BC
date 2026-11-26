/**
 * API helper — wraps fetch with cookie credentials and JSON parsing.
 * Base URL is relative so it works both dev (proxied) and production.
 */
const BASE = "/api";

export async function apiFetch(path, options = {}) {
  const response = await fetch(`${BASE}/${path}`, {
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
