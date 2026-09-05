import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(new URL("../src/core/quoteDocumentNavigation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const { quoteDocumentTab, quoteDocumentSearch, quoteDocumentHref } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

assert.equal(quoteDocumentTab(new URLSearchParams()), "quotation");
assert.equal(quoteDocumentTab(new URLSearchParams("document=unknown")), "quotation");
for (const tab of ["quotation", "proforma", "sales-contract", "commercial-invoice", "packing-list", "customs-declaration"]) {
  assert.equal(quoteDocumentTab(new URLSearchParams(`document=${tab}`)), tab);
}
const current = new URLSearchParams("document=commercial-invoice&source=quotes");
const next = quoteDocumentSearch(current, "proforma");
assert.equal(next.get("source"), "quotes");
assert.equal(next.get("document"), "proforma");
assert.equal(current.get("document"), "commercial-invoice");
assert.equal(quoteDocumentHref("draft-123", "proforma"), "/console/quotes/draft-123/workbench?document=proforma");
assert.equal(quoteDocumentHref("id/with?query", "proforma"), "/console/quotes/id%2Fwith%3Fquery/workbench?document=proforma");
console.log("Document tabs: PI/CI separation, direct entry, reload state and invalid fallback passed");
