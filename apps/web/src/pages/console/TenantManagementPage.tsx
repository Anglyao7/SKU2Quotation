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
import {
  CheckCircle,
  Eye,
  NotePencil,
  Plus,
  Trash,
  UserPlus,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useLocale } from "../../core/LocaleContext";
import { api } from "../../lib/api";
import { dateTime } from "../../lib/format";
import type {
  MerchantOwnerAccount,
  MerchantOwnerAccountPayload,
  Tenant,
  TenantPayload,
} from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";

function tenantLoginEmail(tenant: Tenant): string {
  return (
    tenant.owner_account?.email
    || tenant.contact_email
    || tenant.owner_account?.login_identifier
    || ""
  );
}

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
    setLoading(true);
    setError("");
    try {
      setTenants(await api.getTenants());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("商家列表加载失败。"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async () => {
    if (!deleting) return;
    try {
      await api.deactivateTenant(deleting.id);
      setDeleting(null);
      await Promise.all([load(), reloadTenants()]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("商家停用失败。"));
      setDeleting(null);
    }
  };

  const refreshAll = async () => {
    await Promise.all([load(), reloadTenants()]);
  };

  return (
    <div className="console-page">
      <div className="page-heading-row">
        <div>
          <Text size="2" color="gray">{t("商家、登录账号与商品前台")}</Text>
          <Heading size="7">{t("商家管理")}</Heading>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus size={18} />
          {t("新增商家")}
        </Button>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : loading ? (
        <TableSkeleton />
      ) : tenants.length === 0 ? (
        <EmptyState
          title={t("平台还没有商家")}
          description={t("创建首个商家后，即可上传 SKU 并开放商品前台。")}
          action={(
            <Button onClick={() => setEditing("new")}>
              <Plus size={17} />
              {t("新增商家")}
            </Button>
          )}
        />
      ) : (
        <>
          <div className="desktop-table surface-panel">
            <Table.Root variant="surface" size="2">
              <Table.Header>
                <Table.Row>
                  <Table.ColumnHeaderCell>{t("商家")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("登录邮箱")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("前台地址")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>SKU</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("报价")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("状态")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("创建时间")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell justify="end">{t("操作")}</Table.ColumnHeaderCell>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {tenants.map((tenant) => {
                  const loginEmail = tenantLoginEmail(tenant);
                  return (
                    <Table.Row key={tenant.id}>
                      <Table.RowHeaderCell>
                        <Text size="2" weight="medium">{tenant.name}</Text>
                      </Table.RowHeaderCell>
                      <Table.Cell>
                        {loginEmail ? (
                          <Text size="1">{loginEmail}</Text>
                        ) : (
                          <Text size="1" color="amber">{t("尚未开通")}</Text>
                        )}
                      </Table.Cell>
                      <Table.Cell>
                        <Text className="mono-text" size="1">/{tenant.slug}</Text>
                      </Table.Cell>
                      <Table.Cell>{tenant.sku_count ?? 0}</Table.Cell>
                      <Table.Cell>{tenant.quote_count ?? 0}</Table.Cell>
                      <Table.Cell>
                        <Badge
                          variant="soft"
                          color={tenant.status === "active" ? "jade" : "gray"}
                        >
                          {t(tenant.status === "active" ? "启用" : "停用")}
                        </Badge>
                      </Table.Cell>
                      <Table.Cell>
                        <Text size="1" color="gray">{dateTime(tenant.created_at)}</Text>
                      </Table.Cell>
                      <Table.Cell justify="end">
                        <div className="table-actions">
                          {tenant.owner_account?.status === "active" ? null : (
                            <Tooltip content={t("开通登录账号")}>
                              <IconButton
                                size="1"
                                variant="ghost"
                                color="jade"
                                disabled={tenant.status !== "active"}
                                aria-label={t("为 {name} 开通登录账号", { name: tenant.name })}
                                onClick={() => setOwnerSetup(tenant)}
                              >
                                <UserPlus size={17} />
                              </IconButton>
                            </Tooltip>
                          )}
                          <Tooltip content={t("查看前台")}>
                            <IconButton asChild size="1" variant="ghost" color="gray">
                              <Link
                                to={`/${tenant.slug}`}
                                target="_blank"
                                aria-label={t("查看 {name} 商品前台", { name: tenant.name })}
                              >
                                <Eye size={17} />
                              </Link>
                            </IconButton>
                          </Tooltip>
                          <Tooltip content={t("编辑")}>
                            <IconButton
                              size="1"
                              variant="ghost"
                              color="gray"
                              aria-label={t("编辑 {name}", { name: tenant.name })}
                              onClick={() => setEditing(tenant)}
                            >
                              <NotePencil size={17} />
                            </IconButton>
                          </Tooltip>
                          {tenant.status === "active" ? (
                            <Tooltip content={t("停用")}>
                              <IconButton
                                size="1"
                                variant="ghost"
                                color="red"
                                aria-label={t("停用 {name}", { name: tenant.name })}
                                onClick={() => setDeleting(tenant)}
                              >
                                <Trash size={17} />
                              </IconButton>
                            </Tooltip>
                          ) : null}
                        </div>
                      </Table.Cell>
                    </Table.Row>
                  );
                })}
              </Table.Body>
            </Table.Root>
          </div>

          <div className="mobile-data-list">
            {tenants.map((tenant) => {
              const loginEmail = tenantLoginEmail(tenant);
              return (
                <div className="mobile-data-card" key={tenant.id}>
                  <div className="mobile-card-heading">
                    <div>
                      <Text as="div" size="3" weight="medium">{tenant.name}</Text>
                      <Text className="mono-text" size="1" color="gray">/{tenant.slug}</Text>
                    </div>
                    <Badge color={tenant.status === "active" ? "jade" : "gray"}>
                      {t(tenant.status === "active" ? "启用" : "停用")}
                    </Badge>
                  </div>
                  <Text size="2" color={loginEmail ? "gray" : "amber"}>
                    {loginEmail || t("尚未开通登录账号")}
                  </Text>
                  <Text size="2" color="gray">
                    {t("{skus} 个 SKU / {quotes} 份报价", {
                      skus: tenant.sku_count || 0,
                      quotes: tenant.quote_count || 0,
                    })}
                  </Text>
                  <div className="mobile-card-footer">
                    <div className="page-actions">
                      <Button asChild size="1" variant="soft">
                        <Link to={`/${tenant.slug}`}>{t("查看前台")}</Link>
                      </Button>
                      {tenant.owner_account?.status === "active" ? null : (
                        <Button
                          size="1"
                          variant="soft"
                          color="jade"
                          disabled={tenant.status !== "active"}
                          onClick={() => setOwnerSetup(tenant)}
                        >
                          <UserPlus />
                          {t("开通登录账号")}
                        </Button>
                      )}
                    </div>
                    <div>
                      <IconButton
                        variant="ghost"
                        aria-label={t("编辑 {name}", { name: tenant.name })}
                        onClick={() => setEditing(tenant)}
                      >
                        <NotePencil />
                      </IconButton>
                      {tenant.status === "active" ? (
                        <IconButton
                          variant="ghost"
                          color="red"
                          aria-label={t("停用 {name}", { name: tenant.name })}
                          onClick={() => setDeleting(tenant)}
                        >
                          <Trash />
                        </IconButton>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      <TenantFormDialog
        tenant={editing}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        onChanged={refreshAll}
      />
      <MerchantOwnerDialog
        tenant={ownerSetup}
        onOpenChange={(open) => {
          if (!open) setOwnerSetup(null);
        }}
        onSaved={refreshAll}
      />
      <AlertDialog.Root
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
      >
        <AlertDialog.Content>
          <AlertDialog.Title>{t("停用这个商家？")}</AlertDialog.Title>
          <AlertDialog.Description>
            {t("“{name}”的商品前台将停止访问，历史数据会保留，可在编辑商家时重新启用。", {
              name: deleting?.name ?? "",
            })}
          </AlertDialog.Description>
          <div className="dialog-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">{t("取消")}</Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button color="red" onClick={() => void remove()}>{t("确认停用")}</Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}

function MerchantOwnerDialog({
  tenant,
  onOpenChange,
  onSaved,
}: {
  tenant: Tenant | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<MerchantOwnerAccount | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tenant) return;
    const data = new FormData(event.currentTarget);
    const email = String(data.get("login_email") || "").trim().toLowerCase();
    const payload: MerchantOwnerAccountPayload = {
      display_name: tenant.name,
      login_identifier: email,
      email,
      password: String(data.get("password") || ""),
    };
    setSaving(true);
    setError("");
    try {
      await api.updateTenant(tenant.id, {
        name: tenant.name,
        contact_email: email,
        active: true,
      });
      const owner = await api.provisionMerchantOwner(tenant.id, payload);
      setResult(owner);
      await onSaved().catch(() => undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("登录账号开通失败。"));
    } finally {
      setSaving(false);
    }
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setResult(null);
      setError("");
    }
    onOpenChange(open);
  };

  return (
    <Dialog.Root open={Boolean(tenant)} onOpenChange={handleOpenChange}>
      <Dialog.Content className="merchant-dialog">
        <Dialog.Title>{t("开通商家登录账号")}</Dialog.Title>
        <Dialog.Description>
          {t("为“{name}”设置登录邮箱和初始密码。", { name: tenant?.name ?? "" })}
        </Dialog.Description>
        {result ? (
          <div className="dialog-form">
            <Callout.Root color="green">
              <Callout.Icon><CheckCircle /></Callout.Icon>
              <Callout.Text>{t("登录账号已开通，可以立即使用。")}</Callout.Text>
            </Callout.Root>
            <Text size="2" color="gray">
              {t("登录邮箱：{email}", { email: result.email || result.login_identifier || "—" })}
            </Text>
            <div className="dialog-actions">
              <Dialog.Close><Button>{t("完成")}</Button></Dialog.Close>
            </div>
          </div>
        ) : (
          <form className="dialog-form" onSubmit={submit} key={tenant?.id}>
            <label className="field-group">
              <Text size="2" weight="medium">{t("登录邮箱")} *</Text>
              <TextField.Root
                name="login_email"
                type="email"
                required
                maxLength={320}
                autoComplete="email"
                autoCapitalize="none"
                placeholder="name@company.com"
              />
            </label>
            <label className="field-group">
              <Text size="2" weight="medium">{t("初始密码")} *</Text>
              <TextField.Root
                name="password"
                type="password"
                required
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
                placeholder={t("至少 8 位，包含字母和数字")}
              />
            </label>
            {error ? (
              <Callout.Root color="red">
                <Callout.Icon><WarningCircle /></Callout.Icon>
                <Callout.Text>{error}</Callout.Text>
              </Callout.Root>
            ) : null}
            <div className="dialog-actions">
              <Dialog.Close>
                <Button type="button" variant="soft" color="gray">{t("取消")}</Button>
              </Dialog.Close>
              <Button type="submit" loading={saving}>
                <UserPlus />
                {t("确认开通")}
              </Button>
            </div>
          </form>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}

function TenantFormDialog({
  tenant,
  onOpenChange,
  onChanged,
}: {
  tenant: Tenant | "new" | null;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
}) {
  const { t } = useLocale();
  const current = tenant && tenant !== "new" ? tenant : null;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [createdTenant, setCreatedTenant] = useState<Tenant | null>(null);
  const [createdOwner, setCreatedOwner] = useState<MerchantOwnerAccount | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const name = String(data.get("name") || "").trim();
    setSaving(true);
    setError("");

    try {
      if (current) {
        await api.updateTenant(current.id, {
          name,
          contact_email: current.owner_account?.email || current.contact_email || "",
          active: String(data.get("status") || "active") === "active",
        });
        await onChanged();
        onOpenChange(false);
        return;
      }

      const loginEmail = String(data.get("login_email") || "").trim().toLowerCase();
      const password = String(data.get("password") || "");
      const tenantPayload: TenantPayload = {
        name,
        contact_email: loginEmail,
        active: true,
      };

      let merchant = createdTenant;
      let merchantWasCreated = false;
      if (merchant) {
        merchant = await api.updateTenant(merchant.id, tenantPayload);
      } else {
        merchant = await api.createTenant(tenantPayload);
        merchantWasCreated = true;
        setCreatedTenant(merchant);
      }

      let owner: MerchantOwnerAccount;
      try {
        owner = await api.provisionMerchantOwner(merchant.id, {
          display_name: name,
          login_identifier: loginEmail,
          email: loginEmail,
          password,
        });
      } catch (caught) {
        if (merchantWasCreated) {
          await onChanged().catch(() => undefined);
        }
        const reason = caught instanceof Error ? caught.message : t("登录账号开通失败。");
        setError(t("商家已创建，但登录账号开通失败：{reason}", { reason }));
        return;
      }
      setCreatedOwner(owner);
      await onChanged().catch(() => undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("商家保存失败。"));
    } finally {
      setSaving(false);
    }
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setError("");
      setCreatedTenant(null);
      setCreatedOwner(null);
    }
    onOpenChange(open);
  };

  return (
    <Dialog.Root open={Boolean(tenant)} onOpenChange={handleOpenChange}>
      <Dialog.Content className="merchant-dialog">
        <Dialog.Title>{t(current ? "编辑商家" : "新增商家")}</Dialog.Title>
        <Dialog.Description>
          {t(current ? "修改商家名称或状态。" : "填写三项信息即可创建商家并开通登录账号。")}
        </Dialog.Description>

        {createdOwner ? (
          <div className="dialog-form">
            <Callout.Root color="green">
              <Callout.Icon><CheckCircle /></Callout.Icon>
              <Callout.Text>{t("商家已创建，可以立即登录。")}</Callout.Text>
            </Callout.Root>
            <Text size="2" color="gray">
              {t("登录邮箱：{email}", {
                email: createdOwner.email || createdOwner.login_identifier || "—",
              })}
            </Text>
            <div className="dialog-actions">
              <Dialog.Close><Button>{t("完成")}</Button></Dialog.Close>
            </div>
          </div>
        ) : (
          <form className="dialog-form" onSubmit={submit} key={current?.id || "new"}>
            <label className="field-group">
              <Text size="2" weight="medium">{t("商家名称")} *</Text>
              <TextField.Root
                name="name"
                required
                maxLength={200}
                defaultValue={current?.name}
                placeholder={t("例如 海岸家居")}
              />
            </label>

            {current ? (
              <label className="field-group">
                <Text size="2" weight="medium">{t("状态")}</Text>
                <Select.Root name="status" defaultValue={current.status}>
                  <Select.Trigger />
                  <Select.Content>
                    <Select.Item value="active">{t("启用")}</Select.Item>
                    <Select.Item value="inactive">{t("停用")}</Select.Item>
                  </Select.Content>
                </Select.Root>
              </label>
            ) : (
              <>
                <label className="field-group">
                  <Text size="2" weight="medium">{t("登录邮箱")} *</Text>
                  <TextField.Root
                    name="login_email"
                    type="email"
                    required
                    maxLength={320}
                    autoComplete="email"
                    autoCapitalize="none"
                    placeholder="name@company.com"
                  />
                </label>
                <label className="field-group">
                  <Text size="2" weight="medium">{t("初始密码")} *</Text>
                  <TextField.Root
                    name="password"
                    type="password"
                    required
                    minLength={8}
                    maxLength={128}
                    autoComplete="new-password"
                    placeholder={t("至少 8 位，包含字母和数字")}
                  />
                </label>
              </>
            )}

            {error ? (
              <Callout.Root color="red">
                <Callout.Icon><WarningCircle /></Callout.Icon>
                <Callout.Text>{error}</Callout.Text>
              </Callout.Root>
            ) : null}
            <div className="dialog-actions">
              <Dialog.Close>
                <Button type="button" variant="soft" color="gray">{t("取消")}</Button>
              </Dialog.Close>
              <Button type="submit" loading={saving}>
                {t(current ? "保存商家" : createdTenant ? "继续开通账号" : "创建商家")}
              </Button>
            </div>
          </form>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
