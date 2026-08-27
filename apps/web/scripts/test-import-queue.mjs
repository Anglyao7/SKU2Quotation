import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(
  new URL("../src/core/importQueueState.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const {
  importFileIdentity,
  removeImportItem,
  resetFailedImportItem,
  selectUniqueImportFiles,
} = await import(moduleUrl);

const first = { name: "products-a.xlsx", size: 100, lastModified: 1 };
const duplicate = { ...first };
const second = { name: "products-b.xlsx", size: 200, lastModified: 2 };

assert.equal(importFileIdentity(first), "products-a.xlsx:100:1");
assert.deepEqual(
  selectUniqueImportFiles([first], [duplicate, second]),
  {
    acceptedFiles: [second],
    capacityRemaining: 99,
    duplicateCount: 1,
    overflowCount: 0,
  },
);
assert.deepEqual(
  selectUniqueImportFiles([], [first, duplicate, second], 1),
  {
    acceptedFiles: [first],
    capacityRemaining: 1,
    duplicateCount: 1,
    overflowCount: 1,
  },
);

const failed = {
  id: "queue-1",
  status: "failed",
  progress: 100,
  detection: { detected_type: "OOXML / XLSX" },
  job: { id: "JOB-1" },
  error: "Import failed",
};
assert.deepEqual(resetFailedImportItem(failed), {
  id: "queue-1",
  status: "checking",
  progress: 0,
  detection: undefined,
  job: undefined,
  error: undefined,
});
assert.deepEqual(
  removeImportItem([failed, { id: "queue-2", status: "ready" }], failed.id),
  [{ id: "queue-2", status: "ready" }],
);

const localeSource = await fs.readFile(
  new URL("../src/core/LocaleContext.tsx", import.meta.url),
  "utf8",
);
[
  "商品批量操作",
  "导入与撤回",
  "一次导入多个商品文件，或选择具体文件撤回它带入的商品。",
  "批量导入",
  "撤回导入",
  "拖入或选择多个商品文件",
  "支持 XLSX，多文件会归入同一批次",
  "检查中",
  "待导入",
  "上传中",
  "失败",
  "详情",
  "移除文件",
  "重试文件",
  "继续添加",
  "导入 {count} 个文件",
  "只接受 .xlsx 商品文件。",
  "文件签名与 XLSX 格式不一致。",
  "每个批次最多选择 100 个文件。",
  "每个批次最多选择 100 个文件，超出的文件未加入。",
  "这些文件已经在当前列表中。",
  "导入文件加载失败",
  "按导入文件撤回",
  "选择一个文件，删除该文件带入的全部 SKU；没有其他 SKU 的商品会同时归档。",
  "撤回完成",
  "已删除该文件带入的 {skus} 个 SKU，并归档 {products} 个不再包含有效 SKU 的商品。",
  "正在读取导入文件",
  "等待上传文件",
  "已撤回",
  "可撤回",
  "带入 {products} 个商品 · {skus} 个 SKU",
  "文件带入的数据",
  "导入时新建商品",
  "导入时新建 SKU",
  "当前将删除",
  "文件来源会永久保留。撤回将删除该文件创建的 SKU，即使这些 SKU 后来被人工编辑过；其他文件创建的 SKU 不受影响。",
  "撤回这个文件",
  "暂无商品导入文件",
  "通过“批量导入”上传的文件会显示在这里。",
  "确认撤回这个文件？",
  "将删除“{filename}”带入的 {count} 个 SKU。没有其他 SKU 的商品会同时归档；这个操作不能恢复。",
  "确认撤回",
  "撤回失败，请稍后重试。",
].forEach((key) => {
  assert.ok(localeSource.includes(`"${key}":`), `Missing English locale key: ${key}`);
});

const productsPageSource = await fs.readFile(
  new URL("../src/core/pages/ProductsPage.tsx", import.meta.url),
  "utf8",
);
assert.ok(
  productsPageSource.includes("listProductCatalog"),
  "The SKU catalog screen must load product-first catalog rows",
);
assert.ok(
  !productsPageSource.includes("const next = await listSkus"),
  "The SKU catalog screen must not use the SKU-only page as its primary list",
);
assert.ok(
  productsPageSource.includes("publicationStatus")
    && productsPageSource.includes('t("是否发布")'),
  "SKU details must expose an editable publication status",
);
assert.ok(
  productsPageSource.includes("{rollbackError ? <CoreError message={rollbackError} /> : null}"),
  "Rollback failures must remain visible inside the confirmation dialog",
);
assert.ok(
  productsPageSource.includes("listCatalogImportFiles")
    && productsPageSource.includes("rollbackCatalogImportFile"),
  "Rollback must be driven by the selected import file",
);
assert.ok(
  !productsPageSource.includes("rollbackCategoryId"),
  "File rollback must not ask the user to choose a category",
);
[
  "清理不再被商品使用的 R2 图片",
  "独占的 R2 图片也会被清理",
  "只撤回仍属于该批次的 SKU",
].forEach((stalePromise) => {
  assert.ok(!productsPageSource.includes(stalePromise), `Stale rollback promise: ${stalePromise}`);
});

console.log("Import queue and locale tests passed");
