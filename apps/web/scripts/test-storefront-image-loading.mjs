import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(new URL("../src/lib/storefrontImageQueue.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
const observers = [];
class Observer {
  constructor(callback, options) { this.callback = callback; this.options = options; this.targets = new Set(); observers.push(this); }
  observe(element) { this.targets.add(element); }
  unobserve(element) { this.targets.delete(element); }
  disconnect() { this.targets.clear(); }
  deliver(element, isIntersecting) { this.callback([{ target: element, isIntersecting }]); }
}
const images = [];
class TestImage {
  constructor() { images.push(this); }
  removeAttribute(name) { if (name === "src") this.src = ""; }
  complete(ok = true) { if (ok) this.onload?.(); else this.onerror?.(); }
}
const document = { visibilityState: "visible" };
const navigator = { connection: { saveData: false } };
const lib = new Function("IntersectionObserver", "Image", "document", "navigator", `
  const exports = {}; ${compiled}; return exports;
`)(Observer, TestImage, document, navigator);
const tick = () => new Promise((resolve) => setTimeout(resolve, 10));
const queue = new lib.StorefrontImageQueue();
let successes = 0;
const listen = (loaded) => { if (loaded) successes += 1; };

// Observer callbacks arrive in separate groups. Batch scheduling ensures the
// actual visible row wins even when speculative work was registered first.
const background = Array.from({ length: 3 }, (_, i) => queue.request(`next-${i}`, 2, listen));
const near = Array.from({ length: 3 }, (_, i) => queue.request(`near-${i}`, 1, listen));
const visible = Array.from({ length: 5 }, (_, i) => queue.request(`visible-${i}`, 0, listen));
const duplicate = queue.request("visible-0", 0, listen);
await tick();
assert.deepEqual(images.map((image) => image.src), ["visible-0", "visible-1", "visible-2", "visible-3"]);
assert.ok(images.every((image) => image.fetchPriority === "high"));
images[0].complete();
await tick();
assert.equal(successes, 2, "One URL serves both subscribers");
assert.equal(images[4].src, "visible-4");
for (const image of images.slice(1)) image.complete();
await tick();
assert.deepEqual(images.slice(5).map((image) => image.src), ["near-0", "near-1"], "Next row uses two slots, leaving capacity for newly visible cards");
near[2].setPriority(0);
await tick();
assert.equal(images[7].src, "near-2");
assert.equal(images[7].fetchPriority, "high", "Scrolling into view promotes queued work");
assert.equal(images[8].src, "next-0");
assert.equal(images[8].fetchPriority, "low");
await tick();
assert.equal(images.length, 9, "Only one next-page original may be downloading");
for (const item of [...near, ...visible, duplicate]) item.cancel();
background[1].cancel();
images[8].complete(false);
await tick();
assert.equal(images[9].src, "next-2", "Errors release slots; cancelled queued images are never fetched");
for (const image of images) image.complete();
await tick();
const beforeCache = images.length;
queue.request("visible-0", 0, listen);
await tick();
assert.equal(images.length, beforeCache, "Reopening the same original uses the warm URL");
queue.request("visible-0?v=updated", 0, listen);
await tick();
assert.equal(images.at(-1).src, "visible-0?v=updated", "An edited/versioned image is not mistaken for the old original");
images.at(-1).complete();
const old = queue.request("reused", 2);
old.cancel();
queue.request("reused", 0, listen);
old.cancel();
await tick();
assert.equal(images.at(-1).src, "reused", "Repeated cleanup must not remove a new request for the same URL");
images.at(-1).complete();

const priorities = [];
const element = {};
const stop = lib.observeCatalogImage(element, (priority) => priorities.push(priority));
assert.equal(observers.length, 2);
assert.equal(observers[1].options.rootMargin, "0px 0px 320px 0px");
observers[1].deliver(element, true);
observers[0].deliver(element, true);
observers[1].deliver(element, false);
observers[0].deliver(element, false);
assert.deepEqual(priorities, [1, 0, 0, null], "Visible, next-row and offscreen priorities are distinct");
stop();
assert.ok(observers.every((observer) => observer.targets.size === 0));

const beforePrefetch = images.length;
navigator.connection.saveData = true;
lib.prefetchCatalogImages(["save-data"]);
navigator.connection.saveData = false;
document.visibilityState = "hidden";
lib.prefetchCatalogImages(["hidden"]);
document.visibilityState = "visible";
await tick();
assert.equal(images.length, beforePrefetch, "Do not prefetch in data-saving mode or a background tab");
lib.prefetchCatalogImages([null, "", "warm-0", ...Array.from({ length: 24 }, (_, i) => `warm-${i}`)]);
for (let i = 0; i < 8; i += 1) {
  await tick();
  assert.equal(images.length, beforePrefetch + i + 1);
  assert.equal(images.at(-1).src, `warm-${i}`);
  images.at(-1).complete();
}
await tick();
assert.equal(images.length, beforePrefetch + 8, "Warm only the next screen, not the entire page");
const stopPrefetch = lib.prefetchCatalogImages(["leave-0", "leave-1"]);
await tick();
stopPrefetch();
images.at(-1).complete();
await tick();
assert.equal(images.at(-1).src, "leave-0", "Leaving the category cancels unsent preloads");

const page = await fs.readFile(new URL("../src/pages/StorePage.tsx", import.meta.url), "utf8");
assert.match(page, /if \(disposed\) return;[\s\S]*?prefetchCatalogImages\(nextPage.items.map/);
assert.match(page, /rootMargin: "0px 0px 480px 0px"/);
assert.match(page, /disposed = true;\s*stopImages\(\)/);
assert.match(page, /sourceLocale: loadedStore.source_locale,\s*shareToken: shareToken \|\| undefined,\s*accountId,/);
const card = await fs.readFile(new URL("../src/components/ProductCard.tsx", import.meta.url), "utf8");
assert.match(card, /<StorefrontCatalogImage/);
assert.doesNotMatch(card, /loading="lazy"/);
assert.match(page, /deferImages=\{pageScrolling\}/);
assert.match(page, /\|\| pageScrolling/);

const scrollSource = await fs.readFile(new URL("../src/lib/catalogScrollSettled.ts", import.meta.url), "utf8");
const scrollCode = ts.transpileModule(scrollSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
const scrollWindow = new EventTarget();
const onSettled = new Function("window", `const exports = {}; ${scrollCode}; return exports.onCatalogScrollSettled;`)(scrollWindow);
let scrollFinished = 0;
onSettled(() => scrollFinished += 1);
scrollWindow.dispatchEvent(new Event("scroll"));
assert.equal(scrollFinished, 0, "A warm page must not trigger bottom-row downloads while scrolling to the top");
scrollWindow.dispatchEvent(new Event("scrollend"));
assert.equal(scrollFinished, 1);
scrollWindow.dispatchEvent(new Event("scrollend"));
assert.equal(scrollFinished, 1, "Cleanup is idempotent");
const cancelScroll = onSettled(() => scrollFinished += 1);
cancelScroll();
await new Promise((resolve) => setTimeout(resolve, 160));
assert.equal(scrollFinished, 1, "Unmounting cancels pending scroll callbacks");
onSettled(() => scrollFinished += 1);
await new Promise((resolve) => setTimeout(resolve, 160));
assert.equal(scrollFinished, 2, "Idle fallback works when scrollend is unavailable");
console.log("Storefront image concurrency, priorities, cancellation, URL reuse, observation and next-page preloading passed");
