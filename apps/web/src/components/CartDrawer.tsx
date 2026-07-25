import {
  Badge,
  Button,
  Callout,
  Dialog,
  IconButton,
  Separator,
  Text,
  TextArea,
  TextField,
  Tooltip,
} from "@radix-ui/themes";
import {
  ArrowRight,
  CheckCircle,
  FilePdf,
  FileXls,
  Minus,
  Plus,
  ShoppingCartSimple,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useMemo, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { imageFallback, money, quoteNumber } from "../lib/format";
import type { CreateQuoteInput, Quote, Sku } from "../types";

export interface CartLine {
  sku: Sku;
  quantity: number;
}

interface CartDrawerProps {
  slug: string;
  storeName: string;
  contactEmail?: string | null;
  lines: CartLine[];
  onQuantity: (skuId: string, quantity: number) => void;
  onClear: () => void;
}

export function CartDrawer({ slug, storeName, contactEmail, lines, onQuantity, onClear }: CartDrawerProps) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [downloading, setDownloading] = useState<"pdf" | "xlsx" | null>(null);
  const [error, setError] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const itemCount = lines.reduce((sum, line) => sum + line.quantity, 0);
  const knownTotal = useMemo(
    () => lines.reduce((sum, line) => sum + (Number(line.sku.price) || 0) * line.quantity, 0),
    [lines],
  );
  const currency = lines[0]?.sku.currency || "CNY";

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!lines.length) return;
    setSubmitting(true);
    setError("");
    const data = new FormData(event.currentTarget);
    if (data.get("privacy_acknowledged") !== "on") {
      setError("请先阅读并确认隐私政策。");
      setSubmitting(false);
      return;
    }
    const payload: CreateQuoteInput = {
      customer_name: String(data.get("customer_name") || "").trim(),
      customer_company: String(data.get("customer_company") || "").trim() || undefined,
      customer_email: String(data.get("customer_email") || "").trim() || undefined,
      notes: String(data.get("notes") || "").trim() || undefined,
      privacy_acknowledged: true,
      items: lines.map((line) => ({ sku_id: line.sku.id, quantity: line.quantity })),
    };
    try {
      setQuote(await api.createStoreQuote(slug, payload));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "报价单生成失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDownload = async (type: "pdf" | "xlsx") => {
    if (!quote) return;
    setDownloading(type);
    setError("");
    try {
      await api.downloadStoreQuote(quote.id, type, quote.download_token);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "文件下载失败，请稍后重试。");
    } finally {
      setDownloading(null);
    }
  };

  const handleOpen = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setError("");
      setQuote(null);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={handleOpen}>
      <Dialog.Trigger>
        <Button className="cart-trigger" size="3">
          <ShoppingCartSimple size={19} weight="bold" />
          报价清单
          {itemCount > 0 && <span className="header-count">{itemCount}</span>}
        </Button>
      </Dialog.Trigger>
      {itemCount > 0 && !open && typeof document !== "undefined" ? createPortal(
        <Dialog.Trigger>
          <Button className="cart-floating-trigger" aria-label={`查看报价清单，已选 ${lines.length} 个 SKU，共 ${itemCount} 件`}>
            <span className="floating-cart-icon"><ShoppingCartSimple size={21} weight="bold" /></span>
            <span className="floating-cart-copy">
              <small>已选 {lines.length} 个 SKU · 共 {itemCount} 件</small>
              <strong>{money(knownTotal, currency)}</strong>
            </span>
            <span className="floating-cart-action">查看清单<ArrowRight size={17} /></span>
          </Button>
        </Dialog.Trigger>,
        document.body,
      ) : null}
      <Dialog.Content className="cart-drawer" aria-describedby="cart-description">
        <div className="drawer-header">
          <div>
            <Text size="1" color="gray">{lines.length > 0 ? "报价清单" : "选品报价"}</Text>
            <Dialog.Title>{lines.length > 0 ? "生成报价单" : "报价清单"}</Dialog.Title>
            <Dialog.Description id="cart-description">
              {lines.length > 0 ? "确认商品数量并填写客户信息。" : "添加商品后，即可生成报价草稿。"}
            </Dialog.Description>
          </div>
          <Dialog.Close>
            <IconButton variant="ghost" color="gray" aria-label="关闭报价清单"><X size={19} /></IconButton>
          </Dialog.Close>
        </div>
        <Separator size="4" />

        {quote ? (
          <div className="quote-success">
            <span className="success-icon"><CheckCircle size={38} weight="duotone" /></span>
            <div>
              <Text as="div" size="5" weight="bold">报价草稿已生成</Text>
              <Text as="div" size="2" color="gray">文件可先行下载，正式对客前仍需商家确认。</Text>
              <Text as="div" size="2" color="gray" className="mono-text">{quoteNumber(quote)}</Text>
            </div>
            {error && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root>}
            <div className="download-actions">
              <Button size="3" onClick={() => void handleDownload("pdf")} loading={downloading === "pdf"}>
                <FilePdf size={19} />下载 PDF
              </Button>
              <Button size="3" variant="soft" onClick={() => void handleDownload("xlsx")} loading={downloading === "xlsx"}>
                <FileXls size={19} />下载 Excel
              </Button>
            </div>
            <Button variant="ghost" color="gray" onClick={() => { setQuote(null); onClear(); }}>继续选品</Button>
          </div>
        ) : lines.length === 0 ? (
          <div className="drawer-empty">
            <span className="drawer-empty-icon"><ShoppingCartSimple size={34} weight="duotone" /></span>
            <Text size="4" weight="medium" className="drawer-empty-title">报价清单还是空的</Text>
            <Text size="2" color="gray" className="drawer-empty-copy">从商品列表中选择需要报价的 SKU，再回来确认数量并生成报价草稿。</Text>
            <Dialog.Close><Button size="3" variant="soft">继续浏览商品</Button></Dialog.Close>
          </div>
        ) : (
          <form className="quote-form" onSubmit={handleSubmit}>
            <div className="quote-form-scroll">
              <div className="cart-section-heading">
                <div>
                  <Text size="2" weight="medium">已选商品</Text>
                  <Text size="1" color="gray">{lines.length} 个 SKU，共 {itemCount} 件</Text>
                </div>
                <Button type="button" size="1" variant="ghost" color="gray" onClick={onClear}>清空</Button>
              </div>
              <div className="cart-lines">
                {lines.map(({ sku, quantity }) => (
                  <div className="cart-line" key={sku.id}>
                    <img src={sku.image_url || imageFallback(sku.sku_code)} alt={sku.name} />
                    <div className="cart-line-copy">
                      <Text size="2" weight="medium" className="truncate-text">{sku.name}</Text>
                      <Text size="1" color="gray" className="mono-text">{sku.sku_code}</Text>
                      <Text size="1" color="gray">{money(sku.price, sku.currency)}</Text>
                    </div>
                    <div className="quantity-control">
                      <Tooltip content="减少数量">
                        <IconButton type="button" size="1" variant="soft" color="gray" onClick={() => onQuantity(sku.id, quantity - 1)} aria-label="减少数量">
                          {quantity <= 1 ? <Trash size={14} /> : <Minus size={14} />}
                        </IconButton>
                      </Tooltip>
                      <Text size="2" weight="medium">{quantity}</Text>
                      <Tooltip content="增加数量">
                        <IconButton type="button" size="1" variant="soft" color="gray" onClick={() => onQuantity(sku.id, quantity + 1)} aria-label="增加数量">
                          <Plus size={14} />
                        </IconButton>
                      </Tooltip>
                    </div>
                  </div>
                ))}
              </div>

              <div className="quote-total-row">
                <Text color="gray" size="2">商品参考合计</Text>
                <div>
                  <Text color="gray" size="1" as="div">最终报价以商家确认为准</Text>
                  <Text weight="bold" size="4">{money(knownTotal, currency)}</Text>
                </div>
              </div>

              <div className="quote-customer-section">
                <div className="cart-section-heading">
                  <div>
                    <Text size="2" weight="medium">客户信息</Text>
                    <Text size="1" color="gray">用于生成本次报价草稿</Text>
                  </div>
                </div>
                <div className="form-grid">
                  <label className="field-group">
                    <Text as="span" size="2" weight="medium">客户姓名 *</Text>
                    <TextField.Root name="customer_name" required placeholder="请输入客户姓名" autoComplete="name" />
                  </label>
                  <label className="field-group">
                    <Text as="span" size="2" weight="medium">公司名称</Text>
                    <TextField.Root name="customer_company" placeholder="请输入公司名称" autoComplete="organization" />
                  </label>
                  <label className="field-group field-span-2">
                    <Text as="span" size="2" weight="medium">客户邮箱</Text>
                    <TextField.Root name="customer_email" type="email" placeholder="name@company.com" autoComplete="email" />
                  </label>
                  <label className="field-group field-span-2">
                    <Text as="span" size="2" weight="medium">报价备注</Text>
                    <TextArea name="notes" placeholder="交期、包装或其他说明" resize="vertical" />
                  </label>
                </div>
              </div>
              <label className="privacy-consent">
                <input type="checkbox" name="privacy_acknowledged" required />
                <span>
                  我已阅读并理解<Link to="/privacy" target="_blank" rel="noreferrer">《隐私政策》</Link>；
                  我填写的信息将提供给 {storeName}，仅用于生成和跟进本次报价
                  {contactEmail ? <>（联系邮箱：<a href={`mailto:${contactEmail}`}>{contactEmail}</a>）</> : null}。
                </span>
              </label>
            </div>
            <div className="quote-form-actions">
              {error && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root>}
              <div className="quote-action-summary">
                <span>{lines.length} 个 SKU · {itemCount} 件</span>
                <strong>{money(knownTotal, currency)}</strong>
              </div>
              <Button className="quote-submit" type="submit" size="3" loading={submitting} disabled={!lines.length}>
                生成报价草稿<ArrowRight size={18} />
              </Button>
            </div>
          </form>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
