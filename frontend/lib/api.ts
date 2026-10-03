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

export type Role = "collector" | "dealer" | "satin";

const ROLES: Role[] = ["collector", "dealer", "satin"];

async function handle<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  // Session expired or logged out elsewhere: back to the login page for the app we're in.
  if (res.status === 401 && typeof window !== "undefined" && !res.url.includes("/api/auth/")) {
    const role = ROLES.find((r) => window.location.pathname.startsWith(`/${r}`));
    if (role) toLogin(role);
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

export function post<T>(path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  return fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

/** Full page load on purpose: drops all client state and lets the server re-check the session. */
function toLogin(role: Role) {
  window.location.assign(new URL(`/login?role=${role}`, window.location.origin));
}

export async function logout(role: Role) {
  await post("/auth/logout", { role }).catch(() => {});
  toLogin(role);
}

export function postForm<T>(path: string, form: FormData): Promise<T> {
  return fetch(`/api${path}`, { method: "POST", body: form }).then((r) => handle<T>(r));
}
