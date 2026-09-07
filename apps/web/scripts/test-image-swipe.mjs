import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(new URL("../src/lib/imageSwipe.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { createImageSwipeHandlers } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
let cases = 0;

function fixture({ count = 3, initial = 1, pointerType = "touch" } = {}) {
  let index = initial;
  const steps = [];
  const captured = new Set();
  const element = {
    closest: () => element,
    setPointerCapture: id => captured.add(id),
    hasPointerCapture: id => captured.has(id),
    releasePointerCapture: id => captured.delete(id),
  };
  const handlers = createImageSwipeHandlers(step => {
    steps.push(step);
    index = Math.max(0, Math.min(count - 1, index + step));
  });
  const send = (type, x = 100, y = 100, overrides = {}) => {
    const event = {
      pointerId: 1, isPrimary: true, pointerType, button: 0,
      currentTarget: element, target: element, clientX: x, clientY: y,
      cancelable: true, detail: 1, prevented: false, stopped: false,
      preventDefault() { this.prevented = true; },
      stopPropagation() { this.stopped = true; }, ...overrides,
    };
    handlers[type](event);
    return event;
  };
  return { handlers, send, steps, captured, element, index: () => index };
}

for (const pointerType of ["touch", "mouse", "pen"]) {
  for (const [endX, expected] of [[20, 2], [180, 0]]) {
    const f = fixture({ pointerType });
    f.send("onPointerDown");
    assert.equal(f.send("onPointerMove", endX, 105).prevented, true);
    f.send("onPointerUp", endX, 105);
    assert.equal(f.index(), expected);
    assert.equal(f.steps.length, 1);
    assert.equal(f.captured.size, 0);
    assert.equal(f.send("onClickCapture").prevented, true, "Swiping must not open the lightbox");
    f.send("onPointerDown");
    f.send("onPointerUp", 103, 102);
    assert.equal(f.send("onClickCapture").prevented, false, "A subsequent tap must still open the lightbox");
    cases++;
  }
}

for (const [x, y] of [[105, 200], [180, 180], [125, 102]]) {
  const f = fixture();
  f.send("onPointerDown");
  f.send("onPointerMove", x, y);
  f.send("onPointerUp", x, y);
  assert.equal(f.steps.length, 0, "Vertical, diagonal, and short drags cannot switch images");
  assert.equal(f.send("onClickCapture").prevented, true);
  cases++;
}
{
  const f = fixture();
  f.send("onPointerDown");
  assert.equal(f.send("onPointerMove", 103, 130).prevented, false, "Leave vertical page scrolling native");
  f.send("onPointerMove", 200, 140);
  f.send("onPointerUp", 200, 140);
  assert.equal(f.steps.length, 0, "A vertical scroll must not turn into a swipe halfway through");
  cases++;
}
for (const cancel of ["onPointerCancel", "onLostPointerCapture", "second-finger"]) {
  const f = fixture();
  f.send("onPointerDown");
  f.send("onPointerMove", 20, 105);
  if (cancel === "second-finger") f.send("onPointerDown", 150, 100, { isPrimary: false, pointerId: 2 });
  else f.send(cancel);
  f.send("onPointerUp", 20, 105);
  assert.equal(f.steps.length, 0, "Cancellation/pinch zoom must not change the image");
  assert.equal(f.captured.size, 0);
  assert.equal(f.send("onClickCapture", 0, 0, { detail: 0 }).prevented, false, "Keep keyboard activation");
  cases++;
}
for (const options of [{ count: 1, initial: 0 }, { count: 3, initial: 2 }]) {
  const f = fixture(options);
  f.send("onPointerDown");
  f.send("onPointerUp", 20, 100);
  assert.equal(f.index(), options.initial, "Last/single image cannot go out of bounds");
  assert.equal(f.send("onClickCapture").prevented, true);
  cases++;
}
{
  const f = fixture({ initial: 0 });
  f.send("onPointerDown");
  f.send("onPointerUp", 200, 100);
  assert.equal(f.index(), 0, "First image stays in bounds");
  cases++;
}
{
  const f = fixture();
  f.send("onPointerDown", 100, 100, { button: 2 });
  f.send("onPointerUp", 20, 100, { button: 2 });
  assert.equal(f.steps.length, 0, "Ignore right mouse button");
  const arrow = { closest: () => ({}) };
  f.send("onPointerDown", 100, 100, { target: arrow });
  f.send("onPointerUp", 20, 100, { target: arrow });
  assert.equal(f.steps.length, 0);
  assert.equal(f.send("onClickCapture").prevented, false, "Keep arrow button clicks");
  cases++;
}
{
  const f = fixture();
  f.send("onPointerDown");
  f.send("onPointerUp", 20, 100, { pointerId: 2 });
  assert.equal(f.steps.length, 0);
  f.send("onPointerUp", 20, 100);
  assert.deepEqual(f.steps, [1]);
  assert.equal(f.send("onDragStart").prevented, true, "Disable native image ghost dragging");
  cases++;
}

const component = await fs.readFile(new URL("../src/components/ProductImagePreview.tsx", import.meta.url), "utf8");
assert.equal(component.match(/\{\.\.\.swipeHandlers\}/g)?.length, 2, "Wire both inline gallery and lightbox");
assert.equal(component.match(/draggable=\{false\}/g)?.length, 2);
const css = await fs.readFile(new URL("../src/styles.css", import.meta.url), "utf8");
assert.match(css, /\.sku-detail-image-gallery \.sku-detail-image-trigger,\s*\.product-image-lightbox-stage\s*\{\s*touch-action: pan-y pinch-zoom;/, "Swipe policy must outrank the generic mobile button rule");
console.log(`Image swipe: ${cases} gesture cases passed; inline/lightbox wiring and native scroll/zoom policy checked`);
