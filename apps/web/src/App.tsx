import { Button, Card, Heading, Spinner, Text } from "@radix-ui/themes";
import { ShieldWarning } from "@phosphor-icons/react";
import {
  Navigate,
  Outlet,
  RouterProvider,
  createBrowserRouter,
  isRouteErrorResponse,
  useLocation,
  useParams,
  useRouteError,
  type LoaderFunctionArgs,
} from "react-router-dom";
import type { ReactNode } from "react";
import { Brand } from "./components/Brand";
import { ErrorState } from "./components/States";
import { useCoreAuth } from "./core/AuthContext";
import { AiSearchPage } from "./core/pages/AiSearchPage";
import { AccountSettingsPage } from "./core/pages/AccountSettingsPage";
import { CoreDashboardPage } from "./core/pages/DashboardPage";
import { InquiryPage } from "./core/pages/InquiryPage";
import { PermissionsPage } from "./core/pages/PermissionsPage";
import { ProductsPage } from "./core/pages/ProductsPage";
import { QuotesPage } from "./core/pages/QuotesPage";
import { ReviewPage } from "./core/pages/ReviewPage";
import { SuppliersPage } from "./core/pages/SuppliersPage";
import { api, ApiError } from "./lib/api";
import { LandingPage } from "./pages/marketing/LandingPage";
import { StorePage } from "./pages/StorePage";
import { LoginPage } from "./pages/LoginPage";
import { PrivacyPage } from "./pages/PrivacyPage";
import { ConsoleLayout } from "./pages/console/ConsoleLayout";
import { TenantManagementPage } from "./pages/console/TenantManagementPage";
import { NotFoundPage } from "./pages/NotFoundPage";

function ProtectedRoute() {
  const { status } = useCoreAuth();
  const location = useLocation();
  if (status === "restoring") return <div className="route-loading"><Spinner size="3" /><span>正在恢复安全会话</span></div>;
  if (status !== "authenticated") return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <Outlet />;
}

function PermissionGate({ anyOf, children }: { anyOf: string[]; children: ReactNode }) {
  const { hasAnyPermission } = useCoreAuth();
  if (hasAnyPermission(...anyOf)) return children;
  return <div className="core-workspace"><Card className="core-state"><ShieldWarning size={36} /><Heading size="5">当前成员没有此工作区权限</Heading><Text size="2" color="gray">需要以下任一服务端权限：{anyOf.join("、")}</Text><Button asChild variant="soft"><a href="/console/system/permissions">查看我的权限</a></Button></Card></div>;
}

function PlatformAdminGate({ children }: { children: ReactNode }) {
  const { profile } = useCoreAuth();
  if (profile?.user.isPlatformAdmin) return children;
  return <div className="core-workspace"><Card className="core-state"><ShieldWarning size={36} /><Heading size="5">仅平台管理员可以管理商家</Heading><Text size="2" color="gray">租户创建、启停和平台级状态不属于商家成员权限。</Text><Button asChild variant="soft"><a href="/console">返回仪表盘</a></Button></Card></div>;
}

async function storefrontLoader({ params }: LoaderFunctionArgs) {
  const tenantSlug = params.tenantSlug;
  if (!tenantSlug) throw new Response("Not found", { status: 404 });
  try { return await api.getStore(tenantSlug); }
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
      path: "/console",
      element: <ConsoleLayout />,
      children: [
        { index: true, element: <CoreDashboardPage /> },
        { path: "dashboard", element: <Navigate to="/console" replace /> },
        { path: "ai-search", element: <PermissionGate anyOf={["product.view"]}><AiSearchPage /></PermissionGate> },
        { path: "products", element: <PermissionGate anyOf={["product.view"]}><ProductsPage /></PermissionGate> },
        { path: "products/review", element: <PermissionGate anyOf={["product.review"]}><ReviewPage /></PermissionGate> },
        { path: "suppliers", element: <PermissionGate anyOf={["supplier.view", "supplier.manage"]}><SuppliersPage /></PermissionGate> },
        { path: "inquiries", element: <PermissionGate anyOf={["inquiry.view"]}><InquiryPage /></PermissionGate> },
        { path: "quotes", element: <PermissionGate anyOf={["quotation.view"]}><QuotesPage /></PermissionGate> },
        { path: "account", element: <AccountSettingsPage /> },
        { path: "system/permissions", element: <PermissionsPage /> },
        { path: "skus", element: <Navigate to="/console/products" replace /> },
        { path: "review", element: <Navigate to="/console/products/review" replace /> },
        { path: "quotations", element: <Navigate to="/console/quotes" replace /> },
        { path: "tenants", element: <PlatformAdminGate><TenantManagementPage /></PlatformAdminGate> },
      ],
    }],
  },
  { path: "/dashboard", element: <Navigate to="/console" replace /> },
  { path: "/ai-search", element: <Navigate to="/console/ai-search" replace /> },
  { path: "/products", element: <Navigate to="/console/products" replace /> },
  { path: "/suppliers", element: <Navigate to="/console/suppliers" replace /> },
  { path: "/review", element: <Navigate to="/console/products/review" replace /> },
  { path: "/inquiries", element: <Navigate to="/console/inquiries" replace /> },
  { path: "/quotations", element: <Navigate to="/console/quotes" replace /> },
  { path: "/account", element: <Navigate to="/console/account" replace /> },
  { path: "/system/permissions", element: <Navigate to="/console/system/permissions" replace /> },
  {
    path: "/:tenantSlug",
    loader: storefrontLoader,
    element: <StorePage />,
    errorElement: <StorefrontRouteError />,
  },
  { path: "*", element: <NotFoundPage /> },
]);

export function App() { return <RouterProvider router={router} />; }
