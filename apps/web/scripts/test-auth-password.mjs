import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(
  new URL("../src/core/authCredentials.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { buildPasswordLoginPayload } = await import(moduleUrl);

const email = buildPasswordLoginPayload("  owner@example.com  ", "Secret 123!");
assert.deepEqual(email, {
  grant_type: "password",
  identifier: "owner@example.com",
  password: "Secret 123!",
  device_label: "智贸云 Web",
});

assert.equal(
  buildPasswordLoginPayload("+8613812345678", "phone-password").identifier,
  "+8613812345678",
);
assert.equal(
  buildPasswordLoginPayload("merchant-owner", "  keep-password-spaces  ").password,
  "  keep-password-spaces  ",
);
assert.throws(
  () => buildPasswordLoginPayload("   ", "Secret 123!"),
  /账号、邮箱或手机号/,
);
assert.throws(
  () => buildPasswordLoginPayload("owner@example.com", ""),
  /请输入密码/,
);

console.log("Password login payload tests passed");
