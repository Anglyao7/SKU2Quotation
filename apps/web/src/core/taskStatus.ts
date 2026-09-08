/** Existing task APIs predate each other and use different status vocabularies. */
export function normalizeTaskStatus(status: string): string {
  const value = status.toUpperCase();
  if (value === "SCANNING") return "PROCESSING";
  if (value === "NEEDS_REVIEW") return "REVIEW";
  if (["PUBLISHED", "SUCCEEDED", "SUCCESS"].includes(value)) return "COMPLETED";
  return value;
}

export const activeTaskStates = new Set(["QUEUED", "PENDING", "RUNNING", "PROCESSING", "SCANNING", "PARSING", "UPLOADING", "IMPORTING"]);
export const failedTaskStates = new Set(["FAILED", "PARTIAL"]);
