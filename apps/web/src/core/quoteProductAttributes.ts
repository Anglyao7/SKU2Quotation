import type { PublicQuoteDraft, QuoteCustomField } from "./types";

type QuoteItem = PublicQuoteDraft["items"][number];

export type QuoteAttributeOption = { label: string; count: number };

// Stored in the existing document-scoped custom-field snapshot, but rendered
// as one of the quotation's five configurable product-table columns.
export const QUOTE_ATTRIBUTE_COLUMN_ID = "00000000-0000-4000-8000-000000000001";

const privateAttributeLabel = /supplier|vendor|factory|manufacturer|sourcing|procurement|purchaseprice|cost|internalprice|internal[a-z]*note|internal[a-z]*remark|供应商|供應商|厂家|廠家|工厂|工廠|采购|採購|进货|進貨|成本|内部价|內部價|备注|備註|供货|供貨|^notes?$|^remarks?$/i;

export function isPrivateQuoteAttribute(label: string) {
  return privateAttributeLabel.test(label.replace(/[\s_\-:：,.，。()（）\[\]【】]+/g, ""));
}

export function normalizedQuoteAttributeLabel(label: string) {
  return label.replace(/[\s_\-/:：,.，。()（）\[\]【】]+/g, "").toLocaleLowerCase();
}

export function quoteAttributeText(value: unknown): string {
  if (Array.isArray(value)) return value.map((entry) => String(entry)).join("、");
  if (value && typeof value === "object") return Object.values(value as Record<string, unknown>).map((entry) => String(entry)).join("、");
  return value == null ? "" : String(value);
}

export function productAttributeValue(item: QuoteItem, label: string) {
  const normalized = normalizedQuoteAttributeLabel(label);
  const entry = Object.entries(item.productAttributes ?? {}).find(([key]) => normalizedQuoteAttributeLabel(key) === normalized);
  return quoteAttributeText(entry?.[1]);
}

export function quoteAttributeOptions(items: QuoteItem[]): QuoteAttributeOption[] {
  const options = new Map<string, QuoteAttributeOption>();
  for (const item of items) {
    const seen = new Set<string>();
    for (const [rawLabel, rawValue] of Object.entries(item.productAttributes ?? {})) {
      const label = rawLabel.trim();
      if (!label || isPrivateQuoteAttribute(label) || !quoteAttributeText(rawValue).trim()) continue;
      const key = normalizedQuoteAttributeLabel(label);
      if (seen.has(key)) continue;
      seen.add(key);
      const existing = options.get(key);
      if (existing) existing.count += 1;
      else options.set(key, { label, count: 1 });
    }
  }
  return [...options.values()].sort((left, right) => right.count - left.count || left.label.localeCompare(right.label, "zh-CN"));
}

export function mergeCustomFieldsWithProductAttributes(fields: QuoteCustomField[], items: QuoteItem[]) {
  return fields.map((field) => ({
    ...field,
    values: Object.fromEntries(items.map((item) => [
      item.id,
      field.values[item.id] ?? productAttributeValue(item, field.label),
    ])),
  }));
}
