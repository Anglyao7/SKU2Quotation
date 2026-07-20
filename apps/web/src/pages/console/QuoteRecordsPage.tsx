import { Badge, Button, Callout, Heading, Table, Text } from "@radix-ui/themes";
import { FilePdf, FileXls, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useAuth } from "../../context/AuthContext";
import { api } from "../../lib/api";
import { dateTime, money, quoteNumber } from "../../lib/format";
import type { Quote } from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";

function statusLabel(status?: string) {
  const labels: Record<string, string> = { draft: "草稿", generated: "已生成", accepted: "已接受", sent: "已发送", expired: "已过期", cancelled: "已取消" };
  return labels[status || ""] || status || "已生成";
}

export function QuoteRecordsPage() {
  const { user } = useAuth();
  const { activeTenantId } = useOutletContext<ConsoleOutletContext>();
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [downloading, setDownloading] = useState("");
  const isPlatformAdmin = user?.role === "platform_admin";

  const load = useCallback(async () => {
    if (isPlatformAdmin && !activeTenantId) { setLoading(false); return; }
    setLoading(true);
    setError("");
    try { setQuotes(await api.getQuotes()); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "报价记录加载失败。"); }
    finally { setLoading(false); }
  }, [activeTenantId, isPlatformAdmin]);

  useEffect(() => { void load(); }, [load]);

  const download = async (quote: Quote, type: "pdf" | "xlsx") => {
    const key = `${quote.id}-${type}`;
    setDownloading(key);
    setDownloadError("");
    try { await api.downloadConsoleQuote(quote.id, type); }
    catch (caught) { setDownloadError(caught instanceof Error ? caught.message : "报价文件下载失败。"); }
    finally { setDownloading(""); }
  };

  return (
    <div className="console-page">
      <div className="page-heading-row"><div><Text size="2" color="gray">客户提交与已生成文件</Text><Heading size="7">报价记录</Heading></div></div>
      {downloadError && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{downloadError}</Callout.Text></Callout.Root>}
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : loading ? <TableSkeleton /> : quotes.length === 0 ? (
        <EmptyState title="还没有报价记录" description="从商品前台选择 SKU 并生成第一份报价单。" />
      ) : (
        <>
          <div className="desktop-table surface-panel">
            <Table.Root variant="surface" size="2">
              <Table.Header><Table.Row><Table.ColumnHeaderCell>报价编号</Table.ColumnHeaderCell><Table.ColumnHeaderCell>客户</Table.ColumnHeaderCell><Table.ColumnHeaderCell>SKU / 件数</Table.ColumnHeaderCell><Table.ColumnHeaderCell>金额</Table.ColumnHeaderCell><Table.ColumnHeaderCell>状态</Table.ColumnHeaderCell><Table.ColumnHeaderCell>生成时间</Table.ColumnHeaderCell><Table.ColumnHeaderCell justify="end">下载</Table.ColumnHeaderCell></Table.Row></Table.Header>
              <Table.Body>
                {quotes.map((quote) => {
                  const itemCount = quote.items?.reduce((sum, item) => sum + item.quantity, 0) || 0;
                  return (
                    <Table.Row key={quote.id}>
                      <Table.RowHeaderCell><Text className="mono-text" size="2" weight="medium">{quoteNumber(quote)}</Text></Table.RowHeaderCell>
                      <Table.Cell><Text size="2" weight="medium" as="div">{quote.customer_company || quote.customer_name}</Text>{quote.customer_company && <Text size="1" color="gray">{quote.customer_name}</Text>}</Table.Cell>
                      <Table.Cell><Text size="2">{quote.items?.length ? `${quote.items.length} 个 SKU` : "明细已保存"}</Text><Text as="div" size="1" color="gray">{itemCount ? `共 ${itemCount} 件` : "可下载查看"}</Text></Table.Cell>
                      <Table.Cell><Text size="2" weight="medium">{money(quote.total_amount, quote.currency)}</Text></Table.Cell>
                      <Table.Cell><Badge variant="soft" color={quote.status === "expired" ? "gray" : "jade"}>{statusLabel(quote.status)}</Badge></Table.Cell>
                      <Table.Cell><Text size="1" color="gray">{dateTime(quote.created_at)}</Text></Table.Cell>
                      <Table.Cell justify="end"><div className="download-cell"><Button size="1" variant="ghost" loading={downloading === `${quote.id}-pdf`} onClick={() => void download(quote, "pdf")}><FilePdf size={16} />PDF</Button><Button size="1" variant="ghost" loading={downloading === `${quote.id}-xlsx`} onClick={() => void download(quote, "xlsx")}><FileXls size={16} />Excel</Button></div></Table.Cell>
                    </Table.Row>
                  );
                })}
              </Table.Body>
            </Table.Root>
          </div>
          <div className="mobile-data-list">
            {quotes.map((quote) => (
              <div className="mobile-data-card" key={quote.id}>
                <div className="mobile-card-heading"><div><Text className="mono-text" size="1" color="gray">{quoteNumber(quote)}</Text><Text as="div" size="3" weight="medium">{quote.customer_company || quote.customer_name}</Text></div><Badge variant="soft" color="jade">{statusLabel(quote.status)}</Badge></div>
                <Text size="2" color="gray">{quote.items?.length ? `${quote.items.length} 个 SKU` : "明细已保存"} / {dateTime(quote.created_at)}</Text>
                <div className="mobile-card-footer"><Text weight="bold">{money(quote.total_amount, quote.currency)}</Text><div><Button size="1" variant="soft" onClick={() => void download(quote, "pdf")}>PDF</Button><Button size="1" variant="soft" onClick={() => void download(quote, "xlsx")}>Excel</Button></div></div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
