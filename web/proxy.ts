import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// ── In-memory rate limiter (local-dev safe, swap to Upstash Redis in prod) ──
// Tracks: { ip -> { count, windowStart, violations, bannedUntil } }
const store = new Map<string, {
  count: number;
  windowStart: number;
  violations: number;
  bannedUntil: number;
}>();

// Cleanup stale entries every 5 minutes
if (typeof setInterval !== "undefined") {
  setInterval(() => {
    const now = Date.now();
    for (const [ip, state] of store.entries()) {
      if (state.bannedUntil < now && state.windowStart + 120_000 < now) {
        store.delete(ip);
      }
    }
  }, 300_000);
}

interface RateConfig {
  limit: number;       // max requests per window
  windowMs: number;    // window duration in ms
  banAfter: number;    // violations before ban
  banMs: number;       // ban duration in ms
}

const TIERS: Record<string, RateConfig> = {
  auth:     { limit: 5,  windowMs: 60_000,  banAfter: 3, banMs: 86_400_000 }, // 5/min → 24h ban
  pipeline: { limit: 2,  windowMs: 600_000, banAfter: 2, banMs: 3_600_000  }, // 2/10min → 1h ban
  api:      { limit: 30, windowMs: 60_000,  banAfter: 3, banMs: 3_600_000  }, // 30/min → 1h ban
  default:  { limit: 60, windowMs: 60_000,  banAfter: 3, banMs: 3_600_000  }, // 60/min → 1h ban
};

function getTier(pathname: string): RateConfig {
  if (pathname.startsWith("/api/auth"))                                 return TIERS.auth;
  if (pathname.startsWith("/api/v1/clients") && pathname.includes("collect")) return TIERS.pipeline;
  if (pathname.startsWith("/api/"))                                     return TIERS.api;
  return TIERS.default;
}

function checkRateLimit(ip: string, pathname: string): {
  allowed: boolean;
  remaining: number;
  retryAfter: number;
  banned: boolean;
} {
  const now = Date.now();
  const cfg = getTier(pathname);
  const key = `${ip}:${Object.entries(TIERS).find(([, v]) => v === cfg)?.[0] ?? "default"}`;

  let state = store.get(key);

  if (!state) {
    state = { count: 0, windowStart: now, violations: 0, bannedUntil: 0 };
    store.set(key, state);
  }

  // Check if currently banned
  if (state.bannedUntil > now) {
    return { allowed: false, remaining: 0, retryAfter: Math.ceil((state.bannedUntil - now) / 1000), banned: true };
  }

  // Reset window
  if (now - state.windowStart > cfg.windowMs) {
    state.count = 0;
    state.windowStart = now;
  }

  state.count++;

  if (state.count > cfg.limit) {
    state.violations++;
    if (state.violations >= cfg.banAfter) {
      state.bannedUntil = now + cfg.banMs;
      state.violations = 0;
      console.warn(`[AISO Security] IP BANNED: ${ip} on ${pathname} for ${cfg.banMs / 60000} minutes`);
      return { allowed: false, remaining: 0, retryAfter: Math.ceil(cfg.banMs / 1000), banned: true };
    }
    return {
      allowed: false,
      remaining: 0,
      retryAfter: Math.ceil((cfg.windowMs - (now - state.windowStart)) / 1000),
      banned: false,
    };
  }

  // Reset violations on a clean request
  state.violations = 0;
  return { allowed: true, remaining: cfg.limit - state.count, retryAfter: 0, banned: false };
}

// ── Security Headers ─────────────────────────────────────────────────────────
function applySecurityHeaders(response: NextResponse): NextResponse {
  const h = response.headers;

  // CSP — strict, no unsafe-inline for scripts
  h.set(
    "Content-Security-Policy",
    [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com",  // unsafe-inline needed for Next.js inline scripts; tighten with nonce in prod
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
      "font-src 'self' https://fonts.gstatic.com",
      "img-src 'self' data: https:",
      "connect-src 'self' http://localhost:8000 https://api.sapienic.com",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "upgrade-insecure-requests",
    ].join("; ")
  );

  // HSTS — 1 year, include subdomains
  h.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload");

  // Prevent MIME sniffing
  h.set("X-Content-Type-Options", "nosniff");

  // Block all iframing
  h.set("X-Frame-Options", "DENY");

  // Legacy XSS filter
  h.set("X-XSS-Protection", "1; mode=block");

  // Limit referrer leakage
  h.set("Referrer-Policy", "strict-origin-when-cross-origin");

  // Deny all browser permissions
  h.set("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()");

  // Remove server fingerprinting
  h.delete("X-Powered-By");
  h.delete("Server");

  return response;
}

// ── Injection Detection ───────────────────────────────────────────────────────
const SQL_PATTERNS = /(\bSELECT\b|\bDROP\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|--|;--|\/\*|\*\/|xp_|UNION\b|EXEC\b)/i;
const XSS_PATTERNS = /<script|javascript:|data:text\/html|vbscript:|on\w+\s*=/i;

function detectInjection(url: URL): boolean {
  const check = (s: string) => SQL_PATTERNS.test(s) || XSS_PATTERNS.test(s);
  if (check(url.pathname)) return true;
  for (const [, v] of url.searchParams) {
    if (check(decodeURIComponent(v))) return true;
  }
  return false;
}

// ── Middleware ────────────────────────────────────────────────────────────────
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 1. Skip static assets and Next.js internals
  if (
    pathname.startsWith("/_next/") ||
    pathname.startsWith("/favicon") ||
    pathname.match(/\.(ico|png|jpg|jpeg|svg|webp|woff2?|ttf|otf|css|js\.map)$/)
  ) {
    return applySecurityHeaders(NextResponse.next());
  }

  // 2. Get real client IP
  const ip =
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    request.headers.get("x-real-ip") ??
    "unknown";

  // 3. Block known malicious user agents
  const userAgent = request.headers.get("user-agent") ?? "";
  const BLOCKED_AGENTS = ["sqlmap", "nikto", "nmap", "masscan", "zgrab", "dirbuster", "nuclei", "xsser"];
  if (BLOCKED_AGENTS.some((a) => userAgent.toLowerCase().includes(a))) {
    console.warn(`[AISO Security] Blocked UA: ${userAgent} from ${ip}`);
    return new NextResponse("Forbidden", { status: 403 });
  }

  // 4. Injection detection on URL
  if (detectInjection(request.nextUrl)) {
    console.warn(`[AISO Security] Injection attempt from ${ip} on ${pathname}`);
    return new NextResponse("Bad Request", { status: 400 });
  }

  // 5. Rate limiting + IP banning
  const { allowed, remaining, retryAfter, banned } = checkRateLimit(ip, pathname);

  if (!allowed) {
    const status = banned ? 403 : 429;
    const message = banned ? "Access Denied — IP temporarily blocked" : "Too Many Requests";
    console.warn(`[AISO Security] ${banned ? "BANNED" : "Rate limited"}: ${ip} on ${pathname}`);

    const resp = new NextResponse(message, {
      status,
      headers: {
        "Retry-After": String(retryAfter),
        "X-RateLimit-Remaining": "0",
        "Content-Type": "text/plain",
      },
    });
    return applySecurityHeaders(resp);
  }

  // 6. CSRF check for state-changing API routes
  if (
    ["POST", "PUT", "PATCH", "DELETE"].includes(request.method) &&
    pathname.startsWith("/api/") &&
    !pathname.startsWith("/api/auth")  // NextAuth handles its own CSRF
  ) {
    const origin = request.headers.get("origin");
    const host   = request.headers.get("host");
    if (origin && host && !origin.includes(host)) {
      console.warn(`[AISO Security] CSRF check failed: origin=${origin} host=${host} ip=${ip}`);
      return new NextResponse("CSRF check failed", { status: 403 });
    }
  }

  // 7. Pass through — attach rate limit headers
  const response = NextResponse.next();
  response.headers.set("X-RateLimit-Remaining", String(remaining));
  return applySecurityHeaders(response);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
