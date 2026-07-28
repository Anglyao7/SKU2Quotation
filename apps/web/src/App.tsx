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
import { lazy, Suspense, type ReactNode } from "react";
import { Brand } from "./components/Brand";
import { ErrorState } from "./components/States";
import { useCoreAuth } from "./core/AuthContext";
import { useLocale } from "./core/LocaleContext";
import { api, ApiError } from "./lib/api";
import { LoginPage } from "./pages/LoginPage";

const LandingPage = lazy(() => import("./pages/marketing/LandingPage").then((module) => ({ default: module.LandingPage })));
const StorePage = lazy(() => import("./pages/StorePage").then((module) => ({ default: module.StorePage })));
const SkuDetailPage = lazy(() => import("./pages/SkuDetailPage").then((module) => ({ default: module.SkuDetailPage })));
const PrivacyPage = lazy(() => import("./pages/PrivacyPage").then((module) => ({ default: module.PrivacyPage })));
const ConsoleLayout = lazy(() => import("./pages/console/ConsoleLayout").then((module) => ({ default: module.ConsoleLayout })));
const TenantManagementPage = lazy(() => import("./pages/console/TenantManagementPage").then((module) => ({ default: module.TenantManagementPage })));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })));
const AiSearchPage = lazy(() => import("./core/pages/AiSearchPage").then((module) => ({ default: module.AiSearchPage })));
const AiSearchManagementPage = lazy(() => import("./core/pages/AiSearchManagementPage").then((module) => ({ default: module.AiSearchManagementPage })));
const AccountSettingsPage = lazy(() => import("./core/pages/AccountSettingsPage").then((module) => ({ default: module.AccountSettingsPage })));
const CategoriesPage = lazy(() => import("./core/pages/CategoriesPage").then((module) => ({ default: module.CategoriesPage })));
const CoreDashboardPage = lazy(() => import("./core/pages/DashboardPage").then((module) => ({ default: module.CoreDashboardPage })));
const InquiryPage = lazy(() => import("./core/pages/InquiryPage").then((module) => ({ default: module.InquiryPage })));
const InventoryPage = lazy(() => import("./core/pages/InventoryPage").then((module) => ({ default: module.InventoryPage })));
const PermissionsPage = lazy(() => import("./core/pages/PermissionsPage").then((module) => ({ default: module.PermissionsPage })));
const ProductsPage = lazy(() => import("./core/pages/ProductsPage").then((module) => ({ default: module.ProductsPage })));
const QuotesPage = lazy(() => import("./core/pages/QuotesPage").then((module) => ({ default: module.QuotesPage })));
const TagManagementPage = lazy(() => import("./pages/console/TagManagementPage").then((module) => ({ default: module.TagManagementPage })));
const CustomerAccountsPage = lazy(() => import("./core/pages/CustomerAccountsPage").then((module) => ({ default: module.CustomerAccountsPage })));
const CustomerPortalPage = lazy(() => import("./pages/CustomerPortalPage").then((module) => ({ default: module.CustomerPortalPage })));

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
  return <div className="core-workspace"><Card className="core-state"><ShieldWarning size={36} /><Heading size="5">{t("当前成员没有此工作区权限")}</Heading><Text size="2" color="gray">{t("需要以下任一服务端权限：{permissions}", { permissions: anyOf.join(" / ") })}</Text><Button asChild variant="soft"><a href="/console/system/permissions">{t("查看我的权限")}</a></Button></Card></div>;
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
  try {
    const store = await api.getStore(tenantSlug);
    if (store.slug.toLocaleLowerCase() !== tenantSlug.toLocaleLowerCase()) {
      const currentUrl = new URL(request.url);
      return redirect(`/${encodeURIComponent(store.slug)}${currentUrl.search}${currentUrl.hash}`);
    }
    return store;
  }
  catch (error) {
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) throw new Response("Not found", { status: 404 });
    throw error;
  }
}

async function storefrontSkuLoader({ params }: LoaderFunctionArgs) {
  const tenantSlug = params.tenantSlug;
  const skuId = params.skuId;
  if (!tenantSlug || !skuId) throw new Response("Not found", { status: 404 });
  try {
    const store = await api.getStore(tenantSlug);
    const sku = await api.getStoreSku(store.slug, skuId);
    if (store.slug.toLocaleLowerCase() !== tenantSlug.toLocaleLowerCase()) {
      return redirect(
        `/${encodeURIComponent(store.slug)}/skus/${encodeURIComponent(sku.id)}`,
      );
    }
    return { store, sku };
  }
  catch (error) {
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
  if (isRouteErrorResponse(error) && error.status === 404) return <NotFoundPage />;
  const message = error instanceof Error ? error.message : "商家前台暂时无法加载，请稍后重试。";
  return <main className="not-found-page"><Brand /><div className="not-found-content"><ErrorState message={message} onRetry={() => window.location.reload()} /></div></main>;
}

const router = createBrowserRouter([
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
        { path: "inventory", element: <PermissionGate anyOf={["inventory.view"]}><InventoryPage /></PermissionGate> },
        { path: "products/review", element: <Navigate to="/console/products" replace /> },
        { path: "suppliers", element: <Navigate to="/console/products" replace /> },
        { path: "inquiries", element: <PermissionGate anyOf={["inquiry.view"]}><InquiryPage /></PermissionGate> },
        { path: "quotes", element: <PermissionGate anyOf={["quotation.view"]}><QuotesPage /></PermissionGate> },
        { path: "customer-accounts", element: <PermissionGate anyOf={["customer_portal.subaccount_manage"]}><CustomerAccountsPage /></PermissionGate> },
        { path: "account", element: <AccountSettingsPage /> },
        { path: "system/permissions", element: <PermissionsPage /> },
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
  { path: "/system/permissions", element: <Navigate to="/console/system/permissions" replace /> },
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
]);

export function App() {
  const { t } = useLocale();
  return (
    <Suspense fallback={<div className="route-loading"><Spinner size="3" /><span>{t("正在加载页面")}</span></div>}>
      <RouterProvider router={router} />
    </Suspense>
  );
}
