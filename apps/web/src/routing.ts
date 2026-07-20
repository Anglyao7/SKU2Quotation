export const LEGACY_WORKSPACE_PATHS = {
  dashboard: "/dashboard",
  suppliers: "/suppliers",
  review: "/review",
  products: "/products",
  aiSearch: "/ai-search",
  inquiries: "/inquiries",
  quotations: "/quotations",
  permissions: "/system/permissions",
} as const;

export const CONSOLE_WORKSPACE_PATHS = {
  dashboard: "/console",
  suppliers: "/console/suppliers",
  review: "/console/products/review",
  products: "/console/products",
  aiSearch: "/console/ai-search",
  inquiries: "/console/inquiries",
  quotations: "/console/quotes",
  permissions: "/console/system/permissions",
} as const;
