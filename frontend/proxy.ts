import { type NextRequest, NextResponse } from "next/server";

import { PATH_HEADER } from "@/lib/request-path";

/** Hands each page request's path to the root layout (see lib/request-path). */
export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set(PATH_HEADER, request.nextUrl.pathname);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  // Pages only: never the /api rewrite to the backend, build assets, or files.
  matcher: ["/((?!api/|_next/|.*\\.[^/]+$).*)"],
};
