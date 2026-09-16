import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [page, styles] = await Promise.all([
  readFile(new URL("../src/core/pages/ProductsPage.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/core/core.css", import.meta.url), "utf8"),
]);

assert.ok(page.includes('t("前台展示")'), "Product detail should open a storefront-content editor");
assert.ok(page.includes('t("SKU 详情")'), "SKU editing should remain discoverable from the product detail");
assert.ok(!page.includes("productEditing"), "Product fields should not be hidden behind a second edit action");
assert.match(
  page,
  /const updatedProduct = await updateProduct[\s\S]*?updateProductCategory\(product\.id, updatedProduct\.currentVersion/,
  "Product fields and categories should save as one version-safe action",
);
assert.match(
  page,
  /if \(canManageSku\) editSku\(sku\.id\);[\s\S]*?else toggleSkuDetails\(sku\.id\);/,
  "Clicking an editable SKU should open its editor directly",
);
assert.ok(page.includes("checked={row.isVariant}"), "Every specification can be marked as a storefront choice");
assert.ok(page.includes('t("前台展示")'));
assert.ok(page.includes('t("起订数")} · {t("装箱数")'));
assert.ok(page.includes('t("更多信息")'));
assert.ok(page.includes('t(busy ? "保存中…" : "保存")'));
assert.ok(
  page.indexOf('className="core-sku-quick-actions"') < page.indexOf('className="core-sku-editor-section is-storefront"'),
  "SKU save actions should remain visible before the long editor content",
);
assert.match(styles, /\.core-detail-dialog[^}]*1180px/, "The desktop editor needs enough working width");
assert.ok(styles.includes(".core-sku-option-editor-labels"));
assert.match(styles, /\.core-sku-quick-actions \{ position: sticky; top:/);
assert.ok(page.includes("product.images.map"), "The editor should expose every storefront gallery image");
assert.ok(page.includes("replaceProductImage(product.id, selectedImage.id, file)"));
assert.ok(page.includes("uploadProductGalleryImage(product.id, file)"));
assert.ok(page.includes('"新增图片"'), "The image editor should expose an add-image action");
assert.ok(styles.includes(".core-product-image-gallery"));
assert.match(
  styles,
  /\.core-sku-detail-row \{[^}]*grid-template-columns: auto minmax\(210px, 1fr\) minmax\(120px, \.7fr\) 105px auto auto auto;/,
  "The seven desktop SKU row regions should stay on one grid row",
);

console.log("Product detail editor: product fields, gallery, direct SKU editing and storefront specification controls passed");
