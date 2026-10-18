import { NextRequest } from "next/server";
export const dynamic = "force-dynamic";
async function proxy(request: NextRequest, context: { params: Promise<{path: string[]}> }) {
  const { path } = await context.params;
  const target = new URL("/" + path.map(encodeURIComponent).join("/"), process.env.API_INTERNAL_URL || "http://localhost:8000");
  target.search = request.nextUrl.search;
  const headers = new Headers();
  for (const name of ["content-type", "cookie", "origin", "sec-fetch-site"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    let body: ArrayBuffer | undefined;
    if (!["GET", "HEAD"].includes(request.method)) {
      const chunks: Uint8Array[] = []; let size = 0;
      const reader = request.body?.getReader();
      if (reader) { while (true) { const next = await reader.read(); if (next.done) break;
        size += next.value.byteLength;
        if (size > 50_000_000) { await reader.cancel(); return Response.json({detail:"Upload exceeds 50 MB."},{status:413}); }
        chunks.push(next.value);
      } }
      const bytes = new Uint8Array(size); let position=0;
      for (const chunk of chunks) { bytes.set(chunk,position); position+=chunk.byteLength; }
      body = bytes.buffer;
    }
    const response = await fetch(target, {method: request.method, headers,
      body,
      cache: "no-store", redirect: "manual", signal: AbortSignal.timeout(path[0]==="sources"||path.at(-1)==="refresh"?120000:30000)});
    const resultHeaders = new Headers();
    for (const name of ["content-type", "content-disposition", "x-request-id", "x-content-type-options"]) {
      const value = response.headers.get(name);
      if (value) resultHeaders.set(name, value);
    }
    for (const cookie of response.headers.getSetCookie()) resultHeaders.append("set-cookie", cookie);
    resultHeaders.set("cache-control", "no-store");
    return new Response(response.body, {status: response.status, headers: resultHeaders});
  } catch {
    return Response.json({detail:"API is unavailable. Check the API container and API_INTERNAL_URL."}, {status:502});
  }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
