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

const securePassword = "SimplePass42";
const rules = passwordRules(securePassword, ["owner@example.com"]);
assert.equal(rules.every((rule) => rule.met), true);
assert.equal(passwordStrength(securePassword, rules), "strong");

const weakRules = passwordRules("short1", ["owner@example.com"]);
assert.equal(weakRules.find((rule) => rule.key === "length").met, false);
assert.equal(weakRules.find((rule) => rule.key === "letter").met, true);
assert.equal(passwordStrength("short1", weakRules), "progressing");

for (const validPassword of ["Simple42", "ABCDEFG1", "abcdefg1", "Abcd!234"]) {
  assert.equal(
    passwordRules(validPassword, ["owner@example.com"]).every((rule) => rule.met),
    true,
  );
}

for (const invalidPassword of ["short1", "12345678", "abcdefgh", "Abcd 123"]) {
  assert.equal(
    passwordRules(invalidPassword, ["owner@example.com"]).some((rule) => !rule.met),
    true,
  );
}

assert.equal(
  passwordRules(`A1${"b".repeat(127)}`, [])
    .find((rule) => rule.key === "length").met,
  false,
);

assert.equal(
  passwordRules("Secure Trade2026!", [])
    .find((rule) => rule.key === "whitespace").met,
  false,
);

assert.equal(
  passwordRules("OWNER@EXAMPLE.COM", ["owner@example.com"])
    .find((rule) => rule.key === "identity").met,
  false,
);

assert.deepEqual(
  validatePasswordChange({
    currentPassword: "",
    newPassword: "short1",
    confirmation: "different",
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
assert.match(layoutSource, /<DropdownMenu\.Root>/);
assert.match(layoutSource, /to="\/console\/account"/);
assert.match(layoutSource, /退出登录/);
assert.match(appSource, /path:\s*"account",\s*element:\s*<AccountSettingsPage \/>/);

console.log("Account settings route and API contract tests passed");
