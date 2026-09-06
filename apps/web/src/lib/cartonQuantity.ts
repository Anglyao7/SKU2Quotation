import type { Sku } from "../types";

const PACKING_KEYS = [
  "装箱数", "装箱数量", "一箱个数", "装箱量", "每箱数量", "每箱个数",
  "packingquantity", "unitspercarton", "packingqty", "unitscarton", "qtyctn", "pcsctn",
  "unidadescaja", "koliadedi", "العددفيالكرتون", "梱包数", "포장수량",
  "unidadescaixa", "unitéscarton", "تعداددرکارتن",
];
const SCALE = 1_000_000;
export const MAX_CART_QUANTITY = 1_000_000;

export function positivePackingQuantity(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  const text = String(value).normalize("NFKC").trim();
  if (!/^(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$/.test(text)) return null;
  const number = Number(text.replaceAll(",", ""));
  return Number.isFinite(number) && number > 0 && number <= MAX_CART_QUANTITY
    && Math.round(number * SCALE) / SCALE === number ? number : null;
}

export function optionPackingQuantity(options?: Record<string, unknown>): number | null {
  const marker = options?._sku2quotation as Record<string, unknown> | undefined;
  if (marker && typeof marker === "object") {
    if ("order_packing_quantity" in marker) return positivePackingQuantity(marker.order_packing_quantity);
    if (marker.quote_source_option_values && typeof marker.quote_source_option_values === "object") {
      return optionPackingQuantity(marker.quote_source_option_values as Record<string, unknown>);
    }
  }
  const normalized = Object.fromEntries(Object.entries(options || {}).map(([key, value]) => [
    key.toLowerCase().replace(/[\s\-_/：:()（）]+/g, ""), value,
  ]));
  for (const key of PACKING_KEYS) if (key in normalized) return positivePackingQuantity(normalized[key]);
  return null;
}

export function skuCartonSize(sku?: Pick<Sku, "packing_quantity" | "option_values">): number | null {
  if (!sku) return null;
  // Explicit null from the API means per-piece, even if an old translation has a carton label.
  return sku.packing_quantity !== undefined
    ? positivePackingQuantity(sku.packing_quantity) : optionPackingQuantity(sku.option_values);
}

export function cartQuantity(sku: Sku, quantity: number): number {
  if (!Number.isFinite(quantity) || quantity <= 0) return 0;
  const step = skuCartonSize(sku) || 1;
  const units = Math.round(step * SCALE);
  const count = Math.ceil(Math.round(quantity * SCALE) / units);
  return Math.min(count, Math.floor(MAX_CART_QUANTITY * SCALE / units)) * units / SCALE;
}

export function changeCartQuantity(sku: Sku, quantity: number, cartons: -1 | 1): number {
  return cartQuantity(sku, Math.max(0, Math.round((cartQuantity(sku, quantity) + cartons * (skuCartonSize(sku) || 1)) * SCALE) / SCALE));
}

export function cartCartons(sku: Sku, quantity: number): number | null {
  const size = skuCartonSize(sku);
  return size ? Math.round(quantity * SCALE) / Math.round(size * SCALE) : null;
}
