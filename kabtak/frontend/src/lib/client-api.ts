import type { ApiError } from "@/lib/api/types";

export async function readJson<T>(response: Response): Promise<T> {
  const body = (await response.json()) as T & ApiError;
  if (!response.ok) {
    throw new Error(body.error?.message ?? "Something went wrong. Please try again.");
  }
  return body;
}

export function pretty(value: string) {
  return value.replaceAll("_", " ");
}

export function formatDateTime(value: string) {
  return new Date(value).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  });
}
