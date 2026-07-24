import { Avatar, Badge, Button, DropdownMenu, Select, Text } from "@radix-ui/themes";
import {
  Buildings,
  CaretDown,
  CaretRight,
  ChartDonut,
  ChatCircleDots,
  Cube,
  DotsThreeOutline,
  FileText,
  Key,
  ShieldCheck,
  SignOut,
  Sparkle,
  Storefront as StoreIcon,
  UserGear,
} from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
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

const navigationGroups = [
  {
    label: "工作",
    items: [
      { to: "/console", label: "概览", mobileLabel: "概览", icon: ChartDonut, end: true, permissions: [], platformAdminOnly: false, mobilePrimary: true },
      { to: "/console/ai-search", label: "AI 搜索", mobileLabel: "AI 搜索", icon: Sparkle, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
  {
    label: "商品",
    items: [
      { to: "/console/products", label: "SKU 商品库", mobileLabel: "SKU", icon: Cube, end: true, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: true },
      { to: "/console/suppliers", label: "供应商", mobileLabel: "供应商", icon: Buildings, permissions: ["supplier.view", "supplier.manage"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/products/review", label: "待审核", mobileLabel: "审核", icon: ShieldCheck, permissions: ["product.review"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
  {
    label: "销售",
    items: [
      { to: "/console/inquiries", label: "询盘", mobileLabel: "询盘", icon: ChatCircleDots, permissions: ["inquiry.view"], platformAdminOnly: false, mobilePrimary: true },
      { to: "/console/quotes", label: "报价", mobileLabel: "报价", icon: FileText, permissions: ["quotation.view"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
  {
    label: "平台",
    items: [
      { to: "/console/tenants", label: "商家管理", mobileLabel: "商家", icon: StoreIcon, permissions: [], platformAdminOnly: true, mobilePrimary: false },
    ],
  },
  {
    label: "设置",
    items: [
      { to: "/console/system/permissions", label: "成员与权限", mobileLabel: "权限", icon: Key, permissions: ["system.user_manage", "system.role_manage"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
];

export function ConsoleLayout() {
  const { profile, memberships, status, switchTenant, hasAnyPermission, logout } = useCoreAuth();
  const location = useLocation();
  const [tenantError, setTenantError] = useState("");
  const activeMembershipId = profile?.context.membershipId ?? "";
  const activeTenantId = profile?.context.tenantId ?? "";
  const activeTenantSlug = profile?.context.tenantSlug ?? memberships.find((row) => row.id === activeMembershipId)?.tenantSlug ?? "";
  const displayName = profile?.user.displayName || profile?.user.email || "当前成员";
  const visibleGroups = navigationGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => (!item.platformAdminOnly || profile?.user.isPlatformAdmin) && (item.permissions.length === 0 || hasAnyPermission(...item.permissions))),
    }))
    .filter((group) => group.items.length);
  const visibleNavigation = visibleGroups.flatMap((group) => group.items);
  const mobilePrimary = visibleNavigation.filter((item) => item.mobilePrimary);
  const mobileMore = visibleNavigation.filter((item) => !item.mobilePrimary);
  const accessManagementVisible = visibleNavigation.some((item) => item.to === "/console/system/permissions");
  const mobileMoreActive = mobileMore.some((item) => location.pathname === item.to || location.pathname.startsWith(`${item.to}/`))
    || location.pathname.startsWith("/console/account")
    || location.pathname.startsWith("/console/system/permissions");
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
      <nav className="desktop-console-nav" aria-label="控制台导航">
        {visibleGroups.map((group) => <section className="nav-group" key={group.label}>
          <Text className="nav-group-label" size="1">{group.label}</Text>
          {group.items.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon size={20} weight="duotone" /><span>{label}</span></NavLink>)}
        </section>)}
      </nav>
      <nav className="mobile-console-nav" aria-label="移动端控制台导航">
        {mobilePrimary.map(({ to, mobileLabel, icon: Icon, end }) => <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon size={20} weight="duotone" /><span>{mobileLabel}</span></NavLink>)}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger>
            <button type="button" className={`nav-item mobile-more-trigger ${mobileMoreActive ? "active" : ""}`}><DotsThreeOutline size={20} weight="duotone" /><span>更多</span></button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Content align="end" sideOffset={10} className="mobile-more-content">
            {mobileMore.map(({ to, label, icon: Icon }) => <DropdownMenu.Item asChild key={to}><Link to={to}><Icon size={17} />{label}</Link></DropdownMenu.Item>)}
            <DropdownMenu.Separator />
            <DropdownMenu.Item asChild><Link to="/console/account"><UserGear size={17} />账户与安全</Link></DropdownMenu.Item>
            {!accessManagementVisible ? <DropdownMenu.Item asChild><Link to="/console/system/permissions"><Key size={17} />我的权限</Link></DropdownMenu.Item> : null}
            <DropdownMenu.Item asChild><Link to={storefrontPath}><StoreIcon size={17} />查看商品前台</Link></DropdownMenu.Item>
            <DropdownMenu.Separator />
            <DropdownMenu.Item color="red" onSelect={() => void logout()}><SignOut size={17} />退出登录</DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Root>
      </nav>
      <div className="sidebar-footer">
        <Link className="sidebar-account-card" to="/console/account">
          <Avatar fallback={initials(displayName)} radius="large" color="jade" />
          <span><Text size="2" weight="medium">{displayName}</Text><Text size="1" color="gray">账户与安全</Text></span>
          <CaretRight size={15} />
        </Link>
        <Button asChild variant="ghost" color="gray"><Link to={storefrontPath}><StoreIcon size={18} />查看商品前台</Link></Button>
      </div>
    </aside>

    <div className="console-main">
      <header className="console-topbar">
        <div className="mobile-brand"><Brand compact /></div>
        <div className="tenant-context"><div><Text size="1" color="gray" as="div">当前工作区</Text>{memberships.length > 1 ? <Select.Root value={activeMembershipId} disabled={status === "restoring"} onValueChange={(value) => void selectTenant(value)}><Select.Trigger className="tenant-select" placeholder="选择租户" /><Select.Content>{memberships.filter((membership) => membership.status.toUpperCase() === "ACTIVE").map((membership) => <Select.Item value={membership.id} key={membership.id}>{membership.tenantName}</Select.Item>)}</Select.Content></Select.Root> : <Text size="2" weight="medium">{profile?.context.tenantName ?? "当前租户"}</Text>}{tenantError ? <Text size="1" color="red">{tenantError}</Text> : null}</div></div>
        <div className="topbar-user">
          <ThemeToggle />
          {profile?.user.isPlatformAdmin ? <Badge color="amber">平台管理员</Badge> : null}
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              <Button className="account-menu-trigger" variant="ghost" color="gray" aria-label="打开账户菜单">
                <span className="user-copy"><Text size="2" weight="medium">{displayName}</Text><Text size="1" color="gray">{profile?.user.email || "安全会话"}</Text></span>
                <Avatar fallback={initials(displayName)} radius="large" color="jade" />
                <CaretDown className="account-menu-caret" size={14} aria-hidden="true" />
              </Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="end" className="account-menu-content">
              <DropdownMenu.Label>{displayName}</DropdownMenu.Label>
              <DropdownMenu.Item asChild><Link to="/console/account"><UserGear size={17} />账户与安全</Link></DropdownMenu.Item>
              <DropdownMenu.Item asChild><Link to="/console/system/permissions"><Key size={17} />{accessManagementVisible ? "成员与权限" : "我的权限"}</Link></DropdownMenu.Item>
              <DropdownMenu.Item asChild><Link to={storefrontPath}><StoreIcon size={17} />查看商品前台</Link></DropdownMenu.Item>
              <DropdownMenu.Separator />
              <DropdownMenu.Item color="red" onSelect={() => void logout()}><SignOut size={17} />退出登录</DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
      </header>
      <main className="console-content"><Outlet key={activeMembershipId} context={{ activeTenantId, activeTenant, reloadTenants } satisfies ConsoleOutletContext} /></main>
    </div>
  </div>;
}
