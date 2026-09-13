import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import http from "node:http";
import { createServer } from "vite";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");
const [products, categories, reseller, dialog, api, nginx, vite] = await Promise.all([
  read("../src/core/pages/ProductsPage.tsx"), read("../src/core/components/CategoryManager.tsx"),
  read("../src/core/pages/ResellerProductsPage.tsx"), read("../src/core/components/CatalogShareDialog.tsx"),
  read("../src/core/api.ts"), read("../nginx.conf"), read("../vite.config.ts"),
]);
assert.match(products, /productIds: \[\.\.\.selectedProductIds\]/);
assert.match(products, /productIds: \[product\.id\]/);
assert.match(products, /canSelect = canDelete \|\| canShare/);
assert.match(categories, /onClick=\{\(\) => onShareCategory\(root\)\}/);
assert.match(categories, /onClick=\{\(\) => onShareCategory\(child\)\}/);
assert.match(reseller, /onShare=\{\(\) => setShareTarget/);
assert.match(reseller, /categoryId: item\.id/);
assert.match(dialog, /productIds: target\.productIds/);
assert.match(dialog, /targetType: "STOREFRONT"/);
assert.match(products, /type: "STOREFRONT"/);
assert.match(dialog, /url\.searchParams\.set\("lang", locale\)/);
assert.match(dialog, /useState<StorefrontLocale>\("en-US"\)/);
assert.match(dialog, /setShareLocale\("en-US"\)/);
assert.match(dialog, /STOREFRONT_LANGUAGE_OPTIONS\.map/);
assert.match(api, /product_ids: input\.productIds \?\? \[\]/);
assert.match(nginx, /\/api\/store\/\$1\/shares\/\$2\/preview break/);
assert.match(nginx, /location ~ "\^\/\(\[\^\/\]\+\)\/share/);
assert.match(vite, /changeOrigin: false/);

const source = await read("../../api/app/routers/catalog_shares.py");
const script = source.match(/"const link = document[^\n]+"\s*\n\s*"if \(link[^\n]+"/)[0]
  .split("\n").map((line) => JSON.parse(line.trim().replace(/,$/, ""))).join("");
for (const destination of ["https://shop.test/alice?share=12345678&lang=en-US", "https://other.test/", null]) {
  let redirected;
  vm.runInNewContext(script, {
    URL,
    document: { querySelector: () => destination ? { href: destination } : null },
    location: { origin: "https://shop.test", replace: (value) => { redirected = value; } },
  });
  assert.equal(redirected, destination?.startsWith("https://shop.test/") ? destination : undefined);
}
console.log("Catalog sharing entry points, routing and safe navigation checks passed.");

// Exercise the real Vite proxy with a hermetic local backend. Never touches a
// development database or production API; backend HTML is covered by pytest.
const upstream = http.createServer((request, response) => {
  response.setHeader("Content-Type", "application/json");
  response.end(JSON.stringify({ path: request.url, host: request.headers.host }));
});
await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
const priorTarget = process.env.VITE_PROXY_TARGET;
process.env.VITE_PROXY_TARGET = `http://127.0.0.1:${upstream.address().port}`;
let preview;
try {
  preview = await createServer({
    configFile: new URL("../vite.config.ts", import.meta.url).pathname,
    server: { port: 0, host: "127.0.0.1", hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
    logLevel: "error",
  });
  await preview.listen();
  const port = preview.httpServer.address().port;
  const response = await fetch(`http://127.0.0.1:${port}/alice/share/12345678?lang=en-US`);
  const request = await response.json();
  assert.equal(request.path, "/api/store/alice/shares/12345678/preview?lang=en-US");
  assert.equal(request.host, `127.0.0.1:${port}`);
  console.log("Real development proxy preserves share scope, locale and public host.");
} finally {
  await preview?.close();
  await new Promise((resolve) => upstream.close(resolve));
  if (priorTarget === undefined) delete process.env.VITE_PROXY_TARGET;
  else process.env.VITE_PROXY_TARGET = priorTarget;
}
