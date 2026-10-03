import { backendRequest } from "@/lib/backend";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  return backendRequest(`/v1/runs/${encodeURIComponent(runId)}`);
}
