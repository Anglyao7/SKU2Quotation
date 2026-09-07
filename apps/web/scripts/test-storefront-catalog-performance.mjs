import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

// Execute the real request/cache implementation with deterministic I/O. No
// production server, language provider, or browser storage is used by this test.
const source = (await fs.readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"))
  .replaceAll("import.meta.env.VITE_API_BASE_URL", "undefined");
const parsed = ts.createSourceFile("api.ts", source, ts.ScriptTarget.ES2022, true);
const stripped = ts.createPrinter().printFile(ts.factory.updateSourceFile(
  parsed, parsed.statements.filter((statement) => !ts.isImportDeclaration(statement)),
));
const compiled = ts.transpileModule(stripped, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
let now = Date.now();
let revision = 1;
let failNextPage = false;
let releaseDescriptor;
let holdDescriptor = true;
const productRequests = [];
const descriptorRequests = [];
const fakeFetch = async (path) => {
  const url = new URL(path, "https://catalog.test");
  if (url.pathname.includes("/language-packages/")) {
    descriptorRequests.push(path);
    if (holdDescriptor) await new Promise((resolve) => { releaseDescriptor = resolve; });
    return Response.json({ target_locale: url.pathname.split("/").at(-1), version: 1, download_url: "/pack.json" });
  }
  productRequests.push(path);
  if (failNextPage) {
    failNextPage = false;
    return Response.json({ detail: "Temporary failure" }, { status: 502 });
  }
  return Response.json({
    items: [{ id: "p1", name: "商品", sku_count: 1, translation_status: "SOURCE" }],
    total: 1, page: 1, pages: 1, locale: "zh-CN", source_locale: "zh-CN",
  });
};
const mocks = {
  getCoreAccessToken: () => undefined,
  clearCoreAuthSession: () => {},
  publicCatalogCacheKey: (scope, path) => `${revision}:${scope}:${path}`,
  cachedLanguagePack: async (_slug, descriptor) => ({ ...descriptor, source_locale: "zh-CN" }),
  latestCachedLanguagePack: async () => undefined,
  // Incomplete translation is intentional: it used to evict the catalog page.
  localizeProduct: (product) => ({ ...product, translation_status: "FALLBACK" }),
  localizeCategoryOptions: (options) => options,
};
const api = new Function("fetch", "mocks", "Date", `
  const exports = {};
  const { ${Object.keys(mocks).join(", ")} } = mocks;
  ${compiled}
  return exports.api;
`)(fakeFetch, mocks, class extends Date { static now() { return now; } });

const filters = { category: "分类/子分类", locale: "en-US", includeFacets: false };
const pending = api.getStoreProducts("merchant-a", filters);
assert.equal(productRequests.length, 1, "The page request must start before the language package resolves");
assert.equal(descriptorRequests.length, 1);
holdDescriptor = false;
releaseDescriptor();
assert.equal((await pending).items.length, 1);
await Promise.all(Array.from({ length: 5 }, () => api.getStoreProducts("merchant-a", filters)));
assert.equal(productRequests.length, 1, "Partial translation must not discard source data");
assert.equal((await api.prefetchStoreProducts("merchant-a", filters)).items[0].id, "p1",
  "Next-page prefetch returns the cached products so their original images can be warmed");
await api.getStoreProducts("merchant-a", { ...filters, locale: "ja" });
assert.equal(productRequests.length, 1, "Another language must reuse the source page");
assert.equal(new URL(productRequests[0], "https://catalog.test").searchParams.get("locale"), "zh-CN");

for (const isolatedFilters of [
  { ...filters, accountId: "account-b" },
  { ...filters, shareToken: "share-b" },
  { ...filters, sourceLocale: "fr" },
]) await api.getStoreProducts("merchant-a", isolatedFilters);
await api.getStoreProducts("merchant-b", filters);
assert.equal(productRequests.length, 5, "Merchant/account/share/source-language scopes must remain separate");
await api.getStoreProducts("merchant-a", { ...filters, category: "first-load", includeFacets: true });
await api.getStoreProducts("merchant-a", { ...filters, category: "first-load" });
assert.equal(productRequests.length, 6, "The full-facet response must also prime the compact page cache");
revision += 1;
await api.getStoreProducts("merchant-a", filters);
assert.equal(productRequests.length, 7, "Catalog changes must invalidate the page");
now += 120_001;
await api.getStoreProducts("merchant-a", filters);
assert.equal(productRequests.length, 8, "Expired pages must be fetched again");
failNextPage = true;
await assert.rejects(api.getStoreProducts("merchant-a", { ...filters, category: "retry" }));
await api.getStoreProducts("merchant-a", { ...filters, category: "retry" });
assert.equal(productRequests.length, 10, "Failed requests must be retryable");

const pageSource = await fs.readFile(new URL("../src/pages/StorePage.tsx", import.meta.url), "utf8");
assert.match(pageSource, /if \(showCategoryShowcase\) \{[\s\S]*?requestId\.current \+= 1;[\s\S]*?return;/);
assert.match(pageSource, /categoryPrefetchCount\.current >= 2/);
assert.match(pageSource, /connection\?\.saveData \|\| deferredSearch/);
console.log("Catalog request parallelism, caching, isolation, retry and navigation tests passed");
