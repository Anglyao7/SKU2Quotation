import { Button, Card, Heading, Spinner, Text } from "@radix-ui/themes";
import { ShieldWarning } from "@phosphor-icons/react";
import {
  Navigate,
  Outlet,
  RouterProvider,
  createBrowserRouter,
  isRouteErrorResponse,
  redirect,
  useLocation,
  useParams,
  useRouteError,
  type LoaderFunctionArgs,
} from "react-router-dom";
import {
  lazy,
  Suspense,
  useEffect,
  type ComponentType,
  type ReactNode,
} from "react";
import { Brand } from "./components/Brand";
import { ErrorState } from "./components/States";
import { useCoreAuth } from "./core/AuthContext";
import { useLocale } from "./core/LocaleContext";
import { api, ApiError } from "./lib/api";
import { readStorefrontViewState } from "./lib/storefrontViewState";
import { normalizeStorefrontLocale } from "./lib/storefrontLocale";
import {
  importWithChunkRecovery,
  isChunkLoadFailure,
  reloadLatestBundle,
} from "./lib/chunkRecovery";
import { LoginPage } from "./pages/LoginPage";

function recoverableLazy<T extends ComponentType<any>>(
  loader: () => Promise<{ default: T }>,
) {
  return lazy(() => importWithChunkRecovery(loader));
}

const LandingPage = recoverableLazy(() => import("./pages/marketing/LandingPage").then((module) => ({ default: module.LandingPage })));
const StorePage = recoverableLazy(() => import("./pages/StorePage").then((module) => ({ default: module.StorePage })));
const ProductDetailPage = recoverableLazy(() => import("./pages/ProductDetailPage").then((module) => ({ default: module.ProductDetailPage })));
const SkuDetailPage = recoverableLazy(() => import("./pages/SkuDetailPage").then((module) => ({ default: module.SkuDetailPage })));
const PrivacyPage = recoverableLazy(() => import("./pages/PrivacyPage").then((module) => ({ default: module.PrivacyPage })));
const ConsoleLayout = recoverableLazy(() => import("./pages/console/ConsoleLayout").then((module) => ({ default: module.ConsoleLayout })));
const TenantManagementPage = recoverableLazy(() => import("./pages/console/TenantManagementPage").then((module) => ({ default: module.TenantManagementPage })));
const NotFoundPage = recoverableLazy(() => import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })));
const AiSearchPage = recoverableLazy(() => import("./core/pages/AiSearchPage").then((module) => ({ default: module.AiSearchPage })));
const AiSearchManagementPage = recoverableLazy(() => import("./core/pages/AiSearchManagementPage").then((module) => ({ default: module.AiSearchManagementPage })));
const AccountSettingsPage = recoverableLazy(() => import("./core/pages/AccountSettingsPage").then((module) => ({ default: module.AccountSettingsPage })));
const CategoriesPage = recoverableLazy(() => import("./core/pages/CategoriesPage").then((module) => ({ default: module.CategoriesPage })));
const CoreDashboardPage = recoverableLazy(() => import("./core/pages/DashboardPage").then((module) => ({ default: module.CoreDashboardPage })));
const InquiryPage = recoverableLazy(() => import("./core/pages/InquiryPage").then((module) => ({ default: module.InquiryPage })));
const InventoryPage = recoverableLazy(() => import("./core/pages/InventoryPage").then((module) => ({ default: module.InventoryPage })));
const SystemMonitoringPage = recoverableLazy(() => import("./core/pages/SystemMonitoringPage").then((module) => ({ default: module.SystemMonitoringPage })));
const ConfigurationCenterPage = recoverableLazy(() => import("./core/pages/ConfigurationCenterPage").then((module) => ({ default: module.ConfigurationCenterPage })));
const LanguagePackagesPage = recoverableLazy(() => import("./core/pages/LanguagePackagesPage").then((module) => ({ default: module.LanguagePackagesPage })));
const StorefrontAnalyticsPage = recoverableLazy(() => import("./core/pages/StorefrontAnalyticsPage").then((module) => ({ default: module.StorefrontAnalyticsPage })));
const AnnouncementsPage = recoverableLazy(() => import("./core/pages/AnnouncementsPage").then((module) => ({ default: module.AnnouncementsPage })));
const SupportCenterPage = recoverableLazy(() => import("./core/pages/SupportCenterPage").then((module) => ({ default: module.SupportCenterPage })));
const SupportAIAgentsPage = recoverableLazy(() => import("./core/pages/SupportAIAgentsPage").then((module) => ({ default: module.SupportAIAgentsPage })));
const SupportAIAgentDetailPage = recoverableLazy(() => import("./core/pages/SupportAIAgentDetailPage").then((module) => ({ default: module.SupportAIAgentDetailPage })));
const SupportAIKnowledgePage = recoverableLazy(() => import("./core/pages/SupportAIKnowledgePage").then((module) => ({ default: module.SupportAIKnowledgePage })));
const PersonalCenterPage = recoverableLazy(() => import("./core/pages/PersonalCenterPage").then((module) => ({ default: module.PersonalCenterPage })));
const ProductsPage = recoverableLazy(() => import("./core/pages/ProductsPage").then((module) => ({ default: module.ProductsPage })));
const QuotesPage = recoverableLazy(() => import("./core/pages/QuotesPage").then((module) => ({ default: module.QuotesPage })));
const QuoteTemplatesPage = recoverableLazy(() => import("./core/pages/QuoteTemplatesPage").then((module) => ({ default: module.QuoteTemplatesPage })));
const TagManagementPage = recoverableLazy(() => import("./pages/console/TagManagementPage").then((module) => ({ default: module.TagManagementPage })));
const CustomerAccountsPage = recoverableLazy(() => import("./core/pages/CustomerAccountsPage").then((module) => ({ default: module.CustomerAccountsPage })));
const CustomerPortalPage = recoverableLazy(() => import("./pages/CustomerPortalPage").then((module) => ({ default: module.CustomerPortalPage })));

function ApplicationRouteError() {
  const error = useRouteError();
  const { t } = useLocale();
  const staleBundle = isChunkLoadFailure(error);
  const detail = error instanceof Error ? error.message : String(error ?? "");

  return (
    <main className="application-error-page">
      <Brand />
      <section className="application-error-card">
        <span className="application-error-icon"><ShieldWarning weight="duotone" /></span>
        <Text size="1" color="gray">{t("页面恢复")}</Text>
        <Heading size="7">
          {t(staleBundle ? "页面版本已经更新" : "这个页面暂时无法打开")}
        </Heading>
        <Text size="3" color="gray">
          {t(staleBundle
            ? "系统检测到浏览器仍在使用旧版页面资源，重新加载后会自动切换到最新版。"
            : "系统没有丢失你的数据。请重新加载页面；若问题持续出现，再联系平台管理员。")}
        </Text>
        {import.meta.env.DEV && detail ? <code>{detail}</code> : null}
        <div className="application-error-actions">
          <Button size="3" onClick={() => reloadLatestBundle(true)}>
            {t("重新加载最新版")}
          </Button>
          <Button asChild size="3" variant="soft" color="gray">
            <a href="/">{t("返回首页")}</a>
          </Button>
        </div>
      </section>
    </main>
  );
}

function ProtectedRoute() {
  const { status } = useCoreAuth();
  const { t } = useLocale();
  const location = useLocation();
  if (status === "restoring") return <div className="route-loading"><Spinner size="3" /><span>{t("正在恢复安全会话")}</span></div>;
  if (status !== "authenticated") return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <Outlet />;
}

function StaffConsoleRoute() {
  const { profile } = useCoreAuth();
  if (profile?.context.accountScope === "CUSTOMER_SUBACCOUNT") {
    return <Navigate to="/portal" replace />;
  }
  return <Outlet />;
}

function CustomerPortalRoute() {
  const { profile } = useCoreAuth();
  if (profile?.context.accountScope !== "CUSTOMER_SUBACCOUNT") {
    return <Navigate to="/console" replace />;
  }
  return <Outlet />;
}

function PermissionGate({ anyOf, children }: { anyOf: string[]; children: ReactNode }) {
  const { hasAnyPermission } = useCoreAuth();
  const { t } = useLocale();
  if (hasAnyPermission(...anyOf)) return children;
  return <div className="core-workspace"><Card className="core-state"><ShieldWarning size={36} /><Heading size="5">{t("当前成员没有此工作区权限")}</Heading><Text size="2" color="gray">{t("需要以下任一服务端权限：{permissions}", { permissions: anyOf.join(" / ") })}</Text><Button asChild variant="soft"><a href="/console">{t("返回仪表盘")}</a></Button></Card></div>;
}

function PlatformAdminGate({ children }: { children: ReactNode }) {
  const { profile } = useCoreAuth();
  const { t } = useLocale();
  if (profile?.user.isPlatformAdmin) return children;
  return <div className="core-workspace"><Card className="core-state"><ShieldWarning size={36} /><Heading size="5">{t("仅平台管理员可以管理商家")}</Heading><Text size="2" color="gray">{t("租户创建、启停和平台级状态不属于商家成员权限。")}</Text><Button asChild variant="soft"><a href="/console">{t("返回仪表盘")}</a></Button></Card></div>;
}

async function storefrontLoader({ params, request }: LoaderFunctionArgs) {
  const tenantSlug = params.tenantSlug;
  if (!tenantSlug) throw new Response("Not found", { status: 404 });
  const currentUrl = new URL(request.url);
  const locale = normalizeStorefrontLocale(currentUrl.searchParams.get("lang"));
  try {
    const savedView = readStorefrontViewState(tenantSlug);
    const category = savedView?.secondaryCategory || savedView?.primaryCategory;
    void api.prefetchStoreProducts(tenantSlug, {
      q: savedView?.search.trim() || undefined,
      category: category || undefined,
      semantic: Boolean(savedView?.search.trim()),
      includeFacets: true,
      page: savedView?.page || 1,
      locale,
    }).catch(() => undefined);
    const store = await api.getStore(tenantSlug, locale);
    if (store.slug.toLocaleLowerCase() !== tenantSlug.toLocaleLowerCase()) {
      return redirect(`/${encodeURIComponent(store.slug)}${currentUrl.search}${currentUrl.hash}`);
    }
    return store;
  }
  catch (error) {
    if (error instanceof ApiError && error.status === 422 && currentUrl.searchParams.has("lang")) {
      currentUrl.searchParams.delete("lang");
      const query = currentUrl.searchParams.toString();
      return redirect(`/${encodeURIComponent(tenantSlug)}${query ? `?${query}` : ""}${currentUrl.hash}`);
    }
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) throw new Response("Not found", { status: 404 });
    throw error;
  }
}

async function storefrontProductLoader({ params, request }: LoaderFunctionArgs) {
  const tenantSlug = params.tenantSlug;
  const productId = params.productId;
  if (!tenantSlug || !productId) throw new Response("Not found", { status: 404 });
  const currentUrl = new URL(request.url);
  const locale = normalizeStorefrontLocale(currentUrl.searchParams.get("lang"));
  try {
    const [store, product] = await Promise.all([
      api.getStore(tenantSlug, locale),
      api.getStoreProduct(tenantSlug, productId, locale),
    ]);
    if (store.slug.toLocaleLowerCase() !== tenantSlug.toLocaleLowerCase()) {
      return redirect(
        `/${encodeURIComponent(store.slug)}/products/${encodeURIComponent(product.id)}${currentUrl.search}${currentUrl.hash}`,
      );
    }
    return { store, product };
  }
  catch (error) {
    if (error instanceof ApiError && error.status === 422 && currentUrl.searchParams.has("lang")) {
      currentUrl.searchParams.delete("lang");
      const query = currentUrl.searchParams.toString();
      return redirect(
        `/${encodeURIComponent(tenantSlug)}/products/${encodeURIComponent(productId)}${query ? `?${query}` : ""}${currentUrl.hash}`,
      );
    }
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) throw new Response("Not found", { status: 404 });
    throw error;
  }
}

async function storefrontSkuLoader({ params, request }: LoaderFunctionArgs) {
  const tenantSlug = params.tenantSlug;
  const skuId = params.skuId;
  if (!tenantSlug || !skuId) throw new Response("Not found", { status: 404 });
  const currentUrl = new URL(request.url);
  const locale = normalizeStorefrontLocale(currentUrl.searchParams.get("lang"));
  try {
    const [store, sku] = await Promise.all([
      api.getStore(tenantSlug, locale),
      api.getStoreSku(tenantSlug, skuId, locale),
    ]);
    if (store.slug.toLocaleLowerCase() !== tenantSlug.toLocaleLowerCase()) {
      return redirect(
        `/${encodeURIComponent(store.slug)}/skus/${encodeURIComponent(sku.id)}${currentUrl.search}${currentUrl.hash}`,
      );
    }
    return { store, sku };
  }
  catch (error) {
    if (error instanceof ApiError && error.status === 422 && currentUrl.searchParams.has("lang")) {
      currentUrl.searchParams.delete("lang");
      const query = currentUrl.searchParams.toString();
      return redirect(
        `/${encodeURIComponent(tenantSlug)}/skus/${encodeURIComponent(skuId)}${query ? `?${query}` : ""}${currentUrl.hash}`,
      );
    }
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) throw new Response("Not found", { status: 404 });
    throw error;
  }
}

function LegacyStoreRedirect() {
  const { tenantSlug } = useParams();
  const location = useLocation();
  return tenantSlug ? <Navigate replace to={`/${encodeURIComponent(tenantSlug)}${location.search}${location.hash}`} /> : <Navigate to="/" replace />;
}

function StorefrontRouteError() {
  const error = useRouteError();
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  const staleBundle = isChunkLoadFailure(error);
  const message = staleBundle
    ? "页面资源已经更新，请重新加载最新版。"
    : error instanceof Error
    ? error.message
    : "商家前台暂时无法加载，请稍后重试。";

  useEffect(() => {
    if (!notFound && staleBundle) reloadLatestBundle();
  }, [notFound, staleBundle]);

  if (notFound) return <NotFoundPage />;

  return (
    <main className="not-found-page">
      <Brand />
      <div className="not-found-content">
        <ErrorState
          message={message}
          onRetry={() => staleBundle ? reloadLatestBundle(true) : window.location.reload()}
        />
      </div>
    </main>
  );
}

const router = createBrowserRouter([{
  element: <Outlet />,
  errorElement: <ApplicationRouteError />,
  children: [
  { path: "/", element: <LandingPage /> },
  { path: "/store/:tenantSlug", element: <LegacyStoreRedirect /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/login/callback", element: <Navigate to="/login" replace /> },
  { path: "/privacy", element: <PrivacyPage /> },
  {
    element: <ProtectedRoute />,
    children: [{
      element: <StaffConsoleRoute />,
      children: [{
      path: "/console",
      element: <ConsoleLayout />,
      children: [
        { index: true, element: <CoreDashboardPage /> },
        { path: "dashboard", element: <Navigate to="/console" replace /> },
        { path: "ai-search", element: <PermissionGate anyOf={["product.view"]}><AiSearchPage /></PermissionGate> },
        { path: "ai-search/manage", element: <PermissionGate anyOf={["product.view"]}><AiSearchManagementPage /></PermissionGate> },
        { path: "products", element: <PermissionGate anyOf={["product.view"]}><ProductsPage /></PermissionGate> },
        { path: "products/categories", element: <PermissionGate anyOf={["product.edit"]}><CategoriesPage /></PermissionGate> },
        { path: "products/tags", element: <PermissionGate anyOf={["product.edit"]}><TagManagementPage /></PermissionGate> },
        { path: "languages", element: <PermissionGate anyOf={["product.view"]}><LanguagePackagesPage /></PermissionGate> },
        { path: "inventory", element: <PermissionGate anyOf={["inventory.view"]}><InventoryPage /></PermissionGate> },
        { path: "products/review", element: <Navigate to="/console/products" replace /> },
        { path: "suppliers", element: <Navigate to="/console/products" replace /> },
        { path: "inquiries", element: <PermissionGate anyOf={["inquiry.view"]}><InquiryPage /></PermissionGate> },
        { path: "quotes", element: <PermissionGate anyOf={["quotation.view"]}><QuotesPage /></PermissionGate> },
        { path: "quote-templates", element: <PermissionGate anyOf={["quotation.create"]}><QuoteTemplatesPage /></PermissionGate> },
        { path: "customer-accounts", element: <PermissionGate anyOf={["customer_portal.subaccount_manage"]}><CustomerAccountsPage /></PermissionGate> },
        { path: "account", element: <AccountSettingsPage /> },
        { path: "personal-center", element: <PermissionGate anyOf={["support.settings_manage"]}><PersonalCenterPage /></PermissionGate> },
        { path: "system/monitoring", element: <PlatformAdminGate><SystemMonitoringPage /></PlatformAdminGate> },
        { path: "system/configuration", element: <PlatformAdminGate><ConfigurationCenterPage /></PlatformAdminGate> },
        { path: "system/translation", element: <Navigate to="/console/system/configuration?section=translation" replace /> },
        { path: "analytics", element: <PermissionGate anyOf={["analytics.view"]}><StorefrontAnalyticsPage /></PermissionGate> },
        { path: "announcements", element: <PermissionGate anyOf={["announcement.manage"]}><AnnouncementsPage /></PermissionGate> },
        { path: "support", element: <PermissionGate anyOf={["support.view"]}><SupportCenterPage /></PermissionGate> },
        { path: "agents", element: <PlatformAdminGate><SupportAIAgentsPage /></PlatformAdminGate> },
        { path: "agents/knowledge", element: <PlatformAdminGate><SupportAIKnowledgePage /></PlatformAdminGate> },
        { path: "agents/:agentId", element: <PlatformAdminGate><SupportAIAgentDetailPage /></PlatformAdminGate> },
        { path: "support/ai", element: <Navigate to="/console/agents" replace /> },
        { path: "skus", element: <Navigate to="/console/products" replace /> },
        { path: "review", element: <Navigate to="/console/products" replace /> },
        { path: "quotations", element: <Navigate to="/console/quotes" replace /> },
        { path: "tenants", element: <PlatformAdminGate><TenantManagementPage /></PlatformAdminGate> },
      ],
      }],
    }, {
      element: <CustomerPortalRoute />,
      children: [{ path: "/portal", element: <CustomerPortalPage /> }],
    }],
  },
  { path: "/dashboard", element: <Navigate to="/console" replace /> },
  { path: "/ai-search", element: <Navigate to="/console/ai-search" replace /> },
  { path: "/products", element: <Navigate to="/console/products" replace /> },
  { path: "/inventory", element: <Navigate to="/console/inventory" replace /> },
  { path: "/suppliers", element: <Navigate to="/console/products" replace /> },
  { path: "/review", element: <Navigate to="/console/products" replace /> },
  { path: "/inquiries", element: <Navigate to="/console/inquiries" replace /> },
  { path: "/quotations", element: <Navigate to="/console/quotes" replace /> },
  { path: "/account", element: <Navigate to="/console/account" replace /> },
  {
    path: "/:tenantSlug/products/:productId",
    loader: storefrontProductLoader,
    element: <ProductDetailPage />,
    errorElement: <StorefrontRouteError />,
  },
  {
    path: "/:tenantSlug/skus/:skuId",
    loader: storefrontSkuLoader,
    element: <SkuDetailPage />,
    errorElement: <StorefrontRouteError />,
  },
  {
    path: "/:tenantSlug",
    loader: storefrontLoader,
    element: <StorePage />,
    errorElement: <StorefrontRouteError />,
  },
  { path: "*", element: <NotFoundPage /> },
  ],
}]);

export function App() {
  const { t } = useLocale();
  return (
    <Suspense fallback={<div className="route-loading"><Spinner size="3" /><span>{t("正在加载页面")}</span></div>}>
      <RouterProvider router={router} />
    </Suspense>
  );
}
