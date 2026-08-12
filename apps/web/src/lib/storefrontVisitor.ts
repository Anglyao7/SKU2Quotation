import type { StoreProduct } from "../types";

export interface StorefrontVisitorProduct {
  id: string;
  name: string;
  imageUrl?: string | null;
  priceFrom: number | string;
  priceTo: number | string;
  currency: string;
  category?: string | null;
  savedAt?: string;
  viewedAt?: string;
}

interface VisitorTokenEnvelope {
  version: 1;
  token: string;
  expiresAt: number;
}

const VISITOR_TTL_MS = 180 * 24 * 60 * 60 * 1_000;
const HISTORY_LIMIT = 60;
const FAVORITES_LIMIT = 240;
const memoryVisitorTokens = new Map<string, VisitorTokenEnvelope>();
export const STOREFRONT_VISITOR_EVENT = "atc:storefront-visitor-change";

function normalizedSlug(slug: string) {
  return slug.trim().toLocaleLowerCase();
}

function key(slug: string, name: string) {
  return `aitradecloud:storefront:${normalizedSlug(slug)}:${name}`;
}

function randomToken() {
  const bytes = new Uint8Array(32);
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`.padEnd(64, "0");
}

function emit(slug: string, scope: "profile" | "quotes" = "profile") {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(STOREFRONT_VISITOR_EVENT, { detail: { slug, scope } }));
}

export function notifyStorefrontQuotesChanged(slug: string) {
  emit(slug, "quotes");
}

export function ensureStorefrontVisitorToken(slug: string) {
  if (typeof window === "undefined") return "";
  const storageKey = key(slug, "visitor");
  const memoryKey = normalizedSlug(slug);
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw) {
      const saved = JSON.parse(raw) as Partial<VisitorTokenEnvelope>;
      if (
        saved.version === 1
        && typeof saved.token === "string"
        && saved.token.length >= 32
        && Number(saved.expiresAt) > Date.now()
      ) {
        memoryVisitorTokens.set(memoryKey, saved as VisitorTokenEnvelope);
        return saved.token;
      }
    }
  } catch {
    // Recreate a safe session when local data is malformed or unavailable.
  }
  const memory = memoryVisitorTokens.get(memoryKey);
  if (memory && memory.expiresAt > Date.now()) return memory.token;
  const token = randomToken();
  const envelope = {
    version: 1,
    token,
    expiresAt: Date.now() + VISITOR_TTL_MS,
  } satisfies VisitorTokenEnvelope;
  memoryVisitorTokens.set(memoryKey, envelope);
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(envelope));
  } catch {
    // The current page can still use the in-memory token for this request.
  }
  return token;
}

function productSnapshot(product: StoreProduct): StorefrontVisitorProduct {
  return {
    id: product.id,
    name: product.name,
    imageUrl: product.image_url,
    priceFrom: product.price_from,
    priceTo: product.price_to,
    currency: product.currency,
    category: product.category_label || product.category,
  };
}

function readProducts(slug: string, name: "history" | "favorites") {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key(slug, name)) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is StorefrontVisitorProduct => (
      Boolean(item)
      && typeof item === "object"
      && typeof item.id === "string"
      && typeof item.name === "string"
    ));
  } catch {
    return [];
  }
}

function writeProducts(
  slug: string,
  name: "history" | "favorites",
  products: StorefrontVisitorProduct[],
) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key(slug, name), JSON.stringify(products));
    emit(slug);
  } catch {
    // Browsing remains available when storage is blocked or full.
  }
}

export function readStorefrontHistory(slug: string) {
  return readProducts(slug, "history");
}

export function rememberStorefrontProduct(slug: string, product: StoreProduct) {
  const next = {
    ...productSnapshot(product),
    viewedAt: new Date().toISOString(),
  };
  writeProducts(slug, "history", [
    next,
    ...readStorefrontHistory(slug).filter((item) => item.id !== product.id),
  ].slice(0, HISTORY_LIMIT));
}

export function clearStorefrontHistory(slug: string) {
  writeProducts(slug, "history", []);
}

export function readStorefrontFavorites(slug: string) {
  return readProducts(slug, "favorites");
}

export function isStorefrontFavorite(slug: string, productId: string) {
  return readStorefrontFavorites(slug).some((item) => item.id === productId);
}

export function toggleStorefrontFavorite(slug: string, product: StoreProduct) {
  const current = readStorefrontFavorites(slug);
  const exists = current.some((item) => item.id === product.id);
  const next = exists
    ? current.filter((item) => item.id !== product.id)
    : [{ ...productSnapshot(product), savedAt: new Date().toISOString() }, ...current]
      .slice(0, FAVORITES_LIMIT);
  writeProducts(slug, "favorites", next);
  return !exists;
}

function readStringSet(slug: string, name: "quote-seen" | "quote-notified") {
  if (typeof window === "undefined") return new Set<string>();
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key(slug, name)) || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((value) => typeof value === "string") : []);
  } catch {
    return new Set<string>();
  }
}

function writeStringSet(
  slug: string,
  name: "quote-seen" | "quote-notified",
  values: Iterable<string>,
) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key(slug, name), JSON.stringify(Array.from(values).slice(-500)));
    emit(slug);
  } catch {
    // Notification state is best-effort on privacy-restricted browsers.
  }
}

export function quoteNotificationKey(quote: { id: string; status: string; updated_at: string }) {
  return `${quote.id}:${quote.status}:${quote.updated_at}`;
}

export function readSeenQuoteNotifications(slug: string) {
  return readStringSet(slug, "quote-seen");
}

export function markQuoteNotificationsSeen(slug: string, keys: string[]) {
  const seen = readSeenQuoteNotifications(slug);
  keys.forEach((value) => seen.add(value));
  writeStringSet(slug, "quote-seen", seen);
}

export function readShownQuoteNotifications(slug: string) {
  return readStringSet(slug, "quote-notified");
}

export function markQuoteNotificationShown(slug: string, notificationKey: string) {
  const shown = readShownQuoteNotifications(slug);
  shown.add(notificationKey);
  writeStringSet(slug, "quote-notified", shown);
}
