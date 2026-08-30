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

export function storefrontBasePath(tenantSlug: string, accountKey?: string | null) {
  const root = `/${encodeURIComponent(tenantSlug)}`;
  return accountKey
    ? `${root}/account/${encodeURIComponent(accountKey)}`
    : root;
}

export function storefrontStorageScope(tenantSlug: string, accountId?: string | null) {
  return accountId
    ? `${tenantSlug}:account:${accountId}`
    : tenantSlug;
}
