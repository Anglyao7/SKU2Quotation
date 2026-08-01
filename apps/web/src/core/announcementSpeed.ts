export const DEFAULT_ANNOUNCEMENT_TICKER_SPEED = 60;
export const MIN_ANNOUNCEMENT_TICKER_SPEED = 20;
export const MAX_ANNOUNCEMENT_TICKER_SPEED = 160;

export function normalizeAnnouncementTickerSpeed(value: unknown) {
  const numeric = Number(value);
  if (
    !Number.isFinite(numeric)
    || numeric < MIN_ANNOUNCEMENT_TICKER_SPEED
    || numeric > MAX_ANNOUNCEMENT_TICKER_SPEED
  ) {
    return DEFAULT_ANNOUNCEMENT_TICKER_SPEED;
  }
  return Math.round(numeric);
}
