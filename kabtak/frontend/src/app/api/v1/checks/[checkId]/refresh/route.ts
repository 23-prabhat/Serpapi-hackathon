import { assertSameOrigin, backendRequest } from "@/lib/backend";

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/v1/checks/[checkId]/refresh">,
) {
  const originError = assertSameOrigin(request);
  if (originError) return originError;
  const { checkId } = await params;
  return backendRequest(`/v1/checks/${encodeURIComponent(checkId)}/refresh`, {
    method: "POST",
    headers: { "Idempotency-Key": request.headers.get("Idempotency-Key") ?? "" },
  });
}
