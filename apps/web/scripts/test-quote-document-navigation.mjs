import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(new URL("../src/core/quoteDocumentNavigation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const { quoteDocumentTab, quoteDocumentSearch, quoteDocumentHref } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

const localeAvailabilitySource = await fs.readFile(new URL("../src/core/quoteLocaleAvailability.ts", import.meta.url), "utf8");
const localeAvailabilityCompiled = ts.transpileModule(localeAvailabilitySource, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const { availableQuoteLocales } = await import(`data:text/javascript;base64,${Buffer.from(localeAvailabilityCompiled).toString("base64")}`);

assert.equal(quoteDocumentTab(new URLSearchParams()), "quotation");
assert.equal(quoteDocumentTab(new URLSearchParams("document=unknown")), "quotation");
for (const tab of ["quotation", "proforma", "sales-contract", "commercial-invoice", "packing-list", "purchase-order", "customs-declaration"]) {
  assert.equal(quoteDocumentTab(new URLSearchParams(`document=${tab}`)), tab);
}
const current = new URLSearchParams("document=commercial-invoice&source=quotes");
const next = quoteDocumentSearch(current, "proforma");
assert.equal(next.get("source"), "quotes");
assert.equal(next.get("document"), "proforma");
assert.equal(current.get("document"), "commercial-invoice");
assert.equal(quoteDocumentHref("draft-123", "proforma"), "/console/quotes/draft-123/workbench?document=proforma");
assert.equal(quoteDocumentHref("id/with?query", "proforma"), "/console/quotes/id%2Fwith%3Fquery/workbench?document=proforma");
assert.deepEqual(availableQuoteLocales(undefined), []);
assert.deepEqual(availableQuoteLocales({
  storefrontLocales: ["zh-CN", "en-US", "es", "en-US"],
  configuredStorefrontLocales: ["zh-CN", "en-US"],
}), ["zh-CN", "en-US"]);

const workbench = await fs.readFile(new URL("../src/core/pages/QuoteWorkbenchPage.tsx", import.meta.url), "utf8");
assert.ok(workbench.includes('className="quote-item-detail-image-trigger"'), "Quote item detail images must expose a large-image action");
assert.ok(workbench.includes('className="quote-item-image-preview-dialog"'), "Quote item images must open in a dedicated lightbox");
assert.ok(workbench.includes('aria-label={t("关闭图片预览")}'), "The image lightbox must have an accessible close action");
assert.ok(workbench.includes("changeDocumentLocale"), "Quote language changes must persist immediately so localized item data refreshes");
assert.ok(workbench.includes('value="purchase-order"'), "Elite staff workbenches must expose the purchase-order tab");
assert.ok(workbench.includes("canUsePurchaseOrder"), "Purchase orders must remain hidden from customer subaccounts");
assert.ok(workbench.includes('const canViewSupplierData = accountScope === "STAFF"'), "Supplier UI must fail closed unless the account is explicitly staff-owned");
assert.ok(workbench.includes('{canViewSupplierData ? <div className="quote-supplier-section">'), "Supplier details must use the strict staff-only guard");
console.log("Document tabs: PI/CI separation, direct entry, reload state and invalid fallback passed");
