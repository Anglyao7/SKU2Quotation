const preloads: Record<string, () => Promise<unknown>> = {
  "/console": () => import("./pages/DashboardPage"),
  "/console/analytics": () => import("./pages/StorefrontAnalyticsPage"),
  "/console/ai-search": () => import("./pages/AiSearchPage"),
  "/console/ai-search/manage": () => import("./pages/AiSearchManagementPage"),
  "/console/products": () => import("./pages/ProductsPage"),
  "/console/products/categories": () => import("./pages/CategoriesPage"),
  "/console/products/tags": () => import("../pages/console/TagManagementPage"),
  "/console/inventory": () => import("./pages/InventoryPage"),
  "/console/announcements": () => import("./pages/AnnouncementsPage"),
  "/console/inquiries": () => import("./pages/InquiryPage"),
  "/console/quotes": () => import("./pages/QuotesPage"),
  "/console/quote-templates": () => import("./pages/QuoteTemplatesPage"),
  "/console/customer-accounts": () => import("./pages/CustomerAccountsPage"),
  "/console/system/permissions": () => import("./pages/PermissionsPage"),
  "/console/system/monitoring": () => import("./pages/SystemMonitoringPage"),
  "/console/tenants": () => import("../pages/console/TenantManagementPage"),
  "/console/account": () => import("./pages/AccountSettingsPage"),
};

const inFlight = new Map<string, Promise<unknown>>();

export function preloadConsoleRoute(path: string) {
  const loader = preloads[path];
  if (!loader) return;
  if (!inFlight.has(path)) {
    const pending = loader().catch(() => {
      inFlight.delete(path);
    });
    inFlight.set(path, pending);
  }
}
