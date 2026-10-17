/**
 * API client. Authentication uses the HttpOnly session cookie set by the server (JavaScript never sees
 * the token). State-changing requests echo the readable `sme_csrf` cookie in the X-CSRF-Token header.
 */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

export function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)sme_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export function authHeaders(method = "GET"): Record<string, string> {
  return method === "GET" || method === "HEAD" ? {} : { "X-CSRF-Token": csrfToken() };
}

async function errorFrom(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail)
      ? body.detail.map((d: { msg?: string; loc?: string[] }) => `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg ?? ""}`).join("; ")
      : JSON.stringify(body.detail ?? body);
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, detail);
}

const PUBLIC_AUTH = ["/auth/login", "/auth/register", "/auth/password/", "/auth/invite", "/auth/mfa/verify"];

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const isForm = init?.body instanceof FormData;
  const res = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...authHeaders(method),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const err = await errorFrom(res);
    if (res.status === 401 && !PUBLIC_AUTH.some((p) => path.startsWith(p))) onUnauthorized?.();
    throw err;
  }
  return res.json() as Promise<T>;
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
}

export function put<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "PUT", body: JSON.stringify(body) });
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}

export function del<T>(path: string): Promise<T> {
  return api<T>(path, { method: "DELETE" });
}

export function upload<T>(path: string, form: FormData): Promise<T> {
  return api<T>(path, { method: "POST", body: form });
}
