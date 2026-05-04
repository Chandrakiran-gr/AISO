import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";

const BACKEND_URL =
  process.env.AISO_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const session = await auth();
  if (!session?.user?.email) {
    return new NextResponse("Unauthorized", { status: 401 });
  }

  // Fallback to email as user ID if user.id is missing in NextAuth
  const userId = session.user.id || session.user.email;

  const resolvedParams = await params;
  const backendPath = resolvedParams.path.join("/");
  const url = new URL(req.url);
  const targetUrl = `${BACKEND_URL}/api/${backendPath}${url.search}`;

  const headers = new Headers(req.headers);
  headers.set("X-User-Id", userId);
  headers.delete("host"); // Let fetch set the proper host
  headers.delete("connection");
  headers.delete("content-length");

  // Can't pass body for GET/HEAD
  const hasBody = !["GET", "HEAD"].includes(req.method);
  
  const init: RequestInit = {
    method: req.method,
    headers,
    // @ts-expect-error duplex is required for streaming bodies in Node.js fetch
    duplex: hasBody ? "half" : undefined,
  };

  if (hasBody && req.body) {
    init.body = req.body;
  }

  try {
    const response = await fetch(targetUrl, init);
    // Create a new response to stream back to the client
    const resHeaders = new Headers(response.headers);
    // Remove content-encoding to avoid double compression issues
    resHeaders.delete("content-encoding");
    
    return new NextResponse(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: resHeaders,
    });
  } catch (error) {
    console.error("[Backend Proxy] Error:", error);
    return new NextResponse("Bad Gateway", { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const PATCH = proxy;
