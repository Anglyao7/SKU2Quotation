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
  getCurrentUser,
  getPermissions,
  listMemberships,
  loginEnterpriseOidc,
  loginLocalDemo,
  logoutSession,
  refreshAuthSession,
  switchTenant as switchTenantRequest,
} from "./api";
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
  loginDemo: () => Promise<void>;
  loginOidc: (input: {
    authorizationCode: string;
    codeVerifier: string;
    redirectUri: string;
    nonce: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  switchTenant: (membershipId: string) => Promise<void>;
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (...permissions: string[]) => boolean;
}

const initialState: AuthState = {
  status: "restoring",
  memberships: [],
  permissions: new Set<string>(),
};

const CoreAuthContext = createContext<CoreAuthContextValue | null>(null);

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "认证服务暂时不可用";
}

export function CoreAuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(initialState);

  const hydrate = useCallback(async (session: AuthTokenData) => {
    const memberships = await listMemberships();
    if (session.requiresTenantSelection || !session.context.tenantId) {
      setState({ status: "selecting_tenant", session, memberships, permissions: new Set() });
      return;
    }
    const [profile, permissionSet] = await Promise.all([getCurrentUser(), getPermissions()]);
    setState({
      status: "authenticated",
      session,
      profile,
      memberships,
      permissions: new Set(permissionSet.permissions),
    });
  }, []);

  useEffect(() => {
    let active = true;
    void refreshAuthSession()
      .then(async (session) => {
        if (!active) return;
        if (!session) {
          setState({ ...initialState, status: "anonymous" });
          return;
        }
        await hydrate(session);
      })
      .catch((reason) => {
        if (active) setState({ ...initialState, status: "anonymous", error: errorMessage(reason) });
      });
    const expire = () => {
      clearCoreAuthSession();
      setState({ ...initialState, status: "anonymous", error: "会话已失效，请重新登录。" });
    };
    window.addEventListener("atc:auth-expired", expire);
    return () => {
      active = false;
      window.removeEventListener("atc:auth-expired", expire);
    };
  }, [hydrate]);

  const loginDemo = useCallback(async () => {
    setState((current) => ({ ...current, status: "restoring", error: undefined }));
    try {
      await hydrate(await loginLocalDemo());
    } catch (reason) {
      setState({ ...initialState, status: "anonymous", error: errorMessage(reason) });
      throw reason;
    }
  }, [hydrate]);

  const loginOidc = useCallback(async (input: {
    authorizationCode: string;
    codeVerifier: string;
    redirectUri: string;
    nonce: string;
  }) => {
    setState((current) => ({ ...current, status: "restoring", error: undefined }));
    try {
      await hydrate(await loginEnterpriseOidc(input));
    } catch (reason) {
      setState({ ...initialState, status: "anonymous", error: errorMessage(reason) });
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
    let enterpriseEndSession: string | undefined;
    try {
      enterpriseEndSession = await logoutSession();
    } catch {
      clearCoreAuthSession();
    }
    setState({ ...initialState, status: "anonymous" });
    if (enterpriseEndSession) window.location.assign(enterpriseEndSession);
  }, []);

  const value = useMemo<CoreAuthContextValue>(() => ({
    ...state,
    loading: state.status === "restoring",
    loginDemo,
    loginOidc,
    logout,
    switchTenant,
    hasPermission: (permission) => state.permissions.has(permission),
    hasAnyPermission: (...permissions) => permissions.length === 0 || permissions.some((permission) => state.permissions.has(permission)),
  }), [loginDemo, loginOidc, logout, state, switchTenant]);

  return <CoreAuthContext.Provider value={value}>{children}</CoreAuthContext.Provider>;
}

export function useCoreAuth() {
  const value = useContext(CoreAuthContext);
  if (!value) throw new Error("useCoreAuth 必须在 CoreAuthProvider 内使用");
  return value;
}
