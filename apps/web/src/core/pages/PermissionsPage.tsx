import { Badge, Card, Heading, Text } from "@radix-ui/themes";
import { Check, Eye, Key, LockKey, ShieldCheck, UserGear, X } from "@phosphor-icons/react";
import { useCoreAuth } from "../AuthContext";
import { CorePageHeading } from "../CoreUi";

const groups = [
  { name: "产品中心", keys: ["product.view", "product.create", "product.edit", "product.import", "product.review", "product.cost.read", "product.cost.write"] },
  { name: "供应商中心", keys: ["supplier.view", "supplier.manage"] },
  { name: "销售工作流", keys: ["customer.view", "customer.manage", "inquiry.view", "inquiry.manage", "quotation.view", "quotation.create", "quotation.approve"] },
  { name: "产品图册与订单", keys: ["catalog.view", "catalog.publish", "order.view", "order.manage"] },
  { name: "系统管理", keys: ["system.user_manage", "system.role_manage", "system.settings_manage"] },
];

const labels: Record<string, string> = {
  "product.view": "查看产品", "product.create": "创建产品", "product.edit": "编辑产品", "product.import": "导入产品", "product.review": "审核产品", "product.cost.read": "查看产品成本", "product.cost.write": "维护产品成本",
  "supplier.view": "查看供应商", "supplier.manage": "管理供应商", "customer.view": "查看客户", "customer.manage": "管理客户", "inquiry.view": "查看询盘", "inquiry.manage": "管理询盘", "quotation.view": "查看报价", "quotation.create": "创建报价", "quotation.approve": "批准报价",
  "catalog.view": "查看产品图册", "catalog.publish": "发布产品图册", "order.view": "查看订单", "order.manage": "管理订单", "system.user_manage": "管理用户", "system.role_manage": "管理角色", "system.settings_manage": "管理系统设置",
};

export function PermissionsPage() {
  const { permissions, profile } = useCoreAuth();
  const userName = profile?.user.displayName ?? "当前成员";
  const tenantName = profile?.context.tenantName ?? "当前工作区";
  const administrator = permissions.has("system.role_manage") || permissions.has("system.settings_manage");
  const visibleGroups = groups.filter((group) => group.keys.some((key) => permissions.has(key))).length;

  return <div className="core-workspace">
    <CorePageHeading eyebrow="访问控制" title="权限边界，清晰可见" description="这里展示服务端为当前成员关系签发的权限集合；界面可见性永远不能替代 API 授权。" />
    <section className="core-permission-hero">
      <Card className="core-access-card"><div className="core-avatar">{userName.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase()}</div><div><Text size="1" color="gray">当前有效成员</Text><Heading size="4">{userName}</Heading><Text size="2" color="gray">{tenantName}</Text></div><Badge color={administrator ? "jade" : "gray"}>{administrator ? "负责人 / 管理员权限" : "普通成员权限"}</Badge></Card>
      <div className="core-permission-overview"><Card><Key /><div><strong>{permissions.size}</strong><Text size="1">已授权操作</Text></div></Card><Card><Eye /><div><strong>{visibleGroups}</strong><Text size="1">可见工作区</Text></div></Card><Card><LockKey /><div><strong>服务端</strong><Text size="1">权限执行来源</Text></div></Card><Card><UserGear /><div><strong>{administrator ? "当前租户" : "已分配范围"}</strong><Text size="1">当前数据范围</Text></div></Card></div>
    </section>
    <div className="core-permission-layout">
      <Card className="core-permission-matrix"><div className="core-panel-heading"><div><Text size="1" color="gray">当前访问快照</Text><Heading size="4">工作区权限</Heading></div><Badge color="jade"><span className="core-live-dot" />实时读取 /me/permissions</Badge></div>
        <div className="core-permission-groups">{groups.map((group) => <section key={group.name}><div className="core-permission-group-name"><Heading size="3">{group.name}</Heading><Text size="1" color="gray">已授予 {group.keys.filter((key) => permissions.has(key)).length} / {group.keys.length}</Text></div><div className="core-permission-chips">{group.keys.map((key) => <div className={permissions.has(key) ? "granted" : "denied"} key={key}>{permissions.has(key) ? <Check /> : <X />}<span><Text weight="medium" as="div">{labels[key] ?? key}</Text><code>{key}</code></span></div>)}</div></section>)}</div>
      </Card>
      <aside className="core-permission-aside"><Card><ShieldCheck size={28} /><Heading size="4">纵深防御</Heading><ol><li><b>导航守卫</b><span>只显示当前成员相关任务。</span></li><li><b>API 授权</b><span>服务端再次校验每个请求。</span></li><li><b>租户上下文</b><span>HttpOnly 会话中的成员关系决定可信租户。</span></li><li><b>PostgreSQL RLS</b><span>数据库策略提供最后一道边界。</span></li></ol></Card><Card className="core-notice"><ShieldCheck /><div><Text weight="bold" as="div">只读实现视图</Text><Text size="1" color="gray">角色编辑与审计历史需对应管理 API；这里不会模拟任何仅客户端生效的权限修改。</Text></div></Card></aside>
    </div>
  </div>;
}
