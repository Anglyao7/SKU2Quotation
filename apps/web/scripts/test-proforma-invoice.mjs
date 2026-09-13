import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(new URL("../src/core/proformaInvoice.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const { invoiceParties, invoiceLabel } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const draft = { customerName: "Elena", customerCompany: "Buyer Co", customerEmail: "buyer@example.test", customerPhone: "+44 123" };
const settings = { sellerPhone: "+86 123", sellerEmail: "seller@example.test", sellerAddress: "Shanghai", buyerAddress: "London" };
const defaults = invoiceParties(settings, draft, "Seller Co");
assert.equal(defaults.seller.name, "Seller Co");
assert.equal(defaults.buyer.name, "Buyer Co");
assert.equal(defaults.buyer.contact, "Elena");
assert.equal(defaults.buyer.email, "buyer@example.test");
assert.equal(invoiceParties(settings, { ...draft, customerCompany: "" }, "Seller Co").buyer.name, "Elena");
const custom = invoiceParties({ ...settings, sellerName: "Export Co", sellerContact: "Marco", buyerName: "Import Co", buyerEmail: "", buyerPhone: "" }, draft, "Seller Co");
assert.equal(custom.seller.name, "Export Co");
assert.equal(custom.seller.contact, "Marco");
assert.equal(custom.buyer.name, "Import Co");
assert.equal(custom.buyer.email, "");
assert.equal(custom.buyer.phone, "");
assert.equal(draft.customerCompany, "Buyer Co");
for (const locale of ["zh-CN", "en-US", "es", "tr", "ar", "ja", "ko", "pt", "fr", "fa", "ru"]) {
  assert.ok(invoiceLabel(locale, 0));
  assert.ok(invoiceLabel(locale, 1));
}
console.log("PI seller/buyer defaults, manual overrides and document labels passed");
