import type {
  AttributeDefinition,
  AuthTokenData,
  CoreProduct,
  CurrentUser,
  DashboardSnapshot,
  FileDetection,
  HybridSearchResponse,
  ImportJob,
  InquiryMatch,
  InquiryRecord,
  MembershipSummary,
  PermissionSet,
  ProductActivity,
  ProductAttribute,
  ProductCategory,
  ProductDetail,
  ProductOffer,
  ProductSku,
  PublicCatalogOffer,
  PublicQuoteDraft,
  PublicQuoteDraftSummary,
  QuotationRecord,
  QuotationSummary,
  ReviewItem,
  SupplierPrice,
  SupplierProfile,
  SupplierProfileDetail,
} from "./types";
import { buildPasswordLoginPayload } from "./authCredentials";

const CSRF_STORAGE_KEY = "atc.csrfToken";
let accessToken: string | undefined;
let refreshInFlight: Promise<AuthTokenData | undefined> | undefined;

function resolveApiBase() {
  const configured = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
  if (!configured) return "/api/v1";
  if (configured.endsWith("/api/v1")) return configured;
  if (configured.endsWith("/api")) return `${configured}/v1`;
  return `${configured}/api/v1`;
}

const API_BASE = resolveApiBase();

export interface AuthPublicConfig {
  provider: "local_fake" | "enterprise_oidc";
}

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
  user: { id: string; display_name: string; email?: string | null; is_platform_admin: boolean };
  context: {
    tenant_id?: string | null;
    membership_id?: string | null;
    tenant_name?: string | null;
    tenant_slug?: string | null;
    default_workspace?: string | null;
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
    user: { id: row.user.id, displayName: row.user.display_name, email: defined(row.user.email), isPlatformAdmin: row.user.is_platform_admin },
    context: {
      tenantId: defined(row.context.tenant_id),
      membershipId: defined(row.context.membership_id),
      tenantName: defined(row.context.tenant_name),
      tenantSlug: defined(row.context.tenant_slug),
      defaultWorkspace: defined(row.context.default_workspace),
    },
  };
}

function acceptAuthData(row: ApiAuthTokenData) {
  const mapped = mapAuthData(row);
  accessToken = mapped.accessToken;
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

async function request<T>(path: string, init: RequestInit = {}, retrySession = true): Promise<T> {
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

export async function loginLocalDemo(): Promise<AuthTokenData> {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const verifier = btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
  const payload = await request<{ data: ApiAuthTokenData }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({
      provider: "local_fake",
      authorization_code: "fake:00000000-0000-0000-0000-000000000003",
      code_verifier: verifier,
      redirect_uri: `${window.location.origin}/login/callback`,
      device_label: "AI Trade Cloud Web",
    }),
  }, false);
  return acceptAuthData(payload.data);
}

export async function getAuthConfig(): Promise<AuthPublicConfig> {
  return request<AuthPublicConfig>("/auth/config", {}, false);
}

export async function loginPassword(identifier: string, password: string): Promise<AuthTokenData> {
  const payload = await request<{ data: ApiAuthTokenData }>("/auth/login", {
    method: "POST",
    body: JSON.stringify(buildPasswordLoginPayload(identifier, password)),
  }, false);
  return acceptAuthData(payload.data);
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

export async function getCurrentUser(): Promise<CurrentUser> {
  const row = await request<{
    user: ApiAuthTokenData["user"];
    context: ApiAuthTokenData["context"];
    memberships: ApiMembershipSummary[];
  }>("/me");
  return {
    user: { id: row.user.id, displayName: row.user.display_name, email: defined(row.user.email), isPlatformAdmin: row.user.is_platform_admin },
    context: {
      tenantId: defined(row.context.tenant_id),
      membershipId: defined(row.context.membership_id),
      tenantName: defined(row.context.tenant_name),
      tenantSlug: defined(row.context.tenant_slug),
      defaultWorkspace: defined(row.context.default_workspace),
    },
    memberships: row.memberships.map(mapMembership),
  };
}

export async function getPermissions(): Promise<PermissionSet> {
  const row = await request<{ membership_id: string; permission_version: number; permissions: string[] }>("/me/permissions");
  return { membershipId: row.membership_id, permissionVersion: row.permission_version, permissions: row.permissions };
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
  detected_type: string;
  status: ImportJob["status"];
  progress: number;
  products: number;
  warnings: number;
  created_at: string;
  parser: string;
  extension_matches: boolean;
  error_message?: string | null;
}

function mapImport(row: ApiImportJob): ImportJob {
  return {
    id: row.id,
    filename: row.filename,
    supplier: row.supplier,
    detectedType: row.detected_type,
    status: row.status,
    progress: row.progress,
    products: row.products,
    warnings: row.warnings,
    createdAt: row.created_at,
    parser: row.parser,
    extensionMatches: row.extension_matches,
    errorMessage: defined(row.error_message),
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

export async function createImport(file: File, supplierId?: string) {
  const body = new FormData();
  body.append("file", file);
  body.append("source_type", "SUPPLIER_CATALOG");
  if (supplierId) body.append("supplier_id", supplierId);
  return mapImport(await request<ApiImportJob>("/imports", { method: "POST", body }));
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
  moq?: number | null;
  moq_unit?: string | null;
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
  moq?: number | null;
  tags: string[];
}

interface ApiSku {
  id: string;
  product_id: string;
  sku_code: string;
  name?: string | null;
  option_values: Record<string, string | number | boolean>;
  barcode?: string | null;
  default_moq?: number | null;
  moq_unit?: string | null;
  weight?: number | null;
  weight_unit?: string | null;
  status: ProductSku["status"];
  version: number;
  updated_at: string;
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
    moq: row.moq == null ? undefined : Number(row.moq),
    moqUnit: defined(row.moq_unit),
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
    moq: row.moq == null ? undefined : Number(row.moq),
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
    defaultMoq: defined(row.default_moq),
    moqUnit: defined(row.moq_unit),
    weight: defined(row.weight),
    weightUnit: defined(row.weight_unit),
    status: row.status,
    version: row.version,
    updatedAt: row.updated_at,
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

export async function getProduct(productId: string): Promise<ProductDetail> {
  const row = await request<ApiProductDetail>(`/products/${encodeURIComponent(productId)}`);
  return { ...mapProduct(row), description: defined(row.description), defaultUnit: defined(row.default_unit), attributes: row.attributes.map(mapAttribute), skus: row.skus.map(mapSku), sources: row.sources.map(mapOffer), activity: row.activity.map(mapActivity) };
}

export async function createSkus(productId: string, items: Array<{ skuCode: string; name?: string; optionValues: Record<string, string>; defaultMoq?: number; moqUnit?: string; status?: ProductSku["status"] }>) {
  const rows = await request<ApiSku[]>(`/products/${encodeURIComponent(productId)}/skus`, {
    method: "POST",
    body: JSON.stringify({ items: items.map((item) => ({ sku_code: item.skuCode, name: item.name, option_values: item.optionValues, default_moq: item.defaultMoq, moq_unit: item.moqUnit, status: item.status ?? "DRAFT" })) }),
  });
  return rows.map(mapSku);
}

export async function updateSku(skuId: string, input: Partial<Omit<ProductSku, "id" | "productId" | "skuCode" | "version" | "updatedAt">> & { expectedVersion: number }) {
  return mapSku(await request<ApiSku>(`/skus/${encodeURIComponent(skuId)}`, {
    method: "PATCH",
    body: JSON.stringify({ expected_version: input.expectedVersion, name: input.name, option_values: input.optionValues, barcode: input.barcode, default_moq: input.defaultMoq, moq_unit: input.moqUnit, weight: input.weight, weight_unit: input.weightUnit, status: input.status }),
  }));
}

interface ApiPublicCatalogOffer {
  id: string;
  sku_id: string;
  unit_price: number | string;
  currency: string;
  tags: string[];
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
      publication_status: input.publicationStatus,
      valid_from: input.validFrom,
      valid_to: input.validTo,
    }),
  }));
}

interface ApiCategory { id: string; parent_id?: string | null; code: string; name: string; path?: string | null; status: string; sort_order: number; version: number }
interface ApiAttributeDefinition { id: string; category_id?: string | null; attribute_key: string; display_name: string; data_type: AttributeDefinition["dataType"]; unit_code?: string | null; enum_values?: string[] | null; is_required: boolean; is_variant: boolean; is_filterable: boolean; is_matchable: boolean; status: string; version: number }

export async function listCategories(): Promise<ProductCategory[]> {
  return (await request<ApiCategory[]>("/categories")).map((row) => ({ id: row.id, parentId: defined(row.parent_id), code: row.code, name: row.name, path: defined(row.path), status: row.status, sortOrder: row.sort_order, version: row.version }));
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

interface ApiDashboard { generated_at: string; data_scope: "TENANT" | "SELF"; metrics: Array<{ key: string; label: string; value: number; unit?: string | null; status: string; destination: string }>; recent_imports: Array<{ id: string; filename: string; supplier_name: string; status: string; progress: number; products_count: number; warnings_count: number; created_at: string }>; data_health?: { score: number; active_products: number; approved_image_coverage: number; supplier_source_coverage: number; valid_price_coverage: number } | null }

export async function getDashboard(): Promise<DashboardSnapshot> {
  const row = await request<ApiDashboard>("/dashboard");
  return { generatedAt: row.generated_at, dataScope: row.data_scope, metrics: row.metrics.map((metric) => ({ ...metric, unit: defined(metric.unit) })), recentImports: row.recent_imports.map((item) => ({ id: item.id, filename: item.filename, supplierName: item.supplier_name, status: item.status, progress: item.progress, productsCount: item.products_count, warningsCount: item.warnings_count, createdAt: item.created_at })), dataHealth: row.data_health ? { score: row.data_health.score, activeProducts: row.data_health.active_products, approvedImageCoverage: row.data_health.approved_image_coverage, supplierSourceCoverage: row.data_health.supplier_source_coverage, validPriceCoverage: row.data_health.valid_price_coverage } : undefined };
}

interface ApiSupplierProfile { id: string; supplier_code: string; name: string; category: string; category_summary?: string | null; country_code?: string | null; website?: string | null; status: string; risk_level: string; health: string; version: number; active_products: number; active_skus: number; pending_reviews: number; valid_prices: number; expired_prices: number; latest_import_at?: string | null; updated_at: string; latest_score?: { overall_score?: number | string | null; quality_score?: number | string | null; price_score?: number | string | null; delivery_score?: number | string | null; response_score?: number | string | null; risk_score?: number | string | null; sample_size: number; method_version: string; calculated_at: string } | null }
interface ApiSupplierDetail extends ApiSupplierProfile { sources: Array<{ supplier_product_id: string; product_id: string; product_code: string; product_name: string; sku_id?: string | null; supplier_sku?: string | null; moq?: number | string | null; moq_unit?: string | null; lead_time_days?: number | null; status: string; unit_price?: number | string | null; currency?: string | null; price_valid_to?: string | null; price_validity: string }>; recent_imports: Array<{ id: string; filename: string; status: string; products_count: number; warnings_count: number; created_at: string }> }

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
  return { ...mapSupplier(row), sources: row.sources.map((source) => ({ supplierProductId: source.supplier_product_id, productId: source.product_id, productCode: source.product_code, productName: source.product_name, skuId: defined(source.sku_id), supplierSku: defined(source.supplier_sku), moq: source.moq == null ? undefined : Number(source.moq), moqUnit: defined(source.moq_unit), leadTimeDays: defined(source.lead_time_days), status: source.status, unitPrice: source.unit_price == null ? undefined : Number(source.unit_price), currency: defined(source.currency), priceValidTo: defined(source.price_valid_to), priceValidity: source.price_validity })), recentImports: row.recent_imports.map((item) => ({ id: item.id, filename: item.filename, status: item.status, productsCount: item.products_count, warningsCount: item.warnings_count, createdAt: item.created_at })) };
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

interface ApiPublicQuoteDraftItem { id: string; sku_id: string; position: number; quantity: number | string; sku_code_snapshot: string; name_snapshot: string; description_snapshot?: string | null; category_snapshot?: string | null; tags_snapshot: string[]; image_url_snapshot?: string | null; minimum_order_quantity: number | string; unit_code_snapshot: string; currency_snapshot: string; unit_price_snapshot: number | string; line_total: number | string; product_version: number; sku_version: number }
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
    items: row.items.map((item) => ({ id: item.id, skuId: item.sku_id, position: item.position, quantity: Number(item.quantity), skuCode: item.sku_code_snapshot, name: item.name_snapshot, description: defined(item.description_snapshot), category: defined(item.category_snapshot), tags: item.tags_snapshot ?? [], imageUrl: defined(item.image_url_snapshot), minimumOrderQuantity: Number(item.minimum_order_quantity), unitCode: item.unit_code_snapshot, currency: item.currency_snapshot, unitPrice: Number(item.unit_price_snapshot), lineTotal: Number(item.line_total), productVersion: item.product_version, skuVersion: item.sku_version })),
  };
}

export async function listPublicQuoteDrafts(): Promise<PublicQuoteDraftSummary[]> {
  const rows = await request<ApiPublicQuoteDraftSummary[]>("/public-quote-drafts");
  return rows.map((row) => ({ id: row.id, quoteNumber: row.quote_number, status: row.status, customerName: row.customer_name, customerCompany: defined(row.customer_company), currency: row.currency, total: Number(row.total_amount), validUntil: row.valid_until, createdAt: row.created_at }));
}

export async function getPublicQuoteDraft(draftId: string): Promise<PublicQuoteDraft> {
  return mapPublicQuoteDraft(await request<ApiPublicQuoteDraft>(`/public-quote-drafts/${encodeURIComponent(draftId)}`));
}
