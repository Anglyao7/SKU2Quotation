export type Role = "platform_admin" | "merchant_admin" | "merchant_staff";

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
  created_at?: string;
}

export interface User {
  id: string;
  name?: string;
  full_name?: string;
  email: string;
  role: Role;
  tenant_id?: string | null;
  tenant?: Tenant | null;
}

export interface AuthToken {
  access_token: string;
  token_type: string;
}

export interface Storefront {
  id?: string;
  name: string;
  slug: string;
  description?: string;
  logo_url?: string | null;
  default_currency?: string;
  categories?: string[];
  tags?: string[];
}

export interface Sku {
  id: string;
  tenant_id?: string;
  sku_code: string;
  name: string;
  category?: string | null;
  tags: string[];
  description?: string | null;
  specifications?: Record<string, string | number> | null;
  image_url?: string | null;
  price?: number | string | null;
  currency?: string;
  moq?: number | null;
  stock?: number | null;
  active?: boolean;
  status?: "active" | "inactive";
  created_at?: string;
  updated_at?: string;
}

export interface SkuList {
  items: Sku[];
  total: number;
  page?: number;
  pages?: number;
  categories?: string[];
  tags?: string[];
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

export interface DashboardData {
  tenant?: Storefront;
  sku_count: number;
  active_sku_count?: number;
  quote_count: number;
  quote_this_month?: number;
  tenant_count?: number;
  quote_total?: number | string;
  recent_quotes?: Quote[];
  top_categories?: Array<{ name: string; count: number }>;
}

export interface SkuPayload {
  sku_code: string;
  name: string;
  category?: string;
  tags: string[];
  description?: string;
  image_url?: string;
  price?: number | null;
  currency: string;
  moq?: number | null;
  stock?: number | null;
  active: boolean;
}

export interface SkuImportResult {
  imported?: number;
  created?: number;
  inserted?: number;
  updated?: number;
  failed?: number;
  errors?: Array<{ row?: number; sku_code?: string; message?: string; error?: string }>;
}

export interface TenantPayload {
  name: string;
  slug: string;
  contact_email?: string;
  active: boolean;
}
