import { Avatar, Badge, Button, IconButton, Select, Text, Tooltip } from "@radix-ui/themes";
import { Buildings, CaretLeft, ChartDonut, ChatCircleDots, Cube, FileText, Key, ShieldCheck, SignOut, Sparkle, Storefront as StoreIcon } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { Brand } from "../../components/Brand";
import { ThemeToggle } from "../../components/ThemeToggle";
import { useCoreAuth } from "../../core/AuthContext";
import { initials } from "../../lib/format";
import type { Tenant } from "../../types";

export interface ConsoleOutletContext {
  activeTenantId: string;
  activeTenant?: Tenant;
  reloadTenants: () => Promise<void>;
}

const navigation = [
  { to: "/console", label: "仪表盘", icon: ChartDonut, end: true, permissions: [], platformAdminOnly: false },
  { to: "/console/tenants", label: "商家管理", icon: StoreIcon, permissions: [], platformAdminOnly: true },
  { to: "/console/ai-search", label: "AI 搜索", icon: Sparkle, permissions: ["product.view", "inquiry.view"], platformAdminOnly: false },
  { to: "/console/products", label: "产品中心", icon: Cube, permissions: ["product.view", "product.edit", "product.review"], platformAdminOnly: false },
  { to: "/console/suppliers", label: "供应网络", icon: Buildings, permissions: ["supplier.view", "supplier.manage", "product.import"], platformAdminOnly: false },
  { to: "/console/products/review", label: "产品审核", icon: ShieldCheck, permissions: ["product.review"], platformAdminOnly: false },
  { to: "/console/inquiries", label: "询盘工作台", icon: ChatCircleDots, permissions: ["inquiry.view"], platformAdminOnly: false },
  { to: "/console/quotes", label: "报价工作台", icon: FileText, permissions: ["quotation.view"], platformAdminOnly: false },
  { to: "/console/system/permissions", label: "我的权限", icon: Key, permissions: [], platformAdminOnly: false },
];

export function ConsoleLayout() {
  const { profile, memberships, permissions, status, switchTenant, hasAnyPermission, logout } = useCoreAuth();
  const [tenantError, setTenantError] = useState("");
  const activeMembershipId = profile?.context.membershipId ?? "";
  const activeTenantId = profile?.context.tenantId ?? "";
  const activeTenantSlug = profile?.context.tenantSlug ?? memberships.find((row) => row.id === activeMembershipId)?.tenantSlug ?? "";
  const displayName = profile?.user.displayName || profile?.user.email || "当前成员";
  const visibleNavigation = navigation.filter((item) => (!item.platformAdminOnly || profile?.user.isPlatformAdmin) && (item.permissions.length === 0 || hasAnyPermission(...item.permissions)));
  const storefrontPath = activeTenantSlug ? `/${encodeURIComponent(activeTenantSlug)}` : "/";
  const activeTenant = useMemo<Tenant | undefined>(() => activeTenantId ? { id: activeTenantId, name: profile?.context.tenantName ?? "当前工作区", slug: activeTenantSlug, active: true, status: "active" } : undefined, [activeTenantId, activeTenantSlug, profile?.context.tenantName]);

  const selectTenant = async (membershipId: string) => {
    if (membershipId === activeMembershipId) return;
    setTenantError("");
    try { await switchTenant(membershipId); }
    catch (caught) { setTenantError(caught instanceof Error ? caught.message : "工作区切换失败"); }
  };
  const reloadTenants = async () => undefined;

  return <div className="console-shell">
    <aside className="console-sidebar">
      <div className="sidebar-brand"><Brand /></div>
      <nav className="console-nav" aria-label="控制台导航">{visibleNavigation.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon size={20} weight="duotone" /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-footer"><Button asChild variant="ghost" color="gray"><Link to={storefrontPath}><StoreIcon size={18} />查看商品前台</Link></Button><Button variant="ghost" color="gray" onClick={() => void logout()}><SignOut size={18} />退出登录</Button></div>
    </aside>

    <div className="console-main">
      <header className="console-topbar">
        <div className="mobile-brand"><Brand compact /></div>
        <div className="tenant-context"><div><Text size="1" color="gray" as="div">当前工作区</Text>{memberships.length > 1 ? <Select.Root value={activeMembershipId} disabled={status === "restoring"} onValueChange={(value) => void selectTenant(value)}><Select.Trigger className="tenant-select" placeholder="选择租户" /><Select.Content>{memberships.filter((membership) => membership.status.toUpperCase() === "ACTIVE").map((membership) => <Select.Item value={membership.id} key={membership.id}>{membership.tenantName}</Select.Item>)}</Select.Content></Select.Root> : <Text size="2" weight="medium">{profile?.context.tenantName ?? "当前租户"}</Text>}{tenantError ? <Text size="1" color="red">{tenantError}</Text> : null}</div></div>
        <div className="topbar-user"><ThemeToggle /><Badge color={profile?.user.isPlatformAdmin ? "amber" : "gray"}>{profile?.user.isPlatformAdmin ? "平台管理员" : `${permissions.size} 项权限`}</Badge><div className="user-copy"><Text size="2" weight="medium">{displayName}</Text><Text size="1" color="gray">{profile?.user.email || "安全会话"}</Text></div><Avatar fallback={initials(displayName)} radius="large" color="jade" /><Tooltip content="返回当前商家前台"><IconButton asChild variant="ghost" color="gray"><Link to={storefrontPath} aria-label="返回当前商家前台"><CaretLeft size={18} /></Link></IconButton></Tooltip></div>
      </header>
      <main className="console-content"><Outlet key={activeMembershipId} context={{ activeTenantId, activeTenant, reloadTenants } satisfies ConsoleOutletContext} /></main>
    </div>
  </div>;
}
