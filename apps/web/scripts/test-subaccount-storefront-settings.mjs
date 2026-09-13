import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const read = (path) => fs.readFile(new URL(path, import.meta.url), "utf8");
const compiled = ts.transpileModule(await read("../src/core/storefrontPermissions.ts"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { canManageOwnStorefront } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const permissions = (...values) => (code) => values.includes(code);
assert.equal(canManageOwnStorefront("CUSTOMER_SUBACCOUNT", permissions("customer_portal.access")), true);
assert.equal(canManageOwnStorefront("CUSTOMER_SUBACCOUNT", permissions("system.settings_manage")), false);
assert.equal(canManageOwnStorefront("STAFF", permissions("customer_portal.access")), false);
assert.equal(canManageOwnStorefront("STAFF", permissions("system.settings_manage")), true);
assert.equal(canManageOwnStorefront(undefined, permissions()), false);

const app = await read("../src/App.tsx");
for (const path of ["storefront", "storefront/brand"]) {
  const route = app.split("\n").find(line => line.includes(`path: "${path}"`));
  assert.ok(route?.includes("allowOwnStorefront"), `${path} allows only the scoped storefront exception`);
}
const languagesRoute = app.split("\n").find(line => line.includes('path: "languages"'));
assert.ok(languagesRoute?.includes("PlatformAdminGate"), "storefront language assignments are platform-admin managed");
for (const path of ["products/categories", "supply-chain", "platform/translations"]) {
  const route = app.split("\n").find(line => line.includes(`path: "${path}"`));
  assert.ok(route && !route.includes("allowOwnStorefront"), `${path} retains existing permissions`);
}
for (const page of ["StorefrontLanguageSettings", "StorefrontFooterSettings", "AccountSettingsPage", "StorefrontCatalogDisplaySettings"]) {
  assert.ok((await read(`../src/core/pages/${page}.tsx`)).includes("canManageOwnStorefront"));
}
const languages = await read("../src/core/pages/StorefrontLanguageSettings.tsx");
assert.ok(languages.includes("configuredStorefrontLocales"));
assert.ok(languages.includes("该语言包未配置，请联系管理员。"));
for (const page of ["StorePage", "ProductDetailPage", "SkuDetailPage"]) {
  const source = await read(`../src/pages/${page}.tsx`);
  assert.ok(source.includes("<strong>{store.name}</strong>"), "The public storefront's own branding is authoritative");
  assert.ok(!source.includes("accountName || store.name"));
}
console.log("Subaccount storefront controls: scoped access, shared-pack validation and independent branding passed");
