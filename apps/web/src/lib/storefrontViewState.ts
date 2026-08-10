import type {
  StoreProduct,
  Storefront,
  StorefrontLocale,
} from "../types";
import { currentPublicCatalogRevision } from "./publicCatalogRevision";

export type StorefrontCategoryLayout = "horizontal" | "vertical";

export interface StorefrontViewState {
  page: number;
  scrollY: number;
  search: string;
  primaryCategory: string;
  secondaryCategory: string;
  categoryLayout: StorefrontCategoryLayout;
  expandedCategories: string[];
  savedAt: number;
}

const VIEW_STATE_TTL_MS = 12 * 60 * 60 * 1_000;
const CATALOG_SNAPSHOT_TTL_MS = 15 * 60 * 1_000;
const CATALOG_SNAPSHOT_MAX_ENTRIES = 12;

export interface StorefrontCatalogSnapshot {
  store: Storefront;
  products: StoreProduct[];
  total: number;
  page: number;
  pages: number;
  view: Omit<StorefrontViewState, "savedAt">;
  locale: StorefrontLocale;
  revision: string;
  savedAt: number;
}

const catalogSnapshots = new Map<string, StorefrontCatalogSnapshot>();

function storageKey(slug: string) {
  return `smart-trade-cloud:store-view:${slug.toLocaleLowerCase()}`;
}

function catalogSnapshotKey(slug: string, locale: StorefrontLocale) {
  return `${slug.trim().toLocaleLowerCase()}:${locale}`;
}

function pruneCatalogSnapshots() {
  const now = Date.now();
  const revision = currentPublicCatalogRevision();
  for (const [key, snapshot] of catalogSnapshots) {
    if (
      now - snapshot.savedAt > CATALOG_SNAPSHOT_TTL_MS
      || snapshot.revision !== revision
    ) {
      catalogSnapshots.delete(key);
    }
  }
  while (catalogSnapshots.size > CATALOG_SNAPSHOT_MAX_ENTRIES) {
    const oldestKey = catalogSnapshots.keys().next().value as string | undefined;
    if (!oldestKey) break;
    catalogSnapshots.delete(oldestKey);
  }
}

function normalizedString(value: unknown, maxLength = 500) {
  return typeof value === "string" ? value.slice(0, maxLength) : "";
}

export function readStorefrontViewState(slug: string): StorefrontViewState | null {
  if (typeof window === "undefined") return null;
  const key = storageKey(slug);
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StorefrontViewState>;
    const savedAt = Number(parsed.savedAt);
    if (!Number.isFinite(savedAt) || Date.now() - savedAt > VIEW_STATE_TTL_MS) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    const page = Number(parsed.page);
    const scrollY = Number(parsed.scrollY);
    return {
      page: Number.isFinite(page) ? Math.max(1, Math.min(100_000, Math.floor(page))) : 1,
      scrollY: Number.isFinite(scrollY) ? Math.max(0, Math.floor(scrollY)) : 0,
      search: normalizedString(parsed.search),
      primaryCategory: normalizedString(parsed.primaryCategory, 300),
      secondaryCategory: normalizedString(parsed.secondaryCategory, 300),
      categoryLayout: parsed.categoryLayout === "vertical" ? "vertical" : "horizontal",
      expandedCategories: Array.isArray(parsed.expandedCategories)
        ? parsed.expandedCategories
          .filter((item): item is string => typeof item === "string")
          .slice(0, 200)
          .map((item) => item.slice(0, 300))
        : [],
      savedAt,
    };
  } catch {
    window.sessionStorage.removeItem(key);
    return null;
  }
}

export function writeStorefrontViewState(
  slug: string,
  state: Omit<StorefrontViewState, "savedAt">,
) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(storageKey(slug), JSON.stringify({
      ...state,
      savedAt: Date.now(),
    } satisfies StorefrontViewState));
  } catch {
    // Catalog navigation must still work when session storage is unavailable.
  }
}

export function readStorefrontCatalogSnapshot(
  slug: string,
  locale: StorefrontLocale,
): StorefrontCatalogSnapshot | null {
  pruneCatalogSnapshots();
  const key = catalogSnapshotKey(slug, locale);
  const snapshot = catalogSnapshots.get(key);
  if (!snapshot) return null;
  catalogSnapshots.delete(key);
  catalogSnapshots.set(key, snapshot);
  return snapshot;
}

export function writeStorefrontCatalogSnapshot(
  slug: string,
  locale: StorefrontLocale,
  snapshot: Omit<StorefrontCatalogSnapshot, "locale" | "revision" | "savedAt">,
) {
  const key = catalogSnapshotKey(slug, locale);
  catalogSnapshots.delete(key);
  catalogSnapshots.set(key, {
    ...snapshot,
    products: [...snapshot.products],
    locale,
    revision: currentPublicCatalogRevision(),
    savedAt: Date.now(),
  });
  pruneCatalogSnapshots();
}
