import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(
  new URL("../src/lib/api.ts", import.meta.url),
  "utf8",
);
const localeSource = await fs.readFile(
  new URL("../src/lib/storefrontLocale.ts", import.meta.url),
  "utf8",
);
const localeTypes = await fs.readFile(
  new URL("../src/types.ts", import.meta.url),
  "utf8",
);
const languageSettingsSource = await fs.readFile(
  new URL("../src/core/pages/StorefrontLanguageSettings.tsx", import.meta.url),
  "utf8",
);
const coreStyles = await fs.readFile(
  new URL("../src/core/core.css", import.meta.url),
  "utf8",
);
const coreApiSource = await fs.readFile(
  new URL("../src/core/api.ts", import.meta.url),
  "utf8",
);
const consolePackHookSource = await fs.readFile(
  new URL("../src/core/useConsoleCatalogLanguagePack.ts", import.meta.url),
  "utf8",
);
const productsPageSource = await fs.readFile(
  new URL("../src/core/pages/ProductsPage.tsx", import.meta.url),
  "utf8",
);
const resellerProductsPageSource = await fs.readFile(
  new URL("../src/core/pages/ResellerProductsPage.tsx", import.meta.url),
  "utf8",
);
const coreUiSource = await fs.readFile(
  new URL("../src/core/CoreUi.tsx", import.meta.url),
  "utf8",
);
const coreLanguagePackSource = await fs.readFile(
  new URL("../src/core/catalogLanguagePack.ts", import.meta.url),
  "utf8",
);
const coreProductDetailLocalization = coreLanguagePackSource.slice(
  coreLanguagePackSource.indexOf("export function localizeCoreProductDetail("),
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
  productDetail.includes("storeProductPath(slug, productId, undefined, accountId);"),
  "Product details must request source data before applying a language package",
);
assert.ok(
  skuDetail.includes("storeSkuPath(slug, skuId, undefined, accountId);"),
  "SKU details must request source data before applying a language package",
);
assert.ok(
  source.includes("storePath(slug, locale, accountId)"),
  "Store metadata must preserve the visitor's selected locale",
);
assert.ok(
  source.includes("LANGUAGE_PACK_DESCRIPTOR_TIMEOUT_MS"),
  "A missing or unreachable language-pack descriptor must have a short timeout",
);
for (const locale of ["fr", "fa"]) {
  assert.ok(
    localeSource.includes(`code: "${locale}"`),
    `Storefront language options must include ${locale}`,
  );
  assert.ok(
    localeTypes.includes(`| "${locale}"`),
    `StorefrontLocale must include ${locale}`,
  );
}

assert.ok(
  languageSettingsSource.includes('${enabled ? " is-enabled" : ""}'),
  "Merchant language cards must follow the customer's current enabled selection",
);
assert.match(
  coreStyles,
  /\.language-package-option\.is-enabled\s*\{[^}]*color:\s*white;[^}]*background:\s*color-mix\(in srgb, var\(--core-success\) 88%, var\(--core-surface\)\);/s,
  "Enabled merchant language cards must use an unmistakable green background",
);
assert.ok(
  coreStyles.includes(".language-package-option.is-pending:not(.is-enabled)"),
  "A language being disabled must not retain the green selected state",
);

assert.ok(
  coreApiSource.includes("/catalog/translations/language-pack/${encodeURIComponent(targetLocale)}"),
  "Authenticated console catalog localization must use the tenant-scoped language-pack endpoint",
);
assert.ok(
  consolePackHookSource.includes("useConsoleCatalogLanguagePack"),
  "Console pages must share one tenant-scoped language-pack loader",
);
assert.ok(
  productsPageSource.includes("useConsoleCatalogLanguagePack()"),
  "The staff product catalog must load the authenticated console language pack",
);
assert.ok(
  !productsPageSource.includes("api.getStoreLanguagePack(tenantSlug, locale)"),
  "The staff console must not depend on public storefront language enablement",
);
assert.ok(
  resellerProductsPageSource.includes("useConsoleCatalogLanguagePack()")
    && resellerProductsPageSource.includes("localizeProductDetail(selectedSource, activeLanguagePack)"),
  "Customer subaccounts must use the same tenant translations for products and SKU details",
);
assert.ok(
  coreUiSource.includes('import { ThinkingOrb } from "thinking-orbs";')
    && coreUiSource.includes('<ThinkingOrb state="working" size={64} speed={1.3}'),
  "Console catalog language loading must reuse the storefront search animation",
);
for (const [name, pageSource] of [
  ["staff product catalog", productsPageSource],
  ["reseller product catalog", resellerProductsPageSource],
]) {
  assert.ok(
    pageSource.includes("languagePackLoading ? (")
      && pageSource.includes("<CoreCatalogLanguageLoading"),
    `${name} must hide source-language rows while a language pack is loading`,
  );
}
assert.ok(
  !resellerProductsPageSource.includes("以下价格按当前账号规则展示"),
  "The reseller catalog must not show explanatory pricing annotations",
);
assert.ok(
  !coreProductDetailLocalization.includes("if (!translation) return product;"),
  "SKU translations must still apply when a product-level translation is unavailable",
);

console.log("Storefront language fallback tests passed");
