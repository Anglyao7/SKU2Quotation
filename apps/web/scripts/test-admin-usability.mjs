import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const read = (file) => fs.readFile(new URL(`../src/${file}`, import.meta.url), "utf8");
const compile = (source) => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const importHelper = async (file) => import(`data:text/javascript;base64,${Buffer.from(compile(await read(file))).toString("base64")}`);
const { saveState, acknowledgeEdits } = await importHelper("core/saveState.ts");
assert.equal(saveState({ readOnly: true, saving: false, dirty: true, failed: false }), "READ_ONLY");
assert.equal(saveState({ readOnly: false, saving: true, dirty: true, failed: false }), "SAVING");
assert.equal(saveState({ readOnly: false, saving: false, dirty: true, failed: true }), "FAILED");
assert.equal(saveState({ readOnly: false, saving: false, dirty: true, failed: false }), "UNSAVED");
assert.equal(saveState({ readOnly: false, saving: false, dirty: false, failed: true }), "SAVED");
const oldEdit = { name: "Old edit" }, newEdit = { name: "New edit" };
assert.deepEqual(acknowledgeEdits({ a: newEdit, b: oldEdit }, { a: oldEdit, b: oldEdit }), { a: newEdit });

const { normalizeTaskStatus, activeTaskStates } = await importHelper("core/taskStatus.ts");
for (const value of ["published", "PUBLISHED", "SUCCESS", "SUCCEEDED"]) assert.equal(normalizeTaskStatus(value), "COMPLETED");
assert.equal(normalizeTaskStatus("needs_review"), "REVIEW");
assert.equal(normalizeTaskStatus("failed"), "FAILED");
assert.equal(normalizeTaskStatus("REVOKED"), "REVOKED");
assert.ok(activeTaskStates.has(normalizeTaskStatus("scanning")));

const { filterInquiries, paginateInquiries } = await importHelper("core/inquiryFilters.ts");
const orders = Array.from({ length: 55 }, (_, i) => ({ quoteNumber: `QD-${i}`, customerName: i % 2 ? "Alice" : "张三", customerCompany: "Shop", visitorCountryCode: "US", status: i % 2 ? "CONFIRMED" : "PENDING_CONFIRMATION", createdAt: "2026-09-06T12:00:00", id: i }));
const allFilters = { query: "", status: "", from: "", to: "" };
assert.equal(filterInquiries(orders, { ...allFilters, query: " ALICE " }).length, 27);
assert.equal(filterInquiries(orders, { ...allFilters, query: "us", status: "PENDING_CONFIRMATION" }).length, 28);
assert.equal(filterInquiries(orders, { ...allFilters, from: "2026-09-06", to: "2026-09-06" }).length, 55);
assert.equal(filterInquiries(orders, { ...allFilters, from: "2026-09-07" }).length, 0);
assert.equal(filterInquiries([{ ...orders[0], createdAt: "bad" }], { ...allFilters, to: "2026-09-07" }).length, 0);
assert.equal(paginateInquiries(orders, 2, 20).pageRows[0].id, 20);
assert.equal(paginateInquiries(orders, 99, 20).pageRows.length, 15);
assert.equal(paginateInquiries([], 99, 20).currentPage, 1);

// Compile the actual React callback bodies and exercise the save request race.
const workbench = await read("core/pages/QuoteWorkbenchPage.tsx");
const ast = ts.createSourceFile("QuoteWorkbenchPage.tsx", workbench, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function callback(name, mocks) {
  let result;
  const visit = (node) => {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === name && ts.isCallExpression(node.initializer)) result = node.initializer.arguments[0].getText(ast);
    ts.forEachChild(node, visit);
  };
  visit(ast);
  assert.ok(result, `Missing callback: ${name}`);
  const source = compile(`const callback = ${result};`);
  return new Function(...Object.keys(mocks), `${source}; return callback;`)(...Object.values(mocks));
}
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const pending = deferred();
let edits = { a: oldEdit }, saving = false, failed = false, calls = 0;
const saveBusyRef = { current: false }, failedItemsRef = { current: undefined };
const draft = { id: "draft-a", items: [{ id: "a", name: "Original", unitPrice: 2 }] };
const saveItems = callback("saveAllItemEdits", {
  draft, itemEdits: edits, canEditPrices: true, t: (x) => x, locale: "zh-CN", optionPackingQuantity: () => 0, storefrontText: (l, x) => x,
  saveBusyRef, failedItemsRef, acknowledgeEdits,
  setSavingItems: (v) => { saving = v; }, setSaveFailed: (v) => { failed = v; }, setError() {}, setDraft() {}, setPriceDrafts() {},
  setItemEdits: (f) => { edits = f(edits); }, updatePublicQuoteDraftItems: () => { calls++; return pending.promise; },
});
const savingPromise = saveItems();
assert.ok(saving && saveBusyRef.current);
assert.equal(await saveItems(), undefined);
assert.equal(calls, 1, "Do not overlap item/settings requests");
edits = { a: newEdit };
pending.resolve(draft);
await savingPromise;
assert.equal(edits.a, newEdit, "A completed request must not erase newly typed text");
assert.ok(!saving && !saveBusyRef.current && !failed);

const payload = { locale: "en-US", style: "navy", templateId: null, quoteNumber: "QD-1", visibleColumns: ["name"], extraInformation: [], proformaInvoice: { invoiceNumber: "PI-1", issueDate: "2026-09-07" } };
const savedSettingsRef = { current: { ...payload, quoteNumber: "previous" } };
const latestSettingsRef = { current: payload }, failedSettingsRef = { current: undefined };
const acknowledgedSettingsInputRef = { current: undefined };
let settingChanges = 0, request = deferred();
const persist = callback("persistSettings", {
  activeDocument: "quotation", t: (x) => x, proformaText: (l, x) => x, packingErrors: () => [],
  MAX_PDF_COLUMNS: 5, saveBusyRef, savedSettingsRef, latestSettingsRef, failedSettingsRef, acknowledgedSettingsInputRef,
  quoteSettingsEqual: (a, b) => JSON.stringify(a) === JSON.stringify(b),
  setSaving: (v) => { saving = v; }, setSaveFailed: (v) => { failed = v; }, setError() {}, notify() {}, setDraft() {},
  setQuoteNumber() { settingChanges++; }, setVisibleColumns() {}, setExtraInformation() {}, setProformaInvoice() {}, setPackingList() {},
  updatePublicQuoteDraftSettings: () => request.promise,
});
const settingsPromise = persist(draft, payload, true);
assert.ok(saving, "Quiet autosave still reports saving");
assert.equal(savedSettingsRef.current.quoteNumber, "previous", "Do not claim a save before the server acknowledges it");
latestSettingsRef.current = { ...payload, quoteNumber: "typed-during-save" };
request.resolve({ ...draft, ...payload });
await settingsPromise;
assert.equal(settingChanges, 0, "Preserve settings typed during the request");
assert.equal(savedSettingsRef.current.quoteNumber, "QD-1");
request = deferred();
const failPromise = persist(draft, { ...payload, quoteNumber: "failed" }, true);
request.reject(new Error("offline"));
await failPromise;
assert.equal(savedSettingsRef.current.quoteNumber, "QD-1");
assert.equal(failedSettingsRef.current.quoteNumber, "failed");
assert.ok(failed && !saving && !saveBusyRef.current);
request = deferred();
const incomplete = { ...payload, proformaInvoice: { ...payload.proformaInvoice, invoiceNumber: "" } };
const partialPromise = persist(draft, incomplete, true);
request.resolve({ ...draft, ...payload });
await partialPromise;
assert.equal(acknowledgedSettingsInputRef.current, incomplete);
assert.equal(savedSettingsRef.current.proformaInvoice.invoiceNumber, "PI-1", "Unsaved nested fields remain distinguishable from server values");
assert.ok(workbench.includes("if (quoteSettingsEqual(acknowledgedSettingsInputRef.current, currentSettings)) return;"), "Do not loop autosaves for incomplete sections preserved by the server");
const readOnlyDraft = { ...draft, readOnly: true };
assert.equal(await persist(readOnlyDraft, payload), readOnlyDraft, "Read-only export must not write settings");

const translations = await read("core/pages/LanguagePackagesPage.tsx");
const languageAst = ts.createSourceFile("LanguagePackagesPage.tsx", translations, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const componentKeys = {};
const visitKey = (node) => {
  if (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) {
    const name = node.tagName.getText(languageAst);
    if (["AutomaticTranslationControls", "CatalogTranslationEditor"].includes(name)) {
      componentKeys[name] = node.attributes.properties.find((attribute) => ts.isJsxAttribute(attribute) && attribute.name.getText(languageAst) === "key")?.initializer?.getText(languageAst);
    }
  }
  ts.forEachChild(node, visitKey);
};
visitKey(languageAst);
assert.ok(componentKeys.AutomaticTranslationControls && componentKeys.CatalogTranslationEditor);
assert.notEqual(componentKeys.AutomaticTranslationControls, componentKeys.CatalogTranslationEditor, "Different sibling component types need distinct keys");
for (const key of Object.values(componentKeys)) assert.ok(key.includes("selectedTenantId") && key.includes("selectedLocale"));
const products = await read("core/pages/ProductsPage.tsx");
assert.ok(!/supplier\s*===\s*"—"\s*\?\s*t\("子账号销售价"\)/.test(products));
assert.ok(products.includes('t("销售单价")'));
assert.ok(products.includes('t("移动分类")'), "Batch category changes must be labeled as moving");
assert.ok(!products.includes('t("添加到分类")') && !products.includes("原分类已保留"), "Do not describe category moves as additions");
const apiSource = await read("core/api.ts");
const apiAst = ts.createSourceFile("api.ts", apiSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
const batchCategoryNode = apiAst.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === "batchUpdateSkuCategory");
assert.ok(batchCategoryNode);
const batchCategorySource = compile(batchCategoryNode.getText(apiAst).replace(/^export /, ""));
const categoryCalls = [];
let catalogInvalidations = 0;
const categoryResponse = { success_count: 2, failed_count: 0, affected_product_count: 2 };
const moveCategories = new Function("request", "bumpPublicCatalogRevision", "mapSkuBatchOperationResult", `${batchCategorySource}; return batchUpdateSkuCategory;`)(
  async (path, options) => { categoryCalls.push({ path, ...options, body: JSON.parse(options.body) }); return categoryResponse; },
  () => { catalogInvalidations++; },
  (value) => value,
);
for (const targets of [["target-category"], ["target-category", "another-category"]]) {
  assert.equal(await moveCategories(["product-a", "product-b"], targets), categoryResponse);
  assert.deepEqual(categoryCalls.at(-1), {
    path: "/skus/batch-update-category", method: "POST",
    body: { sku_ids: ["product-a", "product-b"], category_ids: targets, mode: "REPLACE" },
  }, "Send exactly the selected destinations with replacement semantics");
}
assert.equal(catalogInvalidations, 2, "Refresh the storefront catalog after a category move");
assert.ok(products.includes("canEdit && isPlatformAdmin"), "Image enhancement remains admin-only");
const quotes = await read("core/pages/QuotesPage.tsx");
assert.equal(quotes.match(/t\("前往多证工作台"\)/g)?.length, 2, "Inquiry list and detail share the multi-document workbench label");
assert.ok(!quotes.includes('t("制作报价单")'), "Workbench navigation is not limited to creating a quotation");
assert.ok(quotes.includes("canRevise && !row.readOnly"), "Owners cannot modify child quotes");
assert.ok(quotes.includes("canViewHistory ? listQuotations()"), "Inquiry-only users must not request protected quotation history");
const app = await read("App.tsx");
assert.ok(app.includes('path: "inquiries"'), "Preserve the legacy manual inquiry URL");
assert.ok(app.includes('path: "tasks"'));
console.log("Admin usability: save states, request races/failures, inquiry filters/paging, task statuses, translation keys and access boundaries passed");
