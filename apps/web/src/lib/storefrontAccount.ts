const ACCOUNT_SEPARATOR = "--";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function accountNameSlug(value: string) {
  const normalized = value.normalize("NFKC").trim().toLocaleLowerCase();
  let result = "";
  let separatorPending = false;
  for (const character of normalized) {
    if (/^[\p{L}\p{N}]$/u.test(character)) {
      if (separatorPending && result) result += "-";
      result += character;
      separatorPending = false;
    } else {
      separatorPending = Boolean(result);
    }
  }
  return result.replace(/-+$/u, "").slice(0, 80) || "account";
}

export function storefrontAccountKey(displayName: string, membershipId: string) {
  return `${accountNameSlug(displayName)}${ACCOUNT_SEPARATOR}${membershipId.toLocaleLowerCase()}`;
}

export function storefrontAccountMembershipId(accountKey?: string | null) {
  const value = String(accountKey || "").trim();
  const separatorIndex = value.lastIndexOf(ACCOUNT_SEPARATOR);
  if (separatorIndex < 1) return undefined;
  const membershipId = value.slice(separatorIndex + ACCOUNT_SEPARATOR.length);
  return UUID_PATTERN.test(membershipId) ? membershipId.toLocaleLowerCase() : undefined;
}

export function storefrontBasePath(storefrontSlug: string) {
  return `/${encodeURIComponent(storefrontSlug)}`;
}

export function legacyStorefrontBasePath(tenantSlug: string, accountKey: string) {
  return `${storefrontBasePath(tenantSlug)}/account/${encodeURIComponent(accountKey)}`;
}

export function storefrontStorageScope(tenantSlug: string, accountId?: string | null) {
  return accountId
    ? `${tenantSlug}:account:${accountId}`
    : tenantSlug;
}

export function consoleStorefrontPath(context?: {
  tenantSlug?: string;
  membershipId?: string;
  storefrontPath?: string;
  accountScope?: string;
}) {
  const tenantSlug = context?.tenantSlug?.trim() || "";
  if (context?.accountScope !== "CUSTOMER_SUBACCOUNT") {
    return tenantSlug ? storefrontBasePath(tenantSlug) : "/console";
  }
  const path = context.storefrontPath?.trim() || "";
  if (/^\/[^/?#]+\/?$/u.test(path) && !path.startsWith("//")) {
    try {
      const slug = decodeURIComponent(path.replace(/^\/|\/$/gu, ""));
      if (slug.toLocaleLowerCase() !== tenantSlug.toLocaleLowerCase()) return path;
    } catch { /* An invalid path must not select the merchant storefront. */ }
  }
  const membershipId = context.membershipId || "";
  return tenantSlug && UUID_PATTERN.test(membershipId)
    ? legacyStorefrontBasePath(tenantSlug, storefrontAccountKey("account", membershipId))
    : "/console";
}

export function isCanonicalAccountStorefront(
  store: { slug: string; account_id?: string | null; storefront_scope?: string },
  parentSlug: string,
  membershipId: string,
) {
  return store.storefront_scope === "CUSTOMER_SUBACCOUNT"
    && store.account_id?.toLocaleLowerCase() === membershipId.toLocaleLowerCase()
    && Boolean(store.slug.trim())
    && store.slug.trim().toLocaleLowerCase() !== parentSlug.trim().toLocaleLowerCase();
}
