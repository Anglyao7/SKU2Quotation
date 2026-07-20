import { CoreAuthProvider, useCoreAuth } from "../core/AuthContext";
import type { User } from "../types";

export const AuthProvider = CoreAuthProvider;

/** Compatibility view for legacy, unrouted console modules. New code should use useCoreAuth directly. */
export function useAuth() {
  const core = useCoreAuth();
  const user: User | null = core.profile ? {
    id: core.profile.user.id,
    name: core.profile.user.displayName,
    full_name: core.profile.user.displayName,
    email: core.profile.user.email ?? "",
    role: core.hasAnyPermission("system.role_manage", "system.settings_manage") ? "platform_admin" : "merchant_staff",
    tenant_id: core.profile.context.tenantId,
    tenant: core.profile.context.tenantId ? {
      id: core.profile.context.tenantId,
      name: core.profile.context.tenantName ?? "当前工作区",
      slug: "",
      active: true,
      status: "active",
    } : null,
  } : null;
  return { ...core, user };
}
