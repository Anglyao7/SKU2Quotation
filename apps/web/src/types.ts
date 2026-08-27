export type TenantModuleCode =
  | "products"
  | "analytics"
  | "inventory"
  | "announcements"
  | "support"
  | "support_ai"
  | "inquiries"
  | "quotations"
  | "subaccounts";

export type MerchantIdentityCode = string;
export type TenantModuleAccessMode = "INHERIT" | "CUSTOM";

export interface MerchantIdentityProfile {
  code: MerchantIdentityCode;
  name: string;
  enabled_modules: TenantModuleCode[];
  is_system: boolean;
  editable: boolean;
  version: number;
  updated_at: string;
}

export type TenantSubscriptionTier = "TRIAL" | "STANDARD" | "SILVER" | "ELITE";
export type TenantSubscriptionStatus = "active" | "expiring_soon" | "expired";

export interface Tenant {
  id: string;
  organization_id?: string;
  name: string;
  slug: string;
  active?: boolean;
  status: "active" | "suspended" | "archived";
  logo_url?: string | null;
  contact_email?: string | null;
  default_locale?: string;
  default_currency?: string;
  timezone?: string;
  sku_count?: number;
  quote_count?: number;
  owner_account?: MerchantOwnerAccount | null;
  identity_code?: MerchantIdentityCode;
  module_access_mode?: TenantModuleAccessMode;
  enabled_modules?: TenantModuleCode[];
  module_overrides?: TenantModuleCode[] | null;
  subscription_tier: TenantSubscriptionTier;
  subscription_started_at: string;
  subscription_expires_at: string;
  subscription_status: TenantSubscriptionStatus;
  sku_limit: number | null;
  sku_remaining: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface MerchantOwnerAccount {
  user_id: string;
  membership_id: string;
  display_name: string;
  login_identifier?: string | null;
  email?: string | null;
  status: "active" | "invited" | "suspended" | "removed";
  created_at: string;
}

export interface MerchantOwnerPasswordResetResult {
  account: MerchantOwnerAccount;
  one_time_password: string;
}

export interface MerchantDailyMetric {
  date: string;
  count: number;
}

export interface MerchantStatusMetric {
  status: "PENDING_CONFIRMATION" | "CONFIRMED" | "COMPLETED" | "CANCELLED" | "EXPIRED";
  count: number;
}

export interface MerchantMonitoring {
  generated_at: string;
  period_days: number;
  quotes_total: number;
  quotes_period: number;
  quotes_pending: number;
  quotes_confirmed: number;
  quotes_completed: number;
  quotes_cancelled: number;
  skus_total: number;
  subaccounts_total: number;
  subaccounts_active: number;
  storefront_visitors_period: number;
  product_views_period: number;
  last_quote_at?: string | null;
  quote_statuses: MerchantStatusMetric[];
  quote_trend: MerchantDailyMetric[];
  product_view_trend: MerchantDailyMetric[];
}

export type MerchantSubaccountCapability = "catalog" | "submit_orders" | "view_orders";
export type MerchantSubaccountModule = "products" | "inquiries" | "quotations" | "announcements" | "support";

export interface MerchantSubaccountSummary {
  id: string;
  user_id: string;
  display_name: string;
  login_identifier: string;
  email?: string | null;
  status: "invited" | "active" | "suspended";
  modules: MerchantSubaccountModule[];
  capabilities: MerchantSubaccountCapability[];
  parent_membership_id?: string | null;
  parent_display_name?: string | null;
  created_at: string;
  last_login_at?: string | null;
  login_count_30d: number;
  quote_count: number;
  last_quote_at?: string | null;
}

export interface MerchantRecentQuote {
  id: string;
  quote_number: string;
  status: MerchantStatusMetric["status"];
  customer_name: string;
  customer_company?: string | null;
  currency: string;
  total_amount: number | string;
  created_at: string;
  valid_until: string;
}

export interface MerchantDetail {
  merchant: Tenant;
  monitoring: MerchantMonitoring;
  subaccounts: MerchantSubaccountSummary[];
}

export interface MerchantSubaccountDetail {
  merchant: Tenant;
  account: MerchantSubaccountSummary;
  recent_quotes: MerchantRecentQuote[];
}

export interface Storefront {
  id?: string;
  name: string;
  slug: string;
  description?: string;
  logo_url?: string | null;
  contact_email?: string | null;
  default_currency?: string;
  locale?: StorefrontLocale;
  source_locale?: StorefrontLocale;
  available_locales?: StorefrontLocale[];
  categories?: string[];
  category_options?: StorefrontCategoryOption[];
  tags?: string[];
  all_products_position?: number;
  hot_products_enabled?: boolean;
  category_showcase_enabled?: boolean;
  ai_search_questions?: string[];
  announcements?: PublicAnnouncement[];
  support_widget?: PublicSupportWidget;
}

export interface StorefrontExchangeRate {
  currency: string;
  name: string;
  symbol: string;
  rate: number | string | null;
  base_currency: string;
  rate_date?: string | null;
  source: string;
}

export interface StorefrontExchangeRateSnapshot {
  observed_at: string;
  base_currency: string;
  exchange_rates: StorefrontExchangeRate[];
  rate_date?: string | null;
  rate_source: string;
}

export type CatalogShareTargetType = "PRODUCTS" | "CATEGORY";

export interface CatalogSharePublic {
  id: string;
  token: string;
  target_type: CatalogShareTargetType;
  title: string;
  item_count: number;
  category_id?: string | null;
  category_name?: string | null;
  category_path?: string | null;
  share_path: string;
  store_name: string;
  store_subtitle?: string | null;
  store_logo_url?: string | null;
  created_at: string;
}

export interface StorefrontSupportAction {
  slot: 2 | 3;
  visible: boolean;
  label?: string | null;
  external_image_url?: string | null;
  image_url?: string | null;
  has_uploaded_image?: boolean;
}

export interface PublicSupportWidget {
  enabled: boolean;
  title: string;
  welcome_message: string;
  ai_enabled: boolean;
  custom_actions: StorefrontSupportAction[];
}

export type SupportSenderType = "VISITOR" | "MERCHANT" | "SYSTEM" | "AI";

export interface PublicSupportMessage {
  id: string;
  sender_type: SupportSenderType;
  body: string;
  created_at: string;
  citations?: SupportCitation[];
}

export interface SupportCitation {
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

export interface PublicSupportConversation {
  id: string;
  reference_number: string;
  status: "OPEN" | "CLOSED";
  messages: PublicSupportMessage[];
  access_token?: string | null;
  automation_state?: "AI_ACTIVE" | "HUMAN_TAKEOVER";
  ai_processing?: boolean;
  ai_processing_stage?: "USING_TOOLS" | "RAG_SEARCH" | "COMPOSING" | null;
  human_assistance_state?: "NONE" | "OFFERED" | "REQUESTED" | "RESOLVED";
  human_assistance_requested_at?: string | null;
}

export type PublicSupportStreamEvent =
  | { type: "conversation"; conversation: PublicSupportConversation }
  | { type: "message_start"; message: PublicSupportMessage }
  | { type: "message_delta"; message_id: string; delta: string }
  | { type: "message_reset"; message_id: string; body: string }
  | {
      type: "message_end";
      stream_id?: string;
      message: PublicSupportMessage;
      conversation: PublicSupportConversation;
    }
  | {
      type: "message_abort";
      message_id: string;
      conversation: PublicSupportConversation;
    }
  | { type: "stream_error"; code: string };

export type StorefrontLocale =
  | "zh-CN"
  | "en-US"
  | "es"
  | "tr"
  | "ar"
  | "ja"
  | "ko"
  | "pt";

export interface CatalogLanguagePackDescriptor {
  source_locale: StorefrontLocale;
  target_locale: StorefrontLocale;
  version: number;
  download_url: string;
  content_sha256: string;
  content_encoding: "gzip" | string;
  byte_size: number;
  product_count: number;
  sku_count: number;
  category_count: number;
  source_cutoff_at: string;
  published_at: string;
  last_full_translation_at?: string | null;
}

export interface CatalogLanguagePackProduct {
  source_hash: string;
  source_updated_at: string;
  product_version: number;
  name: string;
  description?: string | null;
  category_label?: string | null;
  tags: string[];
  display_tag?: string | null;
  specifications: Record<string, string>;
  option_labels: Record<string, string>;
  option_values: Record<string, string>;
}

export interface CatalogLanguagePackSku {
  source_hash: string;
  source_updated_at: string;
  product_version: number;
  sku_version: number;
  product_id: string;
  name: string;
  description?: string | null;
  category_label?: string | null;
  tags: string[];
  display_tag?: string | null;
  specification?: string | null;
}

export interface CatalogLanguagePack {
  schema: "atc-catalog-language-pack";
  schema_version: 2;
  tenant_id: string;
  source_locale: StorefrontLocale;
  target_locale: StorefrontLocale;
  version: number;
  generated_at: string;
  source_cutoff_at: string;
  products: Record<string, CatalogLanguagePackProduct>;
  skus: Record<string, CatalogLanguagePackSku>;
  categories: Record<string, string>;
}

export type AnnouncementDisplayType = "TICKER" | "MODAL";
export type AnnouncementBlockType =
  | "heading"
  | "paragraph"
  | "bullet_list"
  | "image"
  | "video"
  | "link";

export interface AnnouncementContentBlock {
  type: AnnouncementBlockType;
  text?: string | null;
  url?: string | null;
  alt?: string | null;
  caption?: string | null;
}

export interface PublicAnnouncement {
  id: string;
  title?: string | null;
  display_type: AnnouncementDisplayType;
  ticker_text?: string | null;
  content_blocks: AnnouncementContentBlock[];
  starts_at: string;
  ends_at: string;
  ticker_speed_px_per_second: number;
  version: number;
  related_skus: PublicAnnouncementRelatedSku[];
}

export interface PublicAnnouncementRelatedSku {
  id: string;
  product_id: string;
  sku_code: string;
  name: string;
  product_name: string;
  is_public: boolean;
}

export interface StorefrontCategoryOption {
  value: string;
  label: string;
  id?: string;
  parent_id?: string | null;
  cover_image_url?: string | null;
}

export interface Sku {
  id: string;
  product_id?: string;
  tenant_id?: string;
  sku_code: string;
  name: string;
  category?: string | null;
  category_label?: string | null;
  category_color?: string | null;
  tags: string[];
  display_tag?: string | null;
  tag_color?: string | null;
  description?: string | null;
  specifications?: Record<string, string | number> | null;
  image_url?: string | null;
  price?: number | string | null;
  currency?: string;
  stock?: number | null;
  active?: boolean;
  status?: "active" | "inactive";
  created_at?: string;
  updated_at?: string;
  product_version?: number;
  sku_version?: number;
  source_updated_at?: string;
  translation_source_hash?: string;
  source_locale?: StorefrontLocale;
  locale?: StorefrontLocale;
  translation_status?: "SOURCE" | "TRANSLATED" | "FALLBACK";
  specification?: string | null;
  option_values?: Record<string, unknown>;
}

export interface SkuList {
  items: Sku[];
  total: number;
  page?: number;
  pages?: number;
  categories?: string[];
  category_options?: StorefrontCategoryOption[];
  tags?: string[];
  source_locale?: StorefrontLocale;
  locale?: StorefrontLocale;
  all_products_position?: number;
  category_showcase_enabled?: boolean;
}

export interface StoreProduct {
  id: string;
  product_code?: string | null;
  name: string;
  description?: string | null;
  category?: string | null;
  category_label?: string | null;
  category_color?: string | null;
  tags: string[];
  display_tag?: string | null;
  tag_color?: string | null;
  price_from: number | string;
  price_to: number | string;
  currency: string;
  unit_code: string;
  image_url?: string | null;
  sku_count: number;
  product_version: number;
  source_updated_at?: string;
  translation_source_hash?: string;
  source_locale?: StorefrontLocale;
  locale?: StorefrontLocale;
  translation_status?: "SOURCE" | "TRANSLATED" | "FALLBACK";
}

export interface StoreProductDetail extends StoreProduct {
  image_urls?: string[];
  skus: Sku[];
}

export interface StoreProductList {
  items: StoreProduct[];
  total: number;
  page?: number;
  pages?: number;
  categories?: string[];
  category_options?: StorefrontCategoryOption[];
  tags?: string[];
  source_locale?: StorefrontLocale;
  locale?: StorefrontLocale;
  all_products_position?: number;
  hot_products_enabled?: boolean;
  category_showcase_enabled?: boolean;
  hot_sort_applied?: boolean;
}

export interface StoreImageSearchResult {
  product: StoreProduct;
  matched_image_id: string;
  similarity: number;
  match_percent: number;
  confidence: "HIGH" | "MEDIUM" | "REFERENCE";
}

export interface StoreImageSearchResponse {
  id: string;
  status: "COMPLETED" | "INDEX_EMPTY";
  results: StoreImageSearchResult[];
  warnings: string[];
}

export interface ProductTag {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProductTagList {
  tags: ProductTag[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProductTagPayload {
  name: string;
  description: string | null;
  category: string | null;
}

export interface QuoteItemInput {
  sku_id: string;
  quantity: number;
}

export interface CreateQuoteInput {
  locale: StorefrontLocale;
  customer_name: string;
  customer_company?: string;
  customer_email?: string;
  notes?: string;
  privacy_acknowledged: true;
  items: QuoteItemInput[];
}

export interface QuoteItem {
  id?: string;
  sku_id: string;
  sku_code?: string;
  sku_name?: string;
  name?: string;
  quantity: number;
  unit_price?: number | string | null;
  line_total?: number | string | null;
  image_url?: string | null;
  sku_code_snapshot?: string;
  name_snapshot?: string;
  unit_price_snapshot?: number | string | null;
  image_url_snapshot?: string | null;
}

export interface Quote {
  id: string;
  quote_no?: string;
  quote_number?: string;
  number?: string;
  tenant_id?: string;
  customer_name: string;
  customer_company?: string | null;
  customer_email?: string | null;
  notes?: string | null;
  locale?: StorefrontLocale;
  status?: "draft" | "generated" | "sent" | "expired" | string;
  currency?: string;
  total_amount?: number | string | null;
  subtotal?: number | string | null;
  total?: number | string | null;
  valid_until?: string;
  download_token?: string | null;
  items: QuoteItem[];
  created_at?: string;
  pdf_url?: string;
  xlsx_url?: string;
}

export interface StorefrontVisitorQuote {
  id: string;
  quote_number: string;
  status: "PENDING_CONFIRMATION" | "CONFIRMED" | "COMPLETED" | "CANCELLED" | "EXPIRED";
  customer_name: string;
  customer_company?: string | null;
  locale: StorefrontLocale;
  currency: string;
  total_amount: number | string;
  valid_until: string;
  created_at: string;
  updated_at: string;
}

export interface TenantPayload {
  name: string;
  slug?: string;
  contact_email?: string;
  active: boolean;
  identity_code?: MerchantIdentityCode;
  module_access_mode?: TenantModuleAccessMode;
  enabled_modules?: TenantModuleCode[];
}

export interface TenantBasicInfoPayload {
  name: string;
  contact_email: string | null;
  active: boolean;
  default_locale: string;
  default_currency: string;
  timezone: string;
}

export interface TenantAccessPayload {
  identity_code: MerchantIdentityCode;
  module_access_mode: TenantModuleAccessMode;
  enabled_modules?: TenantModuleCode[];
}

export interface TenantSubscriptionPayload {
  subscription_tier: TenantSubscriptionTier;
  subscription_expires_at: string;
  sku_limit: number | null;
}

export interface PlatformUsageTotals {
  storefront_visitors: number;
  product_visitors: number;
  product_clicks: number;
  quote_requests: number;
  quotations: number;
  image_searches: number;
  ai_conversations: number;
  ai_messages: number;
}

export interface PlatformTenantUsageItem {
  tenant_id: string;
  name: string;
  slug: string;
  status: string;
  active: boolean;
  storefront_visitors: number;
  product_visitors: number;
  product_clicks: number;
  quote_requests: number;
  quotations: number;
  image_searches: number;
  ai_conversations: number;
  ai_messages: number;
}

export interface PlatformUsageResponse {
  generated_at: string;
  start_date: string;
  end_date: string;
  days: number;
  totals: PlatformUsageTotals;
  tenants: PlatformTenantUsageItem[];
}

export interface MerchantOwnerAccountPayload {
  display_name: string;
  login_identifier: string;
  password: string;
  email?: string;
}
