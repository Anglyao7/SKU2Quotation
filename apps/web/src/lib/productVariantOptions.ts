import type { Sku } from "../types";

const TEMPLATE_MARKER_KEY = "_sku2quotation";
const FALLBACK_DIMENSION_KEY = "__sku__";
const NON_VARIANT_OPTION_KEYS = new Set([
  TEMPLATE_MARKER_KEY,
  "商品编码",
  "商品型号",
  "规格名称",
  "备注",
  "一箱个数",
  "装箱数",
  "毛重",
  "起定数",
  "是否是新品",
]);
const PACKING_QUANTITY_OPTION_KEYS = new Set([
  "装箱数量",
  "装箱数",
  "一箱个数",
  "packingquantity",
  "unitspercarton",
  "packingqty",
  "unitscarton",
  "unidadescaja",
  "koliadedi",
  "العددفيالكرتون",
  "梱包数",
  "포장수량",
  "unidadescaixa",
]);

export interface ProductVariantChoice {
  value: string;
  label: string;
}

export interface ProductVariantDimension {
  key: string;
  label: string;
  choices: ProductVariantChoice[];
}

interface ProductVariantItem {
  sku: Sku;
  values: Record<string, string>;
}

export interface ProductVariantModel {
  dimensions: ProductVariantDimension[];
  items: ProductVariantItem[];
}

interface ProductVariantLabels {
  fallbackDimension: string;
  fallbackValue: string;
}

function optionText(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  return null;
}

function normalizedOptionKey(value: string): string {
  return value.toLocaleLowerCase().replace(/[\s\-_/：:()（）]+/g, "");
}

export function skuPackingQuantity(sku: Sku | undefined): string | null {
  if (!sku?.option_values) return null;
  for (const [key, value] of Object.entries(sku.option_values)) {
    if (!PACKING_QUANTITY_OPTION_KEYS.has(normalizedOptionKey(key))) continue;
    return optionText(value);
  }
  return null;
}

function templateVariantKeys(sku: Sku): string[] {
  const marker = sku.option_values?.[TEMPLATE_MARKER_KEY];
  if (!marker || typeof marker !== "object" || Array.isArray(marker)) return [];
  const keys = (marker as Record<string, unknown>).variant_option_keys;
  if (!Array.isArray(keys)) return [];
  return keys
    .map((key) => (typeof key === "string" ? key.trim() : ""))
    .filter(Boolean);
}

function fallbackChoiceLabels(skus: Sku[], fallbackValue: string) {
  const baseLabels = skus.map((sku) => (
    sku.specification?.trim()
    || sku.name?.trim()
    || fallbackValue
  ));
  const counts = new Map<string, number>();
  for (const label of baseLabels) {
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  return baseLabels.map((label, index) => (
    (counts.get(label) || 0) > 1
      ? `${label} · ${skus[index].sku_code}`
      : label
  ));
}

function fallbackModel(
  skus: Sku[],
  labels: ProductVariantLabels,
): ProductVariantModel {
  const choiceLabels = fallbackChoiceLabels(skus, labels.fallbackValue);
  return {
    dimensions: [{
      key: FALLBACK_DIMENSION_KEY,
      label: labels.fallbackDimension,
      choices: skus.map((sku, index) => ({
        value: sku.id,
        label: choiceLabels[index],
      })),
    }],
    items: skus.map((sku) => ({
      sku,
      values: { [FALLBACK_DIMENSION_KEY]: sku.id },
    })),
  };
}

export function buildProductVariantModel(
  skus: Sku[],
  labels: ProductVariantLabels,
): ProductVariantModel {
  if (!skus.length) return { dimensions: [], items: [] };

  const explicitKeys: string[] = [];
  for (const sku of skus) {
    for (const key of templateVariantKeys(sku)) {
      if (!explicitKeys.includes(key)) explicitKeys.push(key);
    }
  }

  const discoveredKeys: string[] = [];
  if (!explicitKeys.length) {
    for (const sku of skus) {
      for (const [key, value] of Object.entries(sku.option_values || {})) {
        if (
          !NON_VARIANT_OPTION_KEYS.has(key)
          && optionText(value)
          && !discoveredKeys.includes(key)
        ) {
          discoveredKeys.push(key);
        }
      }
    }
  }

  const sourceKeys = explicitKeys.length ? explicitKeys : discoveredKeys;
  const usableKeys = sourceKeys.filter((key) => (
    skus.every((sku) => optionText(sku.option_values?.[key]))
    && (
      explicitKeys.length > 0
      || new Set(skus.map((sku) => optionText(sku.option_values?.[key]))).size > 1
    )
  ));

  if (!usableKeys.length) return fallbackModel(skus, labels);

  const items: ProductVariantItem[] = skus.map((sku) => ({
    sku,
    values: Object.fromEntries(
      usableKeys.map((key) => [key, optionText(sku.option_values?.[key]) || ""]),
    ),
  }));
  const dimensions: ProductVariantDimension[] = usableKeys.map((key) => {
    const values = Array.from(new Set(items.map((item) => item.values[key])));
    return {
      key,
      label: key,
      choices: values.map((value) => ({ value, label: value })),
    };
  });

  const signatures = new Set(
    items.map((item) => usableKeys.map((key) => item.values[key]).join("\u001f")),
  );
  if (signatures.size !== items.length) {
    dimensions.push({
      key: FALLBACK_DIMENSION_KEY,
      label: "SKU",
      choices: skus.map((sku) => ({
        value: sku.id,
        label: sku.sku_code,
      })),
    });
    for (const item of items) item.values[FALLBACK_DIMENSION_KEY] = item.sku.id;
  }

  return { dimensions, items };
}

export function selectedVariantValues(
  model: ProductVariantModel,
  skuId: string,
): Record<string, string> {
  return model.items.find((item) => item.sku.id === skuId)?.values || {};
}

export function skuIdForVariantChoice(
  model: ProductVariantModel,
  currentSkuId: string,
  dimensionKey: string,
  value: string,
): string {
  const candidates = model.items.filter((item) => item.values[dimensionKey] === value);
  if (!candidates.length) return currentSkuId;

  const currentValues = selectedVariantValues(model, currentSkuId);
  let best = candidates[0];
  let bestScore = -1;
  for (const candidate of candidates) {
    const score = model.dimensions.reduce((total, dimension) => (
      dimension.key !== dimensionKey
      && candidate.values[dimension.key] === currentValues[dimension.key]
        ? total + 1
        : total
    ), 0);
    if (score > bestScore) {
      best = candidate;
      bestScore = score;
    }
  }
  return best.sku.id;
}
