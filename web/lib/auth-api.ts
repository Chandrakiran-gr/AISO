import "server-only";

type AuthUser = {
  id: string;
  email: string;
  name: string | null;
  provider: string;
  plan_tier: "free" | "pro" | "custom";
  account_role: "user" | "admin";
};

type AuthPayload = Record<string, string | null | undefined>;

export class AuthApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
    this.code = code;
  }
}

const BACKEND_URL =
  process.env.AISO_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

function authHeaders(): Headers {
  const headers = new Headers({
    "Content-Type": "application/json",
  });
  const internalSecret =
    process.env.AISO_INTERNAL_API_SECRET ?? process.env.AUTH_SECRET;

  if (internalSecret) {
    headers.set("X-AISO-Internal-Secret", internalSecret);
  }

  return headers;
}

async function postAuth(path: string, body: AuthPayload): Promise<AuthUser> {
  const response = await fetch(`${BACKEND_URL}/api/v1/auth${path}`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = "Authentication request failed";
    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Keep the generic detail; auth errors should not leak internals.
    }

    const code =
      response.status === 409
        ? "email_exists"
        : response.status === 401
          ? "invalid_credentials"
          : response.status === 422
            ? "validation_error"
            : "auth_api_error";

    throw new AuthApiError(detail, response.status, code);
  }

  return response.json() as Promise<AuthUser>;
}

export async function createCredentialsUser(input: {
  name: string | null;
  email: string;
  password: string;
}): Promise<AuthUser> {
  return postAuth("/signup", input);
}

export async function verifyCredentialsUser(input: {
  email: string;
  password: string;
}): Promise<AuthUser> {
  return postAuth("/credentials/verify", input);
}

export async function upsertOAuthUser(input: {
  email: string;
  name?: string | null;
  provider: "google";
}): Promise<AuthUser> {
  return postAuth("/oauth/upsert", input);
}

// Exchange a one-time post-verification grant for the user (no password). Backs the
// token path in NextAuth's credentials authorize so a just-verified account signs in.
export async function consumeSigninToken(input: {
  email: string;
  token: string;
}): Promise<AuthUser> {
  return postAuth("/consume-signin-token", input);
}

type OkResult = { ok: boolean; status?: string | null; signin_token?: string | null };

// OTP / reset endpoints return { ok, status } rather than a user. On failure the
// backend's machine-readable detail (e.g. "invalid_code", "email_not_verified",
// "too_many_attempts") becomes both the error message and code.
async function postAuthOk(path: string, body: AuthPayload): Promise<OkResult> {
  const response = await fetch(`${BACKEND_URL}/api/v1/auth${path}`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = "request_failed";
    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string") detail = payload.detail;
    } catch {
      // Keep the generic detail.
    }
    throw new AuthApiError(detail, response.status, detail);
  }

  return response.json() as Promise<OkResult>;
}

export async function verifyOtp(input: {
  email: string;
  code: string;
}): Promise<OkResult> {
  return postAuthOk("/verify-otp", input);
}

export async function resendOtp(input: { email: string }): Promise<OkResult> {
  return postAuthOk("/resend-otp", input);
}

export async function forgotPassword(input: { email: string }): Promise<OkResult> {
  return postAuthOk("/forgot-password", input);
}

export async function resetPassword(input: {
  token: string;
  new_password: string;
}): Promise<OkResult> {
  return postAuthOk("/reset-password", input);
}
