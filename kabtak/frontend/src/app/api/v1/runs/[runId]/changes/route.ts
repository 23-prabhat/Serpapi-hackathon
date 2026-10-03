import { backendRequest } from "@/lib/backend";

export async function GET(
  _request: Request,
  { params }: RouteContext<"/api/v1/runs/[runId]/changes">,
) {
  const { runId } = await params;
  return backendRequest(`/v1/runs/${encodeURIComponent(runId)}/changes`);
}
