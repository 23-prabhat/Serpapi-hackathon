import { assertSameOrigin, backendRequest } from "@/lib/backend";

export async function GET(request: Request) {
  const query = new URL(request.url).search;
  return backendRequest(`/v1/checks${query}`);
}

export async function POST(request: Request) {
  const originError = assertSameOrigin(request);
  if (originError) return originError;

  return backendRequest("/v1/checks", {
    method: "POST",
    body: await request.text(),
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": request.headers.get("Idempotency-Key") ?? "",
    },
  });
}
