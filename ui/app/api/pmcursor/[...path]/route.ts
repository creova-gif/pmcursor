import { NextRequest, NextResponse } from "next/server";

const API_BASE = (process.env.PMCURSOR_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);
const API_TOKEN = process.env.PMCURSOR_API_TOKEN ?? "";

async function proxy(
  req: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const target = `${API_BASE}/v1/${path.join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (API_TOKEN) {
    headers.Authorization = `Bearer ${API_TOKEN}`;
  }
  const init: RequestInit = {
    method: req.method,
    headers,
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    headers["Content-Type"] = "application/json";
    init.body = await req.text();
  }
  try {
    const upstream = await fetch(target, init);
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { error: `PMCursor API unreachable at ${API_BASE}` },
      { status: 502 },
    );
  }
}

export { proxy as GET, proxy as POST };
