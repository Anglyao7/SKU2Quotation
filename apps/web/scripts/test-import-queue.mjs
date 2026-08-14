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
  "一次导入多个商品文件，或撤回指定批次与分类。",
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
  "导入批次加载失败",
  "按批次或分类撤回",
  "只撤回该批次新建且之后未被其他导入批次接管的 SKU；既有 SKU 不会被删除。",
  "撤回完成",
  "已撤回 {skus} 个由该批次新建的 SKU，并归档 {products} 个不再包含有效 SKU 的商品。",
  "正在读取导入批次",
  "等待上传文件",
  "已撤回",
  "部分撤回",
  "可撤回",
  "{files} 个文件 · {skus} 个 SKU",
  "撤回范围",
  "选择范围",
  "整个批次（当前可撤回 {count} 个 SKU）",
  "撤回不会恢复字段历史值；只会删除可确认由该批次新建且未被后续批次接管的 SKU。",
  "撤回这个分类",
  "撤回整个批次",
  "暂无可撤回的导入批次",
  "通过“批量导入”上传的文件会显示在这里。",
  "确认撤回这个分类？",
  "确认撤回整个批次？",
  "只会删除所选分类中由该批次新建且未被后续批次接管的 SKU；既有 SKU 与无法确认归属的图片不会被删除。",
  "只会删除该批次新建且未被后续批次接管的 SKU；既有 SKU 与无法确认归属的图片不会被删除。",
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
  productsPageSource.includes("{rollbackError ? <CoreError message={rollbackError} /> : null}"),
  "Rollback failures must remain visible inside the confirmation dialog",
);
[
  "清理不再被商品使用的 R2 图片",
  "独占的 R2 图片也会被清理",
  "只撤回仍属于该批次的 SKU",
].forEach((stalePromise) => {
  assert.ok(!productsPageSource.includes(stalePromise), `Stale rollback promise: ${stalePromise}`);
});

console.log("Import queue and locale tests passed");
