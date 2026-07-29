import type {
  AttributeDefinition,
  AuthTokenData,
  CategoryLayout,
  CatalogTranslationJob,
  CatalogTranslationStatus,
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
  QuotationRecord,
  QuotationSummary,
  ReviewItem,
  SalesOrder,
  SalesOrderSummary,
  SkuListItem,
  SkuListPage,
  StorefrontAnalyticsSnapshot,
  SupplierPrice,
  SupplierProfile,
  SupplierProfileDetail,
  SystemMonitoringSnapshot,
  TenantMember,
  TenantPermission,
  TenantRole,
  UiLocale,
  Warehouse,
} from "./types";
import { buildPasswordChangePayload } from "./accountPassword";
import { buildPasswordLoginPayload } from "./authCredentials";
import { bumpPublicCatalogRevision } from "../lib/publicCatalogRevision";

const CSRF_STORAGE_KEY = "atc.csrfToken";
let accessToken: string | undefined;
let refreshInFlight: Promise<AuthTokenData | undefined> | undefined;
let authGeneration = 0;
const getRequestsInFlight = new Map<string, Promise<unknown>>();

function resolveApiBase() {
  const configured = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
  if (!configured) return "/api/v1";
  if (configured.endsWith("/api/v1")) return configured;
  if (configured.endsWith("/api")) return `${configured}/v1`;
  return `${configured}/api/v1`;
}

const API_BASE = resolveApiBase();
export const PRODUCT_TEMPLATE_DOWNLOAD_URL = `${API_BASE}/product-template.xlsx`;

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
  };
}

function acceptAuthData(row: ApiAuthTokenData) {
  const mapped = mapAuthData(row);
  accessToken = mapped.accessToken;
  authGeneration += 1;
  getRequestsInFlight.clear();
  window.sessionStorage.setItem(CSRF_STORAGE_KEY, mapped.csrfToken);
  window.localStorage.removeItem("qingwan.accessToken");
  window.localStorage.removeItem("atc_access_token");
  return mapped;
}

export function getCoreAccessToken() {
  return accessToken;
}

export function clearCoreAuthSession() {
  accessToken = undefined;
  authGeneration += 1;
  getRequestsInFlight.clear();
  window.sessionStorage.removeItem(CSRF_STORAGE_KEY);
  window.localStorage.removeItem("qingwan.accessToken");
  window.localStorage.removeItem("atc_access_token");
}

export async function refreshAuthSession(): Promise<AuthTokenData | undefined> {
  const csrfToken = window.sessionStorage.getItem(CSRF_STORAGE_KEY);
  if (!csrfToken) return undefined;
  if (!refreshInFlight) {
    refreshInFlight = safeFetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken },
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new CoreApiError(messageFromPayload(payload, "会话已失效"), response.status, payload);
        return acceptAuthData((payload as { data: ApiAuthTokenData }).data);
      })
      .catch(() => {
        clearCoreAuthSession();
        return undefined;
      })
      .finally(() => {
        refreshInFlight = undefined;
      });
  }
  return refreshInFlight;
}

async function performRequest<T>(path: string, init: RequestInit, retrySession: boolean): Promise<T> {
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
    return performRequest<T>(path, init, retrySession);
  }
  const key = `${authGeneration}:${path}`;
  const existing = getRequestsInFlight.get(key);
  if (existing) return existing as Promise<T>;
  const pending = performRequest<T>(path, init, retrySession);
  getRequestsInFlight.set(key, pending);
  try {
    return await pending;
  } finally {
    if (getRequestsInFlight.get(key) === pending) getRequestsInFlight.delete(key);
  }
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
    const csrfToken = window.sessionStorage.getItem(CSRF_STORAGE_KEY);
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
  const csrfToken = window.sessionStorage.getItem(CSRF_STORAGE_KEY);
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

export async function getPermissions(): Promise<PermissionSet> {
  const row = await request<{ membership_id: string; permission_version: number; permissions: string[] }>("/me/permissions");
  return { membershipId: row.membership_id, permissionVersion: row.permission_version, permissions: row.permissions };
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

export async function updateMerchantSettings(input: {
  name?: string;
  businessMode?: "DOMESTIC" | "EXPORT";
}): Promise<MerchantSettings> {
  const row = await request<{
    name: string;
    slug: string;
    storefront_path: string;
    business_mode: "DOMESTIC" | "EXPORT";
    default_currency: string;
  }>(
    "/me/merchant",
    {
      method: "PATCH",
      body: JSON.stringify({
        name: input.name,
        business_mode: input.businessMode,
      }),
    },
  );
  return {
    name: row.name,
    slug: row.slug,
    storefrontPath: row.storefront_path,
    businessMode: row.business_mode,
    defaultCurrency: row.default_currency,
  };
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

export async function listImports() {
  return (await request<ApiImportJob[]>("/imports")).map(mapImport);
}

export async function getImport(jobId: string) {
  return mapImport(await request<ApiImportJob>(`/imports/${encodeURIComponent(jobId)}`));
}

export async function createImport(file: File, supplierId?: string) {
  const body = new FormData();
  body.append("file", file);
  body.append("source_type", "SUPPLIER_CATALOG");
  if (supplierId) body.append("supplier_id", supplierId);
  return mapImport(await request<ApiImportJob>("/imports", { method: "POST", body }));
}

function uploadProductTemplate(
  body: FormData,
  onUploadProgress: ((percent: number) => void) | undefined,
  retrySession: boolean,
): Promise<ApiImportJob> {
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

interface ApiReviewItem {
  id: string;
  job_id?: string;
  task_id?: string;
  candidate_group_key?: string;
  applied_product_id?: string | null;
  status: ReviewItem["status"];
  name: string;
  model: string;
  category: string;
  supplier: string;
  source: string;
  location: string;
  image_status: ReviewItem["imageStatus"];
  fields: ReviewItem["fields"];
}

function mapReview(row: ApiReviewItem): ReviewItem {
  return {
    id: row.id,
    jobId: row.job_id,
    taskId: row.task_id,
    candidateGroupKey: row.candidate_group_key,
    appliedProductId: defined(row.applied_product_id),
    status: row.status,
    name: row.name,
    model: row.model,
    category: row.category,
    supplier: row.supplier,
    source: row.source,
    location: row.location,
    imageStatus: row.image_status,
    fields: row.fields,
  };
}

export async function listReviewItems(jobId?: string) {
  const path = jobId ? `/review-items?job_id=${encodeURIComponent(jobId)}` : "/product-review-items";
  return (await request<ApiReviewItem[]>(path)).map(mapReview);
}

export async function updateReviewItem(itemId: string, normalizedValues: Record<string, string>) {
  return mapReview(await request<ApiReviewItem>(`/review-items/${encodeURIComponent(itemId)}`, {
    method: "PATCH",
    body: JSON.stringify({ normalized_values: normalizedValues }),
  }));
}

export async function approveReviewItem(itemId: string) {
  await request(`/review-items/${encodeURIComponent(itemId)}/approve`, { method: "POST" });
}

export async function approveProductCandidate(item: ReviewItem, confirmedValues: Record<string, string>) {
  if (!item.taskId || !item.candidateGroupKey) throw new CoreApiError("审核记录缺少可信 Candidate 上下文", 400);
  return request<{ product_id: string }>(
    `/ai/product-intelligence/tasks/${encodeURIComponent(item.taskId)}/groups/${encodeURIComponent(item.candidateGroupKey)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({
        idempotency_key: `web-review-${item.taskId}-${item.candidateGroupKey}`,
        confirmed_values: confirmedValues,
        activate: true,
        change_reason: "Product Center human-confirmed internal publication",
      }),
    },
  );
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
  weight?: number | null;
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
  image_status: SkuListItem["imageStatus"];
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
    weight: defined(row.weight),
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
    imageStatus: row.image_status,
  };
}

function mapActivity(row: ApiProductDetail["activity"][number]): ProductActivity {
  return { id: row.id, entityType: row.entity_type, entityId: row.entity_id, action: row.action, before: row.before, after: row.after, actorMembershipId: row.actor_membership_id, occurredAt: row.occurred_at };
}

function mapAttribute(row: ApiProductDetail["attributes"][number]): ProductAttribute {
  return { id: row.id, definitionId: defined(row.definition_id), key: row.key, value: row.value, unitCode: defined(row.unit_code), reviewStatus: row.review_status };
}

export async function listProducts(params: { q?: string; categoryId?: string; approvedImagesOnly?: boolean } = {}) {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.categoryId) query.set("category_id", params.categoryId);
  if (params.approvedImagesOnly) query.set("approved_images_only", "true");
  return (await request<ApiProduct[]>(`/products${query.size ? `?${query}` : ""}`)).map(mapProduct);
}

export async function listSkus(params: {
  q?: string;
  categoryId?: string;
  statuses?: ProductSku["status"][];
  page?: number;
  pageSize?: number;
} = {}): Promise<SkuListPage> {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.categoryId) query.set("category_id", params.categoryId);
  for (const status of params.statuses ?? []) query.append("status", status);
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

interface ApiKnowledgeIndexStatus {
  total_products: number;
  indexed_products: number;
  pending_products: number;
  model_provider: string;
  model_name: string;
  model_version: string;
  dimensions: number;
  mode?: "INCREMENTAL" | "FULL_REBUILD";
  processed_products?: number;
  embeddings?: number;
}

function mapKnowledgeIndexStatus(row: ApiKnowledgeIndexStatus): KnowledgeIndexStatus {
  return {
    totalProducts: row.total_products,
    indexedProducts: row.indexed_products,
    pendingProducts: row.pending_products,
    modelProvider: row.model_provider,
    modelName: row.model_name,
    modelVersion: row.model_version,
    dimensions: row.dimensions,
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

export async function updateKnowledgeIndex(): Promise<KnowledgeIndexStatus> {
  return mapKnowledgeIndexStatus(
    await request<ApiKnowledgeIndexStatus>("/ai/knowledge/index/update", {
      method: "POST",
    }),
  );
}

export async function rebuildKnowledgeIndex(): Promise<KnowledgeIndexStatus> {
  return mapKnowledgeIndexStatus(
    await request<ApiKnowledgeIndexStatus>("/ai/knowledge/index/rebuild", {
      method: "POST",
      body: JSON.stringify({ confirm_full_rebuild: true }),
    }),
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
  model_provider: string;
  model_name: string;
  model_version: string;
  dimensions: number;
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
    modelProvider: row.model_provider,
    modelName: row.model_name,
    modelVersion: row.model_version,
    dimensions: row.dimensions,
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

interface ApiCatalogTranslationFailure {
  sku_id?: string | null;
  sku_code?: string | null;
  name?: string | null;
  message: string;
}

interface ApiCatalogTranslationJob {
  id: string;
  source_locale: string;
  target_locale: string;
  mode: "INCREMENTAL" | "FULL_REBUILD";
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  total_skus: number;
  processed_skus: number;
  failed_skus: number;
  progress_percent: number;
  current_sku_id?: string | null;
  current_sku_name?: string | null;
  provider: string;
  provider_version: string;
  failure_details: ApiCatalogTranslationFailure[];
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

interface ApiCatalogTranslationStatus {
  source_locale: string;
  target_locale: string;
  provider: string;
  provider_version: string;
  provider_configured: boolean;
  total_skus: number;
  translated_skus: number;
  stale_skus: number;
  pending_skus: number;
  available_locales: string[];
  latest_job?: ApiCatalogTranslationJob | null;
}

function mapCatalogTranslationJob(
  row: ApiCatalogTranslationJob,
): CatalogTranslationJob {
  return {
    id: row.id,
    sourceLocale: row.source_locale,
    targetLocale: row.target_locale,
    mode: row.mode,
    status: row.status,
    totalSkus: row.total_skus,
    processedSkus: row.processed_skus,
    failedSkus: row.failed_skus,
    progressPercent: row.progress_percent,
    currentSkuId: defined(row.current_sku_id),
    currentSkuName: defined(row.current_sku_name),
    provider: row.provider,
    providerVersion: row.provider_version,
    failureDetails: (row.failure_details ?? []).map((failure) => ({
      skuId: defined(failure.sku_id),
      skuCode: defined(failure.sku_code),
      name: defined(failure.name),
      message: failure.message,
    })),
    errorMessage: defined(row.error_message),
    createdAt: row.created_at,
    startedAt: defined(row.started_at),
    completedAt: defined(row.completed_at),
  };
}

export async function getCatalogTranslationStatus(): Promise<CatalogTranslationStatus> {
  const row = await request<ApiCatalogTranslationStatus>(
    "/catalog/translations/status?target_locale=en-US",
  );
  return {
    sourceLocale: row.source_locale,
    targetLocale: row.target_locale,
    provider: row.provider,
    providerVersion: row.provider_version,
    providerConfigured: row.provider_configured,
    totalSkus: row.total_skus,
    translatedSkus: row.translated_skus,
    staleSkus: row.stale_skus,
    pendingSkus: row.pending_skus,
    availableLocales: row.available_locales,
    latestJob: row.latest_job
      ? mapCatalogTranslationJob(row.latest_job)
      : undefined,
  };
}

export async function startCatalogTranslationJob(
  fullRebuild = false,
): Promise<CatalogTranslationJob> {
  return mapCatalogTranslationJob(
    await request<ApiCatalogTranslationJob>("/catalog/translations/jobs", {
      method: "POST",
      body: JSON.stringify({
        target_locale: "en-US",
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
    await request<ApiEmbeddingSettings>("/ai/embedding/settings"),
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

export async function getProduct(productId: string): Promise<ProductDetail> {
  const row = await request<ApiProductDetail>(`/products/${encodeURIComponent(productId)}`);
  return { ...mapProduct(row), description: defined(row.description), defaultUnit: defined(row.default_unit), attributes: row.attributes.map(mapAttribute), skus: row.skus.map(mapSku), sources: row.sources.map(mapOffer), activity: row.activity.map(mapActivity) };
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

export async function listCategories(): Promise<ProductCategory[]> {
  return (await request<ApiCategory[]>("/categories")).map(mapCategory);
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

interface ApiPrice { id: string; product_id: string; supplier_product_id: string; supplier_id: string; supplier_name: string; sku_id?: string | null; min_quantity: number; max_quantity?: number | null; unit_price: number; currency: string; unit_code: string; incoterm?: string | null; tax_status?: string | null; valid_from: string; valid_to?: string | null; status: string; price_validity: SupplierPrice["priceValidity"]; confirmed_at?: string | null; created_at: string }

function mapPrice(row: ApiPrice): SupplierPrice {
  return { id: row.id, productId: row.product_id, supplierProductId: row.supplier_product_id, supplierId: row.supplier_id, supplierName: row.supplier_name, skuId: defined(row.sku_id), minQuantity: row.min_quantity, maxQuantity: defined(row.max_quantity), unitPrice: Number(row.unit_price), currency: row.currency, unitCode: row.unit_code, incoterm: defined(row.incoterm), taxStatus: defined(row.tax_status), validFrom: row.valid_from, validTo: defined(row.valid_to), status: row.status, priceValidity: row.price_validity, confirmedAt: defined(row.confirmed_at), createdAt: row.created_at };
}

export async function listPrices(productId: string) {
  return (await request<ApiPrice[]>(`/products/${encodeURIComponent(productId)}/prices`)).map(mapPrice);
}

export async function createPrice(input: { supplierProductId: string; skuId?: string; minQuantity: number; maxQuantity?: number; unitPrice: number; currency: string; unitCode: string; incoterm?: string; validFrom: string; validTo?: string }) {
  return mapPrice(await request<ApiPrice>("/product-prices", {
    method: "POST",
    body: JSON.stringify({ supplier_product_id: input.supplierProductId, sku_id: input.skuId, min_quantity: input.minQuantity, max_quantity: input.maxQuantity, unit_price: input.unitPrice, currency: input.currency, unit_code: input.unitCode, incoterm: input.incoterm, valid_from: input.validFrom, valid_to: input.validTo }),
  }));
}

interface ApiDashboard { generated_at: string; data_scope: "TENANT" | "SELF"; metrics: Array<{ key: string; label: string; value: number; unit?: string | null; status: string; destination: string }>; recent_imports: Array<{ id: string; filename: string; supplier_name: string; source_type: string; status: string; progress: number; products_count: number; warnings_count: number; created_at: string }>; data_health?: { score: number; active_products: number; approved_image_coverage: number; supplier_source_coverage: number; valid_price_coverage: number } | null }

export async function getDashboard(): Promise<DashboardSnapshot> {
  const row = await request<ApiDashboard>("/dashboard");
  return { generatedAt: row.generated_at, dataScope: row.data_scope, metrics: row.metrics.map((metric) => ({ ...metric, unit: defined(metric.unit) })), recentImports: row.recent_imports.map((item) => ({ id: item.id, filename: item.filename, supplierName: item.supplier_name, sourceType: item.source_type, status: item.status, progress: item.progress, productsCount: item.products_count, warningsCount: item.warnings_count, createdAt: item.created_at })), dataHealth: row.data_health ? { score: row.data_health.score, activeProducts: row.data_health.active_products, approvedImageCoverage: row.data_health.approved_image_coverage, supplierSourceCoverage: row.data_health.supplier_source_coverage, validPriceCoverage: row.data_health.valid_price_coverage } : undefined };
}

interface ApiSupplierProfile { id: string; supplier_code: string; name: string; category: string; category_summary?: string | null; country_code?: string | null; website?: string | null; status: string; risk_level: string; health: string; version: number; active_products: number; active_skus: number; pending_reviews: number; valid_prices: number; expired_prices: number; latest_import_at?: string | null; updated_at: string; latest_score?: { overall_score?: number | string | null; quality_score?: number | string | null; price_score?: number | string | null; delivery_score?: number | string | null; response_score?: number | string | null; risk_score?: number | string | null; sample_size: number; method_version: string; calculated_at: string } | null }
interface ApiSupplierDetail extends ApiSupplierProfile { sources: Array<{ supplier_product_id: string; product_id: string; product_code: string; product_name: string; sku_id?: string | null; supplier_sku?: string | null; lead_time_days?: number | null; status: string; unit_price?: number | string | null; currency?: string | null; price_valid_to?: string | null; price_validity: string }>; recent_imports: Array<{ id: string; filename: string; status: string; products_count: number; warnings_count: number; created_at: string }> }

function mapSupplier(row: ApiSupplierProfile): SupplierProfile {
  const numeric = (value: number | string | null | undefined) => value == null ? undefined : Number(value);
  const score = row.latest_score;
  return { id: row.id, supplierCode: row.supplier_code, name: row.name, category: row.category, categorySummary: defined(row.category_summary), countryCode: defined(row.country_code), website: defined(row.website), status: row.status, riskLevel: row.risk_level, health: row.health, version: row.version, activeProducts: row.active_products, activeSkus: row.active_skus, pendingReviews: row.pending_reviews, validPrices: row.valid_prices, expiredPrices: row.expired_prices, latestImportAt: defined(row.latest_import_at), updatedAt: row.updated_at, latestScore: score ? { overallScore: numeric(score.overall_score), qualityScore: numeric(score.quality_score), priceScore: numeric(score.price_score), deliveryScore: numeric(score.delivery_score), responseScore: numeric(score.response_score), riskScore: numeric(score.risk_score), sampleSize: score.sample_size, methodVersion: score.method_version, calculatedAt: score.calculated_at } : undefined };
}

export async function listSupplierProfiles() {
  return (await request<ApiSupplierProfile[]>("/supplier-profiles")).map(mapSupplier);
}

export async function createSupplierProfile(input: {
  supplierCode: string;
  name: string;
  category: string;
  countryCode?: string;
  website?: string;
}) {
  return mapSupplier(await request<ApiSupplierProfile>("/supplier-profiles", {
    method: "POST",
    body: JSON.stringify({
      supplier_code: input.supplierCode,
      name: input.name,
      category: input.category,
      country_code: input.countryCode,
      website: input.website,
    }),
  }));
}

export async function getSupplierProfile(supplierId: string): Promise<SupplierProfileDetail> {
  const row = await request<ApiSupplierDetail>(`/supplier-profiles/${encodeURIComponent(supplierId)}`);
  return { ...mapSupplier(row), sources: row.sources.map((source) => ({ supplierProductId: source.supplier_product_id, productId: source.product_id, productCode: source.product_code, productName: source.product_name, skuId: defined(source.sku_id), supplierSku: defined(source.supplier_sku), leadTimeDays: defined(source.lead_time_days), status: source.status, unitPrice: source.unit_price == null ? undefined : Number(source.unit_price), currency: defined(source.currency), priceValidTo: defined(source.price_valid_to), priceValidity: source.price_validity })), recentImports: row.recent_imports.map((item) => ({ id: item.id, filename: item.filename, status: item.status, productsCount: item.products_count, warningsCount: item.warnings_count, createdAt: item.created_at })) };
}

export async function searchImage(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<{ id: string; status: string; results: Array<{ product_id: string; visual_similarity: number; classification: string }> }>("/image-searches", { method: "POST", body });
}

export async function searchProducts(query: string, limit = 10): Promise<HybridSearchResponse> {
  const row = await request<{ query: string; ranking_version: string; model: HybridSearchResponse["model"]; degraded_channels: string[]; results: Array<{ product_id: string; product_code?: string | null; name: string; source_version: number; score: number; score_breakdown: HybridSearchResponse["results"][number]["scoreBreakdown"]; supplier_signal_status: string; evidence: Array<{ document_id: string; chunk_id: string; chunk_type: string; content_hash: string; excerpt: string }>; ranking_version: string; degraded_channels: string[] }> }>("/ai/search/products", { method: "POST", body: JSON.stringify({ query, limit }) });
  const results = await Promise.all(row.results.map(async (result) => {
    let product: ProductDetail | undefined;
    try { product = await getProduct(result.product_id); } catch { product = undefined; }
    return { productId: result.product_id, productCode: defined(result.product_code), name: result.name, sourceVersion: result.source_version, score: result.score, scoreBreakdown: result.score_breakdown, supplierSignalStatus: result.supplier_signal_status, evidence: result.evidence.map((evidence) => ({ documentId: evidence.document_id, chunkId: evidence.chunk_id, chunkType: evidence.chunk_type, contentHash: evidence.content_hash, excerpt: evidence.excerpt })), rankingVersion: result.ranking_version, degradedChannels: result.degraded_channels, product };
  }));
  return { query: row.query, rankingVersion: row.ranking_version, model: row.model, degradedChannels: row.degraded_channels, results };
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

interface ApiPublicQuoteDraftItem { id: string; sku_id: string; position: number; quantity: number | string; sku_code_snapshot: string; name_snapshot: string; description_snapshot?: string | null; category_snapshot?: string | null; tags_snapshot: string[]; image_url_snapshot?: string | null; unit_code_snapshot: string; currency_snapshot: string; unit_price_snapshot: number | string; line_total: number | string; product_version: number; sku_version: number }
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
    items: row.items.map((item) => ({ id: item.id, skuId: item.sku_id, position: item.position, quantity: Number(item.quantity), skuCode: item.sku_code_snapshot, name: item.name_snapshot, description: defined(item.description_snapshot), category: defined(item.category_snapshot), tags: item.tags_snapshot ?? [], imageUrl: defined(item.image_url_snapshot), unitCode: item.unit_code_snapshot, currency: item.currency_snapshot, unitPrice: Number(item.unit_price_snapshot), lineTotal: Number(item.line_total), productVersion: item.product_version, skuVersion: item.sku_version })),
  };
}

export async function listPublicQuoteDrafts(): Promise<PublicQuoteDraftSummary[]> {
  const rows = await request<ApiPublicQuoteDraftSummary[]>("/public-quote-drafts");
  return rows.map((row) => ({ id: row.id, quoteNumber: row.quote_number, status: row.status, customerName: row.customer_name, customerCompany: defined(row.customer_company), currency: row.currency, total: Number(row.total_amount), validUntil: row.valid_until, createdAt: row.created_at }));
}

export async function getPublicQuoteDraft(draftId: string): Promise<PublicQuoteDraft> {
  return mapPublicQuoteDraft(await request<ApiPublicQuoteDraft>(`/public-quote-drafts/${encodeURIComponent(draftId)}`));
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
