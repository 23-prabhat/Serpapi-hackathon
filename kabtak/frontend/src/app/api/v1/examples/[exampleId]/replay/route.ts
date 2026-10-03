import { assertSameOrigin, backendRequest } from "@/lib/backend";

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/v1/examples/[exampleId]/replay">,
) {
  const originError = assertSameOrigin(request);
  if (originError) return originError;
  const { exampleId } = await params;
  return backendRequest(`/v1/examples/${encodeURIComponent(exampleId)}/replay`, {
    method: "POST",
    headers: { "Idempotency-Key": request.headers.get("Idempotency-Key") ?? "" },
  });
}
