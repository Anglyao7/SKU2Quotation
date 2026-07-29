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

const errorSource = await fs.readFile(
  new URL("../src/core/authLoginError.ts", import.meta.url),
  "utf8",
);
const compiledErrorSource = ts.transpileModule(errorSource, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
}).outputText;
const errorModuleUrl = `data:text/javascript;base64,${Buffer.from(compiledErrorSource).toString("base64")}`;
const { authLoginMessageKey } = await import(errorModuleUrl);

assert.equal(
  authLoginMessageKey({
    status: 401,
    details: {
      detail: {
        code: "AUTH_INVALID_CREDENTIALS",
        message: "authentication failed",
      },
    },
  }),
  "账号或密码错误，请检查开通时的账号和最近一次设置的密码。",
);
assert.equal(
  authLoginMessageKey({
    status: 429,
    details: { detail: { code: "RATE_LIMITED" } },
  }),
  "登录尝试过于频繁，请稍后再试。",
);
assert.equal(
  authLoginMessageKey({
    status: 503,
    details: { detail: { code: "RATE_LIMIT_UNAVAILABLE" } },
  }),
  "认证服务暂时不可用，请稍后再试。",
);
assert.equal(
  authLoginMessageKey({ status: 0, message: "Failed to fetch" }),
  "无法连接登录服务，请检查网络后重试。",
);
assert.equal(
  authLoginMessageKey(new Error("请输入密码。")),
  "请输入密码。",
);

console.log("Password login error mapping tests passed");
