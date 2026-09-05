import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const modules = new Map();
for (const name of ["quoteLocalization", "packingList", "proformaInvoice", "documentExcelPreview"]) {
  const source = await fs.readFile(new URL(`../src/core/${name}.ts`, import.meta.url), "utf8");
  let compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
  for (const [dependency, url] of modules) compiled = compiled.replaceAll(`from "./${dependency}"`, `from "${url}"`);
  modules.set(name, `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
}
const { buildProformaExcelSheet, buildPackingExcelSheet, excelCellText, excelSheetWidth } = await import(modules.get("documentExcelPreview"));
const order = { id: "item1", position: 1, name: "Pet harness", skuCode: "PET-01", specification: "White / L", description: "Not the specification column", imageUrl: "/test-image.png", quantity: 100, unitPrice: 2.5, lineTotal: 250, unitCode: "piece" };
const draft = { customerName: "Elena", customerCompany: "Buyer Co", customerEmail: "buyer@example.test", customerPhone: "+44 123", currency: "USD", validUntil: "2026-09-12T00:00:00Z", items: [order], notes: "Handle carefully", extraInformation: [{ title: "Reference", content: "PO-009" }] };
const invoice = { invoiceNumber: "PI-1", issueDate: "2026-09-05", sellerAddress: "Shanghai", sellerEmail: "sales@example.test", sellerPhone: "+86 123", buyerAddress: "London", sellerContact: "Lin", incoterm: "FOB", paymentTerms: "30% deposit", deliveryTerms: "20 days", shipmentMethod: "Sea", portOfLoading: "Shanghai", portOfDestination: "London", bankName: "Export Bank", bankAddress: "Bank Street", bankAccountNumber: "001002", swiftCode: "EXAMPLE", beneficiaryName: "Exporter", freight: 25.5, remarks: "Freight included" };
const packingItem = { itemId: "item1", barcode: "0012345678905", packingQuantity: "24", cartonLength: "50.0", cartonWidth: "40", cartonHeight: "30", cartonVolume: "", grossWeight: "12.5", cartonCount: "", lastCartonGrossWeight: "2" };
const packing = { packingListNumber: "PL-1", issueDate: "2026-09-05", sellerAddress: "Shanghai", buyerAddress: "London", remarks: "Keep dry", items: [packingItem] };
const snapshot = JSON.stringify({ draft, invoice, packing });
const pi = buildProformaExcelSheet(draft, invoice, [order], "en-US", "Seller Co");
assert.equal(pi.columns.length, 9);
assert.equal(pi.rows[9].kind, "header");
assert.equal(pi.rows[10].cells[4].value, "White / L");
assert.equal(pi.rows[10].cells[1].imageUrl, "/test-image.png");
assert.equal(excelCellText(pi.rows.find((row) => row.kind === "grand-total").cells[8]), "USD 275.50");
const updated = buildProformaExcelSheet(draft, { ...invoice, sellerName: "New Seller", sellerWebsite: "https://example.test", sellerTaxNumber: "T-123", buyerEmail: "", beneficiaryName: "Only beneficiary", bankName: "", bankAddress: "", bankAccountNumber: "", swiftCode: "" }, [{ ...order, name: "Edited name", lineTotal: 300 }], "en-US", "Seller Co");
assert.equal(updated.rows[1].cells[1].value, "New Seller");
assert.equal(updated.rows[6].cells[3].value, "");
assert.equal(updated.rows[10].kind, "header");
assert.equal(updated.rows[11].cells[3].value, "Edited name");
assert.ok(updated.rows.some((row) => row.cells.some((cell) => cell.value === "Only beneficiary")));
assert.equal(excelCellText(updated.rows.find((row) => row.kind === "grand-total").cells[8]), "USD 325.50");
const pl = buildPackingExcelSheet(draft, packing, "en-US", "Seller Co");
assert.equal(pl.columns.length, 12);
assert.equal(pl.rows[4].kind, "header");
assert.equal(pl.rows[5].cells[3].value, "0012345678905");
assert.equal(pl.rows[5].cells[5].value, "50 × 40 × 30");
assert.deepEqual(pl.rows[6].cells.slice(8).map((cell) => cell.value), [5, 100, .3, 52]);
const missing = buildPackingExcelSheet(draft, { ...packing, buyerName: "Ship To", items: [{ ...packingItem, cartonLength: "", cartonWidth: "", cartonHeight: "", packingQuantity: "", grossWeight: "" }] }, "en-US", "Seller Co");
assert.equal(excelCellText(missing.rows[5].cells[4]), "");
assert.deepEqual(missing.rows[6].cells.slice(8).map((cell) => cell.value), [null, 100, null, null]);
assert.ok(missing.rows[3].cells[0].value.includes("Ship To"));
assert.equal(JSON.stringify({ draft, invoice, packing }), snapshot, "Preview must not modify persisted or editor state");
for (const locale of ["zh-CN", "en-US", "es", "tr", "ar", "ja", "ko", "pt", "fr", "fa"]) {
  for (const sheet of [buildProformaExcelSheet(draft, invoice, [order], locale, "Seller Co"), buildPackingExcelSheet(draft, packing, locale, "Seller Co")]) {
    assert.ok(sheet.name);
    assert.ok(excelSheetWidth(sheet) > 1000);
    assert.equal(sheet.rtl, locale === "ar" || locale === "fa");
    for (const row of sheet.rows) assert.equal(row.cells.reduce((sum, cell) => sum + (cell.span ?? 1), 0), sheet.columns.length, "Merged cells must retain column alignment");
  }
}
console.log("Document Excel previews: layout, live edits, parties, images, leading zeros, totals, blanks and 10 locales passed");

const componentSource = await fs.readFile(new URL("../src/core/pages/DocumentExcelPreview.tsx", import.meta.url), "utf8");
let componentCode = ts.transpileModule(componentSource, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
componentCode = componentCode.replace('import "./DocumentExcelPreview.css";', "").replace('from "../documentExcelPreview"', `from "${modules.get("documentExcelPreview")}"`);
for (const name of ["react/jsx-runtime", "@phosphor-icons/react"]) componentCode = componentCode.replaceAll(`from "${name}"`, `from "${import.meta.resolve(name)}"`);
const { DocumentExcelPreview } = await import(`data:text/javascript;base64,${Buffer.from(componentCode).toString("base64")}`);
const { renderToStaticMarkup } = await import("react-dom/server");
const { createElement } = await import("react");
for (const sheet of [pi, pl]) {
  const html = renderToStaticMarkup(createElement(DocumentExcelPreview, { sheet, scale: .75 }));
  assert.ok(html.includes('aria-label="Excel · '));
  assert.ok(html.includes(`colSpan="${sheet.columns.length}"`));
  assert.ok(html.includes('src="/test-image.png"'));
  assert.equal((html.match(/scope="row"/g) || []).length, sheet.rows.length);
}
const escaped = buildProformaExcelSheet(draft, { ...invoice, sellerName: '<script>alert("preview")</script>' }, [order], "fa", "Seller");
const escapedHtml = renderToStaticMarkup(createElement(DocumentExcelPreview, { sheet: escaped, scale: 1 }));
assert.ok(escapedHtml.includes('dir="rtl"'));
assert.ok(escapedHtml.includes("&lt;script&gt;"));
assert.ok(!escapedHtml.includes("<script>"));
console.log("Excel component rendering, row headers, merged cells, images, RTL and text escaping passed");

// Optional parity input generated from the actual server XLSX exporter (no API or database access).
if (process.argv.includes("--verify-export")) {
  const { spawnSync } = await import("node:child_process");
  const { fileURLToPath } = await import("node:url");
  const apiDir = fileURLToPath(new URL("../../api/", import.meta.url));
  const result = spawnSync(`${apiDir}.venv/bin/python`, ["tests/document_excel_preview_fixture.py"], { cwd: apiDir, encoding: "utf8", maxBuffer: 10 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr);
  const normalize = (value) => value === "" || value === undefined ? null : value;
  for (const fixture of JSON.parse(result.stdout)) {
    const sheet = fixture.type === "packing_list" ? buildPackingExcelSheet(fixture.draft, fixture.settings, fixture.locale, fixture.sellerName) : buildProformaExcelSheet(fixture.draft, fixture.settings, fixture.draft.items, fixture.locale, fixture.sellerName);
    const cells = sheet.rows.map((row) => row.cells.flatMap((cell) => [normalize(cell.value), ...Array((cell.span ?? 1) - 1).fill(null)]));
    assert.deepEqual(cells, fixture.cells, `${fixture.type} / ${fixture.locale} / ${fixture.variant}: cells differ from XLSX`);
    const merges = [];
    sheet.rows.forEach((row, rowIndex) => { let column = 1; for (const cell of row.cells) { const span = cell.span ?? 1; if (span > 1) merges.push([rowIndex + 1, column, rowIndex + 1, column + span - 1]); column += span; } });
    assert.deepEqual(merges, fixture.merges, "Merged ranges differ from XLSX");
    assert.deepEqual(sheet.columns, fixture.widths);
    assert.equal(sheet.name, fixture.name);
  }
  console.log("Actual server XLSX export parity passed");
}
