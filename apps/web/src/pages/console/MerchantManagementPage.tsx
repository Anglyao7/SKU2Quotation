import { Badge, Button, Heading, Table, Text, TextField } from "@radix-ui/themes";
import { ArrowRight, MagnifyingGlass, Plus } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useLocale } from "../../core/LocaleContext";
import { api } from "../../lib/api";
import { dateTime } from "../../lib/format";
import { subscriptionTierLabel } from "../../lib/subscriptionTier";
import type { MerchantIdentityProfile, Tenant } from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";
import { TenantFormDialog } from "./TenantManagementPage";
import "./MerchantDetailPage.css";

function tenantLoginEmail(tenant: Tenant) {
  return tenant.owner_account?.email
    || tenant.owner_account?.login_identifier
    || tenant.contact_email
    || "";
}

function isInteractiveTarget(target: EventTarget | null) {
  return target instanceof Element
    && Boolean(target.closest("a, button, input, select, textarea, label, [role='button']"));
}

function subscriptionColor(tier: Tenant["subscription_tier"]): "gray" | "blue" | "violet" | "amber" {
  if (tier === "ELITE") return "amber";
  if (tier === "SILVER") return "violet";
  if (tier === "STANDARD") return "blue";
  return "gray";
}

export function MerchantManagementPage() {
  const { reloadTenants } = useOutletContext<ConsoleOutletContext>();
  const { t } = useLocale();
  const navigate = useNavigate();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [identities, setIdentities] = useState<MerchantIdentityProfile[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextTenants, nextIdentities] = await Promise.all([
        api.getTenants(),
        api.getMerchantIdentities(),
      ]);
      setTenants(nextTenants);
      setIdentities(nextIdentities);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("商家列表加载失败。"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const filteredTenants = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase();
    if (!keyword) return tenants;
    return tenants.filter((tenant) => [
      tenant.name,
      tenant.slug,
      tenantLoginEmail(tenant),
      tenant.contact_email || "",
    ].some((value) => value.toLocaleLowerCase().includes(keyword)));
  }, [query, tenants]);

  const refreshAll = async () => {
    await Promise.all([load(), reloadTenants()]);
  };

  const openMerchant = (tenant: Tenant) => navigate(`/console/tenants/${tenant.id}`);

  return (
    <div className="console-page merchant-management-page merchant-list-page">
      <div className="page-heading-row">
        <div>
          <Text size="2" color="gray">{t("平台商家与经营信息汇总")}</Text>
          <Heading size="7">{t("商家列表")}</Heading>
        </div>
        <Button onClick={() => setCreating(true)}><Plus />{t("新增商家")}</Button>
      </div>

      {!loading && !error && tenants.length ? (
        <div className="merchant-list-toolbar">
          <TextField.Root
            className="merchant-list-search"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder={t("搜索商家名称、前台地址或登录账号")}
          >
            <TextField.Slot><MagnifyingGlass /></TextField.Slot>
          </TextField.Root>
          <div className="merchant-list-summary">
            <Badge variant="soft" color="blue">{t("{count} 个商家", { count: tenants.length })}</Badge>
            <Text size="1" color="gray">{t("{count} 个正常营业", { count: tenants.filter((tenant) => tenant.status === "active").length })}</Text>
          </div>
        </div>
      ) : null}

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : loading ? (
        <TableSkeleton />
      ) : tenants.length === 0 ? (
        <EmptyState
          title={t("平台还没有商家")}
          description={t("创建首个商家后，就可以进入商家内部管理账号、经营数据与配置。")}
          action={<Button onClick={() => setCreating(true)}><Plus />{t("新增商家")}</Button>}
        />
      ) : filteredTenants.length === 0 ? (
        <EmptyState
          title={t("没有找到匹配的商家")}
          description={t("请尝试商家名称、前台地址或主账号。")}
          action={<Button variant="soft" color="gray" onClick={() => setQuery("")}>{t("清除搜索")}</Button>}
        />
      ) : (
        <>
          <div className="desktop-table surface-panel merchant-management-table merchant-list-table">
            <Table.Root variant="surface" size="2">
              <Table.Header>
                <Table.Row>
                  <Table.ColumnHeaderCell>{t("商家")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("主账号")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("业务数据")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("等级与到期")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("状态")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("最近更新")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell justify="end">{t("进入商家")}</Table.ColumnHeaderCell>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {filteredTenants.map((tenant) => {
                  const loginEmail = tenantLoginEmail(tenant);
                  return (
                    <Table.Row
                      className="merchant-list-row"
                      key={tenant.id}
                      tabIndex={0}
                      aria-label={t("进入 {name} 的商家详情", { name: tenant.name })}
                      onClick={(event) => { if (!isInteractiveTarget(event.target)) openMerchant(tenant); }}
                      onKeyDown={(event) => {
                        if ((event.key === "Enter" || event.key === " ") && !isInteractiveTarget(event.target)) {
                          event.preventDefault();
                          openMerchant(tenant);
                        }
                      }}
                    >
                      <Table.RowHeaderCell>
                        <div className="merchant-list-identity">
                          <span>{tenant.name.slice(0, 2).toUpperCase()}</span>
                          <div><Text size="2" weight="medium">{tenant.name}</Text><Text className="mono-text" size="1" color="gray">/{tenant.slug}</Text></div>
                        </div>
                      </Table.RowHeaderCell>
                      <Table.Cell>
                        <div className="merchant-list-account"><Text size="2">{loginEmail || t("尚未开通")}</Text><Text size="1" color="gray">{tenant.owner_account?.display_name || t("无主账号")}</Text></div>
                      </Table.Cell>
                      <Table.Cell>
                        <div className="merchant-list-business"><span><strong>{(tenant.sku_count || 0).toLocaleString()}</strong><small>SKU</small></span><span><strong>{(tenant.quote_count || 0).toLocaleString()}</strong><small>{t("报价")}</small></span></div>
                      </Table.Cell>
                      <Table.Cell>
                        <div className="merchant-list-plan"><Badge color={subscriptionColor(tenant.subscription_tier)} variant="soft">{t(subscriptionTierLabel(tenant.subscription_tier))}</Badge><Text size="1" color={tenant.subscription_status === "expired" ? "red" : "gray"}>{dateTime(tenant.subscription_expires_at)}</Text></div>
                      </Table.Cell>
                      <Table.Cell><Badge variant="soft" color={tenant.status === "active" ? "jade" : "gray"}>{t(tenant.status === "active" ? "正常营业" : "已停用")}</Badge></Table.Cell>
                      <Table.Cell><Text size="1" color="gray">{dateTime(tenant.updated_at || tenant.created_at)}</Text></Table.Cell>
                      <Table.Cell justify="end"><Button asChild size="1" variant="ghost"><Link to={`/console/tenants/${tenant.id}`}>{t("查看详情")}<ArrowRight /></Link></Button></Table.Cell>
                    </Table.Row>
                  );
                })}
              </Table.Body>
            </Table.Root>
          </div>

          <div className="mobile-data-list merchant-list-mobile">
            {filteredTenants.map((tenant) => {
              const loginEmail = tenantLoginEmail(tenant);
              return (
                <Link className="mobile-data-card merchant-list-mobile-card" to={`/console/tenants/${tenant.id}`} key={tenant.id}>
                  <div className="mobile-card-heading">
                    <div className="merchant-list-identity"><span>{tenant.name.slice(0, 2).toUpperCase()}</span><div><Text size="3" weight="medium">{tenant.name}</Text><Text className="mono-text" size="1" color="gray">/{tenant.slug}</Text></div></div>
                    <Badge variant="soft" color={tenant.status === "active" ? "jade" : "gray"}>{t(tenant.status === "active" ? "正常" : "停用")}</Badge>
                  </div>
                  <Text size="2" color={loginEmail ? "gray" : "amber"}>{loginEmail || t("尚未开通主账号")}</Text>
                  <div className="merchant-list-mobile-stats"><span><small>SKU</small><strong>{(tenant.sku_count || 0).toLocaleString()}</strong></span><span><small>{t("报价")}</small><strong>{(tenant.quote_count || 0).toLocaleString()}</strong></span><span><small>{t("等级")}</small><strong>{t(subscriptionTierLabel(tenant.subscription_tier))}</strong></span><ArrowRight /></div>
                </Link>
              );
            })}
          </div>
        </>
      )}

      <TenantFormDialog
        tenant={creating ? "new" : null}
        identities={identities}
        onOpenChange={(open) => { if (!open) setCreating(false); }}
        onChanged={refreshAll}
      />
    </div>
  );
}
