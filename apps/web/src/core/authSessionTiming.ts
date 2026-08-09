const ACCESS_TOKEN_REFRESH_MAX_LEAD_MS = 60_000;
const ACCESS_TOKEN_REFRESH_MIN_LEAD_MS = 5_000;

export function accessTokenRefreshDelayMs(expiresInSeconds: number) {
  if (!Number.isFinite(expiresInSeconds) || expiresInSeconds <= 0) return 0;
  const ttlMs = expiresInSeconds * 1_000;
  const minimumLeadMs = Math.min(ACCESS_TOKEN_REFRESH_MIN_LEAD_MS, ttlMs / 2);
  const refreshLeadMs = Math.min(
    ACCESS_TOKEN_REFRESH_MAX_LEAD_MS,
    Math.max(minimumLeadMs, ttlMs * 0.1),
  );
  return Math.max(0, ttlMs - refreshLeadMs);
}
