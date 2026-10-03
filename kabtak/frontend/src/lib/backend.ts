import "server-only";

const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

function errorResponse(status: number, code: string, message: string) {
  return Response.json(
    { error: { code, message, retryable: status >= 500 } },
    { status },
  );
}

export function assertSameOrigin(request: Request): Response | null {
  const origin = request.headers.get("origin");
  const allowedOrigin = process.env.APP_ORIGIN ?? new URL(request.url).origin;
  if (!origin || origin !== allowedOrigin) {
    return errorResponse(
      403,
      "ORIGIN_NOT_ALLOWED",
      "This request must come from the Kabtak application.",
    );
  }
  return null;
}

export async function backendRequest(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = process.env.INTERNAL_API_TOKEN;
  if (!token) {
    return errorResponse(
      503,
      "PROXY_NOT_CONFIGURED",
      "The local API proxy is not configured.",
    );
  }

  try {
    const upstream = await fetch(`${backendUrl}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "X-Internal-Token": token,
        ...init.headers,
      },
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return errorResponse(
      502,
      "BACKEND_UNAVAILABLE",
      "The local API is unavailable. Start the backend and try again.",
    );
  }
}
