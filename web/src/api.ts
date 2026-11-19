const BASE = import.meta.env.VITE_API_BASE ?? "";

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`${resp.status}: ${detail.slice(0, 300)}`);
  }
  return resp.json();
}

export const STATUS_COLOR: Record<string, string> = {
  QUEUED: "default",
  PREPARING: "processing",
  STARTING: "processing",
  RUNNING: "processing",
  RECONCILING: "warning",
  CANCELLING: "warning",
  FINALIZING: "processing",
  COMPLETED: "success",
  FAILED: "error",
  CANCELLED: "default",
};

export const OUTCOME_COLOR: Record<string, string> = {
  UNKNOWN: "default",
  PASSED: "success",
  FAILED: "error",
  NOT_EVALUATED: "default",
};
