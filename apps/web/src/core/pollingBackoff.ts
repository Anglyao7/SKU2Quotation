export function pollingBackoffMs(
  baseIntervalMs: number,
  consecutiveFailures: number,
  maximumIntervalMs = 60_000,
) {
  const base = Math.max(250, Math.floor(baseIntervalMs));
  const maximum = Math.max(base, Math.floor(maximumIntervalMs));
  const exponent = Math.max(0, Math.min(10, Math.floor(consecutiveFailures)));
  return Math.min(maximum, base * (2 ** exponent));
}
