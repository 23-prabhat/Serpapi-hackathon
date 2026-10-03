import { assertSameOrigin, backendRequest } from "@/lib/backend";

export async function GET(
  _request: Request,
  { params }: RouteContext<"/api/v1/checks/[checkId]">,
) {
  const { checkId } = await params;
  return backendRequest(`/v1/checks/${encodeURIComponent(checkId)}`);
}

export async function PATCH(
  request: Request,
  { params }: RouteContext<"/api/v1/checks/[checkId]">,
) {
  const originError = assertSameOrigin(request);
  if (originError) return originError;
  const { checkId } = await params;
  return backendRequest(`/v1/checks/${encodeURIComponent(checkId)}`, {
    method: "PATCH",
    body: await request.text(),
    headers: { "Content-Type": "application/json" },
  });
}

export async function DELETE(
  request: Request,
  { params }: RouteContext<"/api/v1/checks/[checkId]">,
) {
  const originError = assertSameOrigin(request);
  if (originError) return originError;
  const { checkId } = await params;
  return backendRequest(`/v1/checks/${encodeURIComponent(checkId)}`, {
    method: "DELETE",
  });
}
