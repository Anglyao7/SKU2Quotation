import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  Heading,
  Tabs,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  Check,
  Eye,
  Key,
  LockKey,
  PencilSimple,
  Plus,
  ShieldCheck,
  UserGear,
  UsersThree,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  createTenantRole,
  listTenantMembers,
  listTenantPermissions,
  listTenantRoles,
  updateTenantMemberRoles,
  updateTenantRole,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { TenantMember, TenantPermission, TenantRole } from "../types";

const groups = [
  { name: "产品中心", keys: ["product.view", "product.create", "product.edit", "product.import", "product.cost.read", "product.cost.write"] },
  { name: "供应商中心", keys: ["supplier.view", "supplier.manage"] },
  { name: "销售工作流", keys: ["customer.view", "customer.manage", "inquiry.view", "inquiry.manage", "quotation.view", "quotation.create", "quotation.approve"] },
  { name: "产品图册与订单", keys: ["catalog.view", "catalog.publish", "order.view", "order.manage"] },
  { name: "进销存", keys: ["inventory.view", "inventory.adjust", "inventory.purchase", "inventory.sale", "inventory.transfer", "inventory.warehouse_manage"] },
  { name: "系统管理", keys: ["system.user_manage", "system.role_manage", "system.settings_manage"] },
];

const labels: Record<string, string> = {
  "product.view": "查看产品", "product.create": "创建产品", "product.edit": "编辑产品", "product.import": "导入产品", "product.cost.read": "查看产品成本", "product.cost.write": "维护产品成本",
  "supplier.view": "查看供应商", "supplier.manage": "管理供应商", "customer.view": "查看客户", "customer.manage": "管理客户", "inquiry.view": "查看询盘", "inquiry.manage": "管理询盘", "quotation.view": "查看报价", "quotation.create": "创建报价", "quotation.approve": "批准报价",
  "catalog.view": "查看产品图册", "catalog.publish": "发布产品图册", "order.view": "查看订单", "order.manage": "管理订单", "system.user_manage": "管理用户", "system.role_manage": "管理角色", "system.settings_manage": "管理系统设置",
  "inventory.view": "查看库存与流水", "inventory.adjust": "执行库存调整", "inventory.purchase": "管理采购与入库", "inventory.sale": "管理销售与出库", "inventory.transfer": "执行仓间调拨", "inventory.warehouse_manage": "管理仓库",
};

const moduleLabels: Record<string, string> = {
  product: "产品", supplier: "供应商", customer: "客户", inquiry: "询盘",
  quotation: "报价", catalog: "图册", order: "订单", inventory: "进销存", system: "系统",
};

const systemRoleLabels: Record<string, string> = {
  OWNER: "所有者",
  ADMIN: "管理员",
  SALES: "销售编辑",
  PURCHASING: "采购编辑",
  VIEWER: "只读成员",
};

const memberStatusLabels: Record<string, string> = {
  active: "已生效",
  invited: "待激活",
  suspended: "已停用",
};

function roleDisplayName(role: { code: string; name: string; isSystem: boolean }) {
  return role.isSystem ? systemRoleLabels[role.code] ?? role.name : role.name;
}

export function PermissionsPage() {
  const { permissions, profile } = useCoreAuth();
  const { t } = useLocale();
  const userName = profile?.user.displayName ?? t("当前成员");
  const tenantName = profile?.context.tenantName ?? t("当前工作区");
  const canReadMembers = permissions.has("system.user_manage") || permissions.has("system.role_manage");
  const canManageRoles = permissions.has("system.role_manage");
  const canAssignRoles = permissions.has("system.user_manage") && canManageRoles;
  const administrator = canReadMembers || permissions.has("system.settings_manage");
  const visibleGroups = groups.filter((group) => group.keys.some((key) => permissions.has(key))).length;
  const [members, setMembers] = useState<TenantMember[]>([]);
  const [roles, setRoles] = useState<TenantRole[]>([]);
  const [catalog, setCatalog] = useState<TenantPermission[]>([]);
  const [loading, setLoading] = useState(canReadMembers);
  const [error, setError] = useState("");
  const [roleEditor, setRoleEditor] = useState<TenantRole | null | undefined>(undefined);
  const [memberEditor, setMemberEditor] = useState<TenantMember | undefined>();

  const load = useCallback(async () => {
    if (!canReadMembers) return;
    setLoading(true);
    setError("");
    try {
      const [memberRows, roleRows, permissionRows] = await Promise.all([
        listTenantMembers(),
        canManageRoles ? listTenantRoles() : Promise.resolve([]),
        canManageRoles ? listTenantPermissions() : Promise.resolve([]),
      ]);
      setMembers(memberRows);
      setRoles(roleRows);
      setCatalog(permissionRows);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("访问控制数据加载失败"));
    } finally {
      setLoading(false);
    }
  }, [canManageRoles, canReadMembers, t]);

  useEffect(() => { void load(); }, [load]);

  const currentMembership = members.find((member) => member.id === profile?.context.membershipId);
  const actorIsOwner = currentMembership?.roles.some((role) => role.code === "OWNER") ?? false;

  return <div className="core-workspace">
    <CorePageHeading
      eyebrow={t("访问控制")}
      title={t("成员、角色与权限")}
      description={t("权限由服务端按当前商家成员关系执行；这里的所有变更都会立即刷新权限版本。")}
      actions={canManageRoles ? <Button onClick={() => setRoleEditor(null)}><Plus />{t("新建自定义角色")}</Button> : undefined}
    />
    <section className="core-permission-hero">
      <Card className="core-access-card"><div className="core-avatar">{userName.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase()}</div><div><Text size="1" color="gray">{t("当前有效成员")}</Text><Heading size="4">{userName}</Heading><Text size="2" color="gray">{tenantName}</Text></div><Badge color={administrator ? "jade" : "gray"}>{t(administrator ? "负责人 / 管理员权限" : "普通成员权限")}</Badge></Card>
      <div className="core-permission-overview"><Card><Key /><div><strong>{permissions.size}</strong><Text size="1">{t("已授权操作")}</Text></div></Card><Card><Eye /><div><strong>{visibleGroups}</strong><Text size="1">{t("可见工作区")}</Text></div></Card><Card><LockKey /><div><strong>{t("服务端")}</strong><Text size="1">{t("权限执行来源")}</Text></div></Card><Card><UserGear /><div><strong>{t(administrator ? "当前租户" : "已分配范围")}</strong><Text size="1">{t("当前数据范围")}</Text></div></Card></div>
    </section>

    {canReadMembers ? <Card className="core-access-management">
      <Tabs.Root defaultValue="members">
        <div className="core-access-management-head">
          <div><Text size="1" color="gray">{t("商家后台")}</Text><Heading size="5">{t("访问管理")}</Heading></div>
          <Tabs.List><Tabs.Trigger value="members">{t("成员")} {members.length}</Tabs.Trigger>{canManageRoles ? <Tabs.Trigger value="roles">{t("角色")} {roles.length}</Tabs.Trigger> : null}</Tabs.List>
        </div>
        {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
        {loading ? <CoreLoading label={t("正在读取成员与角色")} /> : null}
        {!loading && !error ? <>
          <Tabs.Content value="members">
            <div className="core-member-list">
              {members.map((member) => <div className="core-member-row" key={member.id}>
                <div className="core-member-identity"><div className="core-avatar small">{member.displayName.slice(0, 2).toUpperCase()}</div><span><strong>{member.displayName}</strong><small>{member.email ?? t("未绑定邮箱")} · {member.jobTitle ?? t("未设置职务")}</small></span></div>
                <div className="core-role-chip-row">{member.roles.map((role) => <Badge color={role.code === "OWNER" ? "amber" : role.isSystem ? "jade" : "gray"} key={role.id}>{t(roleDisplayName(role))}</Badge>)}{!member.roles.length ? <Badge color="red">{t("未分配角色")}</Badge> : null}</div>
                <span className="core-member-version"><small>{t("权限版本")}</small><strong>v{member.permissionVersion}</strong></span>
                <Badge color={member.status === "active" ? "green" : member.status === "invited" ? "blue" : "gray"}>{t(memberStatusLabels[member.status] ?? member.status)}</Badge>
                {canAssignRoles ? <Button variant="soft" color="gray" onClick={() => setMemberEditor(member)}><PencilSimple />{t("分配角色")}</Button> : null}
              </div>)}
            </div>
          </Tabs.Content>
          {canManageRoles ? <Tabs.Content value="roles">
            <div className="core-role-grid">
              {roles.map((role) => <Card className="core-role-card" key={role.id}>
                <div className="core-role-card-head"><span><Text size="1" color="gray">{role.code}</Text><Heading size="4">{t(roleDisplayName(role))}</Heading></span><Badge color={role.isSystem ? "jade" : "gray"}>{t(role.isSystem ? "系统角色" : "自定义")}</Badge></div>
                <Text size="2" color="gray">{role.description || t(role.isSystem ? "平台维护的稳定权限组合。" : "商家自定义角色。")}</Text>
                <div className="core-role-stats"><span><strong>{role.memberCount}</strong><small>{t("成员")}</small></span><span><strong>{role.permissionCodes.length}</strong><small>{t("权限")}</small></span></div>
                <div className="core-role-card-footer"><div className="core-role-chip-row">{role.permissionCodes.slice(0, 3).map((code) => <Badge color="gray" key={code}>{t(labels[code] ?? code)}</Badge>)}{role.permissionCodes.length > 3 ? <Badge color="gray">+{role.permissionCodes.length - 3}</Badge> : null}</div>{!role.isSystem ? <Button variant="ghost" color="gray" onClick={() => setRoleEditor(role)}><PencilSimple />{t("编辑")}</Button> : null}</div>
              </Card>)}
            </div>
          </Tabs.Content> : null}
        </> : null}
      </Tabs.Root>
    </Card> : null}

    <div className="core-permission-layout">
      <Card className="core-permission-matrix"><div className="core-panel-heading"><div><Text size="1" color="gray">{t("我的访问快照")}</Text><Heading size="4">{t("当前权限")}</Heading></div><Badge color="jade"><span className="core-live-dot" />{t("实时读取 /me/permissions")}</Badge></div>
        <div className="core-permission-groups">{groups.map((group) => <section key={group.name}><div className="core-permission-group-name"><Heading size="3">{t(group.name)}</Heading><Text size="1" color="gray">{t("已授予 {granted} / {total}", { granted: group.keys.filter((key) => permissions.has(key)).length, total: group.keys.length })}</Text></div><div className="core-permission-chips">{group.keys.map((key) => <div className={permissions.has(key) ? "granted" : "denied"} key={key}>{permissions.has(key) ? <Check /> : <X />}<span><Text weight="medium" as="div">{t(labels[key] ?? key)}</Text><code>{key}</code></span></div>)}</div></section>)}</div>
      </Card>
      <aside className="core-permission-aside"><Card><ShieldCheck size={28} /><Heading size="4">{t("权限边界")}</Heading><ol><li><b>{t("租户隔离")}</b><span>{t("成员、角色和数据都绑定当前商家。")}</span></li><li><b>{t("不可越权授权")}</b><span>{t("管理员只能委派自己已经拥有的权限。")}</span></li><li><b>{t("安全护栏")}</b><span>{t("系统角色不可编辑，并始终保留至少一位 OWNER。")}</span></li><li><b>{t("即时失效")}</b><span>{t("角色变化后旧权限令牌会立即失效。")}</span></li></ol></Card></aside>
    </div>

    {roleEditor !== undefined ? <RoleEditorDialog
      role={roleEditor}
      permissions={catalog.filter((permission) => permission.code !== "product.review" && permissions.has(permission.code))}
      onClose={() => setRoleEditor(undefined)}
      onSaved={async () => { setRoleEditor(undefined); await load(); }}
    /> : null}
    {memberEditor ? <MemberRoleDialog
      member={memberEditor}
      roles={roles}
      actorPermissions={permissions}
      actorIsOwner={actorIsOwner}
      onClose={() => setMemberEditor(undefined)}
      onSaved={async () => { setMemberEditor(undefined); await load(); }}
    /> : null}
  </div>;
}

function RoleEditorDialog({ role, permissions, onClose, onSaved }: {
  role: TenantRole | null;
  permissions: TenantPermission[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const [code, setCode] = useState(role?.code ?? "");
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set(role?.permissionCodes ?? []));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const grouped = useMemo(() => {
    const result = new Map<string, TenantPermission[]>();
    permissions.forEach((permission) => result.set(permission.module, [...(result.get(permission.module) ?? []), permission]));
    return [...result.entries()];
  }, [permissions]);

  const toggle = (permissionCode: string, checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(permissionCode); else next.delete(permissionCode);
      return next;
    });
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected.size) { setError(t("至少选择一项权限。")); return; }
    setSaving(true);
    setError("");
    try {
      if (role) await updateTenantRole(role.id, { name, description, permissionCodes: [...selected] });
      else await createTenantRole({ code, name, description, permissionCodes: [...selected] });
      await onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("角色保存失败"));
    } finally {
      setSaving(false);
    }
  };

  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="core-access-dialog">
      <form onSubmit={(event) => void submit(event)}>
        <div className="core-dialog-heading"><div><Text size="1" color="gray">{t(role ? "自定义角色" : "新角色")}</Text><Dialog.Title>{role ? t("编辑 {name}", { name: role.name }) : t("创建自定义角色")}</Dialog.Title><Dialog.Description>{t("只能选择你当前拥有的权限，服务端会再次校验授权边界。")}</Dialog.Description></div><Button type="button" variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}><X /></Button></div>
        <div className="core-access-role-fields">
          <label><Text size="1" color="gray">{t("角色代码")}</Text><TextField.Root value={code} disabled={Boolean(role)} onChange={(event) => setCode(event.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"))} required placeholder={t("例如 SALES_ASSISTANT")} /></label>
          <label><Text size="1" color="gray">{t("角色名称")}</Text><TextField.Root value={name} onChange={(event) => setName(event.target.value)} required placeholder={t("例如 销售助理")} /></label>
          <label className="wide"><Text size="1" color="gray">{t("说明")}</Text><TextArea value={description} onChange={(event) => setDescription(event.target.value)} placeholder={t("这个角色负责什么、不能做什么")} /></label>
        </div>
        <div className="core-access-permission-picker">
          {grouped.map(([module, rows]) => <section key={module}><div><Heading size="3">{t(moduleLabels[module] ?? module)}</Heading><Text size="1" color="gray">{rows.filter((row) => selected.has(row.code)).length} / {rows.length}</Text></div>{rows.map((permission) => <label key={permission.code}><Checkbox checked={selected.has(permission.code)} onCheckedChange={(checked) => toggle(permission.code, checked === true)} /><span><Text size="2" weight="medium">{t(labels[permission.code] ?? permission.code)}</Text><code>{permission.code}</code></span></label>)}</section>)}
        </div>
        {error ? <Text color="red" size="2">{error}</Text> : null}
        <div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={onClose}>{t("取消")}</Button><Button type="submit" disabled={saving}>{t(saving ? "保存中…" : role ? "保存角色" : "创建角色")}</Button></div>
      </form>
    </Dialog.Content>
  </Dialog.Root>;
}

function MemberRoleDialog({ member, roles, actorPermissions, actorIsOwner, onClose, onSaved }: {
  member: TenantMember;
  roles: TenantRole[];
  actorPermissions: ReadonlySet<string>;
  actorIsOwner: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const existingIds = new Set(member.roles.map((role) => role.id));
  const canDelegate = (role: TenantRole) => role.permissionCodes.every((code) => actorPermissions.has(code)) && (role.code !== "OWNER" || actorIsOwner);
  const visibleRoles = roles.filter((role) => canDelegate(role) || existingIds.has(role.id));
  const visibleIds = new Set(visibleRoles.map((role) => role.id));
  const lockedIds = new Set(visibleRoles.filter((role) => existingIds.has(role.id) && !canDelegate(role)).map((role) => role.id));
  const [selected, setSelected] = useState<Set<string>>(new Set(member.roles.map((role) => role.id).filter((id) => visibleIds.has(id))));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const toggle = (roleId: string, checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(roleId); else next.delete(roleId);
      return next;
    });
  };
  const save = async () => {
    if (!selected.size) { setError(t("成员至少需要一个角色。")); return; }
    setSaving(true);
    setError("");
    try {
      await updateTenantMemberRoles(member.id, [...selected]);
      await onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("角色分配失败"));
    } finally {
      setSaving(false);
    }
  };

  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="core-access-dialog compact">
      <div className="core-dialog-heading"><div><Text size="1" color="gray">{t("成员访问范围")}</Text><Dialog.Title>{t("为 {name} 分配角色", { name: member.displayName })}</Dialog.Title><Dialog.Description>{t("保存后，该成员现有权限令牌会立即失效并按新角色刷新。")}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}><X /></Button></div>
      <div className="core-member-role-picker">{visibleRoles.map((role) => {
        const locked = lockedIds.has(role.id);
        return <label key={role.id}><Checkbox checked={selected.has(role.id)} disabled={locked} onCheckedChange={(checked) => toggle(role.id, checked === true)} /><span><strong>{t(roleDisplayName(role))}</strong><small>{role.code} · {t("{count} 项权限", { count: role.permissionCodes.length })}{locked ? ` · ${t("仅 OWNER 可变更")}` : ""}</small></span><Badge color={locked ? "amber" : role.isSystem ? "jade" : "gray"}>{t(locked ? "受保护" : role.isSystem ? "系统" : "自定义")}</Badge></label>;
      })}</div>
      {!visibleRoles.length ? <Card className="core-state"><UsersThree /><Text size="2" color="gray">{t("没有可委派的角色。")}</Text></Card> : null}
      {error ? <Text color="red" size="2">{error}</Text> : null}
      <div className="core-dialog-actions"><Button variant="soft" color="gray" onClick={onClose}>{t("取消")}</Button><Button disabled={saving || !visibleRoles.length} onClick={() => void save()}>{t(saving ? "保存中…" : "保存角色分配")}</Button></div>
    </Dialog.Content>
  </Dialog.Root>;
}
