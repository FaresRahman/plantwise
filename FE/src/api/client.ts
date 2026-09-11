// Single source of truth for the API base URL — every other module imports
// this instead of reading import.meta.env.VITE_API_URL itself. Defaults to a
// relative path so it works unchanged behind any dev proxy or tunnel
// (Vite's /api proxy, ngrok, etc.) without needing an absolute host baked in.
export const BASE_URL = import.meta.env.VITE_API_URL ?? "/api/v1";

const TOKEN_KEY = "plantwise_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * Shared fetch wrapper — attaches the auth header and unwraps JSON/errors.
 * Every module's api/*.ts file should call this instead of raw fetch().
 */
/** Message shown for any failure that never got an HTTP response at all
 * (server unreachable, CORS rejection, DNS failure, offline) — fetch()
 * itself throws a browser-internal error for these ("Failed to fetch",
 * "NetworkError when attempting to fetch resource", ...) that's meaningless
 * to a plant operator and shouldn't be shown verbatim. */
const NETWORK_ERROR_MESSAGE = "Can't reach the server right now. Check your connection and try again.";

export async function apiRequest<T>(
  path: string,
  options: { method?: string; body?: unknown; auth?: boolean } = {}
): Promise<T> {
  const { method = "GET", body, auth = true } = options;
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    // status 0 marks "no HTTP response was ever received" — distinct from a
    // real HTTP error code — for any caller that wants to branch on it.
    throw new ApiError(0, NETWORK_ERROR_MESSAGE);
  }

  if (!res.ok) {
    if (res.status === 401) {
      setToken(null);
      window.dispatchEvent(new CustomEvent("plantwise:auth-expired"));
    }
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ?? detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
