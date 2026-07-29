import type {
  AuthToken,
  CreateQuoteInput,
  DashboardData,
  MemberInvitation,
  MemberInvitationPayload,
  MerchantOwnerAccount,
  MerchantOwnerAccountPayload,
  ProductTag,
  ProductTagList,
  ProductTagPayload,
  Quote,
  Sku,
  SkuList,
  SkuImportResult,
  SkuPayload,
  Storefront,
  Tenant,
  TenantPayload,
  User,
} from "../types";
import { clearCoreAuthSession, getCoreAccessToken } from "../core/api";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const PUBLIC_CACHE_MAX_ENTRIES = 160;
const PUBLIC_STORE_CACHE_TTL_MS = 5 * 60_000;
const PUBLIC_CATALOG_CACHE_TTL_MS = 2 * 60_000;
const PUBLIC_SKU_CACHE_TTL_MS = 2 * 60_000;

interface PublicCacheEntry {
  expiresAt: number;
  promise: Promise<unknown>;
}

interface StoreSkuFilters {
  q?: string;
  category?: string;
  tags?: string[];
  semantic?: boolean;
  includeFacets?: boolean;
  page?: number;
  locale?: string;
}

const publicRequestCache = new Map<string, PublicCacheEntry>();

export class ApiError extends Error {
  status: number;
  details?: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export const authStorage = {
  getToken: () => getCoreAccessToken(),
  setToken: (_token: string) => undefined,
  clearToken: () => clearCoreAuthSession(),
  getActiveTenant: () => undefined,
  setActiveTenant: (_tenantId: string) => undefined,
  clearActiveTenant: () => undefined,
};

function apiUrl(path: string) {
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

function getMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object") {
    const data = payload as Record<string, unknown>;
    if (typeof data.detail === "string") return data.detail;
    if (data.detail && typeof data.detail === "object" && "message" in data.detail) {
      return String((data.detail as Record<string, unknown>).message);
    }
    if (typeof data.message === "string") return data.message;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item)))
        .join("；");
    }
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, auth = false): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = authStorage.getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(apiUrl(path), { ...init, headers, credentials: "include" });
  } catch (error) {
    throw new ApiError("无法连接服务器，请检查网络后重试。", 0, error);
  }

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (!response.ok) {
    if (response.status === 401) {
      authStorage.clearToken();
      window.dispatchEvent(new CustomEvent("atc:auth-expired"));
    }
    throw new ApiError(getMessage(payload, `请求失败（${response.status}）`), response.status, payload);
  }
  return payload as T;
}

function prunePublicRequestCache() {
  const now = Date.now();
  for (const [key, entry] of publicRequestCache) {
    if (entry.expiresAt <= now) publicRequestCache.delete(key);
  }
  while (publicRequestCache.size > PUBLIC_CACHE_MAX_ENTRIES) {
    const oldestKey = publicRequestCache.keys().next().value as string | undefined;
    if (!oldestKey) break;
    publicRequestCache.delete(oldestKey);
  }
}

function cachedPublicRequest<T>(
  key: string,
  ttlMs: number,
  loader: () => Promise<T>,
): Promise<T> {
  const now = Date.now();
  const existing = publicRequestCache.get(key);
  if (existing && existing.expiresAt > now) {
    publicRequestCache.delete(key);
    publicRequestCache.set(key, existing);
    return existing.promise as Promise<T>;
  }
  if (existing) publicRequestCache.delete(key);

  const promise = loader().catch((error) => {
    if (publicRequestCache.get(key)?.promise === promise) {
      publicRequestCache.delete(key);
    }
    throw error;
  });
  publicRequestCache.set(key, {
    expiresAt: now + ttlMs,
    promise,
  });
  prunePublicRequestCache();
  return promise;
}

function primePublicRequestCache<T>(key: string, ttlMs: number, value: T) {
  publicRequestCache.delete(key);
  publicRequestCache.set(key, {
    expiresAt: Date.now() + ttlMs,
    promise: Promise.resolve(value),
  });
  prunePublicRequestCache();
}

function storePath(slug: string, locale?: string) {
  const params = new URLSearchParams();
  if (locale) params.set("locale", locale);
  const query = params.toString();
  return `/api/store/${encodeURIComponent(slug)}${query ? `?${query}` : ""}`;
}

function storeSkuPath(slug: string, skuId: string, locale?: string) {
  const params = new URLSearchParams();
  if (locale) params.set("locale", locale);
  const query = params.toString();
  return `/api/store/${encodeURIComponent(slug)}/skus/${encodeURIComponent(skuId)}${query ? `?${query}` : ""}`;
}

function normalizeList<T>(payload: unknown): { items: T[]; total: number } {
  if (Array.isArray(payload)) return { items: payload as T[], total: payload.length };
  if (payload && typeof payload === "object") {
    const data = payload as Record<string, unknown>;
    const items = (data.items || data.results || data.data || []) as T[];
    const total = Number(data.total ?? data.count ?? items.length);
    return { items: Array.isArray(items) ? items : [], total: Number.isFinite(total) ? total : 0 };
  }
  return { items: [], total: 0 };
}

function normalizeSku(raw: Sku): Sku {
  return {
    ...raw,
    tags: raw.tags || [],
    status: raw.active === false ? "inactive" : "active",
  };
}

function normalizeTenant(raw: Tenant): Tenant {
  return { ...raw, status: raw.active === false ? "inactive" : "active" };
}

function normalizeQuote(raw: Quote): Quote {
  return {
    ...raw,
    quote_no: raw.quote_number || raw.quote_no,
    total_amount: raw.total ?? raw.total_amount,
    items: (raw.items || []).map((item) => ({
      ...item,
      sku_code: item.sku_code_snapshot || item.sku_code,
      sku_name: item.name_snapshot || item.sku_name,
      name: item.name_snapshot || item.name,
      unit_price: item.unit_price_snapshot ?? item.unit_price,
      image_url: item.image_url_snapshot || item.image_url,
    })),
  };
}

async function getCachedStoreSkus(
  slug: string,
  filters: StoreSkuFilters = {},
): Promise<SkuList> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.category) params.set("category", filters.category);
  if (filters.tags?.length) params.set("tags", filters.tags.join(","));
  if (filters.semantic) params.set("semantic", "true");
  if (filters.includeFacets === false) params.set("include_facets", "false");
  if (filters.locale) params.set("locale", filters.locale);
  params.set("page", String(filters.page || 1));
  params.set("page_size", "24");
  params.sort();
  const query = params.toString();
  const path = `/api/store/${encodeURIComponent(slug)}/skus${query ? `?${query}` : ""}`;
  return cachedPublicRequest(`catalog:${path}`, PUBLIC_CATALOG_CACHE_TTL_MS, async () => {
    const raw = await request<unknown>(path);
    const list = normalizeList<Sku>(raw);
    const meta = raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {};
    const result: SkuList = {
      ...list,
      items: list.items.map(normalizeSku),
      page: Number(meta.page || filters.page || 1),
      pages: Number(meta.pages || 0),
      categories: Array.isArray(meta.categories) ? (meta.categories as string[]) : undefined,
      category_options: Array.isArray(meta.category_options)
        ? (meta.category_options as Array<{ value: string; label: string }>)
        : undefined,
      tags: Array.isArray(meta.tags) ? (meta.tags as string[]) : undefined,
      source_locale: typeof meta.source_locale === "string"
        ? (meta.source_locale as "zh-CN" | "en-US")
        : undefined,
      locale: typeof meta.locale === "string"
        ? (meta.locale as "zh-CN" | "en-US")
        : undefined,
      all_products_position: Number.isFinite(Number(meta.all_products_position))
        ? Number(meta.all_products_position)
        : undefined,
    };
    for (const sku of result.items) {
      const detailPath = storeSkuPath(slug, sku.id, filters.locale);
      primePublicRequestCache(
        `sku:${detailPath}`,
        PUBLIC_SKU_CACHE_TTL_MS,
        sku,
      );
    }
    if (filters.includeFacets !== false) {
      const withoutFacets = new URLSearchParams(params);
      withoutFacets.set("include_facets", "false");
      withoutFacets.sort();
      const compactPath = `/api/store/${encodeURIComponent(slug)}/skus?${withoutFacets.toString()}`;
      primePublicRequestCache(
        `catalog:${compactPath}`,
        PUBLIC_CATALOG_CACHE_TTL_MS,
        result,
      );
    }
    return result;
  });
}

function consolePath(path: string) {
  return path;
}

async function download(
  path: string,
  filename: string,
  options: { auth?: boolean; headers?: HeadersInit } = {},
) {
  const headers = new Headers(options.headers);
  if (options.auth) {
    const token = authStorage.getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(apiUrl(path), { headers, credentials: "include" });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(getMessage(payload, "文件生成失败，请稍后再试。"), response.status, payload);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const api = {
  async login(email: string, password: string, tenantSlug?: string) {
    return request<AuthToken>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, tenant_slug: tenantSlug?.trim() || undefined }),
    });
  },
  me: () => request<User>("/api/auth/me", {}, true),

  getStore: (slug: string, locale?: string) => {
    const path = storePath(slug, locale);
    return cachedPublicRequest(
      `store:${path}`,
      PUBLIC_STORE_CACHE_TTL_MS,
      () => request<Storefront>(path),
    );
  },
  async getStoreSku(slug: string, skuId: string, locale?: string): Promise<Sku> {
    const path = storeSkuPath(slug, skuId, locale);
    return cachedPublicRequest(
      `sku:${path}`,
      PUBLIC_SKU_CACHE_TTL_MS,
      async () => normalizeSku(await request<Sku>(path)),
    );
  },
  async getStoreSkus(
    slug: string,
    filters: StoreSkuFilters = {},
  ): Promise<SkuList> {
    return getCachedStoreSkus(slug, filters);
  },
  prefetchStoreSkus: async (slug: string, filters: StoreSkuFilters = {}) => {
    await getCachedStoreSkus(slug, filters);
  },
  createStoreQuote: async (slug: string, payload: CreateQuoteInput) =>
    normalizeQuote(await request<Quote>(`/api/store/${encodeURIComponent(slug)}/quotes`, {
      method: "POST",
      body: JSON.stringify(payload),
    }, Boolean(getCoreAccessToken()))),
  downloadStoreQuote: (quoteId: string, type: "pdf" | "xlsx", token?: string | null) =>
    download(
      `/api/quotes/${encodeURIComponent(quoteId)}/${type}`,
      `quotation-${quoteId}.${type}`,
      token ? { headers: { "X-Quote-Download-Token": token } } : {},
    ),

  async getDashboard() {
    const raw = await request<DashboardData>(consolePath("/api/console/dashboard"), {}, true);
    return { ...raw, recent_quotes: (raw.recent_quotes || []).map(normalizeQuote) };
  },
  async getConsoleSkus(q = "", page = 1): Promise<SkuList> {
    const params = new URLSearchParams({ page: String(page), page_size: "100" });
    if (q) params.set("q", q);
    const base = `/api/console/skus?${params.toString()}`;
    const raw = await request<unknown>(consolePath(base), {}, true);
    const list = normalizeList<Sku>(raw);
    const meta = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
    return { ...list, items: list.items.map(normalizeSku), page: Number(meta.page || page), pages: Number(meta.pages || 0) };
  },
  createSku: (payload: SkuPayload) => {
    const body = { ...payload, price: payload.price ?? 0 };
    return request<Sku>(consolePath("/api/console/skus"), { method: "POST", body: JSON.stringify(body) }, true);
  },
  updateSku: (id: string, payload: SkuPayload) => {
    const body = { ...payload, price: payload.price ?? 0 };
    return request<Sku>(consolePath(`/api/console/skus/${id}`), { method: "PATCH", body: JSON.stringify(body) }, true);
  },
  deleteSku: (id: string) =>
    request<void>(consolePath(`/api/console/skus/${id}`), { method: "DELETE" }, true),
  importSkus: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<SkuImportResult>(consolePath("/api/console/skus/import"), { method: "POST", body }, true);
  },
  getProductTags(category = "", limit = 200, offset = 0) {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (category) params.set("category", category);
    return request<ProductTagList>(`/api/tags?${params.toString()}`, {}, true);
  },
  createProductTag: (payload: ProductTagPayload) =>
    request<ProductTag>(
      "/api/tags",
      { method: "POST", body: JSON.stringify(payload) },
      true,
    ),
  updateProductTag: (id: string, payload: Partial<ProductTagPayload>) =>
    request<ProductTag>(
      `/api/tags/${encodeURIComponent(id)}`,
      { method: "PATCH", body: JSON.stringify(payload) },
      true,
    ),
  deleteProductTag: (id: string) =>
    request<void>(
      `/api/tags/${encodeURIComponent(id)}`,
      { method: "DELETE" },
      true,
    ),
  async getQuotes(): Promise<Quote[]> {
    const raw = await request<unknown>("/api/v1/public-quote-drafts", {}, true);
    return normalizeList<Quote>(raw).items.map(normalizeQuote);
  },
  downloadConsoleQuote: (quoteId: string, type: "pdf" | "xlsx") =>
    download(
      `/api/v1/public-quote-drafts/${quoteId}/${type}`,
      `quotation-${quoteId}.${type}`,
      { auth: true },
    ),

  async getTenants(): Promise<Tenant[]> {
    const raw = await request<unknown>("/api/admin/tenants", {}, true);
    return normalizeList<Tenant>(raw).items.map(normalizeTenant);
  },
  createTenant: (payload: TenantPayload) => {
    return request<Tenant>("/api/admin/tenants", { method: "POST", body: JSON.stringify({ ...payload, default_currency: "CNY" }) }, true);
  },
  updateTenant: (id: string, payload: TenantPayload) =>
    request<Tenant>(`/api/admin/tenants/${id}`, { method: "PATCH", body: JSON.stringify({ name: payload.name, contact_email: payload.contact_email || null, active: payload.active }) }, true),
  deactivateTenant: (id: string) =>
    request<Tenant>(`/api/admin/tenants/${id}`, { method: "PATCH", body: JSON.stringify({ active: false }) }, true),
  provisionMerchantOwner: (tenantId: string, payload: MerchantOwnerAccountPayload) =>
    request<MerchantOwnerAccount>(
      `/api/admin/tenants/${encodeURIComponent(tenantId)}/owner-account`,
      { method: "POST", body: JSON.stringify(payload) },
      true,
    ),
  inviteTenantMember: (tenantId: string, payload: MemberInvitationPayload) =>
    request<MemberInvitation>(
      `/api/admin/tenants/${tenantId}/member-invitations`,
      { method: "POST", body: JSON.stringify(payload) },
      true,
    ),
};
