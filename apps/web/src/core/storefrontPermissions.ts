export function canManageOwnStorefront(
  accountScope: string | undefined,
  hasPermission: (permission: string) => boolean,
): boolean {
  return accountScope === "CUSTOMER_SUBACCOUNT"
    ? hasPermission("customer_portal.access")
    : hasPermission("system.settings_manage");
}
