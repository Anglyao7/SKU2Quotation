import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(new URL("../src/lib/storefrontAccount.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { consoleStorefrontPath, isCanonicalAccountStorefront } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`,
);
const membershipId = "11111111-1111-4111-8111-111111111111";
const child = { tenantSlug: "merchant", membershipId, accountScope: "CUSTOMER_SUBACCOUNT" };
const legacy = `/merchant/account/account--${membershipId}`;
assert.equal(consoleStorefrontPath({ ...child, storefrontPath: "/aaa" }), "/aaa");
assert.equal(consoleStorefrontPath(child), legacy);
for (const storefrontPath of ["/merchant", "/MERCHANT/", "/", "//merchant", "/%6derchant", "/merchant?lang=en-US"]) {
  assert.equal(consoleStorefrontPath({ ...child, storefrontPath }), legacy);
}
assert.equal(consoleStorefrontPath({ ...child, membershipId: undefined }), "/console");
assert.equal(consoleStorefrontPath({ ...child, accountScope: "STAFF" }), "/merchant");

const store = { slug: "aaa", account_id: membershipId, storefront_scope: "CUSTOMER_SUBACCOUNT" };
assert.equal(isCanonicalAccountStorefront(store, "merchant", membershipId), true);
for (const invalid of [
  { ...store, slug: "merchant" },
  { ...store, slug: "" },
  { ...store, account_id: undefined },
  { ...store, account_id: "22222222-2222-4222-8222-222222222222" },
  { ...store, storefront_scope: "MERCHANT" },
]) {
  assert.equal(isCanonicalAccountStorefront(invalid, "merchant", membershipId), false);
}

// Execute the real loader functions with a mocked API, not just string checks.
const app = await fs.readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const loaderSource = app.slice(app.indexOf("async function storefrontLoader("), app.indexOf("function LegacyStoreRedirect("));
const loaders = ts.transpileModule(`${loaderSource}\nreturn { storefrontLoader, storefrontProductLoader, storefrontSkuLoader, storefrontCustomPageLoader };`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
}).outputText;
let responseStore = store;
let calls = 0;
let snapshot;
class ApiError extends Error {}
const api = {
  getStore: async () => { calls++; return responseStore; },
  prefetchStoreProducts: async () => ({}),
};
const functions = new Function("api", "ApiError", "redirect", "parseStorefrontLocale", "storefrontAccountMembershipId", "storefrontStorageScope", "storefrontBasePath", "legacyStorefrontBasePath", "isCanonicalAccountStorefront", "readStorefrontCatalogSnapshot", "readStorefrontViewState", loaders)(
  api, ApiError, (url) => url, (value) => value, () => membershipId,
  (slug) => slug, (slug) => `/${slug}`, (slug, key) => `/${slug}/account/${key}`,
  isCanonicalAccountStorefront, () => snapshot, () => undefined,
);
for (const [name, suffix, params] of [
  ["storefrontLoader", "/me", {}],
  ["storefrontProductLoader", "/products/product-1", { productId: "product-1" }],
  ["storefrontSkuLoader", "/skus/sku-1", { skuId: "sku-1" }],
  ["storefrontCustomPageLoader", "/pages/page-1", { pageSlug: "page-1" }],
]) {
  const args = { params: { tenantSlug: "merchant", accountKey: `account--${membershipId}`, ...params }, request: new Request(`https://example.test/merchant/account/account--${membershipId}${suffix}?lang=en-US`) };
  responseStore = store;
  assert.equal(await functions[name](args), `/aaa${suffix}?lang=en-US`);
  responseStore = { ...store, slug: "merchant" };
  await assert.rejects(functions[name](args), (error) => error instanceof Response && error.status === 409);
}
snapshot = { store: { slug: "merchant" } };
responseStore = store;
calls = 0;
assert.deepEqual(await functions.storefrontLoader({ params: { tenantSlug: "aaa" }, request: new Request("https://example.test/aaa?lang=en-US") }), store);
assert.equal(calls, 1, "A stale parent snapshot must be refreshed, never followed as a redirect");
console.log("Child storefront routes: safe console links, all 4 legacy loaders, identity mismatch and stale snapshots passed");
