import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(
  new URL("../src/core/accountPassword.ts", import.meta.url),
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
  buildPasswordChangePayload,
  passwordRules,
  passwordStrength,
  validatePasswordChange,
} = await import(moduleUrl);

const securePassword = "123456";
const rules = passwordRules(securePassword, ["owner@example.com"]);
assert.equal(rules.every((rule) => rule.met), true);
assert.equal(passwordStrength(securePassword, rules), "ready");

const weakRules = passwordRules("12345", ["owner@example.com"]);
assert.equal(weakRules.find((rule) => rule.key === "length").met, false);
assert.equal(weakRules.find((rule) => rule.key === "digits").met, true);
assert.equal(passwordStrength("short1", weakRules), "progressing");

for (const validPassword of ["123456", "987654", "000001"]) {
  assert.equal(
    passwordRules(validPassword, ["owner@example.com"]).every((rule) => rule.met),
    true,
  );
}

for (const invalidPassword of ["short1", "12345", "1234567", "12345a", "１２３４５６"]) {
  assert.equal(
    passwordRules(invalidPassword, ["owner@example.com"]).some((rule) => !rule.met),
    true,
  );
}

assert.equal(
  passwordRules("1234567", [])
    .find((rule) => rule.key === "length").met,
  false,
);

assert.equal(
  passwordRules("123 56", [])
    .find((rule) => rule.key === "digits").met,
  false,
);

assert.equal(
  passwordRules("OWNER@EXAMPLE.COM", ["owner@example.com"])
    .find((rule) => rule.key === "digits").met,
  false,
);

assert.deepEqual(
  validatePasswordChange({
    currentPassword: "",
    newPassword: "12345",
    confirmation: "123456",
    identityCandidates: [],
  }),
  {
    currentPassword: "请输入当前密码",
    newPassword: "新密码还未满足全部安全要求",
    confirmation: "两次输入的新密码不一致",
  },
);

assert.deepEqual(
  validatePasswordChange({
    currentPassword: "Oldpass1",
    newPassword: securePassword,
    confirmation: securePassword,
    identityCandidates: ["owner@example.com"],
  }),
  {},
);

assert.deepEqual(
  buildPasswordChangePayload("  current stays exact  ", "  new stays exact A1!  "),
  {
    current_password: "  current stays exact  ",
    new_password: "  new stays exact A1!  ",
  },
);

console.log("Account password validation tests passed");

const [apiSource, pageSource, layoutSource, appSource] = await Promise.all([
  fs.readFile(new URL("../src/core/api.ts", import.meta.url), "utf8"),
  fs.readFile(new URL("../src/core/pages/AccountSettingsPage.tsx", import.meta.url), "utf8"),
  fs.readFile(new URL("../src/pages/console/ConsoleLayout.tsx", import.meta.url), "utf8"),
  fs.readFile(new URL("../src/App.tsx", import.meta.url), "utf8"),
]);

assert.match(apiSource, /request<void>\("\/auth\/password"/);
assert.match(apiSource, /method:\s*"PUT"/);
assert.match(apiSource, /"X-CSRF-Token":\s*csrfToken/);
assert.match(pageSource, /autoComplete="current-password"/);
assert.match(pageSource, /autoComplete="new-password"/);
assert.match(pageSource, /aria-live="polite"/);
assert.match(pageSource, /isCustomerSubaccount/);
assert.match(pageSource, /\{canManageMerchant \? <Card className="account-merchant-card">/);
assert.match(layoutSource, /<DropdownMenu\.Root>/);
assert.match(layoutSource, /to="\/console\/account"/);
assert.match(layoutSource, /退出登录/);
assert.match(appSource, /path:\s*"account",\s*element:\s*<AccountSettingsPage \/>/);
assert.match(appSource, /profile\?\.context\.accountScope === "CUSTOMER_SUBACCOUNT"[\s\S]*?<ResellerProductsPage \/>/);
assert.match(appSource, /profile\?\.context\.accountScope === "CUSTOMER_SUBACCOUNT"[\s\S]*?<ResellerOrdersPage \/>/);
assert.match(appSource, /return <Navigate to="\/console" replace \/>/);

console.log("Account settings route and API contract tests passed");
