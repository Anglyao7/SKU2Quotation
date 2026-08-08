import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  clearCoreAuthSession,
  getAuthBootstrap,
  getCurrentUser,
  listMemberships,
  loginPassword as loginPasswordRequest,
  logoutSession,
  refreshAuthSession,
  switchTenant as switchTenantRequest,
} from "./api";
import { authLoginMessageKey } from "./authLoginError";
import type { AuthTokenData, CurrentUser, MembershipSummary } from "./types";

export type AuthStatus = "restoring" | "anonymous" | "selecting_tenant" | "authenticated";

interface AuthState {
  status: AuthStatus;
  session?: AuthTokenData;
  profile?: CurrentUser;
  memberships: MembershipSummary[];
  permissions: ReadonlySet<string>;
  error?: string;
}

export interface CoreAuthContextValue extends AuthState {
  loading: boolean;
  loginPassword: (identifier: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  switchTenant: (membershipId: string) => Promise<void>;
  reloadProfile: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (...permissions: string[]) => boolean;
}

const initialState: AuthState = {
  status: "restoring",
  memberships: [],
  permissions: new Set<string>(),
};

const CoreAuthContext = createContext<CoreAuthContextValue | null>(null);
const SESSION_RESTORE_RETRY_DELAYS_MS = [250, 750, 1_500, 3_000, 5_000];

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "认证服务暂时不可用";
}

export function CoreAuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(initialState);

  const hydrate = useCallback(async (session: AuthTokenData) => {
    if (session.requiresTenantSelection || !session.context.tenantId) {
      const memberships = session.memberships?.length
        ? session.memberships
        : await listMemberships();
      setState({ status: "selecting_tenant", session, memberships, permissions: new Set() });
      return;
    }
    if (session.permissions && session.permissionVersion !== undefined) {
      const memberships = session.memberships?.length
        ? session.memberships
        : [{
            id: session.context.membershipId || "",
            tenantId: session.context.tenantId,
            tenantName: session.context.tenantName || "",
            tenantSlug: session.context.tenantSlug || "",
            status: "active",
          }];
      setState({
        status: "authenticated",
        session,
        profile: {
          user: session.user,
          context: session.context,
          memberships,
        },
        memberships,
        permissions: new Set(session.permissions),
      });
      return;
    }
    const bootstrap = await getAuthBootstrap();
    const { profile, permissions: permissionSet } = bootstrap;
    setState({
      status: "authenticated",
      session,
      profile,
      memberships: profile.memberships,
      permissions: new Set(permissionSet.permissions),
    });
  }, []);

  useEffect(() => {
    let active = true;
    let restorationStopped = false;
    let retryCount = 0;
    let retryTimer: number | undefined;

    const restore = async () => {
      try {
        const session = await refreshAuthSession();
        if (!active || restorationStopped) return;
        if (!session) {
          setState({ ...initialState, status: "anonymous" });
          return;
        }
        await hydrate(session);
      } catch (reason) {
        if (!active || restorationStopped) return;
        setState({
          ...initialState,
          status: "restoring",
          error: errorMessage(reason),
        });
        const delay = SESSION_RESTORE_RETRY_DELAYS_MS[
          Math.min(retryCount, SESSION_RESTORE_RETRY_DELAYS_MS.length - 1)
        ];
        retryCount += 1;
        retryTimer = window.setTimeout(() => void restore(), delay);
      }
    };

    void restore();
    const expire = () => {
      restorationStopped = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      clearCoreAuthSession();
      setState({ ...initialState, status: "anonymous", error: "会话已失效，请重新登录。" });
    };
    window.addEventListener("atc:auth-expired", expire);
    return () => {
      active = false;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      window.removeEventListener("atc:auth-expired", expire);
    };
  }, [hydrate]);

  const loginPassword = useCallback(async (identifier: string, password: string) => {
    setState((current) => ({ ...current, status: "restoring", error: undefined }));
    try {
      await hydrate(await loginPasswordRequest(identifier, password));
    } catch (reason) {
      setState({
        ...initialState,
        status: "anonymous",
        error: authLoginMessageKey(reason),
      });
      throw reason;
    }
  }, [hydrate]);

  const switchTenant = useCallback(async (membershipId: string) => {
    setState((current) => ({ ...current, status: "restoring", error: undefined }));
    try {
      await hydrate(await switchTenantRequest(membershipId));
      window.dispatchEvent(new CustomEvent("atc:tenant-changed", { detail: { membershipId } }));
    } catch (reason) {
      setState((current) => ({
        ...current,
        status: current.session ? "selecting_tenant" : "anonymous",
        error: errorMessage(reason),
      }));
      throw reason;
    }
  }, [hydrate]);

  const logout = useCallback(async () => {
    try {
      await logoutSession();
    } catch {
      clearCoreAuthSession();
    }
    setState({ ...initialState, status: "anonymous" });
  }, []);

  const reloadProfile = useCallback(async () => {
    const profile = await getCurrentUser();
    setState((current) => ({
      ...current,
      profile,
      memberships: profile.memberships,
      session: current.session
        ? {
            ...current.session,
            user: profile.user,
            context: {
              ...current.session.context,
              tenantName: profile.context.tenantName,
              tenantSlug: profile.context.tenantSlug,
              businessMode: profile.context.businessMode,
              defaultCurrency: profile.context.defaultCurrency,
              defaultWorkspace: profile.context.defaultWorkspace,
              accountScope: profile.context.accountScope,
            },
          }
        : current.session,
    }));
  }, []);

  const value = useMemo<CoreAuthContextValue>(() => ({
    ...state,
    loading: state.status === "restoring",
    loginPassword,
    logout,
    switchTenant,
    reloadProfile,
    hasPermission: (permission) => state.permissions.has(permission),
    hasAnyPermission: (...permissions) => permissions.length === 0 || permissions.some((permission) => state.permissions.has(permission)),
  }), [loginPassword, logout, reloadProfile, state, switchTenant]);

  return <CoreAuthContext.Provider value={value}>{children}</CoreAuthContext.Provider>;
}

export function useCoreAuth() {
  const value = useContext(CoreAuthContext);
  if (!value) throw new Error("useCoreAuth 必须在 CoreAuthProvider 内使用");
  return value;
}
