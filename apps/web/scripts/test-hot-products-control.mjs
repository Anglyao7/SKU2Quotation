import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const page = await fs.readFile(new URL("../src/core/pages/ProductsPage.tsx", import.meta.url), "utf8");
const account = await fs.readFile(new URL("../src/core/pages/AccountSettingsPage.tsx", import.meta.url), "utf8");
assert.ok(!account.includes("hotProducts"), "Account settings must not read or overwrite this setting");
assert.match(page, /canManageStorefront = hasPermission\("system.settings_manage"\)/);
assert.match(page, /canManageStorefront \? \(\s*<div className="core-sku-storefront-options">/);
assert.match(page, /disabled=\{hotProductsEnabled === undefined \|\| hotProductsSaving\}/);

// Exercise the actual event handler without changing any merchant's settings.
const handler = page.match(/  const saveHotProductsEnabled = async[\s\S]*?\n  };/)?.[0];
assert.ok(handler);
const compiled = ts.transpileModule(handler, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText;
function setup(overrides = {}) {
  const state = { enabled: false, saving: false, calls: [], notices: [] };
  const mocks = {
    canManageStorefront: true,
    hotProductsEnabled: false,
    hotProductsSaving: false,
    merchantSettingsSequence: { current: 1 },
    setHotProductsEnabled: value => { state.enabled = value; },
    setHotProductsSaving: value => { state.saving = value; },
    updateMerchantSettings: async input => {
      state.calls.push(input);
      return input;
    },
    notify: (message, options) => state.notices.push({ message, ...options }),
    t: message => message,
    ...overrides,
  };
  const save = new Function(...Object.keys(mocks), `${compiled}; return saveHotProductsEnabled;`)(...Object.values(mocks));
  return { state, save };
}
const success = setup();
await success.save(true);
assert.deepEqual(success.state.calls, [{ hotProductsEnabled: true }]);
assert.equal(success.state.enabled, true);
assert.equal(success.state.saving, false);
assert.equal(success.state.notices[0].kind, "success");

const failure = setup({ updateMerchantSettings: async () => { throw new Error("offline"); } });
await failure.save(true);
assert.equal(failure.state.enabled, false, "Failed saves restore the previous value");
assert.equal(failure.state.saving, false);
assert.equal(failure.state.notices[0].kind, "error");
for (const guards of [{ canManageStorefront: false }, { hotProductsEnabled: undefined }, { hotProductsSaving: true }]) {
  const blocked = setup(guards);
  await blocked.save(true);
  assert.equal(blocked.state.calls.length, 0);
}

const sequence = { current: 1 };
let finishSave;
const stale = setup({ merchantSettingsSequence: sequence, updateMerchantSettings: () => new Promise(resolve => { finishSave = resolve; }) });
const pending = stale.save(true);
sequence.current += 1;
stale.state.enabled = false;
finishSave({ hotProductsEnabled: true });
await pending;
assert.equal(stale.state.enabled, false, "An old workspace's response must not update the current workspace");
assert.equal(stale.state.notices.length, 0);
console.log("Hot product control: placement, permissions, isolated saves, rollback and stale workspace responses passed");
