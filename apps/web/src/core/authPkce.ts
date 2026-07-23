export const OIDC_TRANSACTION_KEY = "atc.oidc.transaction";
const TRANSACTION_TTL_MS = 10 * 60 * 1000;

export interface OidcTransaction {
  state: string;
  nonce: string;
  codeVerifier: string;
  redirectUri: string;
  returnTo: string;
  createdAt: number;
}

export interface OidcAuthorizationConfig {
  provider: "enterprise_oidc";
  clientId: string;
  authorizationEndpoint: string;
  scopes: string[];
  codeChallengeMethod: "S256";
}

function base64Url(bytes: Uint8Array) {
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function randomBase64Url(length: number) {
  return base64Url(crypto.getRandomValues(new Uint8Array(length)));
}

function safeReturnTo(value: string) {
  return value.startsWith("/") && !value.startsWith("//") ? value : "/console";
}

export async function createOidcTransaction(returnTo: string): Promise<{
  transaction: OidcTransaction;
  codeChallenge: string;
}> {
  const codeVerifier = randomBase64Url(64);
  const transaction: OidcTransaction = {
    state: randomBase64Url(32),
    nonce: randomBase64Url(32),
    codeVerifier,
    redirectUri: `${window.location.origin}/login/callback`,
    returnTo: safeReturnTo(returnTo),
    createdAt: Date.now(),
  };
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(codeVerifier),
  );
  window.sessionStorage.setItem(OIDC_TRANSACTION_KEY, JSON.stringify(transaction));
  return { transaction, codeChallenge: base64Url(new Uint8Array(digest)) };
}

export function consumeOidcTransaction(returnedState: string | null): OidcTransaction {
  const raw = window.sessionStorage.getItem(OIDC_TRANSACTION_KEY);
  window.sessionStorage.removeItem(OIDC_TRANSACTION_KEY);
  if (!raw || !returnedState) throw new Error("登录状态已失效，请重新发起登录。");
  let transaction: OidcTransaction;
  try {
    transaction = JSON.parse(raw) as OidcTransaction;
  } catch {
    throw new Error("登录状态无效，请重新发起登录。");
  }
  if (
    typeof transaction.state !== "string"
    || transaction.state !== returnedState
    || typeof transaction.nonce !== "string"
    || typeof transaction.codeVerifier !== "string"
    || transaction.codeVerifier.length < 43
    || transaction.redirectUri !== `${window.location.origin}/login/callback`
    || !Number.isFinite(transaction.createdAt)
    || Date.now() - transaction.createdAt > TRANSACTION_TTL_MS
    || Date.now() < transaction.createdAt - 30_000
  ) {
    throw new Error("登录校验失败，请重新发起登录。");
  }
  return { ...transaction, returnTo: safeReturnTo(transaction.returnTo) };
}

export function buildOidcAuthorizationUrl(
  config: OidcAuthorizationConfig,
  transaction: OidcTransaction,
  codeChallenge: string,
) {
  const url = new URL(config.authorizationEndpoint);
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", transaction.redirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", config.scopes.join(" "));
  url.searchParams.set("state", transaction.state);
  url.searchParams.set("nonce", transaction.nonce);
  url.searchParams.set("code_challenge", codeChallenge);
  url.searchParams.set("code_challenge_method", config.codeChallengeMethod);
  return url.toString();
}
