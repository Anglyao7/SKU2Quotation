import { AlertDialog, Avatar, Badge, Button, DropdownMenu, Select, Text } from "@radix-ui/themes";
import {
  CaretDown,
  CaretRight,
  ChartDonut,
  ChatCircleDots,
  Check,
  Cube,
  Database,
  DotsThreeOutline,
  FileText,
  GlobeHemisphereWest,
  Key,
  SignOut,
  Sparkle,
  Storefront as StoreIcon,
  Translate,
  TreeStructure,
  UserGear,
  Warehouse,
} from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { Brand } from "../../components/Brand";
import { ThemeToggle } from "../../components/ThemeToggle";
import { useCoreAuth } from "../../core/AuthContext";
import { updateMerchantSettings } from "../../core/api";
import { useLocale } from "../../core/LocaleContext";
import { initials } from "../../lib/format";
import type { BusinessMode, UiLocale } from "../../core/types";
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
      { to: "/console/ai-search", label: "AI 搜索", mobileLabel: "AI 搜索", icon: Sparkle, end: true, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/ai-search/manage", label: "AI 搜索管理", mobileLabel: "搜索管理", icon: Database, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
  {
    label: "商品",
    items: [
      { to: "/console/products", label: "SKU 商品库", mobileLabel: "SKU", icon: Cube, end: true, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: true },
      { to: "/console/products/categories", label: "分类管理", mobileLabel: "分类", icon: TreeStructure, permissions: ["product.edit"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
  {
    label: "经营",
    items: [
      { to: "/console/inventory", label: "进销存", mobileLabel: "库存", icon: Warehouse, permissions: ["inventory.view"], platformAdminOnly: false, mobilePrimary: true },
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
  const {
    profile,
    memberships,
    status,
    switchTenant,
    hasPermission,
    hasAnyPermission,
    logout,
    reloadProfile,
  } = useCoreAuth();
  const { locale, setLocale, t } = useLocale();
  const location = useLocation();
  const [tenantError, setTenantError] = useState("");
  const [modeDialogOpen, setModeDialogOpen] = useState(false);
  const [modeBusy, setModeBusy] = useState(false);
  const [toolbarError, setToolbarError] = useState("");
  const activeMembershipId = profile?.context.membershipId ?? "";
  const activeTenantId = profile?.context.tenantId ?? "";
  const activeTenantSlug = profile?.context.tenantSlug ?? memberships.find((row) => row.id === activeMembershipId)?.tenantSlug ?? "";
  const displayName = profile?.user.displayName || profile?.user.email || t("当前成员");
  const businessMode = profile?.context.businessMode ?? "DOMESTIC";
  const nextBusinessMode: BusinessMode = businessMode === "EXPORT" ? "DOMESTIC" : "EXPORT";
  const canManageSettings = hasPermission("system.settings_manage");
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
  const activeTenant = useMemo<Tenant | undefined>(() => activeTenantId ? { id: activeTenantId, name: profile?.context.tenantName ?? t("当前工作区"), slug: activeTenantSlug, active: true, status: "active" } : undefined, [activeTenantId, activeTenantSlug, profile?.context.tenantName, t]);

  const selectTenant = async (membershipId: string) => {
    if (membershipId === activeMembershipId) return;
    setTenantError("");
    try { await switchTenant(membershipId); }
    catch (caught) { setTenantError(caught instanceof Error ? caught.message : t("工作区切换失败")); }
  };
  const reloadTenants = async () => undefined;

  const switchBusinessMode = async () => {
    if (!canManageSettings || modeBusy) return;
    setModeBusy(true);
    setToolbarError("");
    try {
      await updateMerchantSettings({ businessMode: nextBusinessMode });
      await reloadProfile();
      window.dispatchEvent(
        new CustomEvent("atc:merchant-settings-changed", {
          detail: { businessMode: nextBusinessMode },
        }),
      );
      setModeDialogOpen(false);
    } catch {
      setToolbarError(t("业务版本切换失败，请稍后重试。"));
    } finally {
      setModeBusy(false);
    }
  };

  const changeLanguage = async (nextLocale: UiLocale) => {
    setToolbarError("");
    try {
      await setLocale(nextLocale);
    } catch {
      setToolbarError(t("语言设置保存失败，请稍后重试。"));
    }
  };

  return <div className="console-shell">
    <aside className="console-sidebar">
      <div className="sidebar-brand"><Brand /></div>
      <nav className="desktop-console-nav" aria-label={t("控制台导航")}>
        {visibleGroups.map((group) => <section className="nav-group" key={group.label}>
          <Text className="nav-group-label" size="1">{t(group.label)}</Text>
          {group.items.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon size={20} weight="duotone" /><span>{t(label)}</span></NavLink>)}
        </section>)}
      </nav>
      <nav className="mobile-console-nav" aria-label={t("移动端控制台导航")}>
        {mobilePrimary.map(({ to, mobileLabel, icon: Icon, end }) => <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon size={20} weight="duotone" /><span>{t(mobileLabel)}</span></NavLink>)}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger>
            <button type="button" className={`nav-item mobile-more-trigger ${mobileMoreActive ? "active" : ""}`}><DotsThreeOutline size={20} weight="duotone" /><span>{t("更多")}</span></button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Content align="end" sideOffset={10} className="mobile-more-content">
            {mobileMore.map(({ to, label, icon: Icon }) => <DropdownMenu.Item asChild key={to}><Link to={to}><Icon size={17} />{t(label)}</Link></DropdownMenu.Item>)}
            <DropdownMenu.Separator />
            <DropdownMenu.Item asChild><Link to="/console/account"><UserGear size={17} />{t("账户与安全")}</Link></DropdownMenu.Item>
            {!accessManagementVisible ? <DropdownMenu.Item asChild><Link to="/console/system/permissions"><Key size={17} />{t("我的权限")}</Link></DropdownMenu.Item> : null}
            <DropdownMenu.Item asChild><Link to={storefrontPath}><StoreIcon size={17} />{t("查看商品前台")}</Link></DropdownMenu.Item>
            <DropdownMenu.Separator />
            <DropdownMenu.Item color="red" onSelect={() => void logout()}><SignOut size={17} />{t("退出登录")}</DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Root>
      </nav>
      <div className="sidebar-footer">
        <Link className="sidebar-account-card" to="/console/account">
          <Avatar fallback={initials(displayName)} radius="large" color="jade" />
          <span><Text size="2" weight="medium">{displayName}</Text><Text size="1" color="gray">{t("账户与安全")}</Text></span>
          <CaretRight size={15} />
        </Link>
        <Button asChild variant="ghost" color="gray"><Link to={storefrontPath}><StoreIcon size={18} />{t("查看商品前台")}</Link></Button>
      </div>
    </aside>

    <div className="console-main">
      <header className="console-topbar">
        <div className="mobile-brand"><Brand compact /></div>
        <div className="tenant-context"><div><Text size="1" color="gray" as="div">{t("当前工作区")}</Text>{memberships.length > 1 ? <Select.Root value={activeMembershipId} disabled={status === "restoring"} onValueChange={(value) => void selectTenant(value)}><Select.Trigger className="tenant-select" placeholder={t("选择租户")} /><Select.Content>{memberships.filter((membership) => membership.status.toUpperCase() === "ACTIVE").map((membership) => <Select.Item value={membership.id} key={membership.id}>{membership.tenantName}</Select.Item>)}</Select.Content></Select.Root> : <Text size="2" weight="medium">{profile?.context.tenantName ?? t("当前租户")}</Text>}{tenantError ? <Text size="1" color="red">{tenantError}</Text> : null}</div></div>
        <div className="topbar-user">
          <Button
            className={`business-mode-trigger ${businessMode === "EXPORT" ? "export" : ""}`}
            variant="soft"
            color={businessMode === "EXPORT" ? "amber" : "gray"}
            aria-label={t("切换业务版本")}
            title={!canManageSettings
              ? t("当前成员没有修改商家设置的权限。")
              : t(businessMode === "EXPORT" ? "外贸版 · USD" : "内贸版 · CNY")}
            disabled={!canManageSettings || modeBusy}
            onClick={() => setModeDialogOpen(true)}
          >
            <GlobeHemisphereWest size={17} weight="duotone" />
            <span>{t(businessMode === "EXPORT" ? "外贸版 · USD" : "内贸版 · CNY")}</span>
          </Button>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              <Button className="locale-trigger" variant="ghost" color="gray" aria-label={t("切换语言")} title={t("切换语言")}>
                <Translate size={18} />
                <span>{locale === "en-US" ? "EN" : "中"}</span>
              </Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="end" className="locale-menu-content">
              <DropdownMenu.Item onSelect={() => void changeLanguage("zh-CN")}>
                <span className="locale-check">{locale === "zh-CN" ? <Check size={15} /> : null}</span>
                简体中文
              </DropdownMenu.Item>
              <DropdownMenu.Item onSelect={() => void changeLanguage("en-US")}>
                <span className="locale-check">{locale === "en-US" ? <Check size={15} /> : null}</span>
                English
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
          <ThemeToggle />
          {profile?.user.isPlatformAdmin ? <Badge className="platform-admin-badge" color="amber">{t("平台管理员")}</Badge> : null}
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              <Button className="account-menu-trigger" variant="ghost" color="gray" aria-label={t("打开账户菜单")}>
                <span className="user-copy"><Text size="2" weight="medium">{displayName}</Text><Text size="1" color="gray">{profile?.user.email || t("安全会话")}</Text></span>
                <Avatar fallback={initials(displayName)} radius="large" color="jade" />
                <CaretDown className="account-menu-caret" size={14} aria-hidden="true" />
              </Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="end" className="account-menu-content">
              <DropdownMenu.Label>
                <div className="account-menu-header">
                  <span>
                    <Text size="2" weight="medium">{displayName}</Text>
                    <Text size="1" color="gray">{profile?.user.email || t("安全会话")}</Text>
                  </span>
                  {profile?.user.isPlatformAdmin ? <Badge color="amber">{t("平台管理员")}</Badge> : null}
                </div>
              </DropdownMenu.Label>
              <DropdownMenu.Item asChild><Link to="/console/account"><UserGear size={17} />{t("账户与安全")}</Link></DropdownMenu.Item>
              <DropdownMenu.Item asChild><Link to="/console/system/permissions"><Key size={17} />{t(accessManagementVisible ? "成员与权限" : "我的权限")}</Link></DropdownMenu.Item>
              <DropdownMenu.Item asChild><Link to={storefrontPath}><StoreIcon size={17} />{t("查看商品前台")}</Link></DropdownMenu.Item>
              <DropdownMenu.Separator />
              <DropdownMenu.Item color="red" onSelect={() => void logout()}><SignOut size={17} />{t("退出登录")}</DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
      </header>
      {toolbarError ? <div className="console-toolbar-error" role="alert">{toolbarError}</div> : null}
      <main className="console-content"><Outlet key={activeMembershipId} context={{ activeTenantId, activeTenant, reloadTenants } satisfies ConsoleOutletContext} /></main>
    </div>
    <AlertDialog.Root open={modeDialogOpen} onOpenChange={setModeDialogOpen}>
      <AlertDialog.Content className="business-mode-dialog">
        <AlertDialog.Title>{t(nextBusinessMode === "EXPORT" ? "切换至外贸版" : "切换至内贸版")}</AlertDialog.Title>
        <AlertDialog.Description>
          {t(nextBusinessMode === "EXPORT"
            ? "外贸版默认以 USD 处理新导入商品、采购、销售与报价。已有历史金额不会被重新换算。"
            : "内贸版默认以 CNY 处理新业务。已有 USD 仓库和历史单据会继续保留。")}
        </AlertDialog.Description>
        <div className="business-mode-note">
          <GlobeHemisphereWest size={20} weight="duotone" />
          <Text size="2">{t("系统会自动切换到对应币种的默认仓库；若不存在，将创建一个空仓库。")}</Text>
        </div>
        {toolbarError ? <Text size="2" color="red" role="alert">{toolbarError}</Text> : null}
        <div className="core-dialog-actions">
          <AlertDialog.Cancel><Button variant="soft" color="gray" disabled={modeBusy}>{t("取消")}</Button></AlertDialog.Cancel>
          <Button onClick={() => void switchBusinessMode()} loading={modeBusy}>
            {t(modeBusy ? "正在切换" : "确认切换")}
          </Button>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>
  </div>;
}
