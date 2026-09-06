import type { Sku } from "../types";
import { cartQuantity, changeCartQuantity } from "./cartonQuantity";

export interface StoredCartLine {
  sku: Sku;
  quantity: number;
  note?: string;
}

export type StoredCart = Record<string, StoredCartLine>;

const CART_STORAGE_VERSION = 1;
const CART_TTL_MS = 30 * 24 * 60 * 60 * 1_000;

interface StoredCartEnvelope {
  version: typeof CART_STORAGE_VERSION;
  expiresAt: number;
  cart: StoredCart;
}

function storageKey(slug: string) {
  return `smart-trade-cloud:store-cart:${slug.toLocaleLowerCase()}`;
}

function sanitizeCart(value: unknown): StoredCart {
  if (!value || typeof value !== "object") return {};
  const cart: StoredCart = {};
  Object.entries(value as Record<string, unknown>).forEach(([skuId, entry]) => {
    if (!entry || typeof entry !== "object") return;
    const line = entry as { sku?: Sku; quantity?: number; note?: string };
    const quantity = Number(line.quantity);
    if (!line.sku || line.sku.id !== skuId || !Number.isFinite(quantity) || quantity <= 0) return;
    const normalized = cartQuantity(line.sku, quantity);
    if (normalized <= 0) return;
    cart[skuId] = {
      sku: line.sku,
      quantity: normalized,
      note: typeof line.note === "string" ? line.note.slice(0, 1000) : undefined,
    };
  });
  return cart;
}

export function setCartQuantity(cart: StoredCart, skuId: string, quantity: number): StoredCart {
  if (!cart[skuId]) return cart;
  const next = { ...cart };
  const normalized = cartQuantity(next[skuId].sku, quantity);
  if (normalized <= 0) delete next[skuId];
  else next[skuId] = { ...next[skuId], quantity: normalized };
  return next;
}

export function addCartSku(cart: StoredCart, sku: Sku): StoredCart {
  return { ...cart, [sku.id]: { sku, quantity: changeCartQuantity(sku, cart[sku.id]?.quantity || 0, 1), note: cart[sku.id]?.note } };
}

export function refreshCartSkus(cart: StoredCart, skus: Sku[]): StoredCart {
  const next = { ...cart };
  for (const sku of skus) if (next[sku.id]) {
    next[sku.id] = { ...next[sku.id], sku, quantity: cartQuantity(sku, next[sku.id].quantity) };
  }
  return next;
}

export function readStoreCart(slug: string): StoredCart {
  if (typeof window === "undefined") return {};
  const key = storageKey(slug);
  try {
    const raw = window.localStorage.getItem(key);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<StoredCartEnvelope> | StoredCart;
      if ("cart" in parsed && "expiresAt" in parsed) {
        const expiresAt = Number(parsed.expiresAt);
        if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
          window.localStorage.removeItem(key);
          return {};
        }
        return sanitizeCart(parsed.cart);
      }
      const migrated = sanitizeCart(parsed);
      writeStoreCart(slug, migrated);
      return migrated;
    }

    const legacyRaw = window.sessionStorage.getItem(key);
    if (!legacyRaw) return {};
    const migrated = sanitizeCart(JSON.parse(legacyRaw));
    writeStoreCart(slug, migrated);
    window.sessionStorage.removeItem(key);
    return migrated;
  } catch {
    return {};
  }
}

export function writeStoreCart(slug: string, cart: StoredCart) {
  if (typeof window === "undefined") return;
  const key = storageKey(slug);
  try {
    if (Object.keys(cart).length) {
      const envelope: StoredCartEnvelope = {
        version: CART_STORAGE_VERSION,
        expiresAt: Date.now() + CART_TTL_MS,
        cart: sanitizeCart(cart),
      };
      window.localStorage.setItem(key, JSON.stringify(envelope));
    } else {
      window.localStorage.removeItem(key);
    }
    window.sessionStorage.removeItem(key);
  } catch {
    // A blocked or full local store must not prevent catalog browsing.
  }
}
