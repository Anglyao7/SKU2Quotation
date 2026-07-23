import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { webcrypto } from "node:crypto";
import ts from "typescript";

const values = new Map();
if (!globalThis.crypto) {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto });
}
globalThis.window = {
  location: { origin: "https://app.example.test" },
  sessionStorage: {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  },
};

const source = await fs.readFile(
  new URL("../src/core/authPkce.ts", import.meta.url),
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
  OIDC_TRANSACTION_KEY,
  buildOidcAuthorizationUrl,
  consumeOidcTransaction,
  createOidcTransaction,
} = await import(moduleUrl);

const created = await createOidcTransaction("//evil.example/steal");
assert.ok(created.transaction.codeVerifier.length >= 43);
assert.equal(created.transaction.returnTo, "/console");
assert.match(created.codeChallenge, /^[A-Za-z0-9_-]{43}$/);

const authorizationUrl = new URL(buildOidcAuthorizationUrl({
  provider: "enterprise_oidc",
  clientId: "atc-web",
  authorizationEndpoint: "https://identity.example.test/authorize",
  scopes: ["openid", "profile", "email"],
  codeChallengeMethod: "S256",
}, created.transaction, created.codeChallenge));
assert.equal(authorizationUrl.searchParams.get("state"), created.transaction.state);
assert.equal(authorizationUrl.searchParams.get("nonce"), created.transaction.nonce);
assert.equal(authorizationUrl.searchParams.get("code_challenge_method"), "S256");
assert.equal(
  authorizationUrl.searchParams.get("redirect_uri"),
  "https://app.example.test/login/callback",
);

assert.throws(
  () => consumeOidcTransaction("attacker-controlled-state"),
  /校验失败/,
);
assert.equal(window.sessionStorage.getItem(OIDC_TRANSACTION_KEY), null);

const valid = await createOidcTransaction("/console/quotes");
const consumed = consumeOidcTransaction(valid.transaction.state);
assert.equal(consumed.returnTo, "/console/quotes");
assert.equal(window.sessionStorage.getItem(OIDC_TRANSACTION_KEY), null);

const expired = await createOidcTransaction("/console");
const expiredValue = JSON.parse(window.sessionStorage.getItem(OIDC_TRANSACTION_KEY));
expiredValue.createdAt = 0;
window.sessionStorage.setItem(OIDC_TRANSACTION_KEY, JSON.stringify(expiredValue));
assert.throws(
  () => consumeOidcTransaction(expired.transaction.state),
  /校验失败/,
);

console.log("OIDC PKCE/state/open-redirect tests passed");
