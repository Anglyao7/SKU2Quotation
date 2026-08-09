import type {
  AttributeDefinition,
  AnnouncementContentBlock,
  AnnouncementPayload,
  AuthTokenData,
  CategoryLayout,
  CoreProduct,
  CustomerPortalOrder,
  CustomerPortalOverview,
  CustomerSubaccount,
  CustomerSubaccountDashboard,
  CustomerSubaccountOrder,
  CustomerSubaccountOrderPage,
  CurrentUser,
  DashboardSnapshot,
  EmbeddingSettings,
  FileDetection,
  HybridSearchResponse,
  ImportJob,
  InquiryMatch,
  InquiryRecord,
  InventoryDocument,
  InventoryMovement,
  InventoryMovementPage,
  InventoryOverview,
  InventoryStockItem,
  InventoryStockPage,
  KnowledgeIndexStatus,
  KnowledgeIndexJob,
  ManualProductCreateInput,
  MembershipSummary,
  MerchantSettings,
  PermissionSet,
  ProductActivity,
  ProductAttribute,
  ProductCategory,
  ProductDetail,
  ProductOffer,
  ProductSku,
  PurchaseOrder,
  PurchaseOrderSummary,
  PublicCatalogOffer,
  PublicQuoteDraft,
  PublicQuoteDraftSummary,
  QuoteExcelTemplate,
  QuoteExcelTemplateUpdate,
  QuoteTemplateField,
  QuotationRecord,
  QuotationSummary,
  SalesOrder,
  SalesOrderSummary,
  SkuListItem,
  SkuListPage,
  StorefrontAnalyticsSnapshot,
  StorefrontAnnouncement,
  SupportActionSettings,
  SupportAIIngestionJob,
  SupportAIKnowledgeSource,
  SupportAIMode,
  SupportAIProviderSettings,
  SupportAIRun,
  SupportAIRunPage,
  SupportAISettings,
  SupportAutomationState,
  SupportCitation,
  SupportConversationDetail,
  SupportConversationPage,
  SupportConversationStatus,
  SupportSettings,
  SupportTranslationPreview,
  SystemMonitoringSnapshot,
  TenantMember,
  TenantPermission,
  TenantRole,
  TranslationApiSettings,
  TranslationApiTestResult,
  TranslationProviderKind,
  TranslationReasoningEffort,
  CatalogLanguagePackInfo,
  CatalogTranslationJob,
  CatalogTranslationStatus,
  UiLocale,
  Warehouse,
} from "./types";
import type { StorefrontLocale } from "../types";
import { buildPasswordChangePayload } from "./accountPassword";
import { buildPasswordLoginPayload } from "./authCredentials";
import { accessTokenRefreshDelayMs } from "./authSessionTiming";
import { normalizeAnnouncementTickerSpeed } from "./announcementSpeed";
import { bumpPublicCatalogRevision } from "../lib/publicCatalogRevision";
import { resetStorefrontAnnouncementVisit } from "../lib/storefrontAnnouncementVisit";

const CSRF_STORAGE_KEY = "atc.csrfToken";
const TERMINAL_REFRESH_ERROR_CODES = new Set([
  "AUTH_SESSION_EXPIRED",
  "AUTH_REFRESH_REUSE_DETECTED",
]);
let accessToken: string | undefined;
let refreshInFlight: Promise<AuthTokenData | undefined> | undefined;
let authGeneration = 0;
const getRequestsInFlight = new Map<string, Promise<unknown>>();
const getResponseCache = new Map<string, { expiresAt: number; value: unknown }>();
const GET_RESPONSE_CACHE_TTL_MS = 12_000;
const GET_RESPONSE_CACHE_MAX_ENTRIES = 180;
const AUTH_REFRESH_EXEMPT_PATHS = new Set(["/auth/login", "/auth/refresh"]);
let accessTokenRefreshAt = 0;

function resolveApiBase() {
  const configured = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
  if (!configured) return "/api/v1";
  if (configured.endsWith("/api/v1")) return configured;
  if (configured.endsWith("/api")) return `${configured}/v1`;
  return `${configured}/api/v1`;
}

const API_BASE = resolveApiBase();
export const PRODUCT_TEMPLATE_DOWNLOAD_URL = `${API_BASE}/product-template.xlsx`;
export const CATEGORY_TEMPLATE_DOWNLOAD_URL = `${API_BASE}/category-template.xlsx`;

export class CoreApiError extends Error {
  status: number;
  details?: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "CoreApiError";
    this.status = status;
    this.details = details;
  }
}

function messageFromPayload(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") return fallback;
  const body = payload as Record<string, unknown>;
  if (typeof body.detail === "string") return body.detail;
  if (body.detail && typeof body.detail === "object") {
    const detail = body.detail as Record<string, unknown>;
    if (typeof detail.message === "string") return detail.message;
    if (typeof detail.code === "string") return detail.code;
  }
  if (typeof body.message === "string") return body.message;
  return fallback;
}

function errorCodeFromPayload(payload: unknown) {
  if (!payload || typeof payload !== "object") return undefined;
  const body = payload as Record<string, unknown>;
  if (body.detail && typeof body.detail === "object") {
    const code = (body.detail as Record<string, unknown>).code;
    return typeof code === "string" ? code : undefined;
  }
  return typeof body.code === "string" ? body.code : undefined;
}

function readCsrfToken() {
  try {
    const shared = window.localStorage.getItem(CSRF_STORAGE_KEY);
    if (shared) return shared;
  } catch {
    // Some privacy modes can disable localStorage; keep the same-tab fallback.
  }
  try {
    const legacy = window.sessionStorage.getItem(CSRF_STORAGE_KEY);
    if (legacy) {
      try {
        window.localStorage.setItem(CSRF_STORAGE_KEY, legacy);
      } catch {
        // The sessionStorage value remains usable in this tab.
      }
      return legacy;
    }
  } catch {
    // Missing browser storage means there is no recoverable refresh context.
  }
  return undefined;
}

function storeCsrfToken(csrfToken: string) {
  try {
    window.localStorage.setItem(CSRF_STORAGE_KEY, csrfToken);
  } catch {
    window.sessionStorage.setItem(CSRF_STORAGE_KEY, csrfToken);
    return;
  }
  try {
    window.sessionStorage.removeItem(CSRF_STORAGE_KEY);
  } catch {
    // The shared value is already durable; legacy cleanup is best-effort.
  }
}

function removeCsrfToken() {
  try {
    window.localStorage.removeItem(CSRF_STORAGE_KEY);
  } catch {
    // Continue clearing the same-tab fallback.
  }
  try {
    window.sessionStorage.removeItem(CSRF_STORAGE_KEY);
  } catch {
    // Browser storage cleanup is best-effort during logout.
  }
}

function delay(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}

async function waitForRotatedCsrfToken(previousToken: string) {
  for (const pause of [25, 50, 100, 150]) {
    await delay(pause);
    const current = readCsrfToken();
    if (current && current !== previousToken) return current;
  }
  return undefined;
}

async function safeFetch(input: RequestInfo | URL, init?: RequestInit) {
  try {
    return await fetch(input, init);
  } catch (error) {
    throw new CoreApiError("无法连接服务，请检查网络后重试。", 0, error);
  }
}

interface ApiAuthTokenData {
  access_token: string;
  expires_in: number;
  csrf_token: string;
  session_id: string;
  requires_tenant_selection: boolean;
  user: { id: string; display_name: string; email?: string | null; is_platform_admin: boolean; locale: UiLocale };
  context: {
    tenant_id?: string | null;
    membership_id?: string | null;
    tenant_name?: string | null;
    tenant_slug?: string | null;
    business_mode?: "DOMESTIC" | "EXPORT" | null;
    default_currency?: string | null;
    default_workspace?: string | null;
    account_scope?: "STAFF" | "CUSTOMER_SUBACCOUNT" | null;
  };
  memberships?: ApiMembershipSummary[];
  permission_version?: number | null;
  permissions?: string[];
}

interface ApiMembershipSummary {
  id: string;
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  status: string;
}

const defined = <T,>(value: T | null | undefined): T | undefined => value ?? undefined;

function mapMembership(row: ApiMembershipSummary): MembershipSummary {
  return { id: row.id, tenantId: row.tenant_id, tenantName: row.tenant_name, tenantSlug: row.tenant_slug, status: row.status };
}

function mapAuthData(row: ApiAuthTokenData): AuthTokenData {
  return {
    accessToken: row.access_token,
    expiresIn: row.expires_in,
    csrfToken: row.csrf_token,
    sessionId: row.session_id,
    requiresTenantSelection: row.requires_tenant_selection,
    user: { id: row.user.id, displayName: row.user.display_name, email: defined(row.user.email), isPlatformAdmin: row.user.is_platform_admin, locale: row.user.locale },
    context: {
      tenantId: defined(row.context.tenant_id),
      membershipId: defined(row.context.membership_id),
      tenantName: defined(row.context.tenant_name),
      tenantSlug: defined(row.context.tenant_slug),
      businessMode: defined(row.context.business_mode),
      defaultCurrency: defined(row.context.default_currency),
      defaultWorkspace: defined(row.context.default_workspace),
      accountScope: defined(row.context.account_scope),
    },
    memberships: Array.isArray(row.memberships)
      ? row.memberships.map(mapMembership)
      : undefined,
    permissionVersion: defined(row.permission_version),
    permissions: Array.isArray(row.permissions) ? row.permissions : undefined,
  };
}

function acceptAuthData(row: ApiAuthTokenData) {
  const mapped = mapAuthData(row);
  accessToken = mapped.accessToken;
  accessTokenRefreshAt = Date.now() + accessTokenRefreshDelayMs(mapped.expiresIn);
  authGeneration += 1;
  getRequestsInFlight.clear();
  getResponseCache.clear();
  storeCsrfToken(mapped.csrfToken);
  window.localStorage.removeItem("qingwan.accessToken");
  window.localStorage.removeItem("atc_access_token");
  return mapped;
}

export function getCoreAccessToken() {
  return accessToken;
}

export function clearCoreAuthSession() {
  accessToken = undefined;
  accessTokenRefreshAt = 0;
  resetStorefrontAnnouncementVisit();
  authGeneration += 1;
  getRequestsInFlight.clear();
  getResponseCache.clear();
  removeCsrfToken();
  window.localStorage.removeItem("qingwan.accessToken");
  window.localStorage.removeItem("atc_access_token");
}

async function performAuthRefresh(
  csrfToken: string,
  allowRotatedTokenRetry: boolean,
): Promise<AuthTokenData | undefined> {
  const response = await safeFetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": csrfToken },
  });
  const payload = await response.json().catch(() => null);
  if (response.ok) {
    return acceptAuthData((payload as { data: ApiAuthTokenData }).data);
  }

  const code = errorCodeFromPayload(payload);
  if (code === "AUTH_CSRF_INVALID" && allowRotatedTokenRetry) {
    const rotatedToken = await waitForRotatedCsrfToken(csrfToken);
    if (rotatedToken) return performAuthRefresh(rotatedToken, false);
  }
  if (code === "AUTH_CSRF_INVALID") {
    clearCoreAuthSession();
    return undefined;
  }
  if (response.status === 401 && code && TERMINAL_REFRESH_ERROR_CODES.has(code)) {
    clearCoreAuthSession();
    return undefined;
  }
  throw new CoreApiError(
    messageFromPayload(payload, response.status >= 500 ? "认证服务暂时不可用" : "会话恢复失败"),
    response.status,
    payload,
  );
}

export async function refreshAuthSession(): Promise<AuthTokenData | undefined> {
  const csrfToken = readCsrfToken();
  if (!csrfToken) return undefined;
  if (!refreshInFlight) {
    refreshInFlight = performAuthRefresh(csrfToken, true).finally(() => {
      refreshInFlight = undefined;
    });
  }
  return refreshInFlight;
}

export async function ensureFreshCoreAccessToken(): Promise<boolean> {
  if (accessToken && Date.now() < accessTokenRefreshAt) return true;
  if (!accessToken && !readCsrfToken()) return false;
  return Boolean(await refreshAuthSession());
}

async function prepareCoreRequestAuth(path: string) {
  if (AUTH_REFRESH_EXEMPT_PATHS.has(path)) return;
  if (!accessToken && !readCsrfToken()) return;
  if (await ensureFreshCoreAccessToken()) return;
  window.dispatchEvent(new CustomEvent("atc:auth-expired"));
  throw new CoreApiError("会话已失效，请重新登录。", 401);
}

async function performRequest<T>(path: string, init: RequestInit, retrySession: boolean): Promise<T> {
  await prepareCoreRequestAuth(path);
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await safeFetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  if (response.status === 401 && retrySession && !["/auth/login", "/auth/refresh"].includes(path)) {
    const restored = await refreshAuthSession();
    if (restored) return request<T>(path, init, false);
    window.dispatchEvent(new CustomEvent("atc:auth-expired"));
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");
  if (!response.ok) {
    throw new CoreApiError(messageFromPayload(payload, `请求失败（${response.status}）`), response.status, payload);
  }
  return payload as T;
}

async function request<T>(path: string, init: RequestInit = {}, retrySession = true): Promise<T> {
  const method = (init.method || "GET").toUpperCase();
  if (method !== "GET" || init.signal) {
    if (method !== "GET") getResponseCache.clear();
    return performRequest<T>(path, init, retrySession);
  }
  const key = `${authGeneration}:${path}`;
  const cacheable = init.cache !== "no-store"
    && !path.startsWith("/auth/")
    && !path.includes("/status")
    && !path.includes("/jobs")
    && !path.includes("/system/metrics")
    && !path.includes("/storefront-analytics");
  const now = Date.now();
  const cached = cacheable ? getResponseCache.get(key) : undefined;
  if (cached && cached.expiresAt > now) return cached.value as T;
  if (cached) getResponseCache.delete(key);
  const existing = getRequestsInFlight.get(key);
  if (existing) return existing as Promise<T>;
  const pending = performRequest<T>(path, init, retrySession);
  getRequestsInFlight.set(key, pending);
  try {
    const value = await pending;
    if (cacheable) {
      getResponseCache.set(key, {
        expiresAt: Date.now() + GET_RESPONSE_CACHE_TTL_MS,
        value,
      });
      while (getResponseCache.size > GET_RESPONSE_CACHE_MAX_ENTRIES) {
        const oldest = getResponseCache.keys().next().value as string | undefined;
        if (!oldest) break;
        getResponseCache.delete(oldest);
      }
    }
    return value;
  } finally {
    if (getRequestsInFlight.get(key) === pending) getRequestsInFlight.delete(key);
  }
}

async function downloadCoreRequest(
  path: string,
  filename: string,
  init: RequestInit = {},
  retrySession = true,
): Promise<void> {
  await prepareCoreRequestAuth(path);
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await safeFetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  if (response.status === 401 && retrySession) {
    const restored = await refreshAuthSession();
    if (restored) return downloadCoreRequest(path, filename, init, false);
    window.dispatchEvent(new CustomEvent("atc:auth-expired"));
  }
  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json().catch(() => null)
      : await response.text().catch(() => "");
    throw new CoreApiError(
      messageFromPayload(payload, `下载失败（${response.status}）`),
      response.status,
      payload,
    );
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

async function downloadCoreFile(
  path: string,
  filename: string,
  retrySession = true,
): Promise<void> {
  return downloadCoreRequest(path, filename, {}, retrySession);
}

export async function loginPassword(identifier: string, password: string): Promise<AuthTokenData> {
  const payload = await request<{ data: ApiAuthTokenData }>("/auth/login", {
    method: "POST",
    body: JSON.stringify(buildPasswordLoginPayload(identifier, password)),
  }, false);
  return acceptAuthData(payload.data);
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const submit = async () => {
    if (!(await ensureFreshCoreAccessToken())) {
      window.dispatchEvent(new CustomEvent("atc:auth-expired"));
      throw new CoreApiError("会话已失效，请重新登录。", 419);
    }
    const csrfToken = readCsrfToken();
    if (!csrfToken) throw new CoreApiError("会话校验信息已失效，请重新登录。", 419);
    await request<void>("/auth/password", {
      method: "PUT",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(buildPasswordChangePayload(currentPassword, newPassword)),
    }, false);
  };

  try {
    await submit();
  } catch (caught) {
    const detail = caught instanceof CoreApiError && caught.details && typeof caught.details === "object"
      ? (caught.details as { detail?: { code?: string } }).detail
      : undefined;
    if (!(caught instanceof CoreApiError) || caught.status !== 401 || detail?.code === "CURRENT_PASSWORD_INVALID") {
      throw caught;
    }
    const restored = await refreshAuthSession();
    if (!restored) {
      window.dispatchEvent(new CustomEvent("atc:auth-expired"));
      throw new CoreApiError("会话已失效，请重新登录。", 419);
    }
    await submit();
  }
}

export async function listMemberships() {
  return (await request<ApiMembershipSummary[]>("/auth/memberships")).map(mapMembership);
}

export async function switchTenant(membershipId: string) {
  if (!(await ensureFreshCoreAccessToken())) {
    window.dispatchEvent(new CustomEvent("atc:auth-expired"));
    throw new CoreApiError("会话已失效，请重新登录。", 401);
  }
  const csrfToken = readCsrfToken();
  if (!csrfToken) throw new CoreApiError("会话校验信息已失效，请重新登录。", 401);
  const payload = await request<{ data: ApiAuthTokenData }>("/auth/tenant-context", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ membership_id: membershipId }),
  }, false);
  return acceptAuthData(payload.data);
}

interface ApiCurrentUserResponse {
  user: ApiAuthTokenData["user"];
  context: ApiAuthTokenData["context"];
  memberships: ApiMembershipSummary[];
}

function mapCurrentUser(row: ApiCurrentUserResponse): CurrentUser {
  return {
    user: { id: row.user.id, displayName: row.user.display_name, email: defined(row.user.email), isPlatformAdmin: row.user.is_platform_admin, locale: row.user.locale },
    context: {
      tenantId: defined(row.context.tenant_id),
      membershipId: defined(row.context.membership_id),
      tenantName: defined(row.context.tenant_name),
      tenantSlug: defined(row.context.tenant_slug),
      businessMode: defined(row.context.business_mode),
      defaultCurrency: defined(row.context.default_currency),
      defaultWorkspace: defined(row.context.default_workspace),
      accountScope: defined(row.context.account_scope),
    },
    memberships: row.memberships.map(mapMembership),
  };
}

export async function getCurrentUser(): Promise<CurrentUser> {
  return mapCurrentUser(await request<ApiCurrentUserResponse>("/me"));
}

export async function getAuthBootstrap(): Promise<{ profile: CurrentUser; permissions: PermissionSet }> {
  const row = await request<{
    profile: ApiCurrentUserResponse;
    permissions: { membership_id: string; permission_version: number; permissions: string[] };
  }>("/auth/bootstrap");
  return {
    profile: mapCurrentUser(row.profile),
    permissions: {
      membershipId: row.permissions.membership_id,
      permissionVersion: row.permissions.permission_version,
      permissions: row.permissions.permissions,
    },
  };
}

interface ApiMerchantSettings {
  name: string;
  slug: string;
  storefront_path: string;
  business_mode: "DOMESTIC" | "EXPORT";
  default_currency: string;
  storefront_locales: MerchantSettings["storefrontLocales"];
  hot_products_enabled: boolean;
}

function mapMerchantSettings(row: ApiMerchantSettings): MerchantSettings {
  return {
    name: row.name,
    slug: row.slug,
    storefrontPath: row.storefront_path,
    businessMode: row.business_mode,
    defaultCurrency: row.default_currency,
    storefrontLocales: row.storefront_locales,
    hotProductsEnabled: row.hot_products_enabled,
  };
}

export async function getMerchantSettings(): Promise<MerchantSettings> {
  return mapMerchantSettings(await request<ApiMerchantSettings>("/me/merchant"));
}

export async function updateMerchantSettings(input: {
  name?: string;
  businessMode?: "DOMESTIC" | "EXPORT";
  storefrontLocales?: MerchantSettings["storefrontLocales"];
  hotProductsEnabled?: boolean;
}): Promise<MerchantSettings> {
  const row = await request<ApiMerchantSettings>(
    "/me/merchant",
    {
      method: "PATCH",
      body: JSON.stringify({
        name: input.name,
        business_mode: input.businessMode,
        storefront_locales: input.storefrontLocales,
        hot_products_enabled: input.hotProductsEnabled,
      }),
    },
  );
  bumpPublicCatalogRevision();
  return mapMerchantSettings(row);
}

export async function updateUserPreferences(locale: UiLocale): Promise<UiLocale> {
  const row = await request<{ locale: UiLocale }>("/me/preferences", {
    method: "PATCH",
    body: JSON.stringify({ locale }),
  });
  return row.locale;
}

interface ApiTenantRole {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  is_system: boolean;
  status: string;
  permission_codes: string[];
  member_count: number;
  created_at: string;
  updated_at: string;
}

interface ApiTenantMember {
  id: string;
  user_id: string;
  display_name: string;
  email?: string | null;
  job_title?: string | null;
  status: string;
  permission_version: number;
  roles: Array<{ id: string; code: string; name: string; is_system: boolean }>;
  joined_at?: string | null;
  created_at: string;
}

function mapTenantRole(row: ApiTenantRole): TenantRole {
  return {
    id: row.id,
    code: row.code,
    name: row.name,
    description: defined(row.description),
    isSystem: row.is_system,
    status: row.status,
    permissionCodes: row.permission_codes,
    memberCount: row.member_count,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function mapTenantMember(row: ApiTenantMember): TenantMember {
  return {
    id: row.id,
    userId: row.user_id,
    displayName: row.display_name,
    email: defined(row.email),
    jobTitle: defined(row.job_title),
    status: row.status,
    permissionVersion: row.permission_version,
    roles: row.roles.map((role) => ({
      id: role.id,
      code: role.code,
      name: role.name,
      isSystem: role.is_system,
    })),
    joinedAt: defined(row.joined_at),
    createdAt: row.created_at,
  };
}

export async function listTenantPermissions(): Promise<TenantPermission[]> {
  const rows = await request<Array<{ code: string; module: string; action: string; description?: string | null }>>("/access-control/permissions");
  return rows.map((row) => ({ ...row, description: defined(row.description) }));
}

export async function listTenantRoles(): Promise<TenantRole[]> {
  return (await request<ApiTenantRole[]>("/access-control/roles")).map(mapTenantRole);
}

export async function listTenantMembers(): Promise<TenantMember[]> {
  return (await request<ApiTenantMember[]>("/access-control/members")).map(mapTenantMember);
}

export async function createTenantRole(input: {
  code: string;
  name: string;
  description?: string;
  permissionCodes: string[];
}): Promise<TenantRole> {
  const row = await request<ApiTenantRole>("/access-control/roles", {
    method: "POST",
    body: JSON.stringify({
      code: input.code,
      name: input.name,
      description: input.description || null,
      permission_codes: input.permissionCodes,
    }),
  });
  return mapTenantRole(row);
}

export async function updateTenantRole(
  roleId: string,
  input: { name?: string; description?: string; permissionCodes?: string[] },
): Promise<TenantRole> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.description !== undefined) body.description = input.description || null;
  if (input.permissionCodes !== undefined) body.permission_codes = input.permissionCodes;
  return mapTenantRole(await request<ApiTenantRole>(`/access-control/roles/${roleId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  }));
}

export async function updateTenantMemberRoles(
  membershipId: string,
  roleIds: string[],
): Promise<TenantMember> {
  return mapTenantMember(await request<ApiTenantMember>(`/access-control/members/${membershipId}/roles`, {
    method: "PUT",
    body: JSON.stringify({ role_ids: roleIds }),
  }));
}

interface ApiCustomerSubaccount {
  id: string;
  user_id: string;
  display_name: string;
  login_identifier: string;
  email?: string | null;
  status: string;
  created_at: string;
  last_login_at?: string | null;
  login_count_30d: number;
  order_count: number;
  last_order_at?: string | null;
}

interface ApiCustomerSubaccountOrder {
  id: string;
  quote_number: string;
  status: string;
  submitted_by_membership_id: string;
  submitted_by_name: string;
  customer_name: string;
  customer_company?: string | null;
  currency: string;
  total_amount: number;
  created_at: string;
  valid_until: string;
}

function mapCustomerSubaccount(row: ApiCustomerSubaccount): CustomerSubaccount {
  return {
    id: row.id,
    userId: row.user_id,
    displayName: row.display_name,
    loginIdentifier: row.login_identifier,
    email: defined(row.email),
    status: row.status,
    createdAt: row.created_at,
    lastLoginAt: defined(row.last_login_at),
    loginCount30d: Number(row.login_count_30d || 0),
    orderCount: Number(row.order_count || 0),
    lastOrderAt: defined(row.last_order_at),
  };
}

function mapCustomerSubaccountOrder(row: ApiCustomerSubaccountOrder): CustomerSubaccountOrder {
  return {
    id: row.id,
    quoteNumber: row.quote_number,
    status: row.status,
    submittedByMembershipId: row.submitted_by_membership_id,
    submittedByName: row.submitted_by_name,
    customerName: row.customer_name,
    customerCompany: defined(row.customer_company),
    currency: row.currency,
    totalAmount: Number(row.total_amount),
    createdAt: row.created_at,
    validUntil: row.valid_until,
  };
}

export async function getCustomerSubaccountDashboard(): Promise<CustomerSubaccountDashboard> {
  const row = await request<{
    accounts: ApiCustomerSubaccount[];
    active_count: number;
    suspended_count: number;
    order_count: number;
  }>("/customer-accounts");
  return {
    accounts: row.accounts.map(mapCustomerSubaccount),
    activeCount: Number(row.active_count || 0),
    suspendedCount: Number(row.suspended_count || 0),
    orderCount: Number(row.order_count || 0),
  };
}

export async function listCustomerSubaccountOrders(
  page = 1,
  pageSize = 20,
): Promise<CustomerSubaccountOrderPage> {
  const row = await request<{
    items: ApiCustomerSubaccountOrder[];
    total: number;
    page: number;
    page_size: number;
  }>(`/customer-accounts/orders?page=${encodeURIComponent(page)}&page_size=${encodeURIComponent(pageSize)}`);
  return {
    items: row.items.map(mapCustomerSubaccountOrder),
    total: Number(row.total || 0),
    page: Number(row.page || page),
    pageSize: Number(row.page_size || pageSize),
  };
}

export async function createCustomerSubaccount(input: {
  displayName: string;
  loginIdentifier: string;
  password: string;
  email?: string;
}): Promise<CustomerSubaccount> {
  const row = await request<ApiCustomerSubaccount>("/customer-accounts", {
    method: "POST",
    body: JSON.stringify({
      display_name: input.displayName,
      login_identifier: input.loginIdentifier,
      password: input.password,
      email: input.email || null,
    }),
  });
  return mapCustomerSubaccount(row);
}

export async function updateCustomerSubaccountStatus(
  membershipId: string,
  status: "active" | "suspended",
): Promise<CustomerSubaccount> {
  const row = await request<ApiCustomerSubaccount>(
    `/customer-accounts/${encodeURIComponent(membershipId)}/status`,
    { method: "PATCH", body: JSON.stringify({ status }) },
  );
  return mapCustomerSubaccount(row);
}

export async function getCustomerPortalOverview(): Promise<CustomerPortalOverview> {
  const row = await request<{
    display_name: string;
    tenant_name: string;
    tenant_slug: string;
    account_status: string;
    order_count: number;
    last_order_at?: string | null;
  }>("/customer-portal/overview");
  return {
    displayName: row.display_name,
    tenantName: row.tenant_name,
    tenantSlug: row.tenant_slug,
    accountStatus: row.account_status,
    orderCount: Number(row.order_count || 0),
    lastOrderAt: defined(row.last_order_at),
  };
}

export async function listCustomerPortalOrders(): Promise<CustomerPortalOrder[]> {
  const rows = await request<Array<{
    id: string;
    quote_number: string;
    status: string;
    customer_name: string;
    customer_company?: string | null;
    currency: string;
    total_amount: number;
    created_at: string;
    valid_until: string;
  }>>("/customer-portal/orders");
  return rows.map((row) => ({
    id: row.id,
    quoteNumber: row.quote_number,
    status: row.status,
    customerName: row.customer_name,
    customerCompany: defined(row.customer_company),
    currency: row.currency,
    totalAmount: Number(row.total_amount),
    createdAt: row.created_at,
    validUntil: row.valid_until,
  }));
}

export async function logoutSession(): Promise<void> {
  try {
    await request<void>("/auth/logout", { method: "POST" }, false);
  } finally {
    clearCoreAuthSession();
  }
}

interface ApiImportJob {
  id: string;
  filename: string;
  supplier: string;
  source_type: string;
  detected_type: string;
  status: ImportJob["status"];
  progress: number;
  products: number;
  warnings: number;
  warning_messages: string[];
  created_at: string;
  parser: string;
  extension_matches: boolean;
  error_message?: string | null;
  result_details?: {
    outcome?: string;
    imported?: number;
    created?: number;
    updated?: number;
    unchanged?: number;
    skipped?: number;
    issues?: Array<{
      row_number?: number | null;
      column?: string;
      code?: string;
      message?: string;
      value?: string | null;
      suggestion?: string | null;
    }>;
    issue_total?: number;
    issues_truncated?: number;
    import_progress?: number;
    import_stage?: string;
    processed_rows?: number;
    total_rows?: number;
  };
}

function mapImport(row: ApiImportJob): ImportJob {
  const details = row.result_details ?? {};
  const issues = (details.issues ?? []).map((issue) => ({
    rowNumber: defined(issue.row_number),
    column: issue.column || "未识别字段",
    code: issue.code || "VALIDATION_ERROR",
    message: issue.message || "该字段无法导入。",
    value: defined(issue.value),
    suggestion: defined(issue.suggestion),
  }));
  return {
    id: row.id,
    filename: row.filename,
    supplier: row.supplier,
    sourceType: row.source_type,
    detectedType: row.detected_type,
    status: row.status,
    progress: row.progress,
    products: row.products,
    warnings: row.warnings,
    warningMessages: row.warning_messages ?? [],
    createdAt: row.created_at,
    parser: row.parser,
    extensionMatches: row.extension_matches,
    errorMessage: defined(row.error_message),
    resultDetails: {
      outcome: defined(details.outcome),
      imported: defined(details.imported),
      created: defined(details.created),
      updated: defined(details.updated),
      unchanged: defined(details.unchanged),
      skipped: defined(details.skipped),
      issues,
      issueTotal: details.issue_total ?? issues.length,
      issuesTruncated: details.issues_truncated ?? 0,
      importProgress: defined(details.import_progress),
      importStage: defined(details.import_stage),
      processedRows: defined(details.processed_rows),
      totalRows: defined(details.total_rows),
    },
  };
}

const OLE = "d0cf11e0a1b11ae1";
const ZIP = "504b0304";

async function localDetection(file: File): Promise<FileDetection> {
  const bytes = new Uint8Array(await file.slice(0, 8).arrayBuffer());
  const signature = Array.from(bytes).map((byte) => byte.toString(16).padStart(2, "0")).join("");
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  let detected = "UNKNOWN";
  let parser = "manual_review";
  if (signature.startsWith(OLE)) {
    detected = extension === ".doc" || extension === ".docx" ? "OLE / Legacy DOC" : "OLE / Legacy XLS";
    parser = extension === ".doc" || extension === ".docx" ? "legacy_word_converter" : "xlrd";
  } else if (signature.startsWith(ZIP)) {
    const mapping: Record<string, [string, string]> = {
      ".xlsx": ["OOXML / XLSX", "openpyxl"],
      ".docx": ["OOXML / DOCX", "python-docx"],
      ".pptx": ["OOXML / PPTX", "python-pptx"],
    };
    [detected, parser] = mapping[extension] ?? ["ZIP / OOXML", "ooxml_inspector"];
  } else if (signature.startsWith("25504446")) {
    detected = "PDF";
    parser = "pymupdf";
  }
  const expected: Record<string, string> = {
    ".xlsx": "OOXML / XLSX", ".xls": "OLE / Legacy XLS", ".docx": "OOXML / DOCX",
    ".doc": "OLE / Legacy DOC", ".pdf": "PDF", ".pptx": "OOXML / PPTX",
  };
  const matches = !expected[extension] || expected[extension] === detected;
  return {
    filename: file.name,
    detected_type: detected,
    extension_matches: matches,
    parser,
    warning: matches ? null : `扩展名与真实格式 ${detected} 不一致`,
  };
}

export async function detectFile(file: File) {
  // The server only inspects the leading signature bytes. Sending a large
  // catalog as multipart data just to detect those bytes duplicates the whole
  // upload, so large files are inspected locally and still receive the full
  // server-side security scan during the real import.
  if (file.size > 2 * 1024 * 1024) return localDetection(file);
  try {
    const body = new FormData();
    body.append("file", file);
    return await request<FileDetection>("/imports/detect", { method: "POST", body, signal: AbortSignal.timeout(1500) });
  } catch {
    return localDetection(file);
  }
}

export async function getImport(jobId: string) {
  return mapImport(await request<ApiImportJob>(`/imports/${encodeURIComponent(jobId)}`));
}

async function uploadProductTemplate(
  body: FormData,
  onUploadProgress: ((percent: number) => void) | undefined,
  retrySession: boolean,
): Promise<ApiImportJob> {
  if (!(await ensureFreshCoreAccessToken())) {
    window.dispatchEvent(new CustomEvent("atc:auth-expired"));
    throw new CoreApiError("会话已失效，请重新登录。", 401);
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/imports`);
    xhr.withCredentials = true;
    if (accessToken) xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onUploadProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onerror = () => reject(new CoreApiError("无法连接服务，请检查网络后重试。", 0));
    xhr.onload = () => {
      let payload: unknown = null;
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        payload = xhr.responseText;
      }
      if (xhr.status === 401 && retrySession) {
        void refreshAuthSession()
          .then((restored) => {
            if (!restored) {
              window.dispatchEvent(new CustomEvent("atc:auth-expired"));
              throw new CoreApiError(messageFromPayload(payload, "会话已失效"), 401, payload);
            }
            return uploadProductTemplate(body, onUploadProgress, false);
          })
          .then(resolve)
          .catch(reject);
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new CoreApiError(
          messageFromPayload(payload, `请求失败（${xhr.status}）`),
          xhr.status,
          payload,
        ));
        return;
      }
      onUploadProgress?.(100);
      resolve(payload as ApiImportJob);
    };
    xhr.send(body);
  });
}

export async function createProductTemplateImport(
  file: File,
  onUploadProgress?: (percent: number) => void,
) {
  const body = new FormData();
  body.append("file", file);
  body.append("source_type", "PRODUCT_TEMPLATE");
  body.append("defer_processing", "true");
  return mapImport(await uploadProductTemplate(body, onUploadProgress, true));
}

interface ApiOffer {
  supplier_product_id: string;
  supplier_id: string;
  supplier_name: string;
  supplier_sku?: string | null;
  sku_id?: string | null;
  lead_time_days?: number | null;
  unit_price?: number | null;
  currency?: string | null;
  price_validity: ProductOffer["priceValidity"];
  valid_to?: string | null;
}

interface ApiProduct {
  id: string;
  product_code?: string | null;
  name: string;
  status: string;
  category?: { id: string; code: string; name: string } | null;
  sku_count: number;
  supplier_count: number;
  primary_image_url?: string | null;
  image_status: CoreProduct["imageStatus"];
  current_version: number;
  updated_at: string;
  capabilities: string[];
  model: string;
  supplier: string;
  price?: number | null;
  currency?: string | null;
  tags: string[];
}

interface ApiSku {
  id: string;
  product_id: string;
  sku_code: string;
  name?: string | null;
  option_values: Record<string, string | number | boolean>;
  barcode?: string | null;
  default_moq?: number | string | null;
  moq_unit?: string | null;
  weight?: number | string | null;
  weight_unit?: string | null;
  status: ProductSku["status"];
  version: number;
  updated_at: string;
}

interface ApiSkuListItem {
  id: string;
  sku_code: string;
  name: string;
  product_id: string;
  product_code?: string | null;
  product_name: string;
  category?: { id: string; code: string; name: string } | null;
  tags: string[];
  supplier_summary: {
    count: number;
    primary_supplier_id?: string | null;
    primary_supplier_name?: string | null;
    names: string[];
  };
  public_price?: number | string | null;
  public_currency?: string | null;
  public_offer_status?: SkuListItem["publicOfferStatus"] | null;
  status: SkuListItem["status"];
  version: number;
  updated_at: string;
  source_type: SkuListItem["sourceType"];
  source_filename?: string | null;
  source_imported_at?: string | null;
  image_status: SkuListItem["imageStatus"];
  thumbnail_url?: string | null;
  is_pinned: boolean;
}

interface ApiSkuListPage {
  items: ApiSkuListItem[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

interface ApiProductDetail extends ApiProduct {
  description?: string | null;
  default_unit?: string | null;
  attributes: Array<{ id: string; definition_id?: string | null; key: string; value: unknown; unit_code?: string | null; review_status: string }>;
  skus: ApiSku[];
  sources: ApiOffer[];
  activity: Array<{ id: string; entity_type: string; entity_id: string; action: string; before: Record<string, unknown>; after: Record<string, unknown>; actor_membership_id: string; occurred_at: string }>;
}

function mapOffer(row: ApiOffer): ProductOffer {
  return {
    supplierProductId: row.supplier_product_id,
    supplierId: row.supplier_id,
    supplierName: row.supplier_name,
    supplierSku: defined(row.supplier_sku),
    skuId: defined(row.sku_id),
    leadTimeDays: defined(row.lead_time_days),
    unitPrice: row.unit_price == null ? undefined : Number(row.unit_price),
    currency: defined(row.currency),
    priceValidity: row.price_validity,
    validTo: defined(row.valid_to),
  };
}

function mapProduct(row: ApiProduct): CoreProduct {
  return {
    id: row.id,
    productCode: defined(row.product_code),
    name: row.name,
    model: row.model,
    status: row.status,
    category: row.category?.name ?? "未分类",
    categoryId: row.category?.id,
    supplier: row.supplier,
    price: row.price == null ? undefined : Number(row.price),
    currency: defined(row.currency),
    updated: row.updated_at,
    primaryImageUrl: defined(row.primary_image_url),
    imageStatus: row.image_status,
    tags: row.tags ?? [],
    skuCount: row.sku_count,
    supplierCount: row.supplier_count,
    currentVersion: row.current_version,
    capabilities: row.capabilities ?? [],
  };
}

function mapSku(row: ApiSku): ProductSku {
  return {
    id: row.id,
    productId: row.product_id,
    skuCode: row.sku_code,
    name: defined(row.name),
    optionValues: row.option_values,
    barcode: defined(row.barcode),
    defaultMoq: row.default_moq == null ? undefined : Number(row.default_moq),
    moqUnit: defined(row.moq_unit),
    weight: row.weight == null ? undefined : Number(row.weight),
    weightUnit: defined(row.weight_unit),
    status: row.status,
    version: row.version,
    updatedAt: row.updated_at,
  };
}

function mapSkuListItem(row: ApiSkuListItem): SkuListItem {
  return {
    id: row.id,
    skuCode: row.sku_code,
    name: row.name,
    productId: row.product_id,
    productCode: defined(row.product_code),
    productName: row.product_name,
    category: row.category ?? undefined,
    tags: row.tags ?? [],
    supplierSummary: {
      count: row.supplier_summary.count,
      primarySupplierId: defined(row.supplier_summary.primary_supplier_id),
      primarySupplierName: defined(row.supplier_summary.primary_supplier_name),
      names: row.supplier_summary.names ?? [],
    },
    publicPrice: row.public_price == null ? undefined : Number(row.public_price),
    publicCurrency: defined(row.public_currency),
    publicOfferStatus: defined(row.public_offer_status),
    status: row.status,
    version: row.version,
    updatedAt: row.updated_at,
    sourceType: row.source_type,
    sourceFilename: defined(row.source_filename),
    sourceImportedAt: defined(row.source_imported_at),
    imageStatus: row.image_status,
    thumbnailUrl: defined(row.thumbnail_url),
    isPinned: Boolean(row.is_pinned),
  };
}

function mapActivity(row: ApiProductDetail["activity"][number]): ProductActivity {
  return { id: row.id, entityType: row.entity_type, entityId: row.entity_id, action: row.action, before: row.before, after: row.after, actorMembershipId: row.actor_membership_id, occurredAt: row.occurred_at };
}

function mapAttribute(row: ApiProductDetail["attributes"][number]): ProductAttribute {
  return { id: row.id, definitionId: defined(row.definition_id), key: row.key, value: row.value, unitCode: defined(row.unit_code), reviewStatus: row.review_status };
}

function mapProductDetail(row: ApiProductDetail): ProductDetail {
  return {
    ...mapProduct(row),
    description: defined(row.description),
    defaultUnit: defined(row.default_unit),
    attributes: row.attributes.map(mapAttribute),
    skus: row.skus.map(mapSku),
    sources: row.sources.map(mapOffer),
    activity: row.activity.map(mapActivity),
  };
}

export async function listSkus(params: {
  q?: string;
  categoryId?: string;
  statuses?: ProductSku["status"][];
  missingImagesOnly?: boolean;
  page?: number;
  pageSize?: number;
} = {}): Promise<SkuListPage> {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.categoryId) query.set("category_id", params.categoryId);
  for (const status of params.statuses ?? []) query.append("status", status);
  if (params.missingImagesOnly) query.set("missing_images_only", "true");
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 50));
  query.set("include_supplier_summary", "false");
  const row = await request<ApiSkuListPage>(`/product-center/skus?${query}`);
  return {
    items: row.items.map(mapSkuListItem),
    page: row.page,
    pageSize: row.page_size,
    total: row.total,
    pages: row.pages,
  };
}

export async function exportSkuCatalog(params: {
  q?: string;
  categoryId?: string;
  statuses?: ProductSku["status"][];
  missingImagesOnly?: boolean;
  skuIds?: string[];
} = {}): Promise<void> {
  await downloadCoreRequest(
    "/product-center/skus/export",
    `SKU商品库-${new Date().toISOString().slice(0, 10)}.xlsx`,
    {
      method: "POST",
      body: JSON.stringify({
        q: params.q ?? "",
        category_id: params.categoryId || null,
        statuses: params.statuses ?? [],
        missing_images_only: Boolean(params.missingImagesOnly),
        sku_ids: params.skuIds ?? [],
      }),
    },
  );
}

export interface ProductImageUploadResult {
  id: string;
  productId: string;
  url: string;
  originalFilename?: string;
  contentType: string;
  byteSize: number;
  width?: number;
  height?: number;
}

export async function uploadProductMainImage(
  productId: string,
  image: File,
): Promise<ProductImageUploadResult> {
  const body = new FormData();
  body.append("image", image);
  const row = await request<{
    id: string;
    product_id: string;
    url: string;
    original_filename?: string | null;
    content_type: string;
    byte_size: number;
    width?: number | null;
    height?: number | null;
  }>(`/products/${productId}/images/main`, { method: "POST", body });
  bumpPublicCatalogRevision();
  return {
    id: row.id,
    productId: row.product_id,
    url: row.url,
    originalFilename: defined(row.original_filename),
    contentType: row.content_type,
    byteSize: row.byte_size,
    width: defined(row.width),
    height: defined(row.height),
  };
}

export interface SkuBatchOperationResult {
  successCount: number;
  failedCount: number;
  totalCount: number;
  failedItems: Array<{ skuId: string; reason: string }>;
  affectedProductCount?: number;
}

interface ApiSkuBatchOperationResult {
  success_count: number;
  failed_count: number;
  total_count: number;
  failed_items: Array<{ sku_id: string; reason: string }>;
  affected_product_count?: number | null;
}

function mapSkuBatchOperationResult(
  row: ApiSkuBatchOperationResult,
): SkuBatchOperationResult {
  return {
    successCount: row.success_count,
    failedCount: row.failed_count,
    totalCount: row.total_count,
    failedItems: row.failed_items.map((item) => ({
      skuId: item.sku_id,
      reason: item.reason,
    })),
    affectedProductCount: row.affected_product_count ?? undefined,
  };
}

export async function batchDeleteSkus(skuIds: string[]): Promise<SkuBatchOperationResult> {
  const row = await request<ApiSkuBatchOperationResult>("/skus/batch-delete", {
    method: "POST",
    body: JSON.stringify({ sku_ids: skuIds }),
  });
  bumpPublicCatalogRevision();
  return mapSkuBatchOperationResult(row);
}

export async function batchUpdateSkuStatus(
  skuIds: string[],
  status: "ACTIVE" | "INACTIVE",
): Promise<SkuBatchOperationResult> {
  const row = await request<ApiSkuBatchOperationResult>("/skus/batch-update-status", {
    method: "POST",
    body: JSON.stringify({ sku_ids: skuIds, status }),
  });
  bumpPublicCatalogRevision();
  return mapSkuBatchOperationResult(row);
}

export async function batchUpdateSkuCategory(
  skuIds: string[],
  categoryId: string | null,
): Promise<SkuBatchOperationResult> {
  const row = await request<ApiSkuBatchOperationResult>("/skus/batch-update-category", {
    method: "POST",
    body: JSON.stringify({ sku_ids: skuIds, category_id: categoryId }),
  });
  bumpPublicCatalogRevision();
  return mapSkuBatchOperationResult(row);
}

export async function batchUpdateSkuPinned(
  skuIds: string[],
  pinned: boolean,
): Promise<SkuBatchOperationResult> {
  const row = await request<ApiSkuBatchOperationResult>("/skus/batch-update-pinned", {
    method: "POST",
    body: JSON.stringify({ sku_ids: skuIds, pinned }),
  });
  bumpPublicCatalogRevision();
  return mapSkuBatchOperationResult(row);
}

export interface ProductDeleteAllJob {
  id: string;
  status: "QUEUED" | "RUNNING" | "PAUSED" | "SUCCEEDED" | "FAILED";
  stage: "QUEUED" | "COUNTING" | "HIDING_OFFERS" | "ARCHIVING_SKUS" | "ARCHIVING_PRODUCTS" | "FINALIZING" | "COMPLETED" | "FAILED";
  progress: number;
  totalProductCount: number;
  totalSkuCount: number;
  deletedProductCount: number;
  deletedSkuCount: number;
  errorMessage?: string;
}

interface ApiProductDeleteAllJob {
  id: string;
  status: ProductDeleteAllJob["status"];
  stage: ProductDeleteAllJob["stage"];
  progress: number;
  total_products: number;
  total_skus: number;
  deleted_product_count: number;
  deleted_sku_count: number;
  error_message?: string | null;
}

function mapProductDeleteAllJob(row: ApiProductDeleteAllJob): ProductDeleteAllJob {
  return {
    id: row.id,
    status: row.status,
    stage: row.stage,
    progress: row.progress,
    totalProductCount: row.total_products,
    totalSkuCount: row.total_skus,
    deletedProductCount: row.deleted_product_count,
    deletedSkuCount: row.deleted_sku_count,
    errorMessage: row.error_message ?? undefined,
  };
}

export async function deleteAllProducts(password: string): Promise<ProductDeleteAllJob> {
  const row = await request<ApiProductDeleteAllJob>("/product-center/products/delete-all", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  return mapProductDeleteAllJob(row);
}

export async function getDeleteAllProductsJob(jobId: string): Promise<ProductDeleteAllJob> {
  const row = await request<ApiProductDeleteAllJob>(
    `/product-center/products/delete-all/${encodeURIComponent(jobId)}`,
    { cache: "no-store" },
  );
  const job = mapProductDeleteAllJob(row);
  if (job.status === "SUCCEEDED") bumpPublicCatalogRevision();
  return job;
}

interface ApiKnowledgeIndexStatus {
  total_products: number;
  indexed_products: number;
  pending_products: number;
  mode?: "INCREMENTAL" | "FULL_REBUILD";
  processed_products?: number;
  embeddings?: number;
}

function mapKnowledgeIndexStatus(row: ApiKnowledgeIndexStatus): KnowledgeIndexStatus {
  return {
    totalProducts: row.total_products,
    indexedProducts: row.indexed_products,
    pendingProducts: row.pending_products,
    mode: row.mode,
    processedProducts: row.processed_products,
    embeddings: row.embeddings,
  };
}

export async function getKnowledgeIndexStatus(): Promise<KnowledgeIndexStatus> {
  return mapKnowledgeIndexStatus(
    await request<ApiKnowledgeIndexStatus>("/ai/knowledge/index"),
  );
}

interface ApiKnowledgeIndexJob {
  id: string;
  mode: "INCREMENTAL" | "FULL_REBUILD";
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  total_products: number;
  processed_products: number;
  failed_products: number;
  embeddings: number;
  progress_percent: number;
  current_product_id?: string | null;
  current_product_name?: string | null;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

function mapKnowledgeIndexJob(row: ApiKnowledgeIndexJob): KnowledgeIndexJob {
  return {
    id: row.id,
    mode: row.mode,
    status: row.status,
    totalProducts: row.total_products,
    processedProducts: row.processed_products,
    failedProducts: row.failed_products,
    embeddings: row.embeddings,
    progressPercent: row.progress_percent,
    currentProductId: defined(row.current_product_id),
    currentProductName: defined(row.current_product_name),
    errorMessage: defined(row.error_message),
    createdAt: row.created_at,
    startedAt: defined(row.started_at),
    completedAt: defined(row.completed_at),
  };
}

export async function startKnowledgeIndexJob(
  fullRebuild = false,
): Promise<KnowledgeIndexJob> {
  const row = await request<ApiKnowledgeIndexJob>("/ai/knowledge/index/jobs", {
    method: "POST",
    body: JSON.stringify({
      mode: fullRebuild ? "FULL_REBUILD" : "INCREMENTAL",
      confirm_full_rebuild: fullRebuild,
    }),
  });
  return mapKnowledgeIndexJob(row);
}

export async function getLatestKnowledgeIndexJob(): Promise<KnowledgeIndexJob | undefined> {
  const row = await request<ApiKnowledgeIndexJob | null>(
    "/ai/knowledge/index/jobs/latest",
  );
  return row ? mapKnowledgeIndexJob(row) : undefined;
}

export async function getKnowledgeIndexJob(jobId: string): Promise<KnowledgeIndexJob> {
  return mapKnowledgeIndexJob(
    await request<ApiKnowledgeIndexJob>(
      `/ai/knowledge/index/jobs/${encodeURIComponent(jobId)}`,
    ),
  );
}

interface ApiEmbeddingSettings {
  source: "database" | "environment" | "deterministic";
  provider: string;
  base_url?: string | null;
  model_name: string;
  model_version: string;
  dimensions: number;
  timeout_seconds: number;
  api_key_configured: boolean;
  api_key_hint?: string | null;
  updated_at?: string | null;
}

function mapEmbeddingSettings(row: ApiEmbeddingSettings): EmbeddingSettings {
  return {
    source: row.source,
    provider: row.provider,
    baseUrl: defined(row.base_url),
    modelName: row.model_name,
    modelVersion: row.model_version,
    dimensions: row.dimensions,
    timeoutSeconds: row.timeout_seconds,
    apiKeyConfigured: row.api_key_configured,
    apiKeyHint: defined(row.api_key_hint),
    updatedAt: defined(row.updated_at),
  };
}

export async function getEmbeddingSettings(): Promise<EmbeddingSettings> {
  return mapEmbeddingSettings(
    await request<ApiEmbeddingSettings>("/ai/embedding/settings", {
      cache: "no-store",
    }),
  );
}

export async function updateEmbeddingSettings(input: {
  baseUrl: string;
  apiKey?: string;
  modelName: string;
  dimensions: number;
  timeoutSeconds: number;
}): Promise<EmbeddingSettings> {
  return mapEmbeddingSettings(
    await request<ApiEmbeddingSettings>("/ai/embedding/settings", {
      method: "PUT",
      body: JSON.stringify({
        base_url: input.baseUrl,
        api_key: input.apiKey || undefined,
        model_name: input.modelName,
        dimensions: input.dimensions,
        timeout_seconds: input.timeoutSeconds,
      }),
    }),
  );
}

interface ApiTranslationSettings {
  source: "database" | "environment" | "disabled";
  provider: TranslationProviderKind | "deeplx";
  enabled: boolean;
  base_url?: string | null;
  model_name?: string | null;
  region_id?: string | null;
  timeout_seconds: number;
  max_tokens: number;
  requests_per_minute: number;
  reasoning_effort: TranslationReasoningEffort;
  api_key_configured: boolean;
  api_key_hint?: string | null;
  access_key_id_configured: boolean;
  access_key_id_hint?: string | null;
  updated_at?: string | null;
}

interface ApiTranslationSettingsTestResult {
  success: true;
  provider: string;
  model_name: string;
  latency_ms: number;
  translated_text: string;
}

function mapTranslationSettings(
  row: ApiTranslationSettings,
): TranslationApiSettings {
  return {
    source: row.source,
    provider: row.provider,
    enabled: row.enabled,
    baseUrl: defined(row.base_url),
    modelName: defined(row.model_name),
    regionId: defined(row.region_id),
    timeoutSeconds: row.timeout_seconds,
    maxTokens: row.max_tokens,
    requestsPerMinute: row.requests_per_minute,
    reasoningEffort: row.reasoning_effort,
    apiKeyConfigured: row.api_key_configured,
    apiKeyHint: defined(row.api_key_hint),
    accessKeyIdConfigured: row.access_key_id_configured,
    accessKeyIdHint: defined(row.access_key_id_hint),
    updatedAt: defined(row.updated_at),
  };
}

export interface TranslationSettingsWriteInput {
  provider: TranslationProviderKind;
  baseUrl: string;
  apiKey?: string;
  accessKeyId?: string;
  modelName: string;
  regionId?: string;
  timeoutSeconds: number;
  maxTokens: number;
  requestsPerMinute: number;
  reasoningEffort: TranslationReasoningEffort;
}

function translationSettingsBody(input: TranslationSettingsWriteInput) {
  return {
    provider: input.provider,
    base_url: input.baseUrl,
    api_key: input.apiKey || undefined,
    access_key_id: input.accessKeyId || undefined,
    model_name: input.modelName,
    region_id: input.regionId || undefined,
    timeout_seconds: input.timeoutSeconds,
    max_tokens: input.maxTokens,
    requests_per_minute: input.requestsPerMinute,
    reasoning_effort: input.reasoningEffort,
  };
}

export async function getTranslationSettings(): Promise<TranslationApiSettings> {
  return mapTranslationSettings(
    await request<ApiTranslationSettings>("/system/translation/settings", {
      cache: "no-store",
    }),
  );
}

export async function updateTranslationSettings(
  input: TranslationSettingsWriteInput & { enabled: boolean },
): Promise<TranslationApiSettings> {
  return mapTranslationSettings(
    await request<ApiTranslationSettings>("/system/translation/settings", {
      method: "PUT",
      body: JSON.stringify({
        ...translationSettingsBody(input),
        enabled: input.enabled,
      }),
    }),
  );
}

export async function testTranslationSettings(
  input: TranslationSettingsWriteInput,
): Promise<TranslationApiTestResult> {
  const row = await request<ApiTranslationSettingsTestResult>(
    "/system/translation/settings/test",
    {
      method: "POST",
      body: JSON.stringify(translationSettingsBody(input)),
    },
  );
  return {
    provider: row.provider,
    modelName: row.model_name,
    latencyMs: row.latency_ms,
    translatedText: row.translated_text,
  };
}

interface ApiCatalogLanguagePack {
  source_locale: StorefrontLocale;
  target_locale: StorefrontLocale;
  version: number;
  download_url: string;
  content_sha256: string;
  byte_size: number;
  product_count: number;
  sku_count: number;
  category_count: number;
  source_cutoff_at: string;
  published_at: string;
  last_full_translation_at?: string | null;
}

interface ApiCatalogTranslationJob {
  id: string;
  source_locale: StorefrontLocale;
  target_locale: StorefrontLocale;
  mode: "INCREMENTAL" | "FULL_REBUILD";
  status: "QUEUED" | "RUNNING" | "PAUSED" | "SUCCEEDED" | "FAILED";
  stage: CatalogTranslationJob["stage"];
  total_skus: number;
  processed_skus: number;
  failed_skus: number;
  remaining_skus: number;
  progress_percent: number;
  current_sku_id?: string | null;
  current_sku_name?: string | null;
  failure_details: Array<{
    sku_id?: string | null;
    sku_code?: string | null;
    name?: string | null;
    message: string;
  }>;
  error_message?: string | null;
  package_version?: number | null;
  package_published: boolean;
  package_byte_size?: number | null;
  source_cutoff_at?: string | null;
  pause_requested: boolean;
  pause_requested_at?: string | null;
  paused_at?: string | null;
  resumable: boolean;
  checkpoint_at?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

interface ApiCatalogTranslationStatus {
  source_locale: StorefrontLocale;
  target_locale: StorefrontLocale;
  provider_configured: boolean;
  total_skus: number;
  translated_skus: number;
  stale_skus: number;
  pending_skus: number;
  package_outdated: boolean;
  package_storage_configured: boolean;
  available_locales: StorefrontLocale[];
  package?: ApiCatalogLanguagePack | null;
  latest_job?: ApiCatalogTranslationJob | null;
}

function mapCatalogLanguagePack(row: ApiCatalogLanguagePack): CatalogLanguagePackInfo {
  return {
    sourceLocale: row.source_locale,
    targetLocale: row.target_locale,
    version: row.version,
    downloadUrl: row.download_url,
    contentSha256: row.content_sha256,
    byteSize: row.byte_size,
    productCount: row.product_count,
    skuCount: row.sku_count,
    categoryCount: row.category_count,
    sourceCutoffAt: row.source_cutoff_at,
    publishedAt: row.published_at,
    lastFullTranslationAt: defined(row.last_full_translation_at),
  };
}

function mapCatalogTranslationJob(row: ApiCatalogTranslationJob): CatalogTranslationJob {
  return {
    id: row.id,
    sourceLocale: row.source_locale,
    targetLocale: row.target_locale,
    mode: row.mode,
    status: row.status,
    stage: row.stage,
    totalSkus: row.total_skus,
    processedSkus: row.processed_skus,
    failedSkus: row.failed_skus,
    remainingSkus: row.remaining_skus,
    progressPercent: row.progress_percent,
    currentSkuId: defined(row.current_sku_id),
    currentSkuName: defined(row.current_sku_name),
    failureDetails: row.failure_details.map((failure) => ({
      skuId: defined(failure.sku_id),
      skuCode: defined(failure.sku_code),
      name: defined(failure.name),
      message: failure.message,
    })),
    errorMessage: defined(row.error_message),
    packageVersion: row.package_version ?? undefined,
    packagePublished: row.package_published,
    packageByteSize: row.package_byte_size ?? undefined,
    sourceCutoffAt: defined(row.source_cutoff_at),
    pauseRequested: row.pause_requested,
    pauseRequestedAt: defined(row.pause_requested_at),
    pausedAt: defined(row.paused_at),
    resumable: row.resumable,
    checkpointAt: defined(row.checkpoint_at),
    createdAt: row.created_at,
    startedAt: defined(row.started_at),
    completedAt: defined(row.completed_at),
  };
}

function mapCatalogTranslationStatus(
  row: ApiCatalogTranslationStatus,
): CatalogTranslationStatus {
  return {
    sourceLocale: row.source_locale,
    targetLocale: row.target_locale,
    providerConfigured: row.provider_configured,
    totalSkus: row.total_skus,
    translatedSkus: row.translated_skus,
    staleSkus: row.stale_skus,
    pendingSkus: row.pending_skus,
    packageOutdated: row.package_outdated,
    packageStorageConfigured: row.package_storage_configured,
    availableLocales: row.available_locales,
    package: row.package ? mapCatalogLanguagePack(row.package) : undefined,
    latestJob: row.latest_job ? mapCatalogTranslationJob(row.latest_job) : undefined,
  };
}

export async function getCatalogTranslationStatus(
  targetLocale: StorefrontLocale,
): Promise<CatalogTranslationStatus> {
  return mapCatalogTranslationStatus(
    await request<ApiCatalogTranslationStatus>(
      `/catalog/translations/status?target_locale=${encodeURIComponent(targetLocale)}`,
      { cache: "no-store" },
    ),
  );
}

export async function startCatalogTranslationJob(
  targetLocale: StorefrontLocale,
  fullRebuild = false,
): Promise<CatalogTranslationJob> {
  return mapCatalogTranslationJob(
    await request<ApiCatalogTranslationJob>("/catalog/translations/jobs", {
      method: "POST",
      body: JSON.stringify({
        target_locale: targetLocale,
        mode: fullRebuild ? "FULL_REBUILD" : "INCREMENTAL",
        confirm_full_rebuild: fullRebuild,
      }),
    }),
  );
}

export async function getCatalogTranslationJob(
  jobId: string,
): Promise<CatalogTranslationJob> {
  return mapCatalogTranslationJob(
    await request<ApiCatalogTranslationJob>(
      `/catalog/translations/jobs/${encodeURIComponent(jobId)}`,
      { cache: "no-store" },
    ),
  );
}

export async function pauseCatalogTranslationJob(
  jobId: string,
): Promise<CatalogTranslationJob> {
  return mapCatalogTranslationJob(
    await request<ApiCatalogTranslationJob>(
      `/catalog/translations/jobs/${encodeURIComponent(jobId)}/pause`,
      { method: "POST" },
    ),
  );
}

export async function resumeCatalogTranslationJob(
  jobId: string,
): Promise<CatalogTranslationJob> {
  return mapCatalogTranslationJob(
    await request<ApiCatalogTranslationJob>(
      `/catalog/translations/jobs/${encodeURIComponent(jobId)}/resume`,
      { method: "POST" },
    ),
  );
}

export async function getProduct(productId: string): Promise<ProductDetail> {
  const row = await request<ApiProductDetail>(`/products/${encodeURIComponent(productId)}`);
  return mapProductDetail(row);
}

export async function createManualProduct(
  input: ManualProductCreateInput,
): Promise<ProductDetail> {
  const row = await request<ApiProductDetail>("/products", {
    method: "POST",
    body: JSON.stringify({
      name: input.name,
      product_code: input.productCode,
      description: input.description,
      category_id: input.categoryId,
      default_unit: input.defaultUnit,
      image_url: input.imageUrl,
      sku_code: input.skuCode,
      sku_name: input.skuName,
      barcode: input.barcode,
      default_moq: input.defaultMoq,
      moq_unit: input.moqUnit,
      weight: input.weight,
      weight_unit: input.weightUnit,
      unit_price: input.unitPrice,
      currency: input.currency,
      tags: input.tags,
      publish_to_storefront: input.publishToStorefront,
    }),
  });
  bumpPublicCatalogRevision();
  return mapProductDetail(row);
}

export async function createSkus(productId: string, items: Array<{ skuCode: string; name?: string; optionValues: Record<string, string>; status?: ProductSku["status"] }>) {
  const rows = await request<ApiSku[]>(`/products/${encodeURIComponent(productId)}/skus`, {
    method: "POST",
    body: JSON.stringify({ items: items.map((item) => ({ sku_code: item.skuCode, name: item.name, option_values: item.optionValues, status: item.status ?? "DRAFT" })) }),
  });
  return rows.map(mapSku);
}

export async function updateSku(skuId: string, input: Partial<Omit<ProductSku, "id" | "productId" | "skuCode" | "version" | "updatedAt">> & { expectedVersion: number }) {
  return mapSku(await request<ApiSku>(`/skus/${encodeURIComponent(skuId)}`, {
    method: "PATCH",
    body: JSON.stringify({ expected_version: input.expectedVersion, name: input.name, option_values: input.optionValues, barcode: input.barcode, weight: input.weight, weight_unit: input.weightUnit, status: input.status }),
  }));
}

interface ApiPublicCatalogOffer {
  id: string;
  sku_id: string;
  unit_price: number | string;
  currency: string;
  tags: string[];
  display_tag?: string | null;
  tag_color?: string | null;
  publication_status: PublicCatalogOffer["publicationStatus"];
  published_at?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  created_at: string;
  updated_at: string;
}

function mapPublicCatalogOffer(row: ApiPublicCatalogOffer): PublicCatalogOffer {
  return {
    id: row.id,
    skuId: row.sku_id,
    unitPrice: Number(row.unit_price),
    currency: row.currency,
    tags: row.tags ?? [],
    displayTag: defined(row.display_tag),
    tagColor: defined(row.tag_color),
    publicationStatus: row.publication_status,
    publishedAt: defined(row.published_at),
    validFrom: defined(row.valid_from),
    validTo: defined(row.valid_to),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export async function listPublicCatalogOffers(productId: string) {
  return (await request<ApiPublicCatalogOffer[]>(`/products/${encodeURIComponent(productId)}/public-offers`)).map(mapPublicCatalogOffer);
}

export async function upsertPublicCatalogOffer(
  skuId: string,
  input: {
    unitPrice: number;
    currency: string;
    tags: string[];
    displayTag?: string;
    tagColor?: string;
    publicationStatus: PublicCatalogOffer["publicationStatus"];
    validFrom?: string;
    validTo?: string;
  },
) {
  return mapPublicCatalogOffer(await request<ApiPublicCatalogOffer>(`/skus/${encodeURIComponent(skuId)}/public-offer`, {
    method: "PUT",
    body: JSON.stringify({
      unit_price: input.unitPrice,
      currency: input.currency,
      tags: input.tags,
      display_tag: input.displayTag ?? null,
      tag_color: input.tagColor ?? null,
      publication_status: input.publicationStatus,
      valid_from: input.validFrom,
      valid_to: input.validTo,
    }),
  }));
}

interface ApiCategory { id: string; parent_id?: string | null; code: string; name: string; path?: string | null; display_color?: string | null; status: string; sort_order: number; version: number }
interface ApiAttributeDefinition { id: string; category_id?: string | null; attribute_key: string; display_name: string; data_type: AttributeDefinition["dataType"]; unit_code?: string | null; enum_values?: string[] | null; is_required: boolean; is_variant: boolean; is_filterable: boolean; is_matchable: boolean; status: string; version: number }

interface ApiCategoryImportResult {
  processed_rows: number;
  primary_created: number;
  secondary_created: number;
  primary_existing: number;
  secondary_existing: number;
  duplicate_rows_ignored: number;
  blank_rows_ignored: number;
}

interface ApiCategoryDeleteImpact {
  category_id: string;
  category_name: string;
  is_primary: boolean;
  child_category_count: number;
  affected_product_count: number;
  attribute_definition_count: number;
  attribute_value_count: number;
}

interface ApiCategoryDeleteResult {
  deleted_category_count: number;
  unclassified_product_count: number;
  deleted_attribute_definition_count: number;
  detached_attribute_value_count: number;
  all_products_position: number;
}

export interface CategoryImportResult {
  processedRows: number;
  primaryCreated: number;
  secondaryCreated: number;
  primaryExisting: number;
  secondaryExisting: number;
  duplicateRowsIgnored: number;
  blankRowsIgnored: number;
}

export interface CategoryDeleteImpact {
  categoryId: string;
  categoryName: string;
  isPrimary: boolean;
  childCategoryCount: number;
  affectedProductCount: number;
  attributeDefinitionCount: number;
  attributeValueCount: number;
}

export interface CategoryDeleteResult {
  deletedCategoryCount: number;
  unclassifiedProductCount: number;
  deletedAttributeDefinitionCount: number;
  detachedAttributeValueCount: number;
  allProductsPosition: number;
}

export async function listCategories(): Promise<ProductCategory[]> {
  return (await request<ApiCategory[]>("/categories")).map(mapCategory);
}

export async function importCategories(file: File): Promise<CategoryImportResult> {
  const body = new FormData();
  body.append("file", file);
  const row = await request<ApiCategoryImportResult>("/categories/import", {
    method: "POST",
    body,
  });
  bumpPublicCatalogRevision();
  return {
    processedRows: row.processed_rows,
    primaryCreated: row.primary_created,
    secondaryCreated: row.secondary_created,
    primaryExisting: row.primary_existing,
    secondaryExisting: row.secondary_existing,
    duplicateRowsIgnored: row.duplicate_rows_ignored,
    blankRowsIgnored: row.blank_rows_ignored,
  };
}

export async function getCategoryDeleteImpact(categoryId: string): Promise<CategoryDeleteImpact> {
  const row = await request<ApiCategoryDeleteImpact>(
    `/categories/${encodeURIComponent(categoryId)}/delete-impact`,
    { cache: "no-store" },
  );
  return {
    categoryId: row.category_id,
    categoryName: row.category_name,
    isPrimary: row.is_primary,
    childCategoryCount: row.child_category_count,
    affectedProductCount: row.affected_product_count,
    attributeDefinitionCount: row.attribute_definition_count,
    attributeValueCount: row.attribute_value_count,
  };
}

export async function deleteCategory(
  categoryId: string,
  expectedVersion: number,
): Promise<CategoryDeleteResult> {
  const row = await request<ApiCategoryDeleteResult>(
    `/categories/${encodeURIComponent(categoryId)}?expected_version=${expectedVersion}`,
    { method: "DELETE" },
  );
  bumpPublicCatalogRevision();
  return {
    deletedCategoryCount: row.deleted_category_count,
    unclassifiedProductCount: row.unclassified_product_count,
    deletedAttributeDefinitionCount: row.deleted_attribute_definition_count,
    detachedAttributeValueCount: row.detached_attribute_value_count,
    allProductsPosition: row.all_products_position,
  };
}

interface ApiCategoryLayout {
  all_products_position: number;
  root_category_count: number;
}

function mapCategoryLayout(row: ApiCategoryLayout): CategoryLayout {
  return {
    allProductsPosition: row.all_products_position,
    rootCategoryCount: row.root_category_count,
  };
}

export async function getCategoryLayout(): Promise<CategoryLayout> {
  return mapCategoryLayout(await request<ApiCategoryLayout>("/categories/layout"));
}

export async function updateCategoryLayout(
  allProductsPosition: number,
): Promise<CategoryLayout> {
  const saved = mapCategoryLayout(await request<ApiCategoryLayout>("/categories/layout", {
    method: "PATCH",
    body: JSON.stringify({ all_products_position: allProductsPosition }),
  }));
  bumpPublicCatalogRevision();
  return saved;
}

function mapCategory(row: ApiCategory): ProductCategory {
  return { id: row.id, parentId: defined(row.parent_id), code: row.code, name: row.name, path: defined(row.path), displayColor: defined(row.display_color), status: row.status, sortOrder: row.sort_order, version: row.version };
}

export async function createCategory(input: { name: string; parentId?: string; sortOrder?: number; displayColor?: string }): Promise<ProductCategory> {
  const suffix = crypto.randomUUID().replaceAll("-", "").slice(0, 24).toUpperCase();
  const created = mapCategory(await request<ApiCategory>("/categories", {
    method: "POST",
    body: JSON.stringify({
      parent_id: input.parentId,
      code: `MAN-${suffix}`,
      name: input.name,
      sort_order: input.sortOrder ?? 0,
      display_color: input.displayColor,
    }),
  }));
  bumpPublicCatalogRevision();
  return created;
}

export async function updateCategory(input: { id: string; expectedVersion: number; name: string; parentId?: string; sortOrder: number; status: "ACTIVE" | "INACTIVE"; displayColor?: string | null }): Promise<ProductCategory> {
  const updated = mapCategory(await request<ApiCategory>(`/categories/${encodeURIComponent(input.id)}`, {
    method: "PATCH",
    body: JSON.stringify({
      expected_version: input.expectedVersion,
      parent_id: input.parentId,
      name: input.name,
      sort_order: input.sortOrder,
      status: input.status,
      display_color: input.displayColor,
    }),
  }));
  bumpPublicCatalogRevision();
  return updated;
}

export async function reorderCategories(categories: ProductCategory[]): Promise<ProductCategory[]> {
  const reordered = (await request<ApiCategory[]>("/categories/reorder", {
    method: "PATCH",
    body: JSON.stringify({
      items: categories.map((category) => ({
        id: category.id,
        expected_version: category.version,
      })),
    }),
  })).map(mapCategory);
  bumpPublicCatalogRevision();
  return reordered;
}

interface ApiSystemMonitoringSnapshot {
  sampled_at: string;
  scope: string;
  uptime_seconds?: number | null;
  cpu: {
    utilization_percent?: number | null;
    logical_cores: number;
    quota_cores?: number | null;
    load_1m?: number | null;
    load_5m?: number | null;
    load_15m?: number | null;
  };
  memory: {
    used_bytes?: number | null;
    total_bytes?: number | null;
    available_bytes?: number | null;
    utilization_percent?: number | null;
    container_used_bytes?: number | null;
    container_limit_bytes?: number | null;
  };
  disk: {
    mount_path: string;
    used_bytes: number;
    total_bytes: number;
    available_bytes: number;
    utilization_percent: number;
  };
}

export async function getSystemMonitoring(): Promise<SystemMonitoringSnapshot> {
  const row = await request<ApiSystemMonitoringSnapshot>("/system/metrics", {
    cache: "no-store",
  });
  return {
    sampledAt: row.sampled_at,
    scope: row.scope,
    uptimeSeconds: defined(row.uptime_seconds),
    cpu: {
      utilizationPercent: defined(row.cpu.utilization_percent),
      logicalCores: row.cpu.logical_cores,
      quotaCores: defined(row.cpu.quota_cores),
      load1m: defined(row.cpu.load_1m),
      load5m: defined(row.cpu.load_5m),
      load15m: defined(row.cpu.load_15m),
    },
    memory: {
      usedBytes: defined(row.memory.used_bytes),
      totalBytes: defined(row.memory.total_bytes),
      availableBytes: defined(row.memory.available_bytes),
      utilizationPercent: defined(row.memory.utilization_percent),
      containerUsedBytes: defined(row.memory.container_used_bytes),
      containerLimitBytes: defined(row.memory.container_limit_bytes),
    },
    disk: {
      mountPath: row.disk.mount_path,
      usedBytes: row.disk.used_bytes,
      totalBytes: row.disk.total_bytes,
      availableBytes: row.disk.available_bytes,
      utilizationPercent: row.disk.utilization_percent,
    },
  };
}

export async function getStorefrontAnalytics(
  days: 7 | 30 | 60,
): Promise<StorefrontAnalyticsSnapshot> {
  const row = await request<{
    generated_at: string;
    timezone: string;
    start_date: string;
    end_date: string;
    days: number;
    raw_ip_retention_days: number;
    summary: {
      total_views: number;
      unique_visitors: number;
      viewed_products: number;
      identified_countries: number;
    };
    daily: Array<{ date: string; views: number }>;
    countries: Array<{ country_code: string; views: number; share: number }>;
    products: Array<{
      product_id: string;
      sku_id: string;
      sku_code: string;
      name: string;
      views: number;
    }>;
    country_products: Array<{
      country_code: string;
      sku_id: string;
      views: number;
    }>;
  }>(`/storefront-analytics?days=${days}`, { cache: "no-store" });
  return {
    generatedAt: row.generated_at,
    timezone: row.timezone,
    startDate: row.start_date,
    endDate: row.end_date,
    days: row.days,
    rawIpRetentionDays: row.raw_ip_retention_days,
    summary: {
      totalViews: Number(row.summary.total_views || 0),
      uniqueVisitors: Number(row.summary.unique_visitors || 0),
      viewedProducts: Number(row.summary.viewed_products || 0),
      identifiedCountries: Number(row.summary.identified_countries || 0),
    },
    daily: row.daily.map((item) => ({
      date: item.date,
      views: Number(item.views || 0),
    })),
    countries: row.countries.map((item) => ({
      countryCode: item.country_code,
      views: Number(item.views || 0),
      share: Number(item.share || 0),
    })),
    products: row.products.map((item) => ({
      productId: item.product_id,
      skuId: item.sku_id,
      skuCode: item.sku_code,
      name: item.name,
      views: Number(item.views || 0),
    })),
    countryProducts: row.country_products.map((item) => ({
      countryCode: item.country_code,
      skuId: item.sku_id,
      views: Number(item.views || 0),
    })),
  };
}

interface ApiStorefrontAnnouncement {
  id: string;
  title?: string | null;
  display_type: "TICKER" | "MODAL";
  ticker_text?: string | null;
  content_blocks: AnnouncementContentBlock[];
  starts_at: string;
  ends_at: string;
  ticker_speed_px_per_second?: number | null;
  publication_status: "DRAFT" | "PUBLISHED" | "PAUSED";
  related_skus: Array<{
    id: string;
    product_id: string;
    sku_code: string;
    name: string;
    product_name: string;
    is_public: boolean;
  }>;
  version: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

function mapStorefrontAnnouncement(
  row: ApiStorefrontAnnouncement,
): StorefrontAnnouncement {
  return {
    id: row.id,
    title: defined(row.title),
    displayType: row.display_type,
    tickerText: defined(row.ticker_text),
    contentBlocks: row.content_blocks || [],
    startsAt: row.starts_at,
    endsAt: row.ends_at,
    tickerSpeedPxPerSecond: normalizeAnnouncementTickerSpeed(
      row.ticker_speed_px_per_second,
    ),
    publicationStatus: row.publication_status,
    relatedSkus: (row.related_skus || []).map((sku) => ({
      id: sku.id,
      productId: sku.product_id,
      skuCode: sku.sku_code,
      name: sku.name,
      productName: sku.product_name,
      isPublic: sku.is_public,
    })),
    version: row.version,
    isActive: row.is_active,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function announcementBody(input: AnnouncementPayload) {
  return {
    title: input.title,
    display_type: input.displayType,
    ticker_text: input.displayType === "TICKER" ? input.tickerText || null : null,
    content_blocks: input.displayType === "MODAL" ? input.contentBlocks : [],
    starts_at: input.startsAt,
    ends_at: input.endsAt || null,
    duration_days: input.durationDays ?? null,
    ticker_speed_px_per_second: normalizeAnnouncementTickerSpeed(
      input.tickerSpeedPxPerSecond,
    ),
    publication_status: input.publicationStatus,
    related_sku_ids: input.relatedSkuIds,
  };
}

export async function listAnnouncements(): Promise<{
  items: StorefrontAnnouncement[];
  total: number;
}> {
  const row = await request<{
    items: ApiStorefrontAnnouncement[];
    total: number;
  }>("/announcements");
  return {
    items: row.items.map(mapStorefrontAnnouncement),
    total: row.total,
  };
}

export async function createAnnouncement(
  input: AnnouncementPayload,
): Promise<StorefrontAnnouncement> {
  const announcement = mapStorefrontAnnouncement(
    await request<ApiStorefrontAnnouncement>("/announcements", {
      method: "POST",
      body: JSON.stringify(announcementBody(input)),
    }),
  );
  bumpPublicCatalogRevision();
  return announcement;
}

export async function updateAnnouncement(
  announcementId: string,
  input: AnnouncementPayload,
): Promise<StorefrontAnnouncement> {
  const announcement = mapStorefrontAnnouncement(
    await request<ApiStorefrontAnnouncement>(
      `/announcements/${encodeURIComponent(announcementId)}`,
      {
        method: "PUT",
        body: JSON.stringify(announcementBody(input)),
      },
    ),
  );
  bumpPublicCatalogRevision();
  return announcement;
}

export async function deleteAnnouncement(
  announcementId: string,
): Promise<void> {
  await request<void>(
    `/announcements/${encodeURIComponent(announcementId)}`,
    { method: "DELETE" },
  );
  bumpPublicCatalogRevision();
}

interface ApiSupportAIProviderSettings {
  source: "database" | "environment" | "disabled";
  provider: string;
  enabled: boolean;
  base_url?: string | null;
  model_name?: string | null;
  timeout_seconds: number;
  max_output_tokens: number;
  temperature: number;
  api_key_configured: boolean;
  api_key_hint?: string | null;
  updated_at?: string | null;
}

function mapSupportAIProviderSettings(
  row: ApiSupportAIProviderSettings,
): SupportAIProviderSettings {
  return {
    source: row.source,
    provider: row.provider,
    enabled: row.enabled,
    baseUrl: defined(row.base_url),
    modelName: defined(row.model_name),
    timeoutSeconds: row.timeout_seconds,
    maxOutputTokens: row.max_output_tokens,
    temperature: row.temperature,
    apiKeyConfigured: row.api_key_configured,
    apiKeyHint: defined(row.api_key_hint),
    updatedAt: defined(row.updated_at),
  };
}

export interface SupportAIProviderSettingsWriteInput {
  enabled: boolean;
  baseUrl: string;
  modelName: string;
  apiKey?: string;
  timeoutSeconds: number;
  maxOutputTokens: number;
  temperature: number;
}

export async function getSupportAIProviderSettings(): Promise<SupportAIProviderSettings> {
  return mapSupportAIProviderSettings(
    await request<ApiSupportAIProviderSettings>(
      "/system/ai-generation/settings",
      { cache: "no-store" },
    ),
  );
}

export async function updateSupportAIProviderSettings(
  input: SupportAIProviderSettingsWriteInput,
): Promise<SupportAIProviderSettings> {
  return mapSupportAIProviderSettings(
    await request<ApiSupportAIProviderSettings>(
      "/system/ai-generation/settings",
      {
        method: "PUT",
        body: JSON.stringify({
          enabled: input.enabled,
          base_url: input.baseUrl,
          model_name: input.modelName,
          api_key: input.apiKey || undefined,
          timeout_seconds: input.timeoutSeconds,
          max_output_tokens: input.maxOutputTokens,
          temperature: input.temperature,
        }),
      },
    ),
  );
}

interface ApiSupportAISettings {
  mode: SupportAIMode;
  sku_knowledge_enabled: boolean;
  file_knowledge_enabled: boolean;
  multilingual_enabled: boolean;
  min_retrieval_score: number;
  min_answer_confidence: number;
  max_sources: number;
  daily_auto_reply_limit: number;
  system_prompt?: string | null;
  handoff_messages: Record<string, string>;
  prompt_version: number;
  provider_configured: boolean;
  approved_file_sources: number;
  indexed_sku_products: number;
  updated_at?: string | null;
}

function mapSupportAISettings(row: ApiSupportAISettings): SupportAISettings {
  return {
    mode: row.mode,
    skuKnowledgeEnabled: row.sku_knowledge_enabled,
    fileKnowledgeEnabled: row.file_knowledge_enabled,
    multilingualEnabled: row.multilingual_enabled,
    minRetrievalScore: row.min_retrieval_score,
    minAnswerConfidence: row.min_answer_confidence,
    maxSources: row.max_sources,
    dailyAutoReplyLimit: row.daily_auto_reply_limit,
    systemPrompt: defined(row.system_prompt),
    handoffMessages: row.handoff_messages || {},
    promptVersion: row.prompt_version,
    providerConfigured: row.provider_configured,
    approvedFileSources: row.approved_file_sources,
    indexedSkuProducts: row.indexed_sku_products,
    updatedAt: defined(row.updated_at),
  };
}

export interface SupportAISettingsWriteInput {
  mode: SupportAIMode;
  skuKnowledgeEnabled: boolean;
  fileKnowledgeEnabled: boolean;
  multilingualEnabled: boolean;
  minRetrievalScore: number;
  minAnswerConfidence: number;
  maxSources: number;
  dailyAutoReplyLimit: number;
  systemPrompt?: string;
  handoffMessages: Record<string, string>;
}

export async function getSupportAISettings(): Promise<SupportAISettings> {
  return mapSupportAISettings(
    await request<ApiSupportAISettings>("/support/ai/settings", {
      cache: "no-store",
    }),
  );
}

export async function updateSupportAISettings(
  input: SupportAISettingsWriteInput,
): Promise<SupportAISettings> {
  return mapSupportAISettings(
    await request<ApiSupportAISettings>("/support/ai/settings", {
      method: "PATCH",
      body: JSON.stringify({
        mode: input.mode,
        sku_knowledge_enabled: input.skuKnowledgeEnabled,
        file_knowledge_enabled: input.fileKnowledgeEnabled,
        multilingual_enabled: input.multilingualEnabled,
        min_retrieval_score: input.minRetrievalScore,
        min_answer_confidence: input.minAnswerConfidence,
        max_sources: input.maxSources,
        daily_auto_reply_limit: input.dailyAutoReplyLimit,
        system_prompt: input.systemPrompt || null,
        handoff_messages: input.handoffMessages,
      }),
    }),
  );
}

interface ApiSupportAIKnowledgeSource {
  id: string;
  title: string;
  description?: string | null;
  classification: "PUBLIC" | "CUSTOMER_APPROVED";
  language: string;
  status: SupportAIKnowledgeSource["status"];
  original_filename: string;
  content_type?: string | null;
  sha256: string;
  byte_size: number;
  chunk_count: number;
  version: number;
  failure_code?: string | null;
  failure_message?: string | null;
  approved_at?: string | null;
  created_at: string;
  updated_at: string;
}

function mapSupportAIKnowledgeSource(
  row: ApiSupportAIKnowledgeSource,
): SupportAIKnowledgeSource {
  return {
    id: row.id,
    title: row.title,
    description: defined(row.description),
    classification: row.classification,
    language: row.language,
    status: row.status,
    originalFilename: row.original_filename,
    contentType: defined(row.content_type),
    sha256: row.sha256,
    byteSize: row.byte_size,
    chunkCount: row.chunk_count,
    version: row.version,
    failureCode: defined(row.failure_code),
    failureMessage: defined(row.failure_message),
    approvedAt: defined(row.approved_at),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

interface ApiSupportAIIngestionJob {
  id: string;
  source_id: string;
  status: SupportAIIngestionJob["status"];
  progress: number;
  parser_identifier?: string | null;
  parser_version?: string | null;
  chunks_written: number;
  error_code?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
}

function mapSupportAIIngestionJob(
  row: ApiSupportAIIngestionJob,
): SupportAIIngestionJob {
  return {
    id: row.id,
    sourceId: row.source_id,
    status: row.status,
    progress: row.progress,
    parserIdentifier: defined(row.parser_identifier),
    parserVersion: defined(row.parser_version),
    chunksWritten: row.chunks_written,
    errorCode: defined(row.error_code),
    errorMessage: defined(row.error_message),
    startedAt: defined(row.started_at),
    completedAt: defined(row.completed_at),
    createdAt: row.created_at,
  };
}

export async function listSupportAIKnowledgeSources(): Promise<SupportAIKnowledgeSource[]> {
  return (
    await request<ApiSupportAIKnowledgeSource[]>(
      "/support/ai/knowledge/sources",
      { cache: "no-store" },
    )
  ).map(mapSupportAIKnowledgeSource);
}

export async function uploadSupportAIKnowledgeSource(input: {
  file: File;
  title: string;
  description?: string;
  classification: "PUBLIC" | "CUSTOMER_APPROVED";
  language: string;
}): Promise<{ source: SupportAIKnowledgeSource; job: SupportAIIngestionJob }> {
  const body = new FormData();
  body.append("file", input.file);
  body.append("title", input.title);
  body.append("description", input.description || "");
  body.append("classification", input.classification);
  body.append("language", input.language);
  const row = await request<{
    source: ApiSupportAIKnowledgeSource;
    job: ApiSupportAIIngestionJob;
  }>("/support/ai/knowledge/sources/upload", { method: "POST", body });
  return {
    source: mapSupportAIKnowledgeSource(row.source),
    job: mapSupportAIIngestionJob(row.job),
  };
}

export async function updateSupportAIKnowledgeSource(
  sourceId: string,
  input: {
    title: string;
    description?: string;
    classification: "PUBLIC" | "CUSTOMER_APPROVED";
    language: string;
  },
): Promise<SupportAIKnowledgeSource> {
  return mapSupportAIKnowledgeSource(
    await request<ApiSupportAIKnowledgeSource>(
      `/support/ai/knowledge/sources/${encodeURIComponent(sourceId)}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          title: input.title,
          description: input.description || null,
          classification: input.classification,
          language: input.language,
        }),
      },
    ),
  );
}

export async function approveSupportAIKnowledgeSource(
  sourceId: string,
): Promise<SupportAIKnowledgeSource> {
  return mapSupportAIKnowledgeSource(
    await request<ApiSupportAIKnowledgeSource>(
      `/support/ai/knowledge/sources/${encodeURIComponent(sourceId)}/approve`,
      { method: "POST" },
    ),
  );
}

export async function revokeSupportAIKnowledgeSource(
  sourceId: string,
): Promise<SupportAIKnowledgeSource> {
  return mapSupportAIKnowledgeSource(
    await request<ApiSupportAIKnowledgeSource>(
      `/support/ai/knowledge/sources/${encodeURIComponent(sourceId)}`,
      { method: "DELETE" },
    ),
  );
}

export async function reindexSupportAIKnowledgeSource(
  sourceId: string,
): Promise<SupportAIIngestionJob> {
  return mapSupportAIIngestionJob(
    await request<ApiSupportAIIngestionJob>(
      `/support/ai/knowledge/sources/${encodeURIComponent(sourceId)}/reindex`,
      { method: "POST" },
    ),
  );
}

export async function getSupportAIIngestionJob(
  jobId: string,
): Promise<SupportAIIngestionJob> {
  return mapSupportAIIngestionJob(
    await request<ApiSupportAIIngestionJob>(
      `/support/ai/knowledge/jobs/${encodeURIComponent(jobId)}`,
      { cache: "no-store" },
    ),
  );
}

interface ApiSupportAIRun {
  id: string;
  ai_task_id: string;
  conversation_id?: string | null;
  input_message_id?: string | null;
  output_message_id?: string | null;
  trigger_type: "CHAT" | "TEST";
  mode_snapshot: SupportAIMode;
  status: SupportAIRun["status"];
  question: string;
  visitor_locale: string;
  detected_language?: string | null;
  normalized_query?: string | null;
  answer?: string | null;
  confidence?: number | null;
  handoff_reason?: string | null;
  prompt_version: number;
  retrieval_count: number;
  decision_trace: Record<string, unknown>;
  error_code?: string | null;
  error_message?: string | null;
  evidence: ApiSupportCitation[];
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

function mapSupportAIRun(row: ApiSupportAIRun): SupportAIRun {
  return {
    id: row.id,
    aiTaskId: row.ai_task_id,
    conversationId: defined(row.conversation_id),
    inputMessageId: defined(row.input_message_id),
    outputMessageId: defined(row.output_message_id),
    triggerType: row.trigger_type,
    modeSnapshot: row.mode_snapshot,
    status: row.status,
    question: row.question,
    visitorLocale: row.visitor_locale,
    detectedLanguage: defined(row.detected_language),
    normalizedQuery: defined(row.normalized_query),
    answer: defined(row.answer),
    confidence: row.confidence ?? undefined,
    handoffReason: defined(row.handoff_reason),
    promptVersion: row.prompt_version,
    retrievalCount: row.retrieval_count,
    decisionTrace: row.decision_trace || {},
    errorCode: defined(row.error_code),
    errorMessage: defined(row.error_message),
    evidence: (row.evidence || []).map(mapSupportCitation),
    createdAt: row.created_at,
    startedAt: defined(row.started_at),
    completedAt: defined(row.completed_at),
  };
}

export async function runSupportAITest(
  question: string,
  locale: string,
): Promise<SupportAIRun> {
  return mapSupportAIRun(
    await request<ApiSupportAIRun>("/support/ai/test-runs", {
      method: "POST",
      body: JSON.stringify({ question, locale }),
    }),
  );
}

export async function listSupportAIRuns(input: {
  page?: number;
  pageSize?: number;
  status?: string;
} = {}): Promise<SupportAIRunPage> {
  const params = new URLSearchParams({
    page: String(input.page || 1),
    page_size: String(input.pageSize || 30),
  });
  if (input.status) params.set("status", input.status);
  const row = await request<{
    items: ApiSupportAIRun[];
    total: number;
    page: number;
    page_size: number;
    pages: number;
  }>(`/support/ai/runs?${params}`, { cache: "no-store" });
  return {
    items: row.items.map(mapSupportAIRun),
    total: row.total,
    page: row.page,
    pageSize: row.page_size,
    pages: row.pages,
  };
}

export async function getSupportAIRun(runId: string): Promise<SupportAIRun> {
  return mapSupportAIRun(
    await request<ApiSupportAIRun>(
      `/support/ai/runs/${encodeURIComponent(runId)}`,
      { cache: "no-store" },
    ),
  );
}

interface ApiSupportActionSettings {
  slot: 2 | 3;
  visible: boolean;
  label?: string | null;
  external_image_url?: string | null;
  image_url?: string | null;
  has_uploaded_image: boolean;
}

interface ApiSupportSettings {
  welcome_message: string;
  custom_actions: ApiSupportActionSettings[];
}

interface ApiSupportConversationSummary {
  id: string;
  reference_number: string;
  visitor_name?: string | null;
  visitor_email?: string | null;
  locale: string;
  status: SupportConversationStatus;
  last_message_preview: string;
  last_message_at: string;
  unread: boolean;
  automation_state: SupportAutomationState;
  ai_processing: boolean;
}

interface ApiSupportCitation {
  citation_number: number;
  source_type: "SKU" | "FILE";
  source_entity_id: string;
  source_title: string;
  source_version: number;
  classification: "PUBLIC" | "CUSTOMER_APPROVED";
  locator: Record<string, unknown>;
  excerpt: string;
  score: number;
}

interface ApiSupportConversationDetail extends ApiSupportConversationSummary {
  messages: Array<{
    id: string;
    sender_type: "VISITOR" | "MERCHANT" | "SYSTEM" | "AI";
    body: string;
    draft_body?: string | null;
    translated_body?: string | null;
    translation_source_locale?: StorefrontLocale | null;
    translation_target_locale?: StorefrontLocale | null;
    translation_status: "PENDING" | "READY" | "FAILED" | "UNAVAILABLE" | "NOT_REQUIRED";
    created_at: string;
    citations?: ApiSupportCitation[];
  }>;
}

interface ApiSupportTranslationPreview {
  source_locale: StorefrontLocale;
  target_locale: StorefrontLocale;
  original_message: string;
  translated_message: string;
}

function mapSupportAction(row: ApiSupportActionSettings): SupportActionSettings {
  return {
    slot: row.slot,
    visible: row.visible,
    label: defined(row.label),
    externalImageUrl: defined(row.external_image_url),
    imageUrl: defined(row.image_url),
    hasUploadedImage: row.has_uploaded_image,
  };
}

function mapSupportSettings(row: ApiSupportSettings): SupportSettings {
  return {
    welcomeMessage: row.welcome_message,
    customActions: (row.custom_actions || []).map(mapSupportAction),
  };
}

function mapSupportCitation(row: ApiSupportCitation): SupportCitation {
  return {
    citationNumber: row.citation_number,
    sourceType: row.source_type,
    sourceEntityId: row.source_entity_id,
    sourceTitle: row.source_title,
    sourceVersion: row.source_version,
    classification: row.classification,
    locator: row.locator || {},
    excerpt: row.excerpt,
    score: row.score,
  };
}

function mapSupportSummary(
  row: ApiSupportConversationSummary,
): SupportConversationDetail | SupportConversationPage["items"][number] {
  const summary = {
    id: row.id,
    referenceNumber: row.reference_number,
    visitorName: defined(row.visitor_name),
    visitorEmail: defined(row.visitor_email),
    locale: row.locale,
    status: row.status,
    lastMessagePreview: row.last_message_preview,
    lastMessageAt: row.last_message_at,
    unread: row.unread,
    automationState: row.automation_state,
    aiProcessing: row.ai_processing,
  };
  if ("messages" in row) {
    const detail = row as ApiSupportConversationDetail;
    return {
      ...summary,
      messages: detail.messages.map((message) => ({
        id: message.id,
        senderType: message.sender_type,
        body: message.body,
        draftBody: defined(message.draft_body),
        translatedBody: defined(message.translated_body),
        translationSourceLocale: defined(message.translation_source_locale),
        translationTargetLocale: defined(message.translation_target_locale),
        translationStatus: message.translation_status,
        createdAt: message.created_at,
        citations: (message.citations || []).map(mapSupportCitation),
      })),
    };
  }
  return summary;
}

export async function getSupportSettings(): Promise<SupportSettings> {
  return mapSupportSettings(
    await request<ApiSupportSettings>("/support/settings", { cache: "no-store" }),
  );
}

export async function updateSupportSettings(
  input: SupportSettings,
): Promise<SupportSettings> {
  const saved = mapSupportSettings(
    await request<ApiSupportSettings>("/support/settings", {
      method: "PATCH",
      body: JSON.stringify({
        welcome_message: input.welcomeMessage,
        custom_actions: input.customActions.map((action) => ({
          slot: action.slot,
          visible: action.visible,
          label: action.label || null,
          external_image_url: action.externalImageUrl || null,
        })),
      }),
    }),
  );
  bumpPublicCatalogRevision();
  return saved;
}

export async function uploadSupportActionImage(
  slot: 2 | 3,
  image: File,
): Promise<SupportSettings> {
  const body = new FormData();
  body.append("image", image);
  const saved = mapSupportSettings(
    await request<ApiSupportSettings>(`/support/settings/actions/${slot}/image`, {
      method: "POST",
      body,
    }),
  );
  bumpPublicCatalogRevision();
  return saved;
}

export async function listSupportConversations(input: {
  page?: number;
  pageSize?: number;
  status?: SupportConversationStatus | "";
  query?: string;
} = {}): Promise<SupportConversationPage> {
  const params = new URLSearchParams({
    page: String(input.page || 1),
    page_size: String(input.pageSize || 30),
  });
  if (input.status) params.set("status", input.status);
  if (input.query?.trim()) params.set("q", input.query.trim());
  const row = await request<{
    items: ApiSupportConversationSummary[];
    total: number;
    page: number;
    page_size: number;
    pages: number;
  }>(`/support/conversations?${params}`, { cache: "no-store" });
  return {
    items: row.items.map((item) => mapSupportSummary(item) as SupportConversationPage["items"][number]),
    total: row.total,
    page: row.page,
    pageSize: row.page_size,
    pages: row.pages,
  };
}

export async function getSupportConversation(
  conversationId: string,
): Promise<SupportConversationDetail> {
  return mapSupportSummary(
    await request<ApiSupportConversationDetail>(
      `/support/conversations/${encodeURIComponent(conversationId)}`,
      { cache: "no-store" },
    ),
  ) as SupportConversationDetail;
}

export async function replySupportConversation(
  conversationId: string,
  input: {
    message: string;
    draftMessage?: string;
    sourceLocale?: StorefrontLocale;
    targetLocale?: StorefrontLocale;
  },
): Promise<SupportConversationDetail> {
  return mapSupportSummary(
    await request<ApiSupportConversationDetail>(
      `/support/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        body: JSON.stringify({
          message: input.message,
          draft_message: input.draftMessage || null,
          source_locale: input.sourceLocale || null,
          target_locale: input.targetLocale || null,
        }),
      },
    ),
  ) as SupportConversationDetail;
}

export async function previewSupportReplyTranslation(
  conversationId: string,
  message: string,
  targetLocale: StorefrontLocale,
): Promise<SupportTranslationPreview> {
  const row = await request<ApiSupportTranslationPreview>(
    `/support/conversations/${encodeURIComponent(conversationId)}/translation-preview`,
    {
      method: "POST",
      body: JSON.stringify({ message, target_locale: targetLocale }),
    },
  );
  return {
    sourceLocale: row.source_locale,
    targetLocale: row.target_locale,
    originalMessage: row.original_message,
    translatedMessage: row.translated_message,
  };
}

export async function updateSupportConversationStatus(
  conversationId: string,
  status: SupportConversationStatus,
): Promise<SupportConversationDetail> {
  return mapSupportSummary(
    await request<ApiSupportConversationDetail>(
      `/support/conversations/${encodeURIComponent(conversationId)}`,
      { method: "PATCH", body: JSON.stringify({ status }) },
    ),
  ) as SupportConversationDetail;
}

export async function updateSupportConversationAutomation(
  conversationId: string,
  automationState: SupportAutomationState,
): Promise<SupportConversationDetail> {
  return mapSupportSummary(
    await request<ApiSupportConversationDetail>(
      `/support/conversations/${encodeURIComponent(conversationId)}/automation`,
      {
        method: "PATCH",
        body: JSON.stringify({ automation_state: automationState }),
      },
    ),
  ) as SupportConversationDetail;
}

export async function listAttributeDefinitions(categoryId?: string): Promise<AttributeDefinition[]> {
  const rows = await request<ApiAttributeDefinition[]>(`/attribute-definitions${categoryId ? `?category_id=${encodeURIComponent(categoryId)}` : ""}`);
  return rows.map((row) => ({ id: row.id, categoryId: defined(row.category_id), attributeKey: row.attribute_key, displayName: row.display_name, dataType: row.data_type, unitCode: defined(row.unit_code), enumValues: defined(row.enum_values), isRequired: row.is_required, isVariant: row.is_variant, isFilterable: row.is_filterable, isMatchable: row.is_matchable, status: row.status, version: row.version }));
}

export async function createAttributeDefinition(input: Omit<AttributeDefinition, "id" | "status" | "version">) {
  const row = await request<ApiAttributeDefinition>("/attribute-definitions", {
    method: "POST",
    body: JSON.stringify({ category_id: input.categoryId, attribute_key: input.attributeKey, display_name: input.displayName, data_type: input.dataType, unit_code: input.unitCode, enum_values: input.enumValues, is_required: input.isRequired, is_variant: input.isVariant, is_filterable: input.isFilterable, is_matchable: input.isMatchable }),
  });
  return { ...input, id: row.id, status: row.status, version: row.version };
}

interface ApiDashboard { generated_at: string; data_scope: "TENANT" | "SELF"; metrics: Array<{ key: string; label: string; value: number; unit?: string | null; status: string; destination: string }>; recent_imports: Array<{ id: string; filename: string; supplier_name: string; source_type: string; status: string; progress: number; products_count: number; warnings_count: number; created_at: string }>; data_health?: { score: number; active_products: number; approved_image_coverage: number; supplier_source_coverage: number; valid_price_coverage: number } | null }

export async function getDashboard(): Promise<DashboardSnapshot> {
  const row = await request<ApiDashboard>("/dashboard");
  return { generatedAt: row.generated_at, dataScope: row.data_scope, metrics: row.metrics.map((metric) => ({ ...metric, unit: defined(metric.unit) })), recentImports: row.recent_imports.map((item) => ({ id: item.id, filename: item.filename, supplierName: item.supplier_name, sourceType: item.source_type, status: item.status, progress: item.progress, productsCount: item.products_count, warningsCount: item.warnings_count, createdAt: item.created_at })), dataHealth: row.data_health ? { score: row.data_health.score, activeProducts: row.data_health.active_products, approvedImageCoverage: row.data_health.approved_image_coverage, supplierSourceCoverage: row.data_health.supplier_source_coverage, validPriceCoverage: row.data_health.valid_price_coverage } : undefined };
}

export async function searchImage(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<{ id: string; status: string; results: Array<{ product_id: string; visual_similarity: number; classification: string }> }>("/image-searches", { method: "POST", body });
}

export async function searchProducts(query: string, limit = 10): Promise<HybridSearchResponse> {
  const row = await request<{ query: string; degraded: boolean; results: Array<{ product_id: string; product_code?: string | null; name: string; source_version: number; score: number; score_breakdown: HybridSearchResponse["results"][number]["scoreBreakdown"]; supplier_signal_status: string; evidence: Array<{ chunk_type: string; excerpt: string }> }> }>("/ai/search/products", { method: "POST", body: JSON.stringify({ query, limit }) });
  const results = await Promise.all(row.results.map(async (result) => {
    let product: ProductDetail | undefined;
    try { product = await getProduct(result.product_id); } catch { product = undefined; }
    return { productId: result.product_id, productCode: defined(result.product_code), name: result.name, sourceVersion: result.source_version, score: result.score, scoreBreakdown: result.score_breakdown, supplierSignalStatus: result.supplier_signal_status, evidence: result.evidence.map((evidence) => ({ chunkType: evidence.chunk_type, excerpt: evidence.excerpt })), product };
  }));
  return { query: row.query, degraded: row.degraded, results };
}

interface ApiInquiryItem { id: string; line_number: number; raw_requirement: string; normalized_requirement: Record<string, unknown>; quantity?: number | null; unit_code?: string | null; image_search_id?: string | null; status: string; version: number }
interface ApiInquiry { id: string; inquiry_number: string; customer_id?: string | null; temporary_customer_name?: string | null; currency: string; language: string; status: string; version: number; items: ApiInquiryItem[] }
interface ApiMatch { id: string; inquiry_item_id: string; product_id: string; sku_id?: string | null; supplier_product_id?: string | null; product_version: number; rank: number; total_score: number; score_breakdown: Record<string, unknown>; reasons: string[]; gaps: string[]; evidence: Array<Record<string, unknown>>; ranking_version: string; status: string }
interface ApiQuotation { id: string; quotation_number: string; inquiry_id: string; customer_id: string; currency: string; status: string; current_version: number; total_amount: number | string; expires_at?: string | null; approval_status: string; version_hash: string; created_at: string; updated_at: string; versions: Array<{ version_number: number; total_amount: number | string; currency: string; rule_version: string; content_hash: string; approval_status: string; created_at: string }>; items: Array<{ id: string; inquiry_item_id: string; product_id: string; product_snapshot: Record<string, unknown>; source_snapshot: Record<string, unknown>; quantity: number | string; unit_code: string; unit_cost?: number | string | null; target_margin_rate?: number | string | null; unit_price: number | string; line_total: number | string; warnings: string[] }> }

function mapInquiry(row: ApiInquiry): InquiryRecord {
  return { id: row.id, inquiryNumber: row.inquiry_number, customerId: defined(row.customer_id), temporaryCustomerName: defined(row.temporary_customer_name), currency: row.currency, language: row.language, status: row.status, version: row.version, items: row.items.map((item) => ({ id: item.id, lineNumber: item.line_number, rawRequirement: item.raw_requirement, normalizedRequirement: item.normalized_requirement, quantity: defined(item.quantity), unitCode: defined(item.unit_code), imageSearchId: defined(item.image_search_id), status: item.status, version: item.version })) };
}

function mapMatch(row: ApiMatch): InquiryMatch {
  return { id: row.id, inquiryItemId: row.inquiry_item_id, productId: row.product_id, skuId: defined(row.sku_id), supplierProductId: defined(row.supplier_product_id), productVersion: row.product_version, rank: row.rank, totalScore: row.total_score, scoreBreakdown: row.score_breakdown, reasons: row.reasons, gaps: row.gaps, evidence: row.evidence, rankingVersion: row.ranking_version, status: row.status };
}

function mapQuotation(row: ApiQuotation): QuotationRecord {
  return { id: row.id, quotationNumber: row.quotation_number, inquiryId: row.inquiry_id, customerId: row.customer_id, currency: row.currency, status: row.status, currentVersion: row.current_version, totalAmount: Number(row.total_amount), expiresAt: defined(row.expires_at), approvalStatus: row.approval_status, versionHash: row.version_hash, createdAt: row.created_at, updatedAt: row.updated_at, versions: row.versions.map((version) => ({ versionNumber: version.version_number, totalAmount: Number(version.total_amount), currency: version.currency, ruleVersion: version.rule_version, contentHash: version.content_hash, approvalStatus: version.approval_status, createdAt: version.created_at })), items: row.items.map((item) => ({ id: item.id, inquiryItemId: item.inquiry_item_id, productId: item.product_id, productSnapshot: item.product_snapshot, sourceSnapshot: item.source_snapshot, quantity: Number(item.quantity), unitCode: item.unit_code, unitCost: item.unit_cost == null ? undefined : Number(item.unit_cost), targetMarginRate: item.target_margin_rate == null ? undefined : Number(item.target_margin_rate), unitPrice: Number(item.unit_price), lineTotal: Number(item.line_total), warnings: item.warnings })) };
}

export async function createCustomer(companyName: string, currency: string) {
  return (await request<{ id: string }>("/customers", { method: "POST", body: JSON.stringify({ company_name: companyName, language: "en", default_currency: currency }) })).id;
}

export async function createInquiry(input: { customerId: string; currency: string; items: Array<{ requirement: string; quantity: number; unitCode: string; imageSearchId?: string }> }) {
  return mapInquiry(await request<ApiInquiry>("/inquiries", { method: "POST", body: JSON.stringify({ customer_id: input.customerId, currency: input.currency, language: "en", source_type: "MANUAL", items: input.items.map((item) => ({ requirement: item.requirement, quantity: item.quantity, unit_code: item.unitCode, image_search_id: item.imageSearchId })) }) }));
}

export async function matchInquiry(inquiryId: string) {
  const row = await request<{ candidates: Record<string, ApiMatch[]> }>(`/inquiries/${encodeURIComponent(inquiryId)}/match`, { method: "POST" });
  return Object.fromEntries(Object.entries(row.candidates).map(([key, value]) => [key, value.map(mapMatch)]));
}

export async function selectInquiryCandidate(itemId: string, matchId: string) {
  return mapMatch(await request<ApiMatch>(`/inquiry-items/${encodeURIComponent(itemId)}/selection`, { method: "POST", body: JSON.stringify({ match_result_id: matchId }) }));
}

export async function getInquiry(inquiryId: string) {
  return mapInquiry(await request<ApiInquiry>(`/inquiries/${encodeURIComponent(inquiryId)}`));
}

export async function createQuotation(inquiryId: string, marginRate: number) {
  return mapQuotation(await request<ApiQuotation>(`/inquiries/${encodeURIComponent(inquiryId)}/quotation`, { method: "POST", body: JSON.stringify({ target_margin_rate: marginRate, expires_in_days: 30 }) }));
}

export async function decideQuotation(quotationId: string, decision: "APPROVED" | "REJECTED", reason: string) {
  return mapQuotation(await request<ApiQuotation>(`/quotations/${encodeURIComponent(quotationId)}/decision`, { method: "POST", body: JSON.stringify({ decision, reason }) }));
}

export async function getQuotation(quotationId: string) {
  return mapQuotation(await request<ApiQuotation>(`/quotations/${encodeURIComponent(quotationId)}`));
}

export async function reviseQuotation(quotation: QuotationRecord, items: Array<{ itemId: string; quantity: number; targetMarginRate: number }>, changeReason: string) {
  return mapQuotation(await request<ApiQuotation>(`/quotations/${encodeURIComponent(quotation.id)}/revisions`, { method: "POST", body: JSON.stringify({ expected_version: quotation.currentVersion, change_reason: changeReason, items: items.map((item) => ({ item_id: item.itemId, quantity: item.quantity, target_margin_rate: item.targetMarginRate })) }) }));
}

export async function listQuotations(): Promise<QuotationSummary[]> {
  const rows = await request<Array<{ id: string; quotation_number: string; customer_name: string; currency: string; status: string; current_version: number; total_amount: number | string; updated_at: string }>>("/quotations");
  return rows.map((row) => ({ id: row.id, quotationNumber: row.quotation_number, customerName: row.customer_name, currency: row.currency, status: row.status, currentVersion: row.current_version, totalAmount: Number(row.total_amount), updatedAt: row.updated_at }));
}

interface ApiPublicQuoteDraftItem { id: string; sku_id: string; position: number; quantity: number | string; sku_code_snapshot: string; name_snapshot: string; description_snapshot?: string | null; specification_snapshot?: string | null; option_values_snapshot?: Record<string, unknown>; category_snapshot?: string | null; tags_snapshot: string[]; image_url_snapshot?: string | null; unit_code_snapshot: string; currency_snapshot: string; unit_price_snapshot: number | string; line_total: number | string; product_version: number; sku_version: number }
interface ApiPublicQuoteDraft { id: string; tenant_id: string; quote_number: string; status: string; customer_name: string; customer_company?: string | null; customer_email?: string | null; customer_phone?: string | null; notes?: string | null; currency: string; subtotal: number | string; total: number | string; total_amount: number | string; valid_until: string; created_at: string; content_hash: string; disclaimer: string; disclaimer_version: string; items: ApiPublicQuoteDraftItem[] }
interface ApiPublicQuoteDraftSummary { id: string; quote_number: string; status: string; customer_name: string; customer_company?: string | null; currency: string; total_amount: number | string; valid_until: string; created_at: string }

function mapPublicQuoteDraft(row: ApiPublicQuoteDraft): PublicQuoteDraft {
  return {
    id: row.id,
    tenantId: row.tenant_id,
    quoteNumber: row.quote_number,
    status: row.status,
    customerName: row.customer_name,
    customerCompany: defined(row.customer_company),
    customerEmail: defined(row.customer_email),
    customerPhone: defined(row.customer_phone),
    notes: defined(row.notes),
    currency: row.currency,
    subtotal: Number(row.subtotal),
    total: Number(row.total),
    validUntil: row.valid_until,
    createdAt: row.created_at,
    contentHash: row.content_hash,
    disclaimer: row.disclaimer,
    disclaimerVersion: row.disclaimer_version,
    items: row.items.map((item) => ({ id: item.id, skuId: item.sku_id, position: item.position, quantity: Number(item.quantity), skuCode: item.sku_code_snapshot, name: item.name_snapshot, description: defined(item.description_snapshot), specification: defined(item.specification_snapshot), optionValues: item.option_values_snapshot ?? {}, category: defined(item.category_snapshot), tags: item.tags_snapshot ?? [], imageUrl: defined(item.image_url_snapshot), unitCode: item.unit_code_snapshot, currency: item.currency_snapshot, unitPrice: Number(item.unit_price_snapshot), lineTotal: Number(item.line_total), productVersion: item.product_version, skuVersion: item.sku_version })),
  };
}

export async function listPublicQuoteDrafts(): Promise<PublicQuoteDraftSummary[]> {
  const rows = await request<ApiPublicQuoteDraftSummary[]>("/public-quote-drafts");
  return rows.map((row) => ({ id: row.id, quoteNumber: row.quote_number, status: row.status, customerName: row.customer_name, customerCompany: defined(row.customer_company), currency: row.currency, total: Number(row.total_amount), validUntil: row.valid_until, createdAt: row.created_at }));
}

export async function getPublicQuoteDraft(draftId: string): Promise<PublicQuoteDraft> {
  return mapPublicQuoteDraft(await request<ApiPublicQuoteDraft>(`/public-quote-drafts/${encodeURIComponent(draftId)}`));
}

export async function downloadPublicQuoteDraftDocument(
  draftId: string,
  quoteNumber: string,
  type: "pdf" | "xlsx",
): Promise<void> {
  const safeQuoteNumber = quoteNumber.replace(/[^a-zA-Z0-9._-]+/g, "-") || "quotation";
  await downloadCoreFile(
    `/public-quote-drafts/${encodeURIComponent(draftId)}/${type}`,
    `${safeQuoteNumber}.${type}`,
  );
}

interface ApiQuoteExcelColumn {
  key: string;
  index: number;
  header: string;
  samples: string[];
  suggested_field?: QuoteTemplateField | null;
  mapped_field?: QuoteTemplateField | null;
}

interface ApiQuoteExcelTemplate {
  id: string;
  name: string;
  original_filename: string;
  byte_size: number;
  sheet_names: string[];
  sheet_name: string;
  header_row: number;
  data_start_row: number;
  data_end_row: number;
  columns: ApiQuoteExcelColumn[];
  column_mappings: Record<string, QuoteTemplateField>;
  is_default: boolean;
  is_ready: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

function mapQuoteExcelTemplate(row: ApiQuoteExcelTemplate): QuoteExcelTemplate {
  return {
    id: row.id,
    name: row.name,
    originalFilename: row.original_filename,
    byteSize: row.byte_size,
    sheetNames: row.sheet_names,
    sheetName: row.sheet_name,
    headerRow: row.header_row,
    dataStartRow: row.data_start_row,
    dataEndRow: row.data_end_row,
    columns: row.columns.map((column) => ({
      key: column.key,
      index: column.index,
      header: column.header,
      samples: column.samples ?? [],
      suggestedField: defined(column.suggested_field),
      mappedField: defined(column.mapped_field),
    })),
    columnMappings: row.column_mappings ?? {},
    isDefault: row.is_default,
    isReady: row.is_ready,
    version: row.version,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export async function listQuoteExcelTemplates(): Promise<QuoteExcelTemplate[]> {
  const response = await request<{ items: ApiQuoteExcelTemplate[]; total: number }>(
    "/quote-excel-templates",
  );
  return response.items.map(mapQuoteExcelTemplate);
}

export async function downloadSystemDefaultQuoteTemplate(): Promise<void> {
  await downloadCoreFile(
    "/quote-excel-templates/system-default.xlsx",
    "系统默认报价单模板.xlsx",
  );
}

export async function uploadQuoteExcelTemplate(
  file: File,
  name?: string,
): Promise<QuoteExcelTemplate> {
  const body = new FormData();
  body.append("file", file);
  if (name?.trim()) body.append("name", name.trim());
  return mapQuoteExcelTemplate(await request<ApiQuoteExcelTemplate>(
    "/quote-excel-templates",
    { method: "POST", body },
  ));
}

export async function reparseQuoteExcelTemplate(
  templateId: string,
  sheetName: string,
  headerRow: number,
): Promise<QuoteExcelTemplate> {
  return mapQuoteExcelTemplate(await request<ApiQuoteExcelTemplate>(
    `/quote-excel-templates/${encodeURIComponent(templateId)}/reparse`,
    {
      method: "POST",
      body: JSON.stringify({ sheet_name: sheetName, header_row: headerRow }),
    },
  ));
}

export async function updateQuoteExcelTemplate(
  templateId: string,
  input: QuoteExcelTemplateUpdate,
): Promise<QuoteExcelTemplate> {
  return mapQuoteExcelTemplate(await request<ApiQuoteExcelTemplate>(
    `/quote-excel-templates/${encodeURIComponent(templateId)}`,
    {
      method: "PUT",
      body: JSON.stringify({
        name: input.name,
        column_mappings: input.columnMappings,
        is_default: input.isDefault,
      }),
    },
  ));
}

export async function deleteQuoteExcelTemplate(templateId: string): Promise<void> {
  await request<void>(
    `/quote-excel-templates/${encodeURIComponent(templateId)}`,
    { method: "DELETE" },
  );
}

interface ApiWarehouse {
  id: string;
  code: string;
  name: string;
  address?: string | null;
  currency: string;
  status: "ACTIVE" | "INACTIVE";
  is_default: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

interface ApiInventoryStockItem {
  balance_id?: string | null;
  warehouse_id: string;
  warehouse_name: string;
  currency: string;
  sku_id: string;
  sku_code: string;
  sku_name: string;
  product_id: string;
  product_name: string;
  supplier_id?: string | null;
  supplier_name?: string | null;
  on_hand_quantity: number | string;
  reserved_quantity: number | string;
  available_quantity: number | string;
  average_cost: number | string;
  inventory_value: number | string;
  reorder_point: number | string;
  low_stock: boolean;
  version: number;
  updated_at?: string | null;
}

interface ApiInventoryOverview {
  warehouse_id: string;
  warehouse_name: string;
  currency: string;
  total_skus: number;
  stocked_skus: number;
  on_hand_quantity: number | string;
  reserved_quantity: number | string;
  available_quantity: number | string;
  inventory_value: number | string;
  low_stock_count: number;
  open_purchase_orders: number;
  open_sales_orders: number;
  low_stock_items: ApiInventoryStockItem[];
}

interface ApiInventoryMovement {
  id: string;
  document_id: string;
  document_number: string;
  document_type: string;
  source_number?: string | null;
  warehouse_id: string;
  warehouse_name: string;
  currency: string;
  sku_id: string;
  sku_code: string;
  sku_name: string;
  movement_type: string;
  on_hand_delta: number | string;
  reserved_delta: number | string;
  on_hand_after: number | string;
  reserved_after: number | string;
  unit_cost: number | string;
  total_cost: number | string;
  average_cost_after: number | string;
  notes?: string | null;
  occurred_at: string;
}

interface ApiInventoryDocument {
  id: string;
  document_number: string;
  document_type: string;
  warehouse_id: string;
  counterparty_warehouse_id?: string | null;
  source_type?: string | null;
  source_id?: string | null;
  source_number?: string | null;
  notes?: string | null;
  occurred_at: string;
  items: Array<{
    id: string;
    sku_id: string;
    sku_code: string;
    sku_name: string;
    quantity: number | string;
    unit_cost?: number | string | null;
  }>;
}

interface ApiPurchaseOrderSummary {
  id: string;
  order_number: string;
  supplier_name: string;
  warehouse_id: string;
  warehouse_name: string;
  currency: string;
  status: string;
  total_amount: number | string;
  expected_at?: string | null;
  version: number;
  updated_at: string;
}

interface ApiPurchaseOrder extends ApiPurchaseOrderSummary {
  notes?: string | null;
  confirmed_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  items: Array<{
    id: string;
    sku_id: string;
    sku_code: string;
    sku_name: string;
    quantity: number | string;
    received_quantity: number | string;
    remaining_quantity: number | string;
    unit_cost: number | string;
    line_total: number | string;
    notes?: string | null;
  }>;
}

interface ApiSalesOrderSummary {
  id: string;
  order_number: string;
  customer_name: string;
  warehouse_id: string;
  warehouse_name: string;
  currency: string;
  status: string;
  total_amount: number | string;
  version: number;
  updated_at: string;
}

interface ApiSalesOrder extends ApiSalesOrderSummary {
  customer_id?: string | null;
  source_quotation_id?: string | null;
  notes?: string | null;
  confirmed_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  items: Array<{
    id: string;
    sku_id: string;
    sku_code: string;
    sku_name: string;
    quantity: number | string;
    reserved_quantity: number | string;
    shipped_quantity: number | string;
    remaining_quantity: number | string;
    unit_price: number | string;
    line_total: number | string;
    cost_amount: number | string;
    notes?: string | null;
  }>;
}

const inventoryNumber = (value: number | string) => Number(value);

function mapWarehouse(row: ApiWarehouse): Warehouse {
  return {
    id: row.id,
    code: row.code,
    name: row.name,
    address: defined(row.address),
    currency: row.currency,
    status: row.status,
    isDefault: row.is_default,
    version: row.version,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function mapInventoryStock(row: ApiInventoryStockItem): InventoryStockItem {
  return {
    balanceId: defined(row.balance_id),
    warehouseId: row.warehouse_id,
    warehouseName: row.warehouse_name,
    currency: row.currency,
    skuId: row.sku_id,
    skuCode: row.sku_code,
    skuName: row.sku_name,
    productId: row.product_id,
    productName: row.product_name,
    supplierId: defined(row.supplier_id),
    supplierName: defined(row.supplier_name),
    onHandQuantity: inventoryNumber(row.on_hand_quantity),
    reservedQuantity: inventoryNumber(row.reserved_quantity),
    availableQuantity: inventoryNumber(row.available_quantity),
    averageCost: inventoryNumber(row.average_cost),
    inventoryValue: inventoryNumber(row.inventory_value),
    reorderPoint: inventoryNumber(row.reorder_point),
    lowStock: row.low_stock,
    version: row.version,
    updatedAt: defined(row.updated_at),
  };
}

function mapInventoryDocument(row: ApiInventoryDocument): InventoryDocument {
  return {
    id: row.id,
    documentNumber: row.document_number,
    documentType: row.document_type,
    warehouseId: row.warehouse_id,
    counterpartyWarehouseId: defined(row.counterparty_warehouse_id),
    sourceType: defined(row.source_type),
    sourceId: defined(row.source_id),
    sourceNumber: defined(row.source_number),
    notes: defined(row.notes),
    occurredAt: row.occurred_at,
    items: row.items.map((item) => ({
      id: item.id,
      skuId: item.sku_id,
      skuCode: item.sku_code,
      skuName: item.sku_name,
      quantity: inventoryNumber(item.quantity),
      unitCost: item.unit_cost == null ? undefined : inventoryNumber(item.unit_cost),
    })),
  };
}

function mapPurchaseSummary(row: ApiPurchaseOrderSummary): PurchaseOrderSummary {
  return {
    id: row.id,
    orderNumber: row.order_number,
    supplierName: row.supplier_name,
    warehouseId: row.warehouse_id,
    warehouseName: row.warehouse_name,
    currency: row.currency,
    status: row.status,
    totalAmount: inventoryNumber(row.total_amount),
    expectedAt: defined(row.expected_at),
    version: row.version,
    updatedAt: row.updated_at,
  };
}

function mapPurchaseOrder(row: ApiPurchaseOrder): PurchaseOrder {
  return {
    ...mapPurchaseSummary(row),
    notes: defined(row.notes),
    confirmedAt: defined(row.confirmed_at),
    completedAt: defined(row.completed_at),
    createdAt: row.created_at,
    items: row.items.map((item) => ({
      id: item.id,
      skuId: item.sku_id,
      skuCode: item.sku_code,
      skuName: item.sku_name,
      quantity: inventoryNumber(item.quantity),
      receivedQuantity: inventoryNumber(item.received_quantity),
      remainingQuantity: inventoryNumber(item.remaining_quantity),
      unitCost: inventoryNumber(item.unit_cost),
      lineTotal: inventoryNumber(item.line_total),
      notes: defined(item.notes),
    })),
  };
}

function mapSalesSummary(row: ApiSalesOrderSummary): SalesOrderSummary {
  return {
    id: row.id,
    orderNumber: row.order_number,
    customerName: row.customer_name,
    warehouseId: row.warehouse_id,
    warehouseName: row.warehouse_name,
    currency: row.currency,
    status: row.status,
    totalAmount: inventoryNumber(row.total_amount),
    version: row.version,
    updatedAt: row.updated_at,
  };
}

function mapSalesOrder(row: ApiSalesOrder): SalesOrder {
  return {
    ...mapSalesSummary(row),
    customerId: defined(row.customer_id),
    sourceQuotationId: defined(row.source_quotation_id),
    notes: defined(row.notes),
    confirmedAt: defined(row.confirmed_at),
    completedAt: defined(row.completed_at),
    createdAt: row.created_at,
    items: row.items.map((item) => ({
      id: item.id,
      skuId: item.sku_id,
      skuCode: item.sku_code,
      skuName: item.sku_name,
      quantity: inventoryNumber(item.quantity),
      reservedQuantity: inventoryNumber(item.reserved_quantity),
      shippedQuantity: inventoryNumber(item.shipped_quantity),
      remainingQuantity: inventoryNumber(item.remaining_quantity),
      unitPrice: inventoryNumber(item.unit_price),
      lineTotal: inventoryNumber(item.line_total),
      costAmount: inventoryNumber(item.cost_amount),
      notes: defined(item.notes),
    })),
  };
}

export async function listWarehouses(): Promise<Warehouse[]> {
  return (await request<ApiWarehouse[]>("/inventory/warehouses")).map(mapWarehouse);
}

export async function createWarehouse(input: {
  code: string;
  name: string;
  address?: string;
  currency: string;
  isDefault?: boolean;
}): Promise<Warehouse> {
  return mapWarehouse(await request<ApiWarehouse>("/inventory/warehouses", {
    method: "POST",
    body: JSON.stringify({
      code: input.code,
      name: input.name,
      address: input.address || null,
      currency: input.currency,
      is_default: input.isDefault ?? false,
    }),
  }));
}

export async function updateWarehouse(
  warehouseId: string,
  input: {
    expectedVersion: number;
    name?: string;
    address?: string;
    status?: "ACTIVE" | "INACTIVE";
    isDefault?: boolean;
  },
): Promise<Warehouse> {
  return mapWarehouse(await request<ApiWarehouse>(
    `/inventory/warehouses/${encodeURIComponent(warehouseId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        expected_version: input.expectedVersion,
        name: input.name,
        address: input.address,
        status: input.status,
        is_default: input.isDefault,
      }),
    },
  ));
}

export async function getInventoryOverview(warehouseId?: string): Promise<InventoryOverview> {
  const query = warehouseId ? `?warehouse_id=${encodeURIComponent(warehouseId)}` : "";
  const row = await request<ApiInventoryOverview>(`/inventory/overview${query}`);
  return {
    warehouseId: row.warehouse_id,
    warehouseName: row.warehouse_name,
    currency: row.currency,
    totalSkus: row.total_skus,
    stockedSkus: row.stocked_skus,
    onHandQuantity: inventoryNumber(row.on_hand_quantity),
    reservedQuantity: inventoryNumber(row.reserved_quantity),
    availableQuantity: inventoryNumber(row.available_quantity),
    inventoryValue: inventoryNumber(row.inventory_value),
    lowStockCount: row.low_stock_count,
    openPurchaseOrders: row.open_purchase_orders,
    openSalesOrders: row.open_sales_orders,
    lowStockItems: row.low_stock_items.map(mapInventoryStock),
  };
}

export async function listInventoryStocks(input: {
  warehouseId?: string;
  q?: string;
  lowStockOnly?: boolean;
  page?: number;
  pageSize?: number;
} = {}): Promise<InventoryStockPage> {
  const query = new URLSearchParams();
  if (input.warehouseId) query.set("warehouse_id", input.warehouseId);
  if (input.q) query.set("q", input.q);
  if (input.lowStockOnly) query.set("low_stock_only", "true");
  query.set("page", String(input.page ?? 1));
  query.set("page_size", String(input.pageSize ?? 50));
  const row = await request<{
    items: ApiInventoryStockItem[];
    page: number;
    page_size: number;
    total: number;
    pages: number;
  }>(`/inventory/stocks?${query}`);
  return {
    items: row.items.map(mapInventoryStock),
    page: row.page,
    pageSize: row.page_size,
    total: row.total,
    pages: row.pages,
  };
}

export async function updateStockPolicy(
  warehouseId: string,
  skuId: string,
  expectedVersion: number,
  reorderPoint: number,
): Promise<InventoryStockItem> {
  return mapInventoryStock(await request<ApiInventoryStockItem>(
    `/inventory/stocks/${encodeURIComponent(warehouseId)}/${encodeURIComponent(skuId)}/policy`,
    {
      method: "PATCH",
      body: JSON.stringify({
        expected_version: expectedVersion,
        reorder_point: reorderPoint,
      }),
    },
  ));
}

export async function listInventoryMovements(input: {
  warehouseId?: string;
  q?: string;
  movementType?: string;
  page?: number;
  pageSize?: number;
} = {}): Promise<InventoryMovementPage> {
  const query = new URLSearchParams();
  if (input.warehouseId) query.set("warehouse_id", input.warehouseId);
  if (input.q) query.set("q", input.q);
  if (input.movementType) query.set("movement_type", input.movementType);
  query.set("page", String(input.page ?? 1));
  query.set("page_size", String(input.pageSize ?? 50));
  const row = await request<{
    items: ApiInventoryMovement[];
    page: number;
    page_size: number;
    total: number;
    pages: number;
  }>(`/inventory/movements?${query}`);
  const mapMovement = (item: ApiInventoryMovement): InventoryMovement => ({
    id: item.id,
    documentId: item.document_id,
    documentNumber: item.document_number,
    documentType: item.document_type,
    sourceNumber: defined(item.source_number),
    warehouseId: item.warehouse_id,
    warehouseName: item.warehouse_name,
    currency: item.currency,
    skuId: item.sku_id,
    skuCode: item.sku_code,
    skuName: item.sku_name,
    movementType: item.movement_type,
    onHandDelta: inventoryNumber(item.on_hand_delta),
    reservedDelta: inventoryNumber(item.reserved_delta),
    onHandAfter: inventoryNumber(item.on_hand_after),
    reservedAfter: inventoryNumber(item.reserved_after),
    unitCost: inventoryNumber(item.unit_cost),
    totalCost: inventoryNumber(item.total_cost),
    averageCostAfter: inventoryNumber(item.average_cost_after),
    notes: defined(item.notes),
    occurredAt: item.occurred_at,
  });
  return {
    items: row.items.map(mapMovement),
    page: row.page,
    pageSize: row.page_size,
    total: row.total,
    pages: row.pages,
  };
}

export async function adjustInventory(input: {
  warehouseId?: string;
  reason: string;
  items: Array<{ skuId: string; quantityDelta: number; unitCost?: number }>;
}): Promise<InventoryDocument> {
  return mapInventoryDocument(await request<ApiInventoryDocument>("/inventory/adjustments", {
    method: "POST",
    body: JSON.stringify({
      warehouse_id: input.warehouseId,
      reason: input.reason,
      idempotency_key: `web-adjust-${crypto.randomUUID()}`,
      items: input.items.map((item) => ({
        sku_id: item.skuId,
        quantity_delta: item.quantityDelta,
        unit_cost: item.unitCost,
      })),
    }),
  }));
}

export async function transferInventory(input: {
  fromWarehouseId: string;
  toWarehouseId: string;
  reason: string;
  items: Array<{ skuId: string; quantity: number }>;
}): Promise<InventoryDocument> {
  return mapInventoryDocument(await request<ApiInventoryDocument>("/inventory/transfers", {
    method: "POST",
    body: JSON.stringify({
      from_warehouse_id: input.fromWarehouseId,
      to_warehouse_id: input.toWarehouseId,
      reason: input.reason,
      idempotency_key: `web-transfer-${crypto.randomUUID()}`,
      items: input.items.map((item) => ({
        sku_id: item.skuId,
        quantity: item.quantity,
      })),
    }),
  }));
}

export async function listPurchaseOrders(status?: string): Promise<PurchaseOrderSummary[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return (await request<ApiPurchaseOrderSummary[]>(`/purchases${query}`)).map(mapPurchaseSummary);
}

export async function getPurchaseOrder(orderId: string): Promise<PurchaseOrder> {
  return mapPurchaseOrder(await request<ApiPurchaseOrder>(`/purchases/${encodeURIComponent(orderId)}`));
}

export async function createPurchaseOrder(input: {
  supplierName: string;
  warehouseId?: string;
  currency?: string;
  expectedAt?: string;
  notes?: string;
  items: Array<{ skuId: string; quantity: number; unitCost: number }>;
}): Promise<PurchaseOrder> {
  return mapPurchaseOrder(await request<ApiPurchaseOrder>("/purchases", {
    method: "POST",
    body: JSON.stringify({
      supplier_name: input.supplierName,
      warehouse_id: input.warehouseId,
      currency: input.currency,
      expected_at: input.expectedAt || null,
      notes: input.notes || null,
      items: input.items.map((item) => ({
        sku_id: item.skuId,
        quantity: item.quantity,
        unit_cost: item.unitCost,
      })),
    }),
  }));
}

export async function confirmPurchaseOrder(order: Pick<PurchaseOrder, "id" | "version">): Promise<PurchaseOrder> {
  return mapPurchaseOrder(await request<ApiPurchaseOrder>(
    `/purchases/${encodeURIComponent(order.id)}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ expected_version: order.version }),
    },
  ));
}

export async function receivePurchaseOrder(
  order: Pick<PurchaseOrder, "id" | "version">,
  items: Array<{ orderItemId: string; quantity: number }>,
  notes?: string,
): Promise<PurchaseOrder> {
  return mapPurchaseOrder(await request<ApiPurchaseOrder>(
    `/purchases/${encodeURIComponent(order.id)}/receive`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_version: order.version,
        idempotency_key: `web-receipt-${crypto.randomUUID()}`,
        notes: notes || null,
        items: items.map((item) => ({
          order_item_id: item.orderItemId,
          quantity: item.quantity,
        })),
      }),
    },
  ));
}

export async function cancelPurchaseOrder(
  order: Pick<PurchaseOrder, "id" | "version">,
  reason?: string,
): Promise<PurchaseOrder> {
  return mapPurchaseOrder(await request<ApiPurchaseOrder>(
    `/purchases/${encodeURIComponent(order.id)}/cancel`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_version: order.version,
        reason: reason || null,
      }),
    },
  ));
}

export async function listSalesOrders(status?: string): Promise<SalesOrderSummary[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return (await request<ApiSalesOrderSummary[]>(`/sales-orders${query}`)).map(mapSalesSummary);
}

export async function getSalesOrder(orderId: string): Promise<SalesOrder> {
  return mapSalesOrder(await request<ApiSalesOrder>(`/sales-orders/${encodeURIComponent(orderId)}`));
}

export async function createSalesOrder(input: {
  customerName: string;
  warehouseId?: string;
  currency: string;
  sourceQuotationId?: string;
  notes?: string;
  items: Array<{ skuId: string; quantity: number; unitPrice: number }>;
}): Promise<SalesOrder> {
  return mapSalesOrder(await request<ApiSalesOrder>("/sales-orders", {
    method: "POST",
    body: JSON.stringify({
      customer_name: input.customerName,
      warehouse_id: input.warehouseId,
      currency: input.currency,
      source_quotation_id: input.sourceQuotationId || null,
      notes: input.notes || null,
      items: input.items.map((item) => ({
        sku_id: item.skuId,
        quantity: item.quantity,
        unit_price: item.unitPrice,
      })),
    }),
  }));
}

export async function confirmSalesOrder(order: Pick<SalesOrder, "id" | "version">): Promise<SalesOrder> {
  return mapSalesOrder(await request<ApiSalesOrder>(
    `/sales-orders/${encodeURIComponent(order.id)}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ expected_version: order.version }),
    },
  ));
}

export async function shipSalesOrder(
  order: Pick<SalesOrder, "id" | "version">,
  items: Array<{ orderItemId: string; quantity: number }>,
  notes?: string,
): Promise<SalesOrder> {
  return mapSalesOrder(await request<ApiSalesOrder>(
    `/sales-orders/${encodeURIComponent(order.id)}/ship`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_version: order.version,
        idempotency_key: `web-shipment-${crypto.randomUUID()}`,
        notes: notes || null,
        items: items.map((item) => ({
          order_item_id: item.orderItemId,
          quantity: item.quantity,
        })),
      }),
    },
  ));
}

export async function cancelSalesOrder(
  order: Pick<SalesOrder, "id" | "version">,
  reason?: string,
): Promise<SalesOrder> {
  return mapSalesOrder(await request<ApiSalesOrder>(
    `/sales-orders/${encodeURIComponent(order.id)}/cancel`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_version: order.version,
        reason: reason || null,
      }),
    },
  ));
}
