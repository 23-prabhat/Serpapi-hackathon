import { assertSameOrigin, backendRequest } from "@/lib/backend";

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/v1/runs/[runId]/retry">,
) {
  const originError = assertSameOrigin(request);
  if (originError) return originError;
  const { runId } = await params;
  return backendRequest(`/v1/runs/${encodeURIComponent(runId)}/retry`, {
    method: "POST",
    headers: { "Idempotency-Key": request.headers.get("Idempotency-Key") ?? "" },
  });
}
