export interface Tenant {
  id: string;
  name: string;
  slug: string;
  active?: boolean;
  status: "active" | "inactive";
  logo_url?: string | null;
  contact_email?: string | null;
  sku_count?: number;
  quote_count?: number;
  owner_account?: MerchantOwnerAccount | null;
  created_at?: string;
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
  announcements?: PublicAnnouncement[];
  support_widget?: PublicSupportWidget;
}

export interface StorefrontSupportAction {
  slot: 2 | 3;
  visible: boolean;
  label?: string | null;
  target_url?: string | null;
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
}

export interface PublicSupportConversation {
  id: string;
  reference_number: string;
  status: "OPEN" | "CLOSED";
  messages: PublicSupportMessage[];
  access_token?: string | null;
}

export type StorefrontLocale =
  | "zh-CN"
  | "en-US"
  | "es"
  | "tr"
  | "ar"
  | "ja"
  | "ko"
  | "pt";

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
  source_locale?: StorefrontLocale;
  locale?: StorefrontLocale;
  translation_status?: "SOURCE" | "TRANSLATED" | "FALLBACK";
}

export interface StoreProductDetail extends StoreProduct {
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
  hot_sort_applied?: boolean;
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

export interface TenantPayload {
  name: string;
  slug?: string;
  contact_email?: string;
  active: boolean;
}

export interface MerchantOwnerAccountPayload {
  display_name: string;
  login_identifier: string;
  password: string;
  email?: string;
}
