import { Badge, Button, Card, Heading, Table, Text } from "@radix-ui/themes";
import {
  ArrowLeft,
  CalendarBlank,
  CheckCircle,
  Clock,
  EnvelopeSimple,
  IdentificationCard,
  Quotes,
  SignIn,
  UserCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useLocale } from "../../core/LocaleContext";
import { api } from "../../lib/api";
import { dateTime, money } from "../../lib/format";
import type { MerchantRecentQuote, MerchantSubaccountDetail, MerchantSubaccountModule } from "../../types";
import "./MerchantDetailPage.css";

const MODULE_LABELS: Record<MerchantSubaccountModule, string> = {
  products: "商品与目录",
  inquiries: "询盘",
  quotations: "报价",
  announcements: "公告",
  support: "客户沟通",
};

function accountStatusLabel(status: "invited" | "active" | "suspended") {
  if (status === "active") return "正常";
  if (status === "invited") return "待激活";
  return "已暂停";
}

function quoteStatusLabel(status: MerchantRecentQuote["status"]) {
  if (status === "PENDING_CONFIRMATION") return "待确认";
  if (status === "CONFIRMED") return "已通过";
  if (status === "COMPLETED") return "已完成";
  if (status === "CANCELLED") return "已取消";
  return "已过期";
}

function quoteStatusColor(status: MerchantRecentQuote["status"]): "amber" | "blue" | "jade" | "gray" {
  if (status === "PENDING_CONFIRMATION") return "amber";
  if (status === "CONFIRMED") return "blue";
  if (status === "COMPLETED") return "jade";
  return "gray";
}

export function MerchantSubaccountDetailPage() {
  const { tenantId, membershipId } = useParams();
  const { t } = useLocale();
  const [detail, setDetail] = useState<MerchantSubaccountDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!tenantId || !membershipId) return;
    setLoading(true);
    setError("");
    try {
      setDetail(await api.getTenantSubaccountDetail(tenantId, membershipId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("子账号详情加载失败。"));
    } finally {
      setLoading(false);
    }
  }, [membershipId, t, tenantId]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="console-page merchant-detail-page"><TableSkeleton /></div>;
  if (error || !detail) return <div className="console-page merchant-detail-page"><ErrorState message={error || t("没有找到这个子账号。") } onRetry={() => void load()} /></div>;

  const { account, merchant } = detail;
  return (
    <div className="console-page merchant-detail-page merchant-subaccount-detail-page">
      <div className="merchant-detail-breadcrumb">
        <Button asChild variant="ghost" color="gray" size="1">
          <Link to={`/console/tenants/${merchant.id}?section=subaccounts`}><ArrowLeft />{t("返回 {name}", { name: merchant.name })}</Link>
        </Button>
      </div>

      <header className="merchant-detail-hero merchant-subaccount-hero">
        <div className="merchant-detail-identity">
          <span className="merchant-detail-avatar"><UserCircle /></span>
          <div>
            <div className="merchant-detail-title-row">
              <Heading size="7">{account.display_name}</Heading>
              <Badge variant="soft" color={account.status === "active" ? "jade" : account.status === "invited" ? "blue" : "gray"}>
                {t(accountStatusLabel(account.status))}
              </Badge>
            </div>
            <Text size="2" color="gray">{account.login_identifier} · {t("属于 {merchant}", { merchant: merchant.name })}</Text>
          </div>
        </div>
      </header>

      <div className="merchant-subaccount-detail-metrics">
        <Card><SignIn /><Text size="1" color="gray">{t("近 30 天登录")}</Text><strong>{account.login_count_30d.toLocaleString()}</strong><small>{account.last_login_at ? t("最近 {time}", { time: dateTime(account.last_login_at) }) : t("暂无登录记录")}</small></Card>
        <Card><Quotes /><Text size="1" color="gray">{t("累计报价")}</Text><strong>{account.quote_count.toLocaleString()}</strong><small>{account.last_quote_at ? t("最近 {time}", { time: dateTime(account.last_quote_at) }) : t("暂无报价记录")}</small></Card>
        <Card><CalendarBlank /><Text size="1" color="gray">{t("开通时间")}</Text><strong className="is-date">{dateTime(account.created_at)}</strong><small>{account.parent_display_name ? t("由 {name} 开通", { name: account.parent_display_name }) : t("商家运营账号")}</small></Card>
      </div>

      <div className="merchant-subaccount-detail-grid">
        <Card className="merchant-profile-card merchant-account-profile-card">
          <div className="merchant-panel-heading">
            <div><Heading as="h2" size="5">{t("账号资料")}</Heading><Text size="2" color="gray">{t("身份、联系方式与当前访问范围。")}</Text></div>
            <IdentificationCard size={25} />
          </div>
          <dl className="merchant-account-facts">
            <div><dt><IdentificationCard />{t("登录账号")}</dt><dd>{account.login_identifier}</dd></div>
            <div><dt><EnvelopeSimple />{t("邮箱")}</dt><dd>{account.email || t("未填写")}</dd></div>
            <div><dt><UserCircle />{t("所属主账号")}</dt><dd>{account.parent_display_name || t("未记录")}</dd></div>
            <div><dt><Clock />{t("最近登录")}</dt><dd>{dateTime(account.last_login_at || undefined)}</dd></div>
          </dl>
          <div className="merchant-capability-section">
            <Text size="2" weight="medium">{t("已开放模块")}</Text>
            <div>
              {(account.modules?.length ? account.modules : account.capabilities.map((capability) => capability === "catalog" ? "products" : capability === "submit_orders" || capability === "view_orders" ? "quotations" : "products") as MerchantSubaccountModule[]).map((module) => (
                <Badge key={module} variant="soft" color="blue"><CheckCircle />{t(MODULE_LABELS[module])}</Badge>
              ))}
            </div>
          </div>
        </Card>

        <Card className="merchant-profile-card merchant-account-context-card">
          <div className="merchant-panel-heading">
            <div><Heading as="h2" size="4">{t("归属商家")}</Heading><Text size="2" color="gray">{t("这是该商家的独立运营账号，可处理已开放模块。")}</Text></div>
          </div>
          <div className="merchant-context-summary">
            <span>{merchant.name.slice(0, 2).toUpperCase()}</span>
            <div><strong>{merchant.name}</strong><small>/{merchant.slug}</small></div>
          </div>
          <Button asChild variant="soft" color="gray"><Link to={`/console/tenants/${merchant.id}`}>{t("查看商家汇总")}</Link></Button>
        </Card>
      </div>

      <section className="merchant-recent-quotes">
        <div className="merchant-section-heading">
          <div><Heading as="h2" size="5">{t("最近报价")}</Heading><Text size="2" color="gray">{t("该子账号最近提交的 20 份报价记录。")}</Text></div>
          <Badge variant="soft" color="blue">{detail.recent_quotes.length}</Badge>
        </div>
        {!detail.recent_quotes.length ? (
          <EmptyState title={t("还没有报价记录")} description={t("该子账号提交报价后，会在这里形成可追溯记录。")}/>
        ) : (
          <>
            <div className="desktop-table surface-panel merchant-account-quotes-table">
              <Table.Root variant="surface">
                <Table.Header><Table.Row><Table.ColumnHeaderCell>{t("报价编号")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("客户")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("金额")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("提交时间")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("有效期")}</Table.ColumnHeaderCell><Table.ColumnHeaderCell>{t("状态")}</Table.ColumnHeaderCell></Table.Row></Table.Header>
                <Table.Body>
                  {detail.recent_quotes.map((quote) => (
                    <Table.Row key={quote.id}>
                      <Table.RowHeaderCell><Text className="mono-text" size="2" weight="medium">{quote.quote_number}</Text></Table.RowHeaderCell>
                      <Table.Cell><div className="merchant-quote-customer"><span>{quote.customer_name}</span><small>{quote.customer_company || "—"}</small></div></Table.Cell>
                      <Table.Cell><Text weight="medium">{money(quote.total_amount, quote.currency)}</Text></Table.Cell>
                      <Table.Cell><Text size="1" color="gray">{dateTime(quote.created_at)}</Text></Table.Cell>
                      <Table.Cell><Text size="1" color="gray">{dateTime(quote.valid_until)}</Text></Table.Cell>
                      <Table.Cell><Badge variant="soft" color={quoteStatusColor(quote.status)}>{t(quoteStatusLabel(quote.status))}</Badge></Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table.Root>
            </div>
            <div className="mobile-data-list merchant-account-quotes-mobile">
              {detail.recent_quotes.map((quote) => (
                <div className="mobile-data-card" key={quote.id}>
                  <div className="mobile-card-heading"><Text className="mono-text" weight="medium">{quote.quote_number}</Text><Badge variant="soft" color={quoteStatusColor(quote.status)}>{t(quoteStatusLabel(quote.status))}</Badge></div>
                  <strong>{money(quote.total_amount, quote.currency)}</strong>
                  <Text size="2">{quote.customer_name}{quote.customer_company ? ` · ${quote.customer_company}` : ""}</Text>
                  <Text size="1" color="gray">{dateTime(quote.created_at)}</Text>
                </div>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
