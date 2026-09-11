import { apiRequest } from "./client";

export interface UserOut {
  id: number;
  tenant_id: number;
  email: string;
  full_name: string;
  role: "admin" | "operator" | "viewer";
  is_verified: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export function signup(payload: { tenant_name: string; full_name: string; email: string; password: string }) {
  return apiRequest<UserOut>("/auth/signup", { method: "POST", body: payload, auth: false });
}

export function login(payload: { email: string; password: string }) {
  return apiRequest<TokenResponse>("/auth/login", { method: "POST", body: payload, auth: false });
}

export function verifyEmail(token: string) {
  return apiRequest<{ status: string }>(`/auth/verify?token=${encodeURIComponent(token)}`, { auth: false });
}

export function acceptInvite(payload: { token: string; password: string }) {
  return apiRequest<TokenResponse>("/auth/accept-invite", { method: "POST", body: payload, auth: false });
}

export function me() {
  return apiRequest<UserOut>("/auth/me");
}

export function inviteUser(payload: { email: string; full_name: string; role: string }) {
  return apiRequest<UserOut>("/auth/invite", { method: "POST", body: payload });
}
