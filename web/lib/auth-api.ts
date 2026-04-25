import "server-only";

type AuthUser = {
  id: string;
  email: string;
  name: string | null;
  provider: string;
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
