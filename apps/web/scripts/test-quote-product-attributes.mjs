import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(new URL("../src/core/quoteProductAttributes.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { quoteAttributeOptions, productAttributeValue, mergeCustomFieldsWithProductAttributes } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);

const items = [
  { id: "first", productAttributes: { "材质": "ABS", "装箱数": "24", "供应商名称": "Private", "空值": "" } },
  { id: "second", productAttributes: { "材质": "PP", "颜色": "蓝", "internal_ai_note": "Private" } },
  { id: "third", productAttributes: { "颜色": "红", "材 质": "钢" } },
];

assert.deepEqual(quoteAttributeOptions(items), [
  { label: "材质", count: 3 },
  { label: "颜色", count: 2 },
  { label: "装箱数", count: 1 },
]);
assert.equal(productAttributeValue(items[1], "材质"), "PP");
assert.deepEqual(mergeCustomFieldsWithProductAttributes([
  { id: "field", label: "材质", values: { first: "手动修改", second: "" } },
], items)[0].values, { first: "手动修改", second: "", third: "钢" });

console.log("Quote product attribute selection and document-only values passed");
