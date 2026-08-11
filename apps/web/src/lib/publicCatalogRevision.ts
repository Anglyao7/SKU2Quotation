const REVISION_STORAGE_KEY = "atc.publicCatalogRevision";
const REVISION_EVENT = "atc:public-catalog-revision";
const CACHE_SCHEMA_VERSION = "v2";

let memoryRevision = "0";

export function currentPublicCatalogRevision() {
  if (typeof window === "undefined") return memoryRevision;
  try {
    return window.localStorage.getItem(REVISION_STORAGE_KEY) || memoryRevision;
  } catch {
    return memoryRevision;
  }
}

export function publicCatalogCacheKey(scope: string, path: string) {
  return `${CACHE_SCHEMA_VERSION}:${scope}:${currentPublicCatalogRevision()}:${path}`;
}

export function bumpPublicCatalogRevision() {
  memoryRevision = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(REVISION_STORAGE_KEY, memoryRevision);
  } catch {
    // Private browsing can disable localStorage; the in-memory revision still
    // invalidates this tab.
  }
  window.dispatchEvent(new Event(REVISION_EVENT));
}

export function subscribePublicCatalogRevision(callback: () => void) {
  if (typeof window === "undefined") return () => undefined;
  const handleRevision = () => callback();
  const handleStorage = (event: StorageEvent) => {
    if (event.key !== REVISION_STORAGE_KEY) return;
    memoryRevision = event.newValue || memoryRevision;
    callback();
  };
  window.addEventListener(REVISION_EVENT, handleRevision);
  window.addEventListener("storage", handleStorage);
  return () => {
    window.removeEventListener(REVISION_EVENT, handleRevision);
    window.removeEventListener("storage", handleStorage);
  };
}
