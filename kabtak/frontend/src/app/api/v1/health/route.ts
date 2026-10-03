import { backendRequest } from "@/lib/backend";

export async function GET() {
  return backendRequest("/v1/health");
}
