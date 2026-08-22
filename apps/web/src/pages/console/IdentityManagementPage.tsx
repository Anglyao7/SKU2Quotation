import {
  AlertDialog,
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
  IdentificationCard,
  LockSimple,
  Plus,
  Trash,
  UsersThree,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { ErrorState, TableSkeleton } from "../../components/States";
import { useLocale } from "../../core/LocaleContext";
import { ToastNotice } from "../../core/ToastContext";
import { api } from "../../lib/api";
import type {
  MerchantIdentityProfile,
  TenantModuleCode,
} from "../../types";

const MODULES: Array<{ code: TenantModuleCode; label: string }> = [
  { code: "products", label: "商品中心" },
  { code: "analytics", label: "网站监测" },
  { code: "inventory", label: "进销存" },
  { code: "announcements", label: "公告管理" },
  { code: "support", label: "客服管理" },
  { code: "support_ai", label: "AI 智能客服" },
  { code: "inquiries", label: "询盘" },
  { code: "quotations", label: "报价" },
  { code: "subaccounts", label: "子账号" },
];

const ALL_MODULES = MODULES.map((item) => item.code);

export function IdentityManagementPage() {
  const { t } = useLocale();
  const [identities, setIdentities] = useState<MerchantIdentityProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<MerchantIdentityProfile | "new" | null>(null);
  const [deleting, setDeleting] = useState<MerchantIdentityProfile | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setIdentities(await api.getMerchantIdentities());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("身份列表加载失败。"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const remove = async () => {
    if (!deleting) return;
    try {
      await api.deleteMerchantIdentity(deleting.code);
      setDeleting(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("身份删除失败。"));
      setDeleting(null);
    }
  };

  return <div className="console-page identity-management-page">
    <div className="page-heading-row">
      <div>
        <Text size="2" color="gray">{t("权限模板")}</Text>
        <Heading size="7">{t("身份管理")}</Heading>
      </div>
      <Button onClick={() => setEditing("new")}><Plus />{t("新增身份")}</Button>
    </div>

    {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
    {loading ? <TableSkeleton /> : <div className="identity-profile-grid">
      {identities.map((identity) => {
        const administrator = identity.code === "ADMIN";
        return <Card className={administrator ? "identity-profile-card is-admin" : "identity-profile-card"} key={identity.code}>
          <div className="identity-profile-heading">
            <span className="identity-profile-icon">{administrator ? <LockSimple /> : <IdentificationCard />}</span>
            <div>
              <Heading size="4">{t(identity.name)}</Heading>
              <Text size="1" color="gray">{identity.code}</Text>
            </div>
            <Badge color={administrator ? "amber" : identity.is_system ? "blue" : "gray"}>
              {t(administrator ? "固定全权限" : identity.is_system ? "系统身份" : "自定义身份")}
            </Badge>
          </div>
          <div className="identity-module-tags">
            {MODULES.filter((module) => identity.enabled_modules.includes(module.code)).map((module) => (
              <span key={module.code}>{t(module.label)}</span>
            ))}
          </div>
          <div className="identity-profile-actions">
            {administrator ? <Text size="1" color="gray">{t("管理员始终可见全部模块，无需调整。")}</Text> : <Button variant="soft" onClick={() => setEditing(identity)}>{t("编辑权限")}</Button>}
            {!identity.is_system ? <Button variant="ghost" color="red" onClick={() => setDeleting(identity)}><Trash />{t("删除")}</Button> : null}
          </div>
        </Card>;
      })}

      <Card className="identity-profile-card is-subaccount">
        <div className="identity-profile-heading">
          <span className="identity-profile-icon"><UsersThree /></span>
          <div><Heading size="4">{t("子账号")}</Heading><Text size="1" color="gray">SUBACCOUNT</Text></div>
          <Badge color="jade">{t("账号级身份")}</Badge>
        </div>
        <div className="identity-module-tags">
          <span>{t("商品浏览")}</span><span>{t("提交报价")}</span><span>{t("查看本人订单")}</span>
        </div>
        <Text size="1" color="gray">{t("每个子账号的范围由所属商家的父账号单独配置。")}</Text>
      </Card>
    </div>}

    <IdentityEditor
      identity={editing}
      onClose={() => setEditing(null)}
      onSaved={async () => { setEditing(null); await load(); }}
    />

    <AlertDialog.Root open={Boolean(deleting)} onOpenChange={(open) => { if (!open) setDeleting(null); }}>
      <AlertDialog.Content>
        <AlertDialog.Title>{t("删除身份？")}</AlertDialog.Title>
        <AlertDialog.Description>{t("只有未被商家使用的自定义身份可以删除。")}</AlertDialog.Description>
        <div className="dialog-actions">
          <AlertDialog.Cancel><Button variant="soft" color="gray">{t("取消")}</Button></AlertDialog.Cancel>
          <AlertDialog.Action><Button color="red" onClick={() => void remove()}>{t("确认删除")}</Button></AlertDialog.Action>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>
  </div>;
}

function IdentityEditor({
  identity,
  onClose,
  onSaved,
}: {
  identity: MerchantIdentityProfile | "new" | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const current = identity && identity !== "new" ? identity : null;
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<TenantModuleCode>>(new Set(ALL_MODULES));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!identity) return;
    setName(current?.name ?? "");
    setSelected(new Set(current?.enabled_modules ?? ALL_MODULES));
    setError("");
  }, [current, identity]);

  const save = async () => {
    const normalizedName = name.trim();
    if (!normalizedName || saving) return;
    setSaving(true);
    setError("");
    try {
      const enabled_modules = ALL_MODULES.filter((code) => selected.has(code));
      if (current) {
        await api.updateMerchantIdentity(current.code, { name: normalizedName, enabled_modules });
      } else {
        await api.createMerchantIdentity({ name: normalizedName, enabled_modules });
      }
      await onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("身份保存失败。"));
    } finally {
      setSaving(false);
    }
  };

  return <Dialog.Root open={Boolean(identity)} onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Content className="merchant-module-dialog">
      <Dialog.Title>{t(current ? "编辑身份" : "新增身份")}</Dialog.Title>
      <label className="field-group">
        <Text size="2" weight="medium">{t("身份名称")}</Text>
        <TextField.Root value={name} onChange={(event) => setName(event.target.value)} maxLength={80} placeholder={t("例如 试用客户")} />
      </label>
      <div className="merchant-module-toolbar">
        <Text size="2" color="gray">{t("已选择 {count} 个模块", { count: selected.size })}</Text>
        <div><Button size="1" variant="ghost" color="gray" onClick={() => setSelected(new Set(ALL_MODULES))}>{t("全选")}</Button><Button size="1" variant="ghost" color="gray" onClick={() => setSelected(new Set())}>{t("清空")}</Button></div>
      </div>
      <div className="merchant-module-grid">
        {MODULES.map((module) => <label className={selected.has(module.code) ? "merchant-module-option is-selected" : "merchant-module-option"} key={module.code}>
          <Checkbox checked={selected.has(module.code)} onCheckedChange={(checked) => setSelected((previous) => {
            const next = new Set(previous);
            if (checked === true) next.add(module.code); else next.delete(module.code);
            return next;
          })} />
          <Text size="2" weight="medium">{t(module.label)}</Text>
        </label>)}
      </div>
      {error ? <ToastNotice kind="error" message={error} /> : null}
      <div className="dialog-actions"><Button variant="soft" color="gray" onClick={onClose}>{t("取消")}</Button><Button loading={saving} disabled={!name.trim()} onClick={() => void save()}>{t("保存身份")}</Button></div>
    </Dialog.Content>
  </Dialog.Root>;
}
