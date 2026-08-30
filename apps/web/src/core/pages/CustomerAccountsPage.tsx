import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  Heading,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  CheckCircle,
  CaretDown,
  CaretLeft,
  CaretRight,
  Eye,
  EyeSlash,
  CurrencyDollar,
  Folder,
  FolderOpen,
  Key,
  Plus,
  SlidersHorizontal,
  TreeStructure,
  UserPlus,
  UsersThree,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  createCustomerSubaccount,
  CoreApiError,
  getCustomerSubaccountDashboard,
  updateCustomerSubaccountAccess,
  getCustomerSubaccountPricing,
  listCategories,
  resetCustomerSubaccountPassword,
  updateCustomerSubaccountPricing,
  updateCustomerSubaccountProductPricing,
  updateCustomerSubaccountCategoryPricing,
  clearCustomerSubaccountCategoryPricing,
  clearCustomerSubaccountProductPricing,
  updateCustomerSubaccountSkuPricing,
  clearCustomerSubaccountSkuPricing,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { useToast } from "../ToastContext";
import { money } from "../../lib/format";
import type {
  CustomerSubaccount,
  CustomerSubaccountDashboard,
  CustomerSubaccountModule,
  CustomerSubaccountOrderDetail,
  ProductCategory,
  SubaccountPricingMode,
  SubaccountPricingPage,
  SubaccountProductPricingItem,
} from "../types";

const orderStatusLabel: Record<string, string> = {
  PENDING_CONFIRMATION: "待商家确认",
  CONFIRMED: "已确认",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

const SUBACCOUNT_MODULES: Array<{
  code: CustomerSubaccountModule;
  label: string;
  description: string;
}> = [
  { code: "products", label: "商品与目录", description: "只读查看商品、SKU 与前台目录" },
  { code: "inquiries", label: "询盘", description: "客户需求与询盘处理" },
  { code: "quotations", label: "报价", description: "报价制作与订单跟进" },
  { code: "announcements", label: "公告", description: "发布前台公告" },
  { code: "support", label: "客户沟通", description: "查看并回复客户消息" },
];
const ALL_SUBACCOUNT_MODULES = SUBACCOUNT_MODULES.map((item) => item.code);

function isPasswordPolicyError(reason: unknown): boolean {
  if (!(reason instanceof CoreApiError) || !reason.details || typeof reason.details !== "object") return false;
  const detail = (reason.details as { detail?: unknown }).detail;
  return Boolean(detail && typeof detail === "object" && (detail as { code?: unknown }).code === "PASSWORD_POLICY_VIOLATION");
}

function countryFlag(countryCode?: string) {
  const normalized = String(countryCode || "").trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(normalized)) return "🌐";
  return String.fromCodePoint(
    ...[...normalized].map((character) => 127397 + character.charCodeAt(0)),
  );
}

function countryLabel(countryCode?: string) {
  const normalized = String(countryCode || "").trim().toUpperCase();
  return normalized ? `${countryFlag(normalized)} ${normalized}` : "—";
}

export function CustomerAccountsPage() {
  const { t } = useLocale();
  const [data, setData] = useState<CustomerSubaccountDashboard>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getCustomerSubaccountDashboard());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("客户账号数据加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  if (loading && !data) return <div className="core-workspace"><CoreLoading label={t("正在读取客户账号")} /></div>;

  return <div className="core-workspace customer-accounts-page">
    <CorePageHeading
      eyebrow={t("账户管理")}
      title={t("子账号管理")}
      description={t("管理子账号、价格规则和成交数据。")}
      actions={<Button onClick={() => setEditorOpen(true)}><UserPlus />{t("开通子账号")}</Button>}
    />
    {error ? <CoreError message={error} onRetry={() => void load()} /> : null}

    <section className="customer-account-metrics" aria-label={t("子账号概览")}>
      <Metric icon={<UsersThree />} label={t("全部子账号")} value={(data?.accounts.length ?? 0).toString()} />
      <Metric icon={<CheckCircle />} label={t("当前已开通")} value={(data?.activeCount ?? 0).toString()} tone="jade" />
      <Metric icon={<Eye />} label={t("近期开单申请")} value={(data?.orderCount ?? 0).toString()} />
      <Metric icon={<CurrencyDollar />} label={t("累计询价金额")} value={money(data?.orderAmount ?? 0, data?.currency || "CNY")} tone="jade" />
      <Metric icon={<CurrencyDollar />} label={t("今日成交额")} value={money(data?.todayOrderAmount ?? 0, data?.currency || "CNY")} tone="jade" />
      <Metric icon={<CheckCircle />} label={t("本月成交额")} value={money(data?.monthOrderAmount ?? 0, data?.currency || "CNY")} />
    </section>

    <section className="customer-account-grid">
      <Card className="customer-account-panel">
        <div className="customer-account-panel-heading">
          <div><Text size="1" color="gray">{t("账号列表")}</Text><Heading size="5">{t("子账号列表")}</Heading></div>
          <Text size="2" color="gray">{t("点击子账号进入详情，查看资料、价格和该账号订单")}</Text>
        </div>
        {data?.accounts.length ? <div className="customer-account-list">
          {data.accounts.map((account) => <article className="customer-account-row" key={account.id}>
            <Link className="customer-account-identity customer-account-primary-link" to={`/console/customer-accounts/${encodeURIComponent(account.id)}`}>
              <span className="customer-account-avatar">{account.displayName.slice(0, 2).toUpperCase()}</span>
              <span><strong>{account.displayName}</strong><small>{account.loginIdentifier}{account.email ? ` · ${account.email}` : ""}</small><small className="customer-account-pricing-summary">+{Number(account.markupPercent || 0).toLocaleString()}% · {t("{count} 个单品规则", { count: account.overrideCount })} · {t("{count} 个分类规则", { count: account.categoryOverrideCount ?? 0 })} · {t("{count} 个 SKU 特价", { count: account.skuOverrideCount ?? 0 })}</small></span>
            </Link>
            <div className="customer-account-signal">
              <small>{t("最近访问")}</small><strong>{account.lastLoginAt ? coreDate(account.lastLoginAt) : t("尚未登录")}</strong>
              <span>{t("近 30 天 {count} 次", { count: account.loginCount30d })}</span>
            </div>
            <div className="customer-account-signal">
              <small>{t("订单申请")}</small><strong>{t("{count} 笔", { count: account.orderCount })}</strong>
              <span>{money(account.orderAmount, data?.currency || "CNY")}{account.lastOrderAt ? ` · ${t("最近 {date}", { date: coreDate(account.lastOrderAt) })}` : ""}</span>
            </div>
            <div className="customer-account-signal">
              <small>{t("今日成交")}</small><strong>{money(account.todayOrderAmount, data?.currency || "CNY")}</strong>
              <span>{t("{count} 笔", { count: account.todayOrderCount })} · {t("本月 {amount}", { amount: money(account.monthOrderAmount, data?.currency || "CNY") })}</span>
            </div>
            <Badge color={account.status === "active" ? "jade" : "gray"}>{t(account.status === "active" ? "已开通" : "已停用")}</Badge>
            <div className="customer-account-actions">
              <Button asChild size="1" variant="soft" color="gray">
                <Link to={`/console/customer-accounts/${encodeURIComponent(account.id)}`}><Eye />{t("查看详情")}<CaretRight /></Link>
              </Button>
            </div>
          </article>)}
        </div> : <CoreEmpty
          title={t("还没有子账号")}
          description={t("为团队成员开通独立登录账号，并在这里管理可见范围。")}
          action={<Button variant="soft" onClick={() => setEditorOpen(true)}><Plus />{t("开通第一个子账号")}</Button>}
        />}
      </Card>

      <Card className="customer-account-side-note">
        <span className="customer-account-side-icon"><Eye size={24} /></span>
        <Text size="1" color="gray">{t("主账号管理范围")}</Text>
        <Heading size="4">{t("价格、商品和订单一处管理")}</Heading>
        <Text size="2" color="gray">{t("主账号可以设置统一加价、单品价格，并查看每个子账号的访问与成交数据。")}</Text>
        <ul>
          <li>{t("子账号使用独立工作台，可处理自己的询价；原价格、供应商与供应链不显示")}</li>
          <li>{t("订单和金额按照提交账号自动归属")}</li>
          <li>{t("停用后立即失去门户访问")}</li>
        </ul>
      </Card>
    </section>

    {editorOpen ? <CustomerAccountCreateDialog
      onClose={() => setEditorOpen(false)}
      onCreated={async () => { setEditorOpen(false); await load(); }}
    /> : null}
  </div>;
}

function Metric({ icon, label, value, tone = "" }: { icon: ReactNode; label: string; value: string; tone?: string }) {
  return <Card className={`customer-account-metric ${tone}`}><span>{icon}</span><div><Text size="2" color="gray">{label}</Text><strong>{value}</strong></div></Card>;
}

function CustomerAccountCreateDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const { t } = useLocale();
  const [displayName, setDisplayName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await createCustomerSubaccount({
        displayName: displayName.trim(),
        loginIdentifier: identifier.trim(),
        password,
        email: email.trim() || undefined,
        modules: ALL_SUBACCOUNT_MODULES,
      });
      await onCreated();
    } catch (caught) {
      setError(isPasswordPolicyError(caught) ? t("密码必须是 6 位数字。") : caught instanceof Error ? caught.message : t("子账号创建失败"));
    } finally {
      setSaving(false);
    }
  };
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog">
      <form onSubmit={(event) => void submit(event)}>
        <Dialog.Title>{t("开通子账号")}</Dialog.Title>
        <Dialog.Description>{t("对方使用账号密码登录同一套商品工作台；密码可在输入时显示，后续也可以由主账号重新设置。")}</Dialog.Description>
        <div className="customer-account-form-grid">
          <label><Text size="2" weight="medium">{t("子账号名称")}</Text><TextField.Root value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder={t("例如 上海澄明贸易") } required maxLength={120} /></label>
          <label><Text size="2" weight="medium">{t("登录账号")}</Text><TextField.Root value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder={t("账号、邮箱或手机号") } required maxLength={320} autoCapitalize="none" /></label>
          <label><Text size="2" weight="medium">{t("联系邮箱（可选）")}</Text><TextField.Root value={email} onChange={(event) => setEmail(event.target.value)} placeholder={t("name@example.com") } type="email" maxLength={320} /></label>
          <label>
            <Text size="2" weight="medium">{t("初始密码")}</Text>
            <TextField.Root
              value={password}
              onChange={(event) => setPassword(event.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder={t("请输入 6 位数字")}
              type={passwordVisible ? "text" : "password"}
              inputMode="numeric"
              pattern="[0-9]{6}"
              required
              minLength={6}
              maxLength={6}
              autoComplete="new-password"
            >
              <TextField.Slot side="right">
                <button
                  type="button"
                  className="login-password-toggle"
                  aria-label={t(passwordVisible ? "隐藏密码" : "显示密码")}
                  aria-pressed={passwordVisible}
                  onClick={() => setPasswordVisible((current) => !current)}
                >
                  {passwordVisible ? <EyeSlash size={18} /> : <Eye size={18} />}
                </button>
              </TextField.Slot>
            </TextField.Root>
          </label>
        </div>
        <div className="customer-account-dialog-note"><SlidersHorizontal size={18} />{t("默认开放全部运营模块；创建后可在“权限”中逐项收窄。")}</div>
        <div className="customer-account-dialog-note"><WarningCircle size={18} />{t("请将初始账号密码通过可靠渠道交给客户；密码不会在创建后再次显示。")}</div>
        {error ? <Text color="red" size="2">{error}</Text> : null}
        <div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={onClose}>{t("取消")}</Button><Button type="submit" loading={saving}><UserPlus />{t(saving ? "正在开通" : "确认开通")}</Button></div>
      </form>
    </Dialog.Content>
  </Dialog.Root>;
}

export function CustomerSubaccountPasswordDialog({
  account,
  onClose,
}: {
  account: CustomerSubaccount;
  onClose: () => void;
}) {
  const { t } = useLocale();
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!/^\d{6}$/.test(password)) {
      setError(t("密码必须是 6 位数字。"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      await resetCustomerSubaccountPassword(account.id, password);
      setSaved(true);
    } catch (caught) {
      setError(isPasswordPolicyError(caught) ? t("密码必须是 6 位数字。") : caught instanceof Error ? caught.message : t("密码更新失败"));
    } finally {
      setSaving(false);
    }
  };

  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog customer-password-dialog">
      <form onSubmit={(event) => void submit(event)}>
        <Dialog.Title>{t("修改子账号密码")}</Dialog.Title>
        <Dialog.Description>{t("为 {name} 设置新的登录密码。保存后，该账号之前的登录会话会失效。", { name: account.displayName })}</Dialog.Description>
        {saved ? <Card className="customer-account-success"><CheckCircle size={22} /><div><Text weight="bold">{t("密码已更新")}</Text><Text size="2" color="gray">{t("请将新的 6 位数字密码安全地交给子账号。")}</Text></div></Card> : <label><Text size="2" weight="medium">{t("新密码")}</Text><TextField.Root value={password} onChange={(event) => setPassword(event.target.value.replace(/\D/g, "").slice(0, 6))} type={visible ? "text" : "password"} inputMode="numeric" pattern="[0-9]{6}" minLength={6} maxLength={6} autoFocus required placeholder={t("6 位数字")}>
          <TextField.Slot side="right"><button type="button" className="login-password-toggle" aria-label={t(visible ? "隐藏密码" : "显示密码")} aria-pressed={visible} onClick={() => setVisible((current) => !current)}>{visible ? <EyeSlash size={18} /> : <Eye size={18} />}</button></TextField.Slot>
        </TextField.Root></label>}
        {error ? <Text color="red" size="2">{error}</Text> : null}
        <div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={onClose}>{t("关闭")}</Button>{!saved ? <Button type="submit" loading={saving}><Key />{t("保存新密码")}</Button> : null}</div>
      </form>
    </Dialog.Content>
  </Dialog.Root>;
}

export function CustomerSubaccountOrderDetailDialog({
  detail,
  loading,
  onClose,
}: {
  detail?: CustomerSubaccountOrderDetail;
  loading: boolean;
  onClose: () => void;
}) {
  const { t } = useLocale();
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog customer-order-detail-dialog">
      {loading || !detail ? <CoreLoading label={t("正在读取订单详情")} /> : <>
        <div className="core-dialog-heading"><div><Text size="1" color="gray">{t("子账号询价 · 只读")}</Text><Dialog.Title>{detail.quoteNumber}</Dialog.Title><Dialog.Description>{detail.submittedByName} · {coreDate(detail.createdAt)}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}>×</Button></div>
        <div className="customer-order-detail-meta">
          <Card><Text size="1" color="gray">{t("客户")}</Text><strong>{detail.customerCompany || detail.customerName}</strong><Text size="1">{detail.customerName}</Text></Card>
          <Card><Text size="1" color="gray">{t("客户国家")}</Text><strong>{countryLabel(detail.visitorCountryCode)}</strong></Card>
          <Card><Text size="1" color="gray">{t("最终报价")}</Text><strong>{money(detail.totalAmount, detail.currency)}</strong></Card>
          <Card><Text size="1" color="gray">{t("状态")}</Text><Badge color={detail.status === "CONFIRMED" || detail.status === "COMPLETED" ? "jade" : detail.status === "CANCELLED" ? "gray" : "amber"}>{t(orderStatusLabel[detail.status] ?? detail.status)}</Badge></Card>
        </div>
        <div className="customer-order-detail-items">
          <div className="customer-order-detail-items-head"><span>{t("商品 / SKU")}</span><span>{t("数量")}</span><span>{t("最终单价")}</span><span>{t("小计")}</span></div>
          {detail.items.map((item) => <div className="customer-order-detail-item" key={item.skuId}><div><strong>{item.productName}</strong><small className="mono-text">{item.skuCode}</small></div><span>{item.quantity}</span><span>{money(item.unitPrice, item.currency)}</span><strong>{money(item.lineTotal, item.currency)}</strong></div>)}
          {!detail.items.length ? <Text size="2" color="gray">{t("没有商品明细")}</Text> : null}
        </div>
        <div className="core-dialog-actions"><Button onClick={onClose}>{t("关闭")}</Button></div>
      </>}
    </Dialog.Content>
  </Dialog.Root>;
}

export function CustomerAccountAccessDialog({
  account,
  onClose,
  onSaved,
}: {
  account: CustomerSubaccount;
  onClose: () => void;
  onSaved: (updated: CustomerSubaccount) => void;
}) {
  const { t } = useLocale();
  const [selected, setSelected] = useState<Set<CustomerSubaccountModule>>(
    new Set(account.modules?.length ? account.modules : ALL_SUBACCOUNT_MODULES),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const modules = SUBACCOUNT_MODULES
        .map((item) => item.code)
        .filter((code) => selected.has(code));
      onSaved(await updateCustomerSubaccountAccess(account.id, { modules }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("子账号权限保存失败"));
    } finally {
      setSaving(false);
    }
  };
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog subaccount-access-dialog">
      <Dialog.Title>{t("{name} 的可见范围", { name: account.displayName })}</Dialog.Title>
      <Dialog.Description>{t("子账号是独立运营账号。勾选它需要使用的模块；原价格、供应商、库存和平台统计始终隐藏，子账号自己的询价和报价由它独立处理。")}</Dialog.Description>
      <div className="subaccount-access-options">
        {SUBACCOUNT_MODULES.map((item) => <label key={item.code}>
          <Checkbox
            checked={selected.has(item.code)}
            disabled={item.code === "products"}
            onCheckedChange={(checked) => setSelected((current) => {
              const next = new Set(current);
              if (checked === true) next.add(item.code); else next.delete(item.code);
              return next;
            })}
          />
          <span><Text size="2" weight="medium">{t(item.label)}</Text><Text size="1" color="gray">{t(item.description)}</Text></span>
        </label>)}
      </div>
      <div className="customer-account-dialog-note"><WarningCircle size={18} />{t("商品与目录为必选入口；关闭其他模块只会隐藏入口，不会删除数据。")}</div>
      {error ? <Text color="red" size="2">{error}</Text> : null}
      <div className="core-dialog-actions"><Button variant="soft" color="gray" onClick={onClose}>{t("取消")}</Button><Button loading={saving} onClick={() => void save()}>{t("保存权限")}</Button></div>
    </Dialog.Content>
  </Dialog.Root>;
}

export function SubaccountPricingDialog({
  account,
  onClose,
  onSaved,
}: {
  account: CustomerSubaccount;
  onClose: () => void;
  onSaved: (policy: { markupPercent: number; overrideCount: number; categoryOverrideCount?: number; skuOverrideCount?: number }) => void;
}) {
  const { t } = useLocale();
  const { notify } = useToast();
  const [data, setData] = useState<SubaccountPricingPage>();
  const [markupDraft, setMarkupDraft] = useState<string>();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editingProduct, setEditingProduct] = useState<string>();
  const [editingSku, setEditingSku] = useState<string>();
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [categoryId, setCategoryId] = useState("");
  const [categoryDrafts, setCategoryDrafts] = useState<Record<string, string>>({});
  const [expandedCategoryIds, setExpandedCategoryIds] = useState<Set<string>>(new Set());

  const savedCategoryRulesById = useMemo(
    () => new Map((data?.categoryRules || []).map((rule) => [rule.categoryId, rule.markupPercent])),
    [data?.categoryRules],
  );
  const categoryRulesById = useMemo(() => {
    const next = new Map(savedCategoryRulesById);
    Object.entries(categoryDrafts).forEach(([draftCategoryId, rawValue]) => {
      if (!rawValue.trim()) {
        next.delete(draftCategoryId);
        return;
      }
      const value = Number(rawValue);
      if (Number.isFinite(value)) next.set(draftCategoryId, value);
    });
    return next;
  }, [categoryDrafts, savedCategoryRulesById]);
  const rootCategories = useMemo(
    () => categories.filter((category) => !category.parentId).sort((left, right) => left.sortOrder - right.sortOrder),
    [categories],
  );
  const childCategoriesByParent = useMemo(() => {
    const result = new Map<string, ProductCategory[]>();
    categories.forEach((category) => {
      if (!category.parentId) return;
      const children = result.get(category.parentId) || [];
      children.push(category);
      result.set(category.parentId, children);
    });
    result.forEach((children) => children.sort((left, right) => left.sortOrder - right.sortOrder));
    return result;
  }, [categories]);
  const selectedCategory = categories.find((category) => category.id === categoryId);
  const selectedCategoryHasRule = Boolean(categoryId && categoryRulesById.has(categoryId));
  const selectedParentMarkup = selectedCategory?.parentId
    ? categoryRulesById.get(selectedCategory.parentId)
    : undefined;
  const markup = markupDraft ?? String(data?.policy.markupPercent ?? account.markupPercent ?? 0);
  const categoryMarkup = categoryId
    ? Object.prototype.hasOwnProperty.call(categoryDrafts, categoryId)
      ? categoryDrafts[categoryId]
      : savedCategoryRulesById.has(categoryId)
        ? String(savedCategoryRulesById.get(categoryId))
        : ""
    : "";
  const hasGlobalPricingChange = markupDraft !== undefined
    && (markupDraft.trim() === "" || Number(markupDraft) !== Number(data?.policy.markupPercent ?? account.markupPercent ?? 0));
  const hasCategoryPricingChange = Object.entries(categoryDrafts).some(([draftCategoryId, rawValue]) => {
    const savedValue = savedCategoryRulesById.get(draftCategoryId);
    if (!rawValue.trim()) return savedValue != null;
    return Number(rawValue) !== savedValue;
  });
  const hasPricingChanges = hasGlobalPricingChange || hasCategoryPricingChange;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await getCustomerSubaccountPricing(account.id, query, page, 30);
      setData(next);
      return next;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("价格规则加载失败"));
      return undefined;
    } finally {
      setLoading(false);
    }
  }, [account.id, page, query, t]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    let active = true;
    void listCategories().then((rows) => {
      if (active) setCategories(rows);
    }).catch(() => {
      // Keep product-level pricing usable if the optional category list is
      // temporarily unavailable.
    });
    return () => { active = false; };
  }, []);

  const selectCategory = (category: ProductCategory) => {
    setCategoryId(category.id);
    if (category.parentId) {
      setExpandedCategoryIds((previous) => new Set(previous).add(category.parentId as string));
    }
  };

  const toggleCategory = (categoryIdToToggle: string) => {
    setExpandedCategoryIds((previous) => {
      const next = new Set(previous);
      if (next.has(categoryIdToToggle)) next.delete(categoryIdToToggle);
      else next.add(categoryIdToToggle);
      return next;
    });
  };

  const savePriceSettings = async () => {
    const globalValue = Number(markup);
    if (!markup.trim() || !Number.isFinite(globalValue) || globalValue < 0 || globalValue > 100000) {
      setError(t("统一加价必须是 0 到 100000 之间的数字"));
      return;
    }
    const categoryUpdates: Array<{ categoryId: string; value?: number }> = [];
    for (const [draftCategoryId, rawValue] of Object.entries(categoryDrafts)) {
      const savedValue = savedCategoryRulesById.get(draftCategoryId);
      if (!rawValue.trim()) {
        if (savedValue != null) categoryUpdates.push({ categoryId: draftCategoryId });
        continue;
      }
      const value = Number(rawValue);
      if (!Number.isFinite(value) || value < 0 || value > 100000) {
        const categoryName = categories.find((category) => category.id === draftCategoryId)?.name;
        setError(categoryName
          ? t("{name} 的分类加价必须是 0 到 100000 之间的数字", { name: categoryName })
          : t("分类加价必须是 0 到 100000 之间的数字"));
        return;
      }
      if (value !== savedValue) categoryUpdates.push({ categoryId: draftCategoryId, value });
    }
    setSaving(true);
    setError("");
    try {
      let policy = data?.policy;
      if (markupDraft !== undefined && globalValue !== Number(data?.policy.markupPercent ?? account.markupPercent ?? 0)) {
        policy = await updateCustomerSubaccountPricing(account.id, globalValue);
      }
      for (const update of categoryUpdates) {
        if (update.value == null) {
          await clearCustomerSubaccountCategoryPricing(account.id, update.categoryId);
        } else {
          policy = await updateCustomerSubaccountCategoryPricing(account.id, update.categoryId, update.value);
        }
      }
      const refreshed = await load();
      setMarkupDraft(undefined);
      setCategoryDrafts({});
      if (refreshed) onSaved(refreshed.policy);
      else if (policy) onSaved(policy);
      notify(t("价格设置已保存"), { kind: "success" });
    } catch (caught) {
      await load();
      const message = caught instanceof Error ? caught.message : t("价格规则保存失败");
      setError(message);
      notify(message, { kind: "error" });
    } finally {
      setSaving(false);
    }
  };

  const saveProductRule = async (
    productId: string,
    mode: SubaccountPricingMode,
    rawValue: string,
  ) => {
    const value = Number(rawValue);
    if (!Number.isFinite(value) || value < 0) return;
    setEditingProduct(productId);
    setError("");
    try {
      const item = await updateCustomerSubaccountProductPricing(account.id, productId, mode, value);
      setData((current) => current ? {
        ...current,
        items: current.items.map((row) => row.productId === item.productId ? item : row),
        policy: { ...current.policy, overrideCount: current.items.some((row) => row.productId === item.productId && row.overrideMode) ? current.policy.overrideCount : current.policy.overrideCount + 1 },
      } : current);
      onSaved({ ...data?.policy, markupPercent: data?.policy.markupPercent ?? account.markupPercent ?? 0, overrideCount: (data?.policy.overrideCount || 0) + (data?.items.find((row) => row.productId === productId)?.overrideMode ? 0 : 1), categoryOverrideCount: data?.policy.categoryOverrideCount });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("单品价格保存失败"));
    } finally {
      setEditingProduct(undefined);
    }
  };

  const clearProductRule = async (productId: string) => {
    setEditingProduct(productId);
    try {
      await clearCustomerSubaccountProductPricing(account.id, productId);
      setData((current) => current ? {
        ...current,
        items: current.items.map((row) => row.productId === productId
          ? { ...row, overrideMode: undefined, overrideValue: undefined, effectivePriceFrom: Number((row.basePriceFrom * (1 + (current.policy.markupPercent / 100))).toFixed(2)), effectivePriceTo: Number((row.basePriceTo * (1 + (current.policy.markupPercent / 100))).toFixed(2)) }
          : row),
        policy: { ...current.policy, overrideCount: Math.max(0, current.policy.overrideCount - 1) },
      } : current);
      onSaved({ ...data?.policy, markupPercent: data?.policy.markupPercent ?? account.markupPercent ?? 0, overrideCount: Math.max(0, (data?.policy.overrideCount || 1) - 1), categoryOverrideCount: data?.policy.categoryOverrideCount });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("单品价格清除失败"));
    } finally {
      setEditingProduct(undefined);
    }
  };

  const clearCategoryRule = () => {
    if (!categoryId) return;
    setError("");
    setCategoryDrafts((current) => ({ ...current, [categoryId]: "" }));
  };

  const saveSkuRule = async (
    productId: string,
    skuId: string,
    mode: SubaccountPricingMode,
    rawValue: string,
  ) => {
    const value = Number(rawValue);
    if (!Number.isFinite(value) || value < 0) return;
    setEditingSku(skuId);
    setError("");
    try {
      const item = await updateCustomerSubaccountSkuPricing(account.id, skuId, mode, value);
      setData((current) => {
        if (!current) return current;
        const previous = current.items.find((row) => row.productId === productId);
        const previousCount = previous?.skuOverrideCount ?? 0;
        const nextCount = item.skuOverrideCount ?? 0;
        return {
          ...current,
          items: current.items.map((row) => row.productId === item.productId ? item : row),
          policy: {
            ...current.policy,
            skuOverrideCount: Math.max(0, current.policy.skuOverrideCount - previousCount + nextCount),
          },
        };
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("SKU 价格保存失败"));
    } finally {
      setEditingSku(undefined);
    }
  };

  const clearSkuRule = async (productId: string, skuId: string) => {
    setEditingSku(skuId);
    setError("");
    try {
      await clearCustomerSubaccountSkuPricing(account.id, skuId);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("SKU 价格清除失败"));
    } finally {
      setEditingSku(undefined);
    }
  };

  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="customer-account-dialog subaccount-pricing-dialog">
      <Dialog.Title>{t("{name} 的价格设置", { name: account.displayName })}</Dialog.Title>
      <Dialog.Description>{t("最终价格按 SKU 计算：SKU 特价 > 商品规则 > 分类规则 > 统一加价。子账号只会看到最终销售价。")}</Dialog.Description>
      <section className="subaccount-pricing-policy">
        <label><Text size="2" weight="medium">{t("统一加价（%）")}</Text><TextField.Root type="number" min="0" max="100000" step="0.1" value={markup} onChange={(event) => setMarkupDraft(event.target.value)} /></label>
        <Text size="1" color="gray">{t("当前已有 {count} 个单品规则、{skuCount} 个 SKU 特价；整体和分类改动由底部统一保存。", { count: data?.policy.overrideCount ?? account.overrideCount, skuCount: data?.policy.skuOverrideCount ?? 0 })}</Text>
      </section>
      <section className="subaccount-category-pricing">
        <div className="subaccount-category-pricing-heading">
          <div className="subaccount-category-pricing-copy">
            <Text size="2" weight="medium">{t("分类加价（%）")}</Text>
            <Text size="1" color="gray">{t("一级分类规则会自动应用到未单独设置的二级分类；单品规则优先。")}</Text>
          </div>
          <Text className="subaccount-category-pricing-count" size="1" color="gray">{t("已设置 {count} 个分类规则", { count: data ? categoryRulesById.size : account.categoryOverrideCount ?? 0 })}</Text>
        </div>
        <div className="subaccount-category-pricing-layout">
          <div className="subaccount-category-pricing-tree" role="tree" aria-label={t("选择加价分类")}>
            {rootCategories.map((root) => {
              const children = childCategoriesByParent.get(root.id) || [];
              const expanded = expandedCategoryIds.has(root.id);
              const rootMarkup = categoryRulesById.get(root.id);
              const colorStyle = { "--tag-glass-color": root.displayColor || "#287d6e" } as CSSProperties;
              return <div className="subaccount-category-pricing-branch" key={root.id}>
                <div className={`subaccount-category-pricing-node root${categoryId === root.id ? " is-selected" : ""}`} role="treeitem" aria-selected={categoryId === root.id} aria-expanded={children.length ? expanded : undefined}>
                  {children.length ? <button type="button" className="subaccount-category-pricing-toggle" onClick={() => toggleCategory(root.id)} aria-label={t(expanded ? "收起 {name}" : "展开 {name}", { name: root.name })}>{expanded ? <CaretDown weight="bold" /> : <CaretRight weight="bold" />}</button> : <span className="subaccount-category-pricing-toggle-placeholder" />}
                  <button type="button" className="subaccount-category-pricing-node-main" onClick={() => selectCategory(root)}>
                    <span className="core-category-color-mark" style={colorStyle}>{expanded ? <FolderOpen weight="duotone" /> : <Folder weight="duotone" />}</span>
                    <span><strong>{root.name}</strong><small>{children.length ? t("{count} 个二级分类", { count: children.length }) : t("暂无二级分类")}{root.status !== "ACTIVE" ? ` · ${t("停用")}` : ""}</small></span>
                  </button>
                  {rootMarkup == null ? <span className="subaccount-category-price-state is-inherited">{t("统一 +{value}%", { value: markup || "0" })}</span> : <span className="subaccount-category-price-state">+{rootMarkup}%</span>}
                </div>
                {children.length && expanded ? <div className="subaccount-category-pricing-children" role="group">
                  {children.map((child) => {
                    const childMarkup = categoryRulesById.get(child.id);
                    return <div className={`subaccount-category-pricing-node child${categoryId === child.id ? " is-selected" : ""}`} role="treeitem" aria-selected={categoryId === child.id} key={child.id}>
                      <button type="button" className="subaccount-category-pricing-node-main" onClick={() => selectCategory(child)}>
                        <Folder weight="duotone" />
                        <span><strong>{child.name}</strong><small>{t("{count} 个商品", { count: child.productCount })}{child.status !== "ACTIVE" ? ` · ${t("停用")}` : ""}</small></span>
                      </button>
                      {childMarkup == null ? <span className="subaccount-category-price-state is-inherited">{rootMarkup == null ? t("统一 +{value}%", { value: markup || "0" }) : t("继承 +{value}%", { value: rootMarkup })}</span> : <span className="subaccount-category-price-state">+{childMarkup}%</span>}
                    </div>;
                  })}
                </div> : null}
              </div>;
            })}
            {!rootCategories.length ? <div className="subaccount-category-pricing-empty"><TreeStructure size={26} /><strong>{t("还没有分类")}</strong><small>{t("请先在分类管理中创建分类。")}</small></div> : null}
          </div>
          <div className="subaccount-category-pricing-editor">
            {selectedCategory ? <>
              <div className="subaccount-category-pricing-editor-heading">
                <Text size="1" color="gray">{t(selectedCategory.parentId ? "二级分类" : "一级分类")}</Text>
                <Heading size="4">{selectedCategory.name}</Heading>
              </div>
              <label>
                <Text size="2" weight="medium">{t("加价百分比")}</Text>
                <TextField.Root type="number" min="0" max="100000" step="0.1" value={categoryMarkup} onChange={(event) => setCategoryDrafts((current) => ({ ...current, [categoryId]: event.target.value }))} placeholder={selectedCategory.parentId && selectedParentMarkup != null ? t("当前继承 +{value}%", { value: selectedParentMarkup }) : t("使用统一加价") } aria-label={t("分类加价百分比")} />
              </label>
              <Text className="subaccount-category-pricing-help" size="1" color="gray">
                {selectedCategory.parentId
                  ? selectedCategoryHasRule
                    ? t("该二级分类使用自己的规则，不再继承一级分类。")
                    : selectedParentMarkup == null
                      ? t("未单独设置时，使用子账号的统一加价。")
                      : t("当前继承一级分类的 +{value}% 加价。", { value: selectedParentMarkup })
                  : t("保存后，该规则会应用到本分类以及未单独设置的全部二级分类。")}
              </Text>
              <div className="subaccount-category-pricing-actions">
                <Button size="2" variant="ghost" color="gray" disabled={!selectedCategoryHasRule} onClick={clearCategoryRule}>{t("恢复继承")}</Button>
              </div>
            </> : <div className="subaccount-category-pricing-empty is-editor"><TreeStructure size={26} /><strong>{t("选择一个分类")}</strong><small>{t("点击左侧一级或二级分类设置加价。")}</small></div>}
          </div>
        </div>
      </section>
      <TextField.Root value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={t("搜索商品名称或编码") } />
      {error ? <Text color="red" size="2">{error}</Text> : null}
      {loading ? <CoreLoading label={t("正在读取商品价格")} /> : data?.items.length ? <div className="subaccount-pricing-table">
        <div className="subaccount-pricing-table-head"><span>{t("商品")}</span><span>{t("主账号价格")}</span><span>{t("子账号价格")}</span><span>{t("单品规则")}</span></div>
        {data.items.map((item) => <SubaccountPricingRow key={item.productId} item={item} busy={editingProduct === item.productId} skuBusy={editingSku} onSave={saveProductRule} onClear={clearProductRule} onSaveSku={saveSkuRule} onClearSku={clearSkuRule} />)}
      </div> : <CoreEmpty title={t("没有匹配商品")} description={t("先确认商品已经发布到前台。")} />}
      {data && data.total > data.pageSize ? <div className="subaccount-pricing-pagination">
        <Text size="1" color="gray">{t("第 {page} / {pages} 页", { page: data.page, pages: Math.ceil(data.total / data.pageSize) })}</Text>
        <div>
          <Button size="1" variant="soft" color="gray" disabled={loading || data.page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}><CaretLeft />{t("上一页")}</Button>
          <Button size="1" variant="soft" color="gray" disabled={loading || data.page >= Math.ceil(data.total / data.pageSize)} onClick={() => setPage((current) => Math.min(Math.ceil(data.total / data.pageSize), current + 1))}>{t("下一页")}<CaretRight /></Button>
        </div>
      </div> : null}
      <div className="core-dialog-actions"><Button variant="soft" color="gray" disabled={saving} onClick={onClose}>{t("关闭")}</Button><Button loading={saving} disabled={loading || !hasPricingChanges} onClick={() => void savePriceSettings()}><CurrencyDollar />{t("应用价格设置")}</Button></div>
    </Dialog.Content>
  </Dialog.Root>;
}

function SubaccountPricingRow({
  item,
  busy,
  skuBusy,
  onSave,
  onClear,
  onSaveSku,
  onClearSku,
}: {
  item: SubaccountPricingPage["items"][number];
  busy: boolean;
  skuBusy?: string;
  onSave: (productId: string, mode: SubaccountPricingMode, value: string) => Promise<void>;
  onClear: (productId: string) => Promise<void>;
  onSaveSku: (productId: string, skuId: string, mode: SubaccountPricingMode, value: string) => Promise<void>;
  onClearSku: (productId: string, skuId: string) => Promise<void>;
}) {
  const { t } = useLocale();
  const [mode, setMode] = useState<SubaccountPricingMode>(item.overrideMode || "MARKUP_PERCENT");
  const [value, setValue] = useState(item.overrideValue == null ? "" : String(item.overrideValue));
  const [showSkus, setShowSkus] = useState(false);
  useEffect(() => {
    setMode(item.overrideMode || "MARKUP_PERCENT");
    setValue(item.overrideValue == null ? "" : String(item.overrideValue));
  }, [item.overrideMode, item.overrideValue]);
  return <div className="subaccount-pricing-table-row">
    <div><strong>{item.productName}</strong><small>{item.productCode || "—"} · {item.categoryName || t("未分类")} · {t("{count} 个 SKU", { count: item.skuCount })}</small>{item.skuPrices.length ? <button type="button" className="subaccount-sku-price-toggle" onClick={() => setShowSkus((current) => !current)}>{showSkus ? t("收起 SKU 价格") : t("按 SKU 调整价格")} <CaretDown data-expanded={showSkus || undefined} /></button> : null}{showSkus ? <div className="subaccount-sku-price-list">{item.skuPrices.map((sku) => <SubaccountSkuPriceRuleRow key={sku.skuId} productId={item.productId} sku={sku} busy={skuBusy === sku.skuId} onSave={onSaveSku} onClear={onClearSku} />)}</div> : null}</div>
    <span>{item.basePriceFrom === item.basePriceTo ? `${item.currency} ${item.basePriceFrom}` : `${item.currency} ${item.basePriceFrom}–${item.basePriceTo}`}</span>
    <strong>{item.effectivePriceFrom === item.effectivePriceTo ? `${item.currency} ${item.effectivePriceFrom}` : `${item.currency} ${item.effectivePriceFrom}–${item.effectivePriceTo}`}</strong>
    <div className="subaccount-pricing-rule-editor">
      <select value={mode} onChange={(event) => setMode(event.target.value as SubaccountPricingMode)} aria-label={t("单品价格方式")}><option value="MARKUP_PERCENT">{t("加价百分比")}</option><option value="FIXED_PRICE">{t("统一固定价")}</option></select>
      <TextField.Root size="1" type="number" min="0" step="0.1" value={value} onChange={(event) => setValue(event.target.value)} placeholder="—" aria-label={t("单品价格数值")} />
      <Button size="1" loading={busy} onClick={() => void onSave(item.productId, mode, value)}>{t("应用")}</Button>
      {item.overrideMode ? <Button size="1" variant="ghost" color="gray" disabled={busy} onClick={() => void onClear(item.productId)}>{t("恢复")}</Button> : null}
    </div>
  </div>;
}

function SubaccountSkuPriceRuleRow({
  productId,
  sku,
  busy,
  onSave,
  onClear,
}: {
  productId: string;
  sku: SubaccountProductPricingItem["skuPrices"][number];
  busy: boolean;
  onSave: (productId: string, skuId: string, mode: SubaccountPricingMode, value: string) => Promise<void>;
  onClear: (productId: string, skuId: string) => Promise<void>;
}) {
  const { t } = useLocale();
  const [mode, setMode] = useState<SubaccountPricingMode>(sku.overrideMode || "MARKUP_PERCENT");
  const [value, setValue] = useState(sku.overrideValue == null ? "" : String(sku.overrideValue));
  useEffect(() => {
    setMode(sku.overrideMode || "MARKUP_PERCENT");
    setValue(sku.overrideValue == null ? "" : String(sku.overrideValue));
  }, [sku.overrideMode, sku.overrideValue]);
  return <div className="subaccount-sku-price-rule">
    <span className="mono-text" title={sku.skuCode}>{sku.skuCode}</span>
    <span>{sku.currency} {sku.basePrice.toFixed(2)}</span>
    <strong>{sku.currency} {sku.effectivePrice.toFixed(2)}</strong>
    <select value={mode} onChange={(event) => setMode(event.target.value as SubaccountPricingMode)} aria-label={t("SKU 价格方式")}>
      <option value="MARKUP_PERCENT">{t("加价 %")}</option>
      <option value="FIXED_PRICE">{t("固定价")}</option>
    </select>
    <TextField.Root size="1" type="number" min="0" step="0.1" value={value} onChange={(event) => setValue(event.target.value)} placeholder={t("继承")} aria-label={t("SKU 价格数值")} />
    <Button size="1" loading={busy} onClick={() => void onSave(productId, sku.skuId, mode, value)}>{t("应用")}</Button>
    {sku.overrideMode ? <Button size="1" variant="ghost" color="gray" disabled={busy} onClick={() => void onClear(productId, sku.skuId)}>{t("恢复")}</Button> : null}
  </div>;
}
