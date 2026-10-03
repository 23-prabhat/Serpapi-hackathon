import { backendRequest } from "@/lib/backend";

export async function GET(
  _request: Request,
  {
    params,
  }: {
    params: Promise<{ runId: string; versionId: string; blockId: string }>;
  },
) {
  const { runId, versionId, blockId } = await params;
  return backendRequest(
    `/v1/runs/${encodeURIComponent(runId)}/evidence/${encodeURIComponent(versionId)}/${encodeURIComponent(blockId)}`,
  );
}
