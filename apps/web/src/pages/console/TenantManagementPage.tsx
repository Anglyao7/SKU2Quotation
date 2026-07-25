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
import type { MemberInvitation, MemberInvitationPayload, Tenant, TenantPayload, TenantRoleCode } from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";

export function TenantManagementPage() {
  const { reloadTenants } = useOutletContext<ConsoleOutletContext>();
  const { t } = useLocale();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Tenant | "new" | null>(null);
  const [inviting, setInviting] = useState<Tenant | null>(null);
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
      <Callout.Root color="blue"><Callout.Icon><Info /></Callout.Icon><Callout.Text>{t("新增商家会创建独立租户与角色体系。请使用“邀请成员”登记经核验的邮箱和租户角色，再由运维在 Keycloak 开通同邮箱身份；邮箱验证完成后，成员首次登录会自动绑定工作区。")}</Callout.Text></Callout.Root>
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : loading ? <TableSkeleton /> : tenants.length === 0 ? (
        <EmptyState title={t("平台还没有商家")} description={t("创建首个商家后，即可上传 SKU 并开放商品前台。")} action={<Button onClick={() => setEditing("new")}><Plus size={17} />{t("新增商家")}</Button>} />
      ) : (
        <>
          <div className="desktop-table surface-panel">
            <Table.Root variant="surface" size="2">
              <Table.Header><Table.Row><Table.ColumnHeaderCell>{t("商家")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("前台地址")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>SKU</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("报价")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("状态")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("创建时间")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell justify="end">{t("操作")}</Table.ColumnHeaderCell></Table.Row></Table.Header>
              <Table.Body>{tenants.map((tenant) => (
                <Table.Row key={tenant.id}>
                  <Table.RowHeaderCell><Text size="2" weight="medium" as="div">{tenant.name}</Text><Text size="1" color="gray">{tenant.contact_email || t("未设置联系邮箱")}</Text></Table.RowHeaderCell>
                  <Table.Cell><Text className="mono-text" size="1">/{tenant.slug}</Text></Table.Cell>
                  <Table.Cell>{tenant.sku_count ?? 0}</Table.Cell><Table.Cell>{tenant.quote_count ?? 0}</Table.Cell>
                  <Table.Cell><Badge variant="soft" color={tenant.status === "active" ? "jade" : "gray"}>{t(tenant.status === "active" ? "启用" : "停用")}</Badge></Table.Cell>
                  <Table.Cell><Text size="1" color="gray">{dateTime(tenant.created_at)}</Text></Table.Cell>
                  <Table.Cell justify="end"><div className="table-actions"><Tooltip content={t("邀请成员")}><IconButton size="1" variant="ghost" color="gray" disabled={tenant.status !== "active"} aria-label={t("邀请 {name} 成员", { name: tenant.name })} onClick={() => setInviting(tenant)}><UserPlus size={17} /></IconButton></Tooltip><Tooltip content={t("查看前台")}><IconButton asChild size="1" variant="ghost" color="gray"><Link to={`/${tenant.slug}`} target="_blank" aria-label={t("查看 {name} 商品前台", { name: tenant.name })}><Eye size={17} /></Link></IconButton></Tooltip><Tooltip content={t("编辑")}><IconButton size="1" variant="ghost" color="gray" aria-label={t("编辑 {name}", { name: tenant.name })} onClick={() => setEditing(tenant)}><NotePencil size={17} /></IconButton></Tooltip><Tooltip content={t("停用")}><IconButton size="1" variant="ghost" color="red" aria-label={t("停用 {name}", { name: tenant.name })} onClick={() => setDeleting(tenant)}><Trash size={17} /></IconButton></Tooltip></div></Table.Cell>
                </Table.Row>
              ))}</Table.Body>
            </Table.Root>
          </div>
          <div className="mobile-data-list">{tenants.map((tenant) => <div className="mobile-data-card" key={tenant.id}><div className="mobile-card-heading"><div><Text as="div" size="3" weight="medium">{tenant.name}</Text><Text className="mono-text" size="1" color="gray">/{tenant.slug}</Text></div><Badge color={tenant.status === "active" ? "jade" : "gray"}>{t(tenant.status === "active" ? "启用" : "停用")}</Badge></div><Text size="2" color="gray">{t("{skus} 个 SKU / {quotes} 份报价", { skus: tenant.sku_count || 0, quotes: tenant.quote_count || 0 })}</Text><div className="mobile-card-footer"><div className="page-actions"><Button asChild size="1" variant="soft"><Link to={`/${tenant.slug}`}>{t("查看前台")}</Link></Button><Button size="1" variant="soft" disabled={tenant.status !== "active"} onClick={() => setInviting(tenant)}><UserPlus />{t("邀请成员")}</Button></div><div><IconButton variant="ghost" aria-label={t("编辑 {name}", { name: tenant.name })} onClick={() => setEditing(tenant)}><NotePencil /></IconButton><IconButton variant="ghost" color="red" aria-label={t("停用 {name}", { name: tenant.name })} onClick={() => setDeleting(tenant)}><Trash /></IconButton></div></div></div>)}</div>
        </>
      )}

      <TenantFormDialog tenant={editing} onOpenChange={(open) => { if (!open) setEditing(null); }} onSaved={async () => { setEditing(null); await Promise.all([load(), reloadTenants()]); }} />
      <MemberInvitationDialog tenant={inviting} onOpenChange={(open) => { if (!open) setInviting(null); }} />
      <AlertDialog.Root open={Boolean(deleting)} onOpenChange={(open) => { if (!open) setDeleting(null); }}><AlertDialog.Content><AlertDialog.Title>{t("停用这个商家？")}</AlertDialog.Title><AlertDialog.Description>{t("“{name}”的商品前台将停止访问，历史数据会保留，可在编辑商家时重新启用。", { name: deleting?.name ?? "" })}</AlertDialog.Description><div className="dialog-actions"><AlertDialog.Cancel><Button variant="soft" color="gray">{t("取消")}</Button></AlertDialog.Cancel><AlertDialog.Action><Button color="red" onClick={() => void remove()}>{t("确认停用")}</Button></AlertDialog.Action></div></AlertDialog.Content></AlertDialog.Root>
    </div>
  );
}

function MemberInvitationDialog({ tenant, onOpenChange }: { tenant: Tenant | null; onOpenChange: (open: boolean) => void }) {
  const { t } = useLocale();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<MemberInvitation | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tenant) return;
    setSaving(true);
    setError("");
    const data = new FormData(event.currentTarget);
    const payload: MemberInvitationPayload = {
      email: String(data.get("email") || "").trim().toLowerCase(),
      display_name: String(data.get("display_name") || "").trim(),
      role: String(data.get("role") || "OWNER") as TenantRoleCode,
    };
    try { setResult(await api.inviteTenantMember(tenant.id, payload)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : t("成员邀请创建失败。")); }
    finally { setSaving(false); }
  };
  const handleOpenChange = (open: boolean) => {
    if (!open) { setResult(null); setError(""); }
    onOpenChange(open);
  };
  return (
    <Dialog.Root open={Boolean(tenant)} onOpenChange={handleOpenChange}>
      <Dialog.Content>
        <Dialog.Title>{t("邀请商家成员")}</Dialog.Title>
        <Dialog.Description>{t("为“{name}”登记真实邮箱与租户角色。此操作不会创建本地密码。", { name: tenant?.name ?? "" })}</Dialog.Description>
        {result ? (
          <div className="dialog-form">
            <Callout.Root color="green"><Callout.Icon><CheckCircle /></Callout.Icon><Callout.Text>{t(result.identity_already_bound ? "该邮箱已有已验证身份，工作区权限已立即生效。" : "待验证邀请已创建。请由运维在 Keycloak 开通完全相同的邮箱，并完成邮箱验证后再让成员登录。")}</Callout.Text></Callout.Root>
            <Text size="2" color="gray">{t("邮箱：{email} · 角色：{role} · 状态：{status}", { email: result.email, role: result.role, status: t(result.membership_status === "active" ? "已生效" : "待身份验证") })}</Text>
            <div className="dialog-actions"><Dialog.Close><Button>{t("完成")}</Button></Dialog.Close></div>
          </div>
        ) : (
          <form className="dialog-form" onSubmit={submit} key={tenant?.id}>
            <label className="field-group"><Text size="2" weight="medium">{t("姓名")} *</Text><TextField.Root name="display_name" required maxLength={120} placeholder={t("例如 陈晓")} /></label>
            <label className="field-group"><Text size="2" weight="medium">{t("登录邮箱")} *</Text><TextField.Root name="email" type="email" required maxLength={320} placeholder="owner@company.com" /></label>
            <label className="field-group"><Text size="2" weight="medium">{t("租户角色")} *</Text><Select.Root name="role" defaultValue="OWNER"><Select.Trigger /><Select.Content><Select.Item value="OWNER">{t("所有者（OWNER）")}</Select.Item><Select.Item value="ADMIN">{t("管理员（ADMIN）")}</Select.Item><Select.Item value="SALES">{t("销售编辑（SALES）")}</Select.Item><Select.Item value="PURCHASING">{t("采购编辑（PURCHASING）")}</Select.Item><Select.Item value="VIEWER">{t("只读成员（VIEWER）")}</Select.Item></Select.Content></Select.Root></label>
            <Text size="1" color="gray">{t("同一邮箱只对应一个平台身份。已有歧义、停用或历史删除记录时，系统会拒绝并要求人工复核。")}</Text>
            {error && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root>}
            <div className="dialog-actions"><Dialog.Close><Button type="button" variant="soft" color="gray">{t("取消")}</Button></Dialog.Close><Button type="submit" loading={saving}>{t("创建邀请")}</Button></div>
          </form>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}

function TenantFormDialog({ tenant, onOpenChange, onSaved }: { tenant: Tenant | "new" | null; onOpenChange: (open: boolean) => void; onSaved: () => Promise<void> }) {
  const { t } = useLocale();
  const current = tenant && tenant !== "new" ? tenant : null;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSaving(true); setError("");
    const data = new FormData(event.currentTarget);
    const payload: TenantPayload = { name: String(data.get("name") || "").trim(), contact_email: String(data.get("contact_email") || "").trim(), active: String(data.get("status") || "active") === "active" };
    try { if (current) await api.updateTenant(current.id, payload); else await api.createTenant(payload); await onSaved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : t("商家保存失败。")); }
    finally { setSaving(false); }
  };
  return (
    <Dialog.Root open={Boolean(tenant)} onOpenChange={onOpenChange}><Dialog.Content><Dialog.Title>{t(current ? "编辑商家" : "新增商家")}</Dialog.Title><Dialog.Description>{t("商家拥有独立商品前台和租户数据空间；前台地址会根据商家名称自动生成。")}</Dialog.Description><form className="dialog-form" onSubmit={submit} key={current?.id || "new"}><label className="field-group"><Text size="2" weight="medium">{t("商家名称")} *</Text><TextField.Root name="name" required defaultValue={current?.name} placeholder={t("例如 海岸家居")} /><Text size="1" color="gray">{t("中文名称可直接用于前台路径；修改名称后，旧地址仍会自动跳转。")}</Text></label><label className="field-group"><Text size="2" weight="medium">{t("联系邮箱")}</Text><TextField.Root name="contact_email" type="email" defaultValue={current?.contact_email || ""} placeholder="ops@company.com" /></label><label className="field-group"><Text size="2" weight="medium">{t("状态")}</Text><Select.Root name="status" defaultValue={current?.status || "active"}><Select.Trigger /><Select.Content><Select.Item value="active">{t("启用")}</Select.Item><Select.Item value="inactive">{t("停用")}</Select.Item></Select.Content></Select.Root></label>{error && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root>}<div className="dialog-actions"><Dialog.Close><Button variant="soft" color="gray">{t("取消")}</Button></Dialog.Close><Button type="submit" loading={saving}>{t("保存商家")}</Button></div></form></Dialog.Content></Dialog.Root>
  );
}
