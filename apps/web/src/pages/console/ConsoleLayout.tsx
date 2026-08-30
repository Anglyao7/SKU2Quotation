import { AlertDialog, Avatar, Badge, Button, DropdownMenu, Select, Text, TextField } from "@radix-ui/themes";
import {
  CaretDown,
  CaretRight,
  ChartDonut,
  ChartLineUp,
  ChatCircleDots,
  Check,
  Cube,
  Database,
  DotsThreeOutline,
  FileText,
  FileXls,
  Factory,
  GlobeHemisphereWest,
  Headset,
  IdentificationCard,
  ImageSquare,
  Megaphone,
  Pulse,
  Robot,
  SignOut,
  SlidersHorizontal,
  Sparkle,
  Storefront as StoreIcon,
  Tag,
  Translate,
  TreeStructure,
  UserCircle,
  UserGear,
  UsersThree,
  Warehouse,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Brand } from "../../components/Brand";
import { ThemeToggle } from "../../components/ThemeToggle";
import { SupportNotificationBell } from "../../core/components/SupportNotificationBell";
import { useCoreAuth } from "../../core/AuthContext";
import { listPublicQuoteDrafts, updateMerchantSettings } from "../../core/api";
import { preloadConsoleRoute } from "../../core/routePreload";
import { useLocale } from "../../core/LocaleContext";
import { pollingBackoffMs } from "../../core/pollingBackoff";
import { initials } from "../../lib/format";
import { storefrontAccountKey, storefrontBasePath } from "../../lib/storefrontAccount";
import {
  SUBSCRIPTION_TIER_PRESENTATION,
  subscriptionTierLabel,
} from "../../lib/subscriptionTier";
import type { UiLocale } from "../../core/types";
import type { Tenant, TenantSubscriptionTier } from "../../types";

export interface ConsoleOutletContext {
  activeTenantId: string;
  activeTenant?: Tenant;
  reloadTenants: () => Promise<void>;
}

const navigationGroups = [
  {
    key: "workspace",
    label: "工作",
    icon: ChartDonut,
    items: [
      { to: "/console", label: "概览", mobileLabel: "概览", icon: ChartDonut, end: true, permissions: [], platformAdminOnly: false, mobilePrimary: true },
      { to: "/console/analytics", label: "网站监测", mobileLabel: "网站监测", icon: ChartLineUp, permissions: ["analytics.view"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/ai-search", label: "AI 搜索", mobileLabel: "AI 搜索", icon: Sparkle, end: true, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/ai-search/manage", label: "AI 搜索管理", mobileLabel: "搜索管理", icon: Database, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/image-search/manage", label: "图片搜索管理", mobileLabel: "图搜管理", icon: ImageSquare, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
  {
    key: "products",
    label: "商品",
    icon: Cube,
    items: [
      { to: "/console/products", label: "SKU 商品库", mobileLabel: "SKU", icon: Cube, end: true, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: true },
      { to: "/console/products/categories", label: "分类管理", mobileLabel: "分类", icon: TreeStructure, permissions: ["product.edit"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/products/tags", label: "标签管理", mobileLabel: "标签", icon: Tag, permissions: ["product.edit"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/languages", label: "多语言", mobileLabel: "语言", icon: Translate, permissions: ["product.view"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
  {
    key: "operations",
    label: "经营",
    icon: Warehouse,
    items: [
      { to: "/console/inventory", label: "进销存", mobileLabel: "库存", icon: Warehouse, permissions: ["inventory.view"], platformAdminOnly: false, mobilePrimary: true },
      { to: "/console/supply-chain", label: "供应链", mobileLabel: "供应链", icon: Factory, permissions: ["supplier.view", "supplier.manage"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/storefront", label: "前台管理", mobileLabel: "前台", icon: StoreIcon, permissions: ["system.settings_manage"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/announcements", label: "公告管理", mobileLabel: "公告", icon: Megaphone, permissions: ["announcement.manage"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/support", label: "客服管理", mobileLabel: "客服", icon: Headset, end: true, permissions: ["support.view"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
  {
    key: "sales",
    label: "销售",
    icon: FileText,
    items: [
      { to: "/console/inquiries", label: "询盘", mobileLabel: "询盘", icon: ChatCircleDots, permissions: ["inquiry.view"], platformAdminOnly: false, mobilePrimary: true },
      { to: "/console/quotes", label: "报价", mobileLabel: "报价", icon: FileText, permissions: ["quotation.view"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/quote-templates", label: "报价模板", mobileLabel: "模板", icon: FileXls, permissions: ["quotation.create"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
  {
    key: "agents",
    label: "智能体管理",
    icon: Robot,
    items: [
      { to: "/console/agents", label: "智能体列表", mobileLabel: "智能体", icon: Robot, end: true, permissions: [], platformAdminOnly: true, mobilePrimary: false },
      { to: "/console/agents/knowledge", label: "知识库管理", mobileLabel: "知识库", icon: Database, permissions: [], platformAdminOnly: true, mobilePrimary: false },
    ],
  },
  {
    key: "platform",
    label: "平台",
    icon: StoreIcon,
    items: [
      { to: "/console/tenants", label: "商家管理", mobileLabel: "商家", icon: StoreIcon, permissions: [], platformAdminOnly: true, mobilePrimary: false },
      { to: "/console/identities", label: "身份管理", mobileLabel: "身份", icon: IdentificationCard, permissions: [], platformAdminOnly: true, mobilePrimary: false },
      { to: "/console/system/monitoring", label: "系统监控", mobileLabel: "监控", icon: Pulse, permissions: [], platformAdminOnly: true, mobilePrimary: false },
      { to: "/console/system/usage", label: "数据监控", mobileLabel: "数据", icon: ChartLineUp, permissions: [], platformAdminOnly: true, mobilePrimary: false },
      { to: "/console/system/configuration", label: "配置中心", mobileLabel: "配置", icon: SlidersHorizontal, permissions: [], platformAdminOnly: true, mobilePrimary: false },
    ],
  },
  {
    key: "settings",
    label: "设置",
    icon: UserGear,
    items: [
      { to: "/console/personal-center", label: "个人中心", mobileLabel: "我的", icon: UserCircle, permissions: ["support.settings_manage"], platformAdminOnly: false, mobilePrimary: false },
      { to: "/console/customer-accounts", label: "子账号管理", mobileLabel: "子账号", icon: UsersThree, permissions: ["customer_portal.subaccount_manage"], platformAdminOnly: false, mobilePrimary: false },
    ],
  },
];

const COMMON_CURRENCIES = [
  "CNY", "USD", "EUR", "GBP", "JPY", "KRW", "HKD", "SGD",
  "CAD", "AUD", "CHF", "AED", "SAR", "TRY", "BRL", "MXN",
] as const;

function navigationItemIsActive(
  pathname: string,
  item: { to: string; end?: boolean },
) {
  if (item.end) return pathname === item.to;
  return pathname === item.to || pathname.startsWith(`${item.to}/`);
}

function initialNavigationGroup(pathname: string) {
  if (pathname.startsWith("/console/account")) return "settings";
  if (pathname.startsWith("/console/agents/")) return "agents";
  return navigationGroups.find((group) =>
    group.items.some((item) => navigationItemIsActive(pathname, item)))?.key ?? "workspace";
}

type GreetingKey = "早上好" | "下午好" | "晚上好";

function greetingKeyForHour(hour: number): GreetingKey {
  if (hour < 12) return "早上好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

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
  const navigate = useNavigate();
  const [tenantError, setTenantError] = useState("");
  const [modeDialogOpen, setModeDialogOpen] = useState(false);
  const [modeBusy, setModeBusy] = useState(false);
  const [currencyPreset, setCurrencyPreset] = useState("CNY");
  const [customCurrency, setCustomCurrency] = useState("");
  const [toolbarError, setToolbarError] = useState("");
  const [pendingInquiryCount, setPendingInquiryCount] = useState(0);
  const [newInquiryNotice, setNewInquiryNotice] = useState<{ count: number; customers: string[] }>();
  const [greetingKey, setGreetingKey] = useState<GreetingKey>(() => (
    greetingKeyForHour(new Date().getHours())
  ));
  const [expandedNavigationGroups, setExpandedNavigationGroups] = useState<Set<string>>(
    () => new Set([initialNavigationGroup(location.pathname)]),
  );
  const activeMembershipId = profile?.context.membershipId ?? "";
  const activeTenantId = profile?.context.tenantId ?? "";
  const activeTenantSlug = profile?.context.tenantSlug ?? memberships.find((row) => row.id === activeMembershipId)?.tenantSlug ?? "";
  const displayName = profile?.user.displayName || profile?.user.email || t("当前成员");
  const defaultCurrency = (profile?.context.defaultCurrency ?? "CNY").toUpperCase();
  const businessMode = defaultCurrency === "CNY" ? "DOMESTIC" : "EXPORT";
  const subscriptionTier: TenantSubscriptionTier = profile?.context.subscriptionTier ?? "TRIAL";
  const subscriptionPresentation = SUBSCRIPTION_TIER_PRESENTATION[subscriptionTier];
  const canManageSettings = hasPermission("system.settings_manage");
  const canViewSalesInbox = hasAnyPermission("inquiry.view", "quotation.view");
  const isCustomerSubaccount = profile?.context.accountScope === "CUSTOMER_SUBACCOUNT";
  const visibleGroups = navigationGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => (
        // A child account is an operator, not a guest: it receives the same
        // workspace navigation as the parent. Only owner-only relationship
        // management remains hidden; sensitive product fields are redacted by
        // the API response rather than by removing the whole module.
        (!item.platformAdminOnly || profile?.user.isPlatformAdmin)
        && (
          item.permissions.length === 0
          || hasAnyPermission(...item.permissions)
          || (isCustomerSubaccount && item.to === "/console/products" && hasPermission("customer_portal.access"))
          || (isCustomerSubaccount && item.to === "/console/quotes" && hasPermission("customer_portal.order_view_self"))
        )
        // Supplier relationships are internal to the owner workspace. A child
        // account must not receive this navigation item; the API applies the
        // same permission boundary server-side.
        && !(isCustomerSubaccount && (
          item.to === "/console/supply-chain"
          || item.to === "/console/customer-accounts"
        ))
      )),
    }))
    .filter((group) => group.items.length);
  const visibleNavigation = visibleGroups.flatMap((group) => group.items);
  const activeNavigationGroup = visibleGroups.find((group) =>
    group.items.some((item) => navigationItemIsActive(location.pathname, item)))?.key
    ?? (location.pathname.startsWith("/console/agents/") ? "agents" : null)
    ?? (location.pathname.startsWith("/console/account") ? "settings" : null);
  const mobilePrimary = visibleNavigation.filter((item) => item.mobilePrimary);
  const mobileMore = visibleNavigation.filter((item) => !item.mobilePrimary);
  const mobileMoreActive = mobileMore.some((item) => location.pathname === item.to || location.pathname.startsWith(`${item.to}/`))
    || location.pathname.startsWith("/console/account");
  const storefrontPath = activeTenantSlug
    ? storefrontBasePath(
        activeTenantSlug,
        isCustomerSubaccount && activeMembershipId
          ? storefrontAccountKey(displayName, activeMembershipId)
          : undefined,
      )
    : "/";
  const activeTenant = useMemo<Tenant | undefined>(() => activeTenantId ? {
    id: activeTenantId,
    name: profile?.context.tenantName ?? t("当前工作区"),
    slug: activeTenantSlug,
    active: true,
    status: "active",
    subscription_tier: subscriptionTier,
    subscription_started_at: "",
    subscription_expires_at: "",
    subscription_status: "active",
    sku_limit: subscriptionTier === "ELITE" ? null : subscriptionTier === "TRIAL" ? 500 : 5_000,
    sku_remaining: subscriptionTier === "ELITE" ? null : subscriptionTier === "TRIAL" ? 500 : 5_000,
  } : undefined, [activeTenantId, activeTenantSlug, profile?.context.tenantName, subscriptionTier, t]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setGreetingKey(greetingKeyForHour(new Date().getHours()));
    }, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let disposed = false;
    if (!activeTenantId || !canViewSalesInbox) {
      setPendingInquiryCount(0);
      setNewInquiryNotice(undefined);
      return undefined;
    }

    const noticeOwner = profile?.user.id ?? "member";
    const storageKey = `zhimaoyun.console.pending-quote-notices.${activeTenantId}.${noticeOwner}`;
    // Keep a memory fallback for private browsing modes where localStorage is
    // unavailable. This prevents the same reminder from reopening on every
    // polling cycle while still allowing a new tab/session to be notified.
    const memorySeenIds = new Set<string>();
    let refreshInFlight: Promise<void> | null = null;
    let consecutiveFailures = 0;
    let nextRefreshAt = 0;
    const readSeenIds = () => {
      const seen = new Set(memorySeenIds);
      try {
        const value = JSON.parse(window.localStorage.getItem(storageKey) ?? "[]");
        if (Array.isArray(value)) {
          value.forEach((entry) => {
            if (typeof entry === "string") seen.add(entry);
          });
        }
      } catch {
        // Private browsing may deny localStorage; the in-memory set remains.
      }
      return seen;
    };
    const refreshPendingQuotes = () => {
      if (disposed || refreshInFlight || Date.now() < nextRefreshAt) {
        return refreshInFlight ?? Promise.resolve();
      }
      const pendingRequest = (async () => {
        try {
          const rows = await listPublicQuoteDrafts();
          if (disposed) return;
          consecutiveFailures = 0;
          nextRefreshAt = Date.now() + 20_000;
          const pending = rows.filter((row) => ["PENDING_CONFIRMATION", "SUBMITTED", "PENDING_REVIEW"].includes(row.status));
          setPendingInquiryCount(pending.length);
          const seen = readSeenIds();
          const unseen = pending.filter((row) => !seen.has(row.id));
          if (unseen.length) {
            setNewInquiryNotice({
              count: unseen.length,
              customers: unseen.slice(0, 3).map((row) => row.customerCompany || row.customerName),
            });
            pending.forEach((row) => seen.add(row.id));
            pending.forEach((row) => memorySeenIds.add(row.id));
            try {
              window.localStorage.setItem(storageKey, JSON.stringify([...seen].slice(-200)));
            } catch {
              // Private browsing may deny localStorage; the memory fallback still works.
            }
          }
        } catch {
          consecutiveFailures += 1;
          nextRefreshAt = Date.now() + pollingBackoffMs(
            20_000,
            consecutiveFailures,
            60_000,
          );
          // Notification polling must never block the console or show a noisy
          // error when the member does not have access to the sales inbox.
        }
      })();
      refreshInFlight = pendingRequest;
      void pendingRequest.finally(() => {
        if (refreshInFlight === pendingRequest) refreshInFlight = null;
      });
      return pendingRequest;
    };

    void refreshPendingQuotes();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshPendingQuotes();
    }, 20_000);
    const handleQuoteChanged = () => void refreshPendingQuotes();
    window.addEventListener("atc:public-quote-changed", handleQuoteChanged);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.removeEventListener("atc:public-quote-changed", handleQuoteChanged);
    };
  }, [activeTenantId, canViewSalesInbox, profile?.user.id]);

  useEffect(() => {
    if (!activeNavigationGroup) return;
    setExpandedNavigationGroups((current) => {
      if (current.has(activeNavigationGroup)) return current;
      const next = new Set(current);
      next.add(activeNavigationGroup);
      return next;
    });
  }, [activeNavigationGroup]);

  const selectTenant = async (membershipId: string) => {
    if (membershipId === activeMembershipId) return;
    setTenantError("");
    try { await switchTenant(membershipId); }
    catch (caught) { setTenantError(caught instanceof Error ? caught.message : t("工作区切换失败")); }
  };
  const reloadTenants = reloadProfile;

  const openCurrencyDialog = () => {
    if (COMMON_CURRENCIES.includes(defaultCurrency as typeof COMMON_CURRENCIES[number])) {
      setCurrencyPreset(defaultCurrency);
      setCustomCurrency("");
    } else {
      setCurrencyPreset("OTHER");
      setCustomCurrency(defaultCurrency);
    }
    setToolbarError("");
    setModeDialogOpen(true);
  };

  const saveDefaultCurrency = async () => {
    if (!canManageSettings || modeBusy) return;
    const nextCurrency = (currencyPreset === "OTHER" ? customCurrency : currencyPreset)
      .trim()
      .toUpperCase();
    if (!/^[A-Z]{3}$/.test(nextCurrency)) {
      setToolbarError(t("请输入三位英文字母币种代码。"));
      return;
    }
    setModeBusy(true);
    setToolbarError("");
    try {
      await updateMerchantSettings({ defaultCurrency: nextCurrency });
      await reloadProfile();
      window.dispatchEvent(
        new CustomEvent("atc:merchant-settings-changed", {
          detail: {
            defaultCurrency: nextCurrency,
            businessMode: nextCurrency === "CNY" ? "DOMESTIC" : "EXPORT",
          },
        }),
      );
      setModeDialogOpen(false);
    } catch {
      setToolbarError(t("币种设置保存失败，请稍后重试。"));
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

  const isQuoteWorkbenchRoute = /^\/console\/quotes\/[^/]+\/workbench$/.test(location.pathname);

  return <div className={`console-shell${isQuoteWorkbenchRoute ? " console-shell--quote-workbench" : ""}`}>
    <aside className="console-sidebar">
      <div className="sidebar-brand"><Brand /></div>
      <nav className="desktop-console-nav" aria-label={t("控制台导航")}>
        {visibleGroups.map((group) => {
          const isExpanded = expandedNavigationGroups.has(group.key);
          const hasActiveItem = activeNavigationGroup === group.key;
          const GroupIcon = group.icon;
          const panelId = `console-nav-${group.key}`;
          const toggleLabel = t(isExpanded ? "收起 {name}" : "展开 {name}", {
            name: t(group.label),
          });

          return <section
            className={`nav-group${isExpanded ? " is-expanded" : ""}${hasActiveItem ? " has-active-item" : ""}`}
            key={group.key}
          >
            <button
              type="button"
              className="nav-group-trigger"
              aria-expanded={isExpanded}
              aria-controls={panelId}
              aria-label={toggleLabel}
              title={toggleLabel}
              onClick={() => setExpandedNavigationGroups((current) => {
                const next = new Set(current);
                if (next.has(group.key)) next.delete(group.key);
                else next.add(group.key);
                return next;
              })}
            >
              <GroupIcon className="nav-group-icon" size={20} weight="duotone" />
              <span>{t(group.label)}</span>
              {group.key === "sales" && pendingInquiryCount > 0 ? <span className="nav-unread-dot" aria-label={t("有 {count} 条待处理询价", { count: pendingInquiryCount })}>{pendingInquiryCount > 9 ? "9+" : pendingInquiryCount}</span> : null}
              <CaretDown className="nav-group-caret" size={15} weight="bold" aria-hidden="true" />
            </button>
            {isExpanded ? <div className="nav-group-items" id={panelId}>
              {group.items.map(({ to, label, icon: Icon, end }) => {
                const hasPending = pendingInquiryCount > 0 && (to === "/console/inquiries" || to === "/console/quotes");
                return <NavLink
                  key={to}
                  to={to}
                  end={end}
                  title={t(label)}
                  onPointerEnter={() => preloadConsoleRoute(to)}
                  onPointerDown={() => preloadConsoleRoute(to)}
                  onFocus={() => preloadConsoleRoute(to)}
                  className={({ isActive }) => `nav-item nav-subitem ${isActive ? "active" : ""}`}
                >
                  <Icon size={18} weight="duotone" />
                  <span>{t(label)}</span>
                  {hasPending ? <span className="nav-unread-dot" aria-label={t("有 {count} 条待处理询价", { count: pendingInquiryCount })}>{pendingInquiryCount > 9 ? "9+" : pendingInquiryCount}</span> : null}
                </NavLink>;
              })}
            </div> : null}
          </section>;
        })}
      </nav>
      <nav className="mobile-console-nav" aria-label={t("移动端控制台导航")}>
        {mobilePrimary.map(({ to, mobileLabel, icon: Icon, end }) => {
          const hasPending = pendingInquiryCount > 0 && (to === "/console/inquiries" || to === "/console/quotes");
          return <NavLink key={to} to={to} end={end} onPointerDown={() => preloadConsoleRoute(to)} onFocus={() => preloadConsoleRoute(to)} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon size={20} weight="duotone" /><span>{t(mobileLabel)}</span>{hasPending ? <span className="nav-unread-dot" aria-label={t("有 {count} 条待处理询价", { count: pendingInquiryCount })}>{pendingInquiryCount > 9 ? "9+" : pendingInquiryCount}</span> : null}</NavLink>;
        })}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger>
            <button type="button" className={`nav-item mobile-more-trigger ${mobileMoreActive ? "active" : ""}`}><DotsThreeOutline size={20} weight="duotone" /><span>{t("更多")}</span></button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Content align="end" sideOffset={10} className="mobile-more-content">
            {mobileMore.map(({ to, label, icon: Icon }) => <DropdownMenu.Item asChild key={to}><Link to={to} onPointerEnter={() => preloadConsoleRoute(to)} onPointerDown={() => preloadConsoleRoute(to)} onFocus={() => preloadConsoleRoute(to)}><Icon size={17} />{t(label)}{pendingInquiryCount > 0 && (to === "/console/inquiries" || to === "/console/quotes") ? <span className="nav-unread-dot" aria-hidden="true">{pendingInquiryCount > 9 ? "9+" : pendingInquiryCount}</span> : null}</Link></DropdownMenu.Item>)}
            <DropdownMenu.Separator />
            <DropdownMenu.Item asChild><Link to="/console/account"><UserGear size={17} />{t("账户与安全")}</Link></DropdownMenu.Item>
            <DropdownMenu.Item asChild><Link to={storefrontPath} target="_blank" rel="noopener noreferrer"><StoreIcon size={17} />{t("查看商品前台")}</Link></DropdownMenu.Item>
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
      </div>
    </aside>

    <div className="console-main">
      <header className="console-topbar">
        <div className="mobile-brand"><Brand compact /></div>
        <div className="tenant-context">
          <div className="tenant-context-heading">
            <div className="tenant-context-name">
              <Text size="1" color="gray" as="div">{t(greetingKey)}</Text>
              {memberships.length > 1 ? <Select.Root value={activeMembershipId} disabled={status === "restoring"} onValueChange={(value) => void selectTenant(value)}><Select.Trigger className="tenant-select" placeholder={t("选择租户")} /><Select.Content>{memberships.filter((membership) => membership.status.toUpperCase() === "ACTIVE").map((membership) => <Select.Item value={membership.id} key={membership.id}>{membership.tenantName}</Select.Item>)}</Select.Content></Select.Root> : <Text size="2" weight="medium">{profile?.context.tenantName ?? t("当前租户")}</Text>}
              {tenantError ? <Text size="1" color="red">{tenantError}</Text> : null}
            </div>
            <Link className="topbar-storefront-link" to={storefrontPath} target="_blank" rel="noopener noreferrer" title={t("查看商品前台")}>
              <StoreIcon size={16} weight="duotone" />
              <span>{t("查看商品前台")}</span>
            </Link>
          </div>
        </div>
        <div className="topbar-user">
          <SupportNotificationBell
            tenantId={activeTenantId}
            enabled={hasPermission("support.view")}
          />
          <Button
            className={`business-mode-trigger ${businessMode === "EXPORT" ? "export" : ""}`}
            variant="soft"
            color={businessMode === "EXPORT" ? "amber" : "gray"}
            aria-label={t("设置前台币种")}
            title={!canManageSettings
              ? t("当前成员没有修改商家设置的权限。")
              : t("设置前台币种")}
            disabled={!canManageSettings || modeBusy}
            onClick={openCurrencyDialog}
          >
            <GlobeHemisphereWest size={17} weight="duotone" />
            <span>{t("币种")} · {defaultCurrency}</span>
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
          {activeTenantId ? (
            <Badge
              className={`subscription-level-badge is-${subscriptionTier.toLowerCase()}`}
              color={subscriptionPresentation.color}
              variant="soft"
            >
              {t(subscriptionTierLabel(subscriptionTier))}
            </Badge>
          ) : null}
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
                  {activeTenantId ? (
                    <Badge color={subscriptionPresentation.color} variant="soft">
                      {t(subscriptionTierLabel(subscriptionTier))}
                    </Badge>
                  ) : null}
                </div>
              </DropdownMenu.Label>
              <DropdownMenu.Item asChild><Link to="/console/account"><UserGear size={17} />{t("账户与安全")}</Link></DropdownMenu.Item>
              <DropdownMenu.Item asChild><Link to={storefrontPath} target="_blank" rel="noopener noreferrer"><StoreIcon size={17} />{t("查看商品前台")}</Link></DropdownMenu.Item>
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
        <AlertDialog.Title>{t("设置前台币种")}</AlertDialog.Title>
        <AlertDialog.Description>
          {t("商品前台和之后生成的报价单会统一使用所选币种展示。")}
        </AlertDialog.Description>
        <div className="business-currency-field">
          <Text as="label" size="2" weight="medium">{t("币种代码")}</Text>
          <Select.Root value={currencyPreset} onValueChange={setCurrencyPreset}>
            <Select.Trigger aria-label={t("选择币种")} />
            <Select.Content>
              {COMMON_CURRENCIES.map((currency) => (
                <Select.Item key={currency} value={currency}>
                  {currency === "CNY" ? "CNY / RMB" : currency}
                </Select.Item>
              ))}
              <Select.Separator />
              <Select.Item value="OTHER">{t("其他币种")}</Select.Item>
            </Select.Content>
          </Select.Root>
          {currencyPreset === "OTHER" ? <TextField.Root
            value={customCurrency}
            onChange={(event) => setCustomCurrency(event.currentTarget.value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 3))}
            placeholder="EUR"
            maxLength={3}
            autoCapitalize="characters"
            aria-label={t("三位币种代码")}
          /> : null}
        </div>
        <div className="business-mode-note">
          <GlobeHemisphereWest size={20} weight="duotone" />
          <Text size="2">{t("切换币种不会换算或修改价格数值；系统仅更换币种符号与代码，并切换到对应币种的默认仓库。")}</Text>
        </div>
        {toolbarError ? <Text size="2" color="red" role="alert">{toolbarError}</Text> : null}
        <div className="core-dialog-actions">
          <AlertDialog.Cancel><Button variant="soft" color="gray" disabled={modeBusy}>{t("取消")}</Button></AlertDialog.Cancel>
          <Button onClick={() => void saveDefaultCurrency()} loading={modeBusy}>
            {t(modeBusy ? "正在保存" : "保存币种")}
          </Button>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>
    <AlertDialog.Root
      open={Boolean(newInquiryNotice)}
      onOpenChange={(open) => {
        if (!open) setNewInquiryNotice(undefined);
      }}
    >
      <AlertDialog.Content className="console-inquiry-notice-dialog">
        <AlertDialog.Title>{t("收到新的客户询价")}</AlertDialog.Title>
        <AlertDialog.Description size="2">
          {newInquiryNotice
            ? t("收到 {count} 条待处理询价，请及时处理。", { count: newInquiryNotice.count })
            : ""}
        </AlertDialog.Description>
        {newInquiryNotice?.customers.length ? (
          <div className="console-inquiry-notice-customers" aria-label={t("待处理客户")}>
            {newInquiryNotice.customers.map((customer, index) => (
              <span key={`${customer}-${index}`}>{customer}</span>
            ))}
          </div>
        ) : null}
        <div className="console-inquiry-notice-actions">
          <AlertDialog.Cancel>
            <Button variant="soft" color="gray">{t("稍后处理")}</Button>
          </AlertDialog.Cancel>
          <AlertDialog.Action>
            <Button color="blue" onClick={() => { setNewInquiryNotice(undefined); navigate("/console/quotes"); }}>
              {t("查看报价")}
            </Button>
          </AlertDialog.Action>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>
  </div>;
}
