import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

async function moduleUrl(path, replacements = {}) {
  let source = await fs.readFile(new URL(path, import.meta.url), "utf8");
  for (const [key, value] of Object.entries(replacements)) source = source.replaceAll(key, value);
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
  return `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
}
const quantityUrl = await moduleUrl("../src/lib/cartonQuantity.ts");
const { skuCartonSize, cartQuantity, cartCartons, changeCartQuantity } = await import(quantityUrl);
const { addCartSku, setCartQuantity, refreshCartSkus, readStoreCart, writeStoreCart } = await import(await moduleUrl("../src/lib/storeCart.ts", { '"./cartonQuantity"': JSON.stringify(quantityUrl) }));
const sku = { id: "box", sku_code: "BOX", name: "Carton SKU", price: 10, currency: "USD", tags: [], packing_quantity: "20", option_values: { "Unités / carton": "999" } };
assert.equal(skuCartonSize(sku), 20);
let cart = addCartSku({}, sku);
assert.equal(cart.box.quantity, 20);
assert.equal(cartCartons(sku, cart.box.quantity), 1);
assert.equal(cart.box.quantity * sku.price, 200);
cart.box.note = "Blue packaging";
cart = addCartSku(cart, sku);
assert.equal(cart.box.quantity, 40);
assert.equal(cart.box.quantity * sku.price, 400);
assert.equal(cart.box.note, "Blue packaging");
cart = setCartQuantity(cart, sku.id, changeCartQuantity(sku, cart.box.quantity, -1));
assert.equal(cart.box.quantity, 20);
cart = setCartQuantity(cart, sku.id, changeCartQuantity(sku, cart.box.quantity, -1));
assert.deepEqual(cart, {});
assert.equal(cartQuantity(sku, 1), 20);
assert.equal(cartQuantity(sku, 21), 40);
const perPiece = { ...sku, packing_quantity: null };
assert.equal(addCartSku({}, perPiece).box.quantity, 1, "API null overrides stale translated options");
assert.equal(skuCartonSize({ option_values: { "装箱数": "20" } }), 20);
assert.equal(skuCartonSize({ option_values: { "装箱数": "" } }), null);
assert.equal(skuCartonSize({ option_values: { "装箱数": "24.重量0.2kg" } }), null);
assert.equal(skuCartonSize({ packing_quantity: "0.00000000001" }), null);
const fractional = { ...sku, packing_quantity: "0.1" };
assert.equal(changeCartQuantity(fractional, 0.2, 1), 0.3);
assert.equal(changeCartQuantity(fractional, 0.1, -1), 0);
assert.equal(cartQuantity({ ...sku, packing_quantity: 24 }, 1_000_000), 999984);
assert.equal(refreshCartSkus({ box: { sku: perPiece, quantity: 1 } }, [sku]).box.quantity, 20);
const storage = () => { const data = new Map(); return { getItem: key => data.get(key) || null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) }; };
globalThis.window = { localStorage: storage(), sessionStorage: storage() };
window.localStorage.setItem("smart-trade-cloud:store-cart:child-a", JSON.stringify({ box: { sku, quantity: 1, note: "Keep note" } }));
assert.equal(readStoreCart("child-a").box.quantity, 20);
assert.deepEqual(readStoreCart("parent"), {});
writeStoreCart("child-a", addCartSku(readStoreCart("child-a"), sku));
assert.equal(readStoreCart("child-a").box.quantity, 40);
assert.equal(readStoreCart("child-a").box.note, "Keep note");

for (const path of ["../src/pages/ProductDetailPage.tsx", "../src/pages/SkuDetailPage.tsx"]) {
  const page = await fs.readFile(new URL(path, import.meta.url), "utf8");
  assert.ok(page.includes("addCartSku(current, sku)"));
  assert.ok(!page.includes("?.quantity || 0) + 1"));
}
console.log("Carton ordering: add/remove, subtotal, empty field, decimal precision, old carts, SKU refresh and account isolation passed");
