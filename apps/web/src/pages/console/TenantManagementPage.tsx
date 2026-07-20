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
import { Eye, Info, NotePencil, Plus, Trash, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { api } from "../../lib/api";
import { dateTime } from "../../lib/format";
import type { Tenant, TenantPayload } from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";

export function TenantManagementPage() {
  const { reloadTenants } = useOutletContext<ConsoleOutletContext>();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Tenant | "new" | null>(null);
  const [deleting, setDeleting] = useState<Tenant | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setTenants(await api.getTenants()); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "商家列表加载失败。"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const remove = async () => {
    if (!deleting) return;
    try { await api.deactivateTenant(deleting.id); setDeleting(null); await Promise.all([load(), reloadTenants()]); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "商家停用失败。"); setDeleting(null); }
  };

  return (
    <div className="console-page">
      <div className="page-heading-row"><div><Text size="2" color="gray">平台租户与前台入口</Text><Heading size="7">商家管理</Heading></div><Button onClick={() => setEditing("new")}><Plus size={18} />新增商家</Button></div>
      <Callout.Root color="blue"><Callout.Icon><Info /></Callout.Icon><Callout.Text>新增商家会创建独立租户并开通其商品前台，但不会自动伪造商家成员关系，因此不会立刻出现在工作区切换列表。平台管理员仍可在本页管理启停；商家成员需通过后续成员邀请流程加入后才能进入其工作台。</Callout.Text></Callout.Root>
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : loading ? <TableSkeleton /> : tenants.length === 0 ? (
        <EmptyState title="平台还没有商家" description="创建首个商家后，即可上传 SKU 并开放商品前台。" action={<Button onClick={() => setEditing("new")}><Plus size={17} />新增商家</Button>} />
      ) : (
        <>
          <div className="desktop-table surface-panel">
            <Table.Root variant="surface" size="2">
              <Table.Header><Table.Row><Table.ColumnHeaderCell>商家</Table.ColumnHeaderCell><Table.ColumnHeaderCell>前台地址</Table.ColumnHeaderCell><Table.ColumnHeaderCell>SKU</Table.ColumnHeaderCell><Table.ColumnHeaderCell>报价</Table.ColumnHeaderCell><Table.ColumnHeaderCell>状态</Table.ColumnHeaderCell><Table.ColumnHeaderCell>创建时间</Table.ColumnHeaderCell><Table.ColumnHeaderCell justify="end">操作</Table.ColumnHeaderCell></Table.Row></Table.Header>
              <Table.Body>{tenants.map((tenant) => (
                <Table.Row key={tenant.id}>
                  <Table.RowHeaderCell><Text size="2" weight="medium" as="div">{tenant.name}</Text><Text size="1" color="gray">{tenant.contact_email || "未设置联系邮箱"}</Text></Table.RowHeaderCell>
                  <Table.Cell><Text className="mono-text" size="1">/{tenant.slug}</Text></Table.Cell>
                  <Table.Cell>{tenant.sku_count ?? 0}</Table.Cell><Table.Cell>{tenant.quote_count ?? 0}</Table.Cell>
                  <Table.Cell><Badge variant="soft" color={tenant.status === "active" ? "jade" : "gray"}>{tenant.status === "active" ? "启用" : "停用"}</Badge></Table.Cell>
                  <Table.Cell><Text size="1" color="gray">{dateTime(tenant.created_at)}</Text></Table.Cell>
                  <Table.Cell justify="end"><div className="table-actions"><Tooltip content="查看前台"><IconButton asChild size="1" variant="ghost" color="gray"><Link to={`/${tenant.slug}`} target="_blank" aria-label={`查看 ${tenant.name} 商品前台`}><Eye size={17} /></Link></IconButton></Tooltip><Tooltip content="编辑"><IconButton size="1" variant="ghost" color="gray" aria-label={`编辑 ${tenant.name}`} onClick={() => setEditing(tenant)}><NotePencil size={17} /></IconButton></Tooltip><Tooltip content="停用"><IconButton size="1" variant="ghost" color="red" aria-label={`停用 ${tenant.name}`} onClick={() => setDeleting(tenant)}><Trash size={17} /></IconButton></Tooltip></div></Table.Cell>
                </Table.Row>
              ))}</Table.Body>
            </Table.Root>
          </div>
          <div className="mobile-data-list">{tenants.map((tenant) => <div className="mobile-data-card" key={tenant.id}><div className="mobile-card-heading"><div><Text as="div" size="3" weight="medium">{tenant.name}</Text><Text className="mono-text" size="1" color="gray">/{tenant.slug}</Text></div><Badge color={tenant.status === "active" ? "jade" : "gray"}>{tenant.status === "active" ? "启用" : "停用"}</Badge></div><Text size="2" color="gray">{tenant.sku_count || 0} 个 SKU / {tenant.quote_count || 0} 份报价</Text><div className="mobile-card-footer"><Button asChild size="1" variant="soft"><Link to={`/${tenant.slug}`}>查看前台</Link></Button><div><IconButton variant="ghost" aria-label={`编辑 ${tenant.name}`} onClick={() => setEditing(tenant)}><NotePencil /></IconButton><IconButton variant="ghost" color="red" aria-label={`停用 ${tenant.name}`} onClick={() => setDeleting(tenant)}><Trash /></IconButton></div></div></div>)}</div>
        </>
      )}

      <TenantFormDialog tenant={editing} onOpenChange={(open) => { if (!open) setEditing(null); }} onSaved={async () => { setEditing(null); await Promise.all([load(), reloadTenants()]); }} />
      <AlertDialog.Root open={Boolean(deleting)} onOpenChange={(open) => { if (!open) setDeleting(null); }}><AlertDialog.Content><AlertDialog.Title>停用这个商家？</AlertDialog.Title><AlertDialog.Description>“{deleting?.name}”的商品前台将停止访问，历史数据会保留，可在编辑商家时重新启用。</AlertDialog.Description><div className="dialog-actions"><AlertDialog.Cancel><Button variant="soft" color="gray">取消</Button></AlertDialog.Cancel><AlertDialog.Action><Button color="red" onClick={() => void remove()}>确认停用</Button></AlertDialog.Action></div></AlertDialog.Content></AlertDialog.Root>
    </div>
  );
}

function TenantFormDialog({ tenant, onOpenChange, onSaved }: { tenant: Tenant | "new" | null; onOpenChange: (open: boolean) => void; onSaved: () => Promise<void> }) {
  const current = tenant && tenant !== "new" ? tenant : null;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSaving(true); setError("");
    const data = new FormData(event.currentTarget);
    const payload: TenantPayload = { name: String(data.get("name") || "").trim(), slug: current?.slug || String(data.get("slug") || "").trim(), contact_email: String(data.get("contact_email") || "").trim(), active: String(data.get("status") || "active") === "active" };
    try { if (current) await api.updateTenant(current.id, payload); else await api.createTenant(payload); await onSaved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "商家保存失败。"); }
    finally { setSaving(false); }
  };
  return (
    <Dialog.Root open={Boolean(tenant)} onOpenChange={onOpenChange}><Dialog.Content><Dialog.Title>{current ? "编辑商家" : "新增商家"}</Dialog.Title><Dialog.Description>商家拥有独立商品前台和租户数据空间。</Dialog.Description><form className="dialog-form" onSubmit={submit} key={current?.id || "new"}><label className="field-group"><Text size="2" weight="medium">商家名称 *</Text><TextField.Root name="name" required defaultValue={current?.name} placeholder="例如 海岸家居" /></label><label className="field-group"><Text size="2" weight="medium">前台标识 *</Text><TextField.Root name="slug" required minLength={3} pattern="[a-z0-9][a-z0-9-]{1,78}[a-z0-9]" defaultValue={current?.slug} placeholder="coastal-home" disabled={Boolean(current)} /><Text size="1" color="gray">{current ? "创建后不可修改，避免已有前台链接失效" : "仅使用小写字母、数字和连字符"}</Text></label><label className="field-group"><Text size="2" weight="medium">联系邮箱</Text><TextField.Root name="contact_email" type="email" defaultValue={current?.contact_email || ""} placeholder="ops@company.com" /></label><label className="field-group"><Text size="2" weight="medium">状态</Text><Select.Root name="status" defaultValue={current?.status || "active"}><Select.Trigger /><Select.Content><Select.Item value="active">启用</Select.Item><Select.Item value="inactive">停用</Select.Item></Select.Content></Select.Root></label>{error && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root>}<div className="dialog-actions"><Dialog.Close><Button variant="soft" color="gray">取消</Button></Dialog.Close><Button type="submit" loading={saving}>保存商家</Button></div></form></Dialog.Content></Dialog.Root>
  );
}
