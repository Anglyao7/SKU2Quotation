// This deliberately uses process memory rather than localStorage or
// sessionStorage. Client-side route changes share it, while a full document
// reload or an explicitly cleared authentication session starts a new visit.
const dismissals = new Set<string>();

export function announcementDismissedForVisit(key: string) {
  return dismissals.has(key);
}

export function dismissAnnouncementForVisit(key: string) {
  dismissals.add(key);
}

export function resetStorefrontAnnouncementVisit() {
  dismissals.clear();
}
