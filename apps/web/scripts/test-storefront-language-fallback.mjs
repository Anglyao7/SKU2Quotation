import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

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
const fixedLocaleGeneratorSource = await fs.readFile(
  new URL("./generate-console-locales.mjs", import.meta.url),
  "utf8",
);
const visitorCenterSource = await fs.readFile(
  new URL("../src/pages/StorefrontVisitorCenterPage.tsx", import.meta.url),
  "utf8",
);
const storefrontPageSource = await fs.readFile(
  new URL("../src/pages/StorePage.tsx", import.meta.url),
  "utf8",
);
const languageTransitionSource = await fs.readFile(
  new URL("../src/components/StorefrontLanguageTransition.tsx", import.meta.url),
  "utf8",
);
const storefrontTopNavigationSource = await fs.readFile(
  new URL("../src/components/StorefrontTopNavigation.tsx", import.meta.url),
  "utf8",
);
const storefrontFooterSource = await fs.readFile(
  new URL("../src/components/StorefrontFooter.tsx", import.meta.url),
  "utf8",
);
const storefrontAccountSource = await fs.readFile(
  new URL("../src/lib/storefrontAccount.ts", import.meta.url),
  "utf8",
);
const appSource = await fs.readFile(
  new URL("../src/App.tsx", import.meta.url),
  "utf8",
);

const storefrontAccountModule = await import(
  `data:text/javascript;base64,${Buffer.from(ts.transpileModule(storefrontAccountSource, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  }).outputText).toString("base64")}`
);

assert.equal(
  storefrontAccountModule.storefrontBasePath("aaa"),
  "/aaa",
  "A child storefront's canonical root must be its own account slug",
);
assert.equal(
  storefrontAccountModule.legacyStorefrontBasePath(
    "main-merchant",
    "aaa--11111111-1111-4111-8111-111111111111",
  ),
  "/main-merchant/account/aaa--11111111-1111-4111-8111-111111111111",
  "The parent-prefixed route must remain isolated as legacy compatibility only",
);
assert.ok(
  (appSource.match(/if \(accountKey && accountId\)/g) || []).length >= 4
    && appSource.includes("`${storefrontBasePath(store.slug)}/products/")
    && appSource.includes("`${storefrontBasePath(store.slug)}/skus/")
    && appSource.includes('const suffix = /\\/me\\/?$/u.test(currentUrl.pathname) ? "/me" : "";'),
  "Legacy child storefront URLs must redirect to canonical account-only paths",
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
  localeSource.includes("consoleLocaleMessage(locale, source)"),
  "Storefront fixed copy must fall back to the complete pre-generated locale dictionary",
);
assert.ok(
  fixedLocaleGeneratorSource.includes('path.join(sourceRoot, "components")')
    && fixedLocaleGeneratorSource.includes('node.expression.text === "storefrontText"')
    && fixedLocaleGeneratorSource.includes('path.join(sourceRoot, "pages", "StorefrontVisitorCenterPage.tsx")'),
  "Fixed locale extraction must include storefront components, direct storefrontText calls, and the visitor account",
);
assert.ok(
  languageTransitionSource.includes('storefrontText(transition.target, "正在切换语言 · {language}"'),
  "The storefront language transition status must use the selected language",
);
assert.ok(
  storefrontTopNavigationSource.includes('aria-label={t("商品前台导航")}')
    && storefrontFooterSource.includes('aria-label={t("页脚链接")}'),
  "Storefront navigation accessibility labels must use the selected language",
);

const personalAccountMessages = [
  "访客个人中心",
  "我的",
  "浏览记录",
  "我的收藏",
  "待确认询价单",
  "已确认询价单",
  "已成交订单",
  "记录仅保存在当前浏览器；商家确认询价或订单后会在这里通知你。",
  "这里还没有内容",
  "提交询价后，处理进度会显示在这里。",
  "商家已确认你的询价单",
  "前往个人中心",
];
for (const locale of ["es", "tr", "ar", "ja", "ko", "pt", "fr", "fa"]) {
  const dictionary = JSON.parse(await fs.readFile(
    new URL(`../src/core/locales/console.${locale}.json`, import.meta.url),
    "utf8",
  ));
  for (const message of personalAccountMessages) {
    assert.ok(
      typeof dictionary[message] === "string"
        && dictionary[message].trim()
        && dictionary[message] !== message,
      `${locale} must pre-translate storefront personal-account copy: ${message}`,
    );
  }
}
assert.ok(
  visitorCenterSource.includes("storefrontText(locale, source, values)"),
  "The storefront visitor account must render fixed copy through storefront localization",
);
assert.ok(
  storefrontPageSource.includes("<ProductGridSkeleton count={8} translate={t} />")
    && storefrontPageSource.includes("<ProductGridSkeleton translate={t} />")
    && storefrontPageSource.includes("translate={t}"),
  "Shared storefront loading, error, and empty states must use the visitor-selected language",
);
for (const message of [
  "内容加载失败",
  "重新加载",
  "商品加载中",
  "切换中…",
  "正在切换",
  "查看上一张图片",
  "查看下一张图片",
  "装箱数",
  "未设置",
]) {
  assert.ok(
    localeSource.includes(`${JSON.stringify(message)}:`),
    `English storefront fixed copy must include: ${message}`,
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
