import { assertSameOrigin, backendRequest } from "@/lib/backend";

export async function POST(request: Request) {
  const originError = assertSameOrigin(request);
  if (originError) return originError;

  return backendRequest("/v1/checks/link", {
    method: "POST",
    body: await request.text(),
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": request.headers.get("Idempotency-Key") ?? "",
    },
  });
}
