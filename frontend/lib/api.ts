export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public rule?: string | null,
    public evidence?: Record<string, unknown>,
  ) {
    super(message);
  }
}

async function handle<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  // Session expired or logged out elsewhere: back to the login page for the app we're in.
  if (res.status === 401 && typeof window !== "undefined" && !res.url.includes("/api/auth/")) {
    const role = window.location.pathname.startsWith("/dealer") ? "dealer" : "collector";
    if (window.location.pathname.startsWith(`/${role}`)) toLogin(role);
  }
  if (!res.ok) {
    const msg = body.error ?? (typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
    throw new ApiError(res.status, msg, body.rule, body.evidence);
  }
  return body as T;
}

export function get<T>(path: string): Promise<T> {
  return fetch(`/api${path}`, { cache: "no-store" }).then((r) => handle<T>(r));
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

/** Full page load on purpose: drops all client state and lets the server re-check the session. */
function toLogin(role: "collector" | "dealer") {
  window.location.assign(new URL(`/login?role=${role}`, window.location.origin));
}

export async function logout(role: "collector" | "dealer") {
  await post("/auth/logout", { role }).catch(() => {});
  toLogin(role);
}

export function postForm<T>(path: string, form: FormData): Promise<T> {
  return fetch(`/api${path}`, { method: "POST", body: form }).then((r) => handle<T>(r));
}
