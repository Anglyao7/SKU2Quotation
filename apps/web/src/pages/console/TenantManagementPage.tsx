import {
  AlertDialog,
  Badge,
  Button,
  Callout,
  Dialog,
  Heading,
  IconButton,
  Select,
  Table,
  Text,
  TextField,
  Tooltip,
} from "@radix-ui/themes";
import { CheckCircle, Eye, Info, NotePencil, Plus, Trash, UserPlus, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useLocale } from "../../core/LocaleContext";
import { api } from "../../lib/api";
import { dateTime } from "../../lib/format";
import type { MerchantOwnerAccount, MerchantOwnerAccountPayload, Tenant, TenantPayload } from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";

export function TenantManagementPage() {
  const { reloadTenants } = useOutletContext<ConsoleOutletContext>();
  const { t } = useLocale();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Tenant | "new" | null>(null);
  const [ownerSetup, setOwnerSetup] = useState<Tenant | null>(null);
  const [deleting, setDeleting] = useState<Tenant | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setTenants(await api.getTenants()); }
    catch (caught) { setError(caught instanceof Error ? caught.message : t("商家列表加载失败。")); }
    finally { setLoading(false); }
  }, [t]);
  useEffect(() => { void load(); }, [load]);

  const remove = async () => {
    if (!deleting) return;
    try { await api.deactivateTenant(deleting.id); setDeleting(null); await Promise.all([load(), reloadTenants()]); }
    catch (caught) { setError(caught instanceof Error ? caught.message : t("商家停用失败。")); setDeleting(null); }
  };

  return (
    <div className="console-page">
      <div className="page-heading-row"><div><Text size="2" color="gray">{t("平台租户与前台入口")}</Text><Heading size="7">{t("商家管理")}</Heading></div><Button onClick={() => setEditing("new")}><Plus size={18} />{t("新增商家")}</Button></div>
      <Callout.Root color="blue"><Callout.Icon><Info /></Callout.Icon><Callout.Text>{t("新增商家时请一并开通主账号。主账号使用账号、邮箱或手机号加密码登录，并自动获得该商家的所有者权限。")}</Callout.Text></Callout.Root>
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : loading ? <TableSkeleton /> : tenants.length === 0 ? (
        <EmptyState title={t("平台还没有商家")} description={t("创建首个商家后，即可上传 SKU 并开放商品前台。")} action={<Button onClick={() => setEditing("new")}><Plus size={17} />{t("新增商家")}</Button>} />
      ) : (
        <>
          <div className="desktop-table surface-panel">
            <Table.Root variant="surface" size="2">
              <Table.Header><Table.Row><Table.ColumnHeaderCell>{t("商家")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("前台地址")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>SKU</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("报价")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("状态")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("创建时间")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell justify="end">{t("操作")}</Table.ColumnHeaderCell></Table.Row></Table.Header>
              <Table.Body>{tenants.map((tenant) => (
                <Table.Row key={tenant.id}>
                  <Table.RowHeaderCell><Text size="2" weight="medium" as="div">{tenant.name}</Text><Text size="1" color="gray">{tenant.contact_email || t("未设置联系邮箱")}</Text>{tenant.owner_account ? <Text size="1" color="gray">{t("主账号：{account}", { account: tenant.owner_account.login_identifier || tenant.owner_account.email || t("待完善") })}</Text> : <Text size="1" color="amber">{t("尚未开通主账号")}</Text>}</Table.RowHeaderCell>
                  <Table.Cell><Text className="mono-text" size="1">/{tenant.slug}</Text></Table.Cell>
                  <Table.Cell>{tenant.sku_count ?? 0}</Table.Cell><Table.Cell>{tenant.quote_count ?? 0}</Table.Cell>
                  <Table.Cell><Badge variant="soft" color={tenant.status === "active" ? "jade" : "gray"}>{t(tenant.status === "active" ? "启用" : "停用")}</Badge></Table.Cell>
                  <Table.Cell><Text size="1" color="gray">{dateTime(tenant.created_at)}</Text></Table.Cell>
                  <Table.Cell justify="end"><div className="table-actions">{tenant.owner_account?.status === "active" ? null : <Tooltip content={t("开通主账号")}><IconButton size="1" variant="ghost" color="jade" disabled={tenant.status !== "active"} aria-label={t("为 {name} 开通主账号", { name: tenant.name })} onClick={() => setOwnerSetup(tenant)}><UserPlus size={17} /></IconButton></Tooltip>}<Tooltip content={t("查看前台")}><IconButton asChild size="1" variant="ghost" color="gray"><Link to={`/${tenant.slug}`} target="_blank" aria-label={t("查看 {name} 商品前台", { name: tenant.name })}><Eye size={17} /></Link></IconButton></Tooltip><Tooltip content={t("编辑")}><IconButton size="1" variant="ghost" color="gray" aria-label={t("编辑 {name}", { name: tenant.name })} onClick={() => setEditing(tenant)}><NotePencil size={17} /></IconButton></Tooltip><Tooltip content={t("停用")}><IconButton size="1" variant="ghost" color="red" aria-label={t("停用 {name}", { name: tenant.name })} onClick={() => setDeleting(tenant)}><Trash size={17} /></IconButton></Tooltip></div></Table.Cell>
                </Table.Row>
              ))}</Table.Body>
            </Table.Root>
          </div>
          <div className="mobile-data-list">{tenants.map((tenant) => <div className="mobile-data-card" key={tenant.id}><div className="mobile-card-heading"><div><Text as="div" size="3" weight="medium">{tenant.name}</Text><Text className="mono-text" size="1" color="gray">/{tenant.slug}</Text><Text size="1" color={tenant.owner_account ? "gray" : "amber"}>{tenant.owner_account ? t("主账号：{account}", { account: tenant.owner_account.login_identifier || tenant.owner_account.email || t("待完善") }) : t("尚未开通主账号")}</Text></div><Badge color={tenant.status === "active" ? "jade" : "gray"}>{t(tenant.status === "active" ? "启用" : "停用")}</Badge></div><Text size="2" color="gray">{t("{skus} 个 SKU / {quotes} 份报价", { skus: tenant.sku_count || 0, quotes: tenant.quote_count || 0 })}</Text><div className="mobile-card-footer"><div className="page-actions"><Button asChild size="1" variant="soft"><Link to={`/${tenant.slug}`}>{t("查看前台")}</Link></Button>{tenant.owner_account?.status === "active" ? null : <Button size="1" variant="soft" color="jade" disabled={tenant.status !== "active"} onClick={() => setOwnerSetup(tenant)}><UserPlus />{t("开通主账号")}</Button>}</div><div><IconButton variant="ghost" aria-label={t("编辑 {name}", { name: tenant.name })} onClick={() => setEditing(tenant)}><NotePencil /></IconButton><IconButton variant="ghost" color="red" aria-label={t("停用 {name}", { name: tenant.name })} onClick={() => setDeleting(tenant)}><Trash /></IconButton></div></div></div>)}</div>
        </>
      )}

      <TenantFormDialog tenant={editing} onOpenChange={(open) => { if (!open) setEditing(null); }} onChanged={async () => { await Promise.all([load(), reloadTenants()]); }} />
      <MerchantOwnerDialog tenant={ownerSetup} onOpenChange={(open) => { if (!open) setOwnerSetup(null); }} onSaved={async () => { await Promise.all([load(), reloadTenants()]); }} />
      <AlertDialog.Root open={Boolean(deleting)} onOpenChange={(open) => { if (!open) setDeleting(null); }}><AlertDialog.Content><AlertDialog.Title>{t("停用这个商家？")}</AlertDialog.Title><AlertDialog.Description>{t("“{name}”的商品前台将停止访问，历史数据会保留，可在编辑商家时重新启用。", { name: deleting?.name ?? "" })}</AlertDialog.Description><div className="dialog-actions"><AlertDialog.Cancel><Button variant="soft" color="gray">{t("取消")}</Button></AlertDialog.Cancel><AlertDialog.Action><Button color="red" onClick={() => void remove()}>{t("确认停用")}</Button></AlertDialog.Action></div></AlertDialog.Content></AlertDialog.Root>
    </div>
  );
}

function MerchantOwnerDialog({ tenant, onOpenChange, onSaved }: { tenant: Tenant | null; onOpenChange: (open: boolean) => void; onSaved: () => Promise<void> }) {
  const { t } = useLocale();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<MerchantOwnerAccount | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tenant) return;
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password") || "");
    if (password !== String(data.get("password_confirmation") || "")) {
      setError(t("两次输入的密码不一致。"));
      return;
    }
    const payload: MerchantOwnerAccountPayload = {
      display_name: String(data.get("display_name") || "").trim(),
      login_identifier: String(data.get("login_identifier") || "").trim(),
      password,
      email: String(data.get("email") || "").trim() || undefined,
    };
    setSaving(true);
    setError("");
    try {
      setResult(await api.provisionMerchantOwner(tenant.id, payload));
      await onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("主账号开通失败。"));
    } finally {
      setSaving(false);
    }
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) { setResult(null); setError(""); }
    onOpenChange(open);
  };

  return <Dialog.Root open={Boolean(tenant)} onOpenChange={handleOpenChange}>
    <Dialog.Content>
      <Dialog.Title>{t("开通商家主账号")}</Dialog.Title>
      <Dialog.Description>{t("为“{name}”创建可直接登录的所有者账号。该账号拥有本商家的完整管理权限。", { name: tenant?.name ?? "" })}</Dialog.Description>
      {result ? <div className="dialog-form">
        <Callout.Root color="green"><Callout.Icon><CheckCircle /></Callout.Icon><Callout.Text>{t("主账号已开通，可以立即登录工作台。")}</Callout.Text></Callout.Root>
        <Text size="2" color="gray">{t("登录账号：{account}", { account: result.login_identifier || result.email || "—" })}</Text>
        <Text size="1" color="gray">{t("密码不会被系统再次展示，请使用刚刚设置的密码登录。")}</Text>
        <div className="dialog-actions"><Dialog.Close><Button>{t("完成")}</Button></Dialog.Close></div>
      </div> : <form className="dialog-form" onSubmit={submit} key={tenant?.id}>
        <label className="field-group"><Text size="2" weight="medium">{t("主账号姓名")} *</Text><TextField.Root name="display_name" required maxLength={120} placeholder={t("例如 陈晓")} /></label>
        <label className="field-group"><Text size="2" weight="medium">{t("登录账号")} *</Text><TextField.Root name="login_identifier" required minLength={2} maxLength={320} autoCapitalize="none" placeholder={t("账号、邮箱或手机号")} /><Text size="1" color="gray">{t("对方可使用这个账号登录；邮箱或手机号也可以作为账号。")}</Text></label>
        <label className="field-group"><Text size="2" weight="medium">{t("联系邮箱（可选）")}</Text><TextField.Root name="email" type="email" maxLength={320} placeholder="owner@company.com" /></label>
        <label className="field-group"><Text size="2" weight="medium">{t("初始密码")} *</Text><TextField.Root name="password" type="password" required minLength={8} maxLength={128} autoComplete="new-password" placeholder={t("至少 8 位，包含字母和数字")} /></label>
        <label className="field-group"><Text size="2" weight="medium">{t("确认初始密码")} *</Text><TextField.Root name="password_confirmation" type="password" required minLength={8} maxLength={128} autoComplete="new-password" /></label>
        <Text size="1" color="gray">{t("请通过可靠渠道将账号和初始密码交给商家；密码创建后不会再次显示。")}</Text>
        {error ? <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root> : null}
        <div className="dialog-actions"><Dialog.Close><Button type="button" variant="soft" color="gray">{t("取消")}</Button></Dialog.Close><Button type="submit" loading={saving}><UserPlus />{t("确认开通")}</Button></div>
      </form>}
    </Dialog.Content>
  </Dialog.Root>;
}

function TenantFormDialog({ tenant, onOpenChange, onChanged }: { tenant: Tenant | "new" | null; onOpenChange: (open: boolean) => void; onChanged: () => Promise<void> }) {
  const { t } = useLocale();
  const current = tenant && tenant !== "new" ? tenant : null;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [createdTenant, setCreatedTenant] = useState<Tenant | null>(null);
  const [createdOwner, setCreatedOwner] = useState<MerchantOwnerAccount | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    let merchantWasCreated = false;
    const password = String(data.get("owner_password") || "");
    if (!current && password !== String(data.get("owner_password_confirmation") || "")) {
      setError(t("两次输入的密码不一致。"));
      return;
    }
    const payload: TenantPayload = {
      name: String(data.get("name") || "").trim(),
      contact_email: String(data.get("contact_email") || "").trim(),
      active: String(data.get("status") || "active") === "active",
    };
    setSaving(true);
    setError("");
    try {
      if (current) {
        await api.updateTenant(current.id, payload);
        await onChanged();
        onOpenChange(false);
        return;
      }
      const merchant = createdTenant || await api.createTenant(payload);
      merchantWasCreated = !createdTenant;
      setCreatedTenant(merchant);
      const owner = await api.provisionMerchantOwner(merchant.id, {
        display_name: String(data.get("owner_display_name") || "").trim(),
        login_identifier: String(data.get("owner_login_identifier") || "").trim(),
        password,
        email: String(data.get("owner_email") || "").trim() || undefined,
      });
      setCreatedOwner(owner);
      await onChanged();
    } catch (caught) {
      if (!current && (createdTenant || merchantWasCreated)) {
        setError(t("商家已创建，但主账号尚未开通。请修正账号信息后再次提交，或关闭后从列表中开通。"));
      } else {
        setError(caught instanceof Error ? caught.message : t("商家保存失败。"));
      }
    } finally {
      setSaving(false);
    }
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) { setError(""); setCreatedTenant(null); setCreatedOwner(null); }
    onOpenChange(open);
  };

  return <Dialog.Root open={Boolean(tenant)} onOpenChange={handleOpenChange}>
    <Dialog.Content>
      <Dialog.Title>{t(current ? "编辑商家" : "新增商家")}</Dialog.Title>
      <Dialog.Description>{t(current ? "修改商家资料和前台地址。" : "创建商家工作区，并同步开通可登录的主账号。")}</Dialog.Description>
      {createdOwner ? <div className="dialog-form">
        <Callout.Root color="green"><Callout.Icon><CheckCircle /></Callout.Icon><Callout.Text>{t("商家与主账号均已创建。")}</Callout.Text></Callout.Root>
        <Text size="2" color="gray">{t("登录账号：{account}", { account: createdOwner.login_identifier || createdOwner.email || "—" })}</Text>
        <Text size="1" color="gray">{t("请使用刚刚设置的密码登录；密码不会再次显示。")}</Text>
        <div className="dialog-actions"><Dialog.Close><Button>{t("完成")}</Button></Dialog.Close></div>
      </div> : <form className="dialog-form" onSubmit={submit} key={current?.id || "new"}>
        <label className="field-group"><Text size="2" weight="medium">{t("商家名称")} *</Text><TextField.Root name="name" required defaultValue={current?.name} disabled={Boolean(createdTenant)} placeholder={t("例如 海岸家居")} /><Text size="1" color="gray">{t("中文名称可直接用于前台路径；修改名称后，旧地址仍会自动跳转。")}</Text></label>
        <label className="field-group"><Text size="2" weight="medium">{t("联系邮箱")}</Text><TextField.Root name="contact_email" type="email" disabled={Boolean(createdTenant)} defaultValue={current?.contact_email || ""} placeholder="ops@company.com" /></label>
        <label className="field-group"><Text size="2" weight="medium">{t("状态")}</Text><Select.Root name="status" defaultValue={current?.status || "active"} disabled={Boolean(createdTenant)}><Select.Trigger /><Select.Content><Select.Item value="active">{t("启用")}</Select.Item><Select.Item value="inactive">{t("停用")}</Select.Item></Select.Content></Select.Root></label>
        {!current ? <><Text size="2" weight="medium">{t("商家主账号")}</Text><label className="field-group"><Text size="2" weight="medium">{t("主账号姓名")} *</Text><TextField.Root name="owner_display_name" required maxLength={120} placeholder={t("例如 陈晓")} /></label><label className="field-group"><Text size="2" weight="medium">{t("登录账号")} *</Text><TextField.Root name="owner_login_identifier" required minLength={2} maxLength={320} autoCapitalize="none" placeholder={t("账号、邮箱或手机号")} /></label><label className="field-group"><Text size="2" weight="medium">{t("主账号邮箱（可选）")}</Text><TextField.Root name="owner_email" type="email" maxLength={320} placeholder="owner@company.com" /></label><label className="field-group"><Text size="2" weight="medium">{t("初始密码")} *</Text><TextField.Root name="owner_password" type="password" required minLength={8} maxLength={128} autoComplete="new-password" placeholder={t("至少 8 位，包含字母和数字")} /></label><label className="field-group"><Text size="2" weight="medium">{t("确认初始密码")} *</Text><TextField.Root name="owner_password_confirmation" type="password" required minLength={8} maxLength={128} autoComplete="new-password" /></label><Text size="1" color="gray">{t("密码创建后不会再次显示，请通过可靠渠道交给商家。")}</Text></> : null}
        {error ? <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root> : null}
        <div className="dialog-actions"><Dialog.Close><Button type="button" variant="soft" color="gray">{t("取消")}</Button></Dialog.Close><Button type="submit" loading={saving}>{t(current ? "保存商家" : createdTenant ? "继续开通主账号" : "创建商家并开通账号")}</Button></div>
      </form>}
    </Dialog.Content>
  </Dialog.Root>;
}
