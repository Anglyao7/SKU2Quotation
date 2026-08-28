import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(
  new URL("../src/lib/api.ts", import.meta.url),
  "utf8",
);

function section(start, end) {
  const startIndex = source.indexOf(start);
  assert.notEqual(startIndex, -1, `Missing source section: ${start}`);
  const endIndex = source.indexOf(end, startIndex + start.length);
  assert.notEqual(endIndex, -1, `Missing source boundary: ${end}`);
  return source.slice(startIndex, endIndex);
}

const skuList = section(
  "async function getCachedStoreSkus(",
  "async function getCachedStoreProducts(",
);
const productList = section(
  "async function getCachedStoreProducts(",
  "async function download(",
);
const productDetail = section(
  "async getStoreProduct(",
  "prefetchStoreProduct:",
);
const imageSearch = section(
  "async searchStoreProductsByImage(",
  "prefetchStoreProducts:",
);
const skuDetail = section(
  "async getStoreSku(",
  "recordStoreSkuView:",
);

for (const [name, catalogSource] of [
  ["SKU list", skuList],
  ["product list", productList],
  ["image search", imageSearch],
]) {
  assert.ok(
    !catalogSource.includes('params.set("locale"'),
    `${name} must request source catalog data instead of foreground translation`,
  );
}

assert.ok(
  productDetail.includes("storeProductPath(slug, productId);"),
  "Product details must request source data before applying a language package",
);
assert.ok(
  skuDetail.includes("storeSkuPath(slug, skuId);"),
  "SKU details must request source data before applying a language package",
);
assert.ok(
  source.includes("storePath(slug, locale)"),
  "Store metadata must preserve the visitor's selected locale",
);
assert.ok(
  source.includes("LANGUAGE_PACK_DESCRIPTOR_TIMEOUT_MS"),
  "A missing or unreachable language-pack descriptor must have a short timeout",
);

console.log("Storefront language fallback tests passed");
