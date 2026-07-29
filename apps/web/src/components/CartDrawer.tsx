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
import { storefrontText } from "../lib/storefrontLocale";
import type { CreateQuoteInput, Quote, Sku, StorefrontLocale } from "../types";

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
  locale: StorefrontLocale;
}

export function CartDrawer({ slug, storeName, contactEmail, lines, onQuantity, onClear, locale }: CartDrawerProps) {
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
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!lines.length) return;
    setSubmitting(true);
    setError("");
    const data = new FormData(event.currentTarget);
    if (data.get("privacy_acknowledged") !== "on") {
      setError(t("请先阅读并确认隐私政策。"));
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
      setError(caught instanceof Error ? caught.message : t("报价单生成失败，请稍后重试。"));
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
      setError(caught instanceof Error ? caught.message : t("文件下载失败，请稍后重试。"));
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
          {t("报价清单")}
          {itemCount > 0 && <span className="header-count">{itemCount}</span>}
        </Button>
      </Dialog.Trigger>
      {itemCount > 0 && !open && typeof document !== "undefined" ? createPortal(
        <Dialog.Trigger>
          <Button className="cart-floating-trigger" aria-label={t("查看报价清单，已选 {skus} 个 SKU，共 {items} 件", { skus: lines.length, items: itemCount })}>
            <span className="floating-cart-icon"><ShoppingCartSimple size={21} weight="bold" /></span>
            <span className="floating-cart-copy">
              <small>{t("已选 {skus} 个 SKU · 共 {items} 件", { skus: lines.length, items: itemCount })}</small>
              <strong>{money(knownTotal, currency)}</strong>
            </span>
            <span className="floating-cart-action">{t("查看清单")}<ArrowRight size={17} /></span>
          </Button>
        </Dialog.Trigger>,
        document.body,
      ) : null}
      <Dialog.Content className="cart-drawer" aria-describedby="cart-description">
        <div className="drawer-header">
          <div>
            <Text size="1" color="gray">{t(lines.length > 0 ? "报价清单" : "选品报价")}</Text>
            <Dialog.Title>{t(lines.length > 0 ? "生成报价单" : "报价清单")}</Dialog.Title>
            <Dialog.Description id="cart-description">
              {t(lines.length > 0 ? "确认商品数量并填写客户信息。" : "添加商品后，即可生成报价草稿。")}
            </Dialog.Description>
          </div>
          <Dialog.Close>
            <IconButton variant="ghost" color="gray" aria-label={t("关闭报价清单")}><X size={19} /></IconButton>
          </Dialog.Close>
        </div>
        <Separator size="4" />

        {quote ? (
          <div className="quote-success">
            <span className="success-icon"><CheckCircle size={38} weight="duotone" /></span>
            <div>
              <Text as="div" size="5" weight="bold">{t("报价草稿已生成")}</Text>
              <Text as="div" size="2" color="gray">{t("文件可先行下载，正式对客前仍需商家确认。")}</Text>
              <Text as="div" size="2" color="gray" className="mono-text">{quoteNumber(quote)}</Text>
            </div>
            {error && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root>}
            <div className="download-actions">
              <Button size="3" onClick={() => void handleDownload("pdf")} loading={downloading === "pdf"}>
                <FilePdf size={19} />{t("下载 PDF")}
              </Button>
              <Button size="3" variant="soft" onClick={() => void handleDownload("xlsx")} loading={downloading === "xlsx"}>
                <FileXls size={19} />{t("下载 Excel")}
              </Button>
            </div>
            <Button variant="ghost" color="gray" onClick={() => { setQuote(null); onClear(); }}>{t("继续选品")}</Button>
          </div>
        ) : lines.length === 0 ? (
          <div className="drawer-empty">
            <span className="drawer-empty-icon"><ShoppingCartSimple size={34} weight="duotone" /></span>
            <Text size="4" weight="medium" className="drawer-empty-title">{t("报价清单还是空的")}</Text>
            <Text size="2" color="gray" className="drawer-empty-copy">{t("从商品列表中选择需要报价的 SKU，再回来确认数量并生成报价草稿。")}</Text>
            <Dialog.Close><Button size="3" variant="soft">{t("继续浏览商品")}</Button></Dialog.Close>
          </div>
        ) : (
          <form className="quote-form" onSubmit={handleSubmit}>
            <div className="quote-form-scroll">
              <div className="cart-section-heading">
                <div>
                  <Text size="2" weight="medium">{t("已选商品")}</Text>
                  <Text size="1" color="gray">{t("{skus} 个 SKU，共 {items} 件", { skus: lines.length, items: itemCount })}</Text>
                </div>
                <Button type="button" size="1" variant="ghost" color="gray" onClick={onClear}>{t("清空")}</Button>
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
                      <Tooltip content={t("减少数量")}>
                        <IconButton type="button" size="1" variant="soft" color="gray" onClick={() => onQuantity(sku.id, quantity - 1)} aria-label={t("减少数量")}>
                          {quantity <= 1 ? <Trash size={14} /> : <Minus size={14} />}
                        </IconButton>
                      </Tooltip>
                      <Text size="2" weight="medium">{quantity}</Text>
                      <Tooltip content={t("增加数量")}>
                        <IconButton type="button" size="1" variant="soft" color="gray" onClick={() => onQuantity(sku.id, quantity + 1)} aria-label={t("增加数量")}>
                          <Plus size={14} />
                        </IconButton>
                      </Tooltip>
                    </div>
                  </div>
                ))}
              </div>

              <div className="quote-total-row">
                <Text color="gray" size="2">{t("商品参考合计")}</Text>
                <div>
                  <Text color="gray" size="1" as="div">{t("最终报价以商家确认为准")}</Text>
                  <Text weight="bold" size="4">{money(knownTotal, currency)}</Text>
                </div>
              </div>

              <div className="quote-customer-section">
                <div className="cart-section-heading">
                  <div>
                    <Text size="2" weight="medium">{t("客户信息")}</Text>
                    <Text size="1" color="gray">{t("用于生成本次报价草稿")}</Text>
                  </div>
                </div>
                <div className="form-grid">
                  <label className="field-group">
                    <Text as="span" size="2" weight="medium">{t("客户姓名 *")}</Text>
                    <TextField.Root name="customer_name" required placeholder={t("请输入客户姓名")} autoComplete="name" />
                  </label>
                  <label className="field-group">
                    <Text as="span" size="2" weight="medium">{t("公司名称")}</Text>
                    <TextField.Root name="customer_company" placeholder={t("请输入公司名称")} autoComplete="organization" />
                  </label>
                  <label className="field-group field-span-2">
                    <Text as="span" size="2" weight="medium">{t("客户邮箱")}</Text>
                    <TextField.Root name="customer_email" type="email" placeholder="name@company.com" autoComplete="email" />
                  </label>
                  <label className="field-group field-span-2">
                    <Text as="span" size="2" weight="medium">{t("报价备注")}</Text>
                    <TextArea name="notes" placeholder={t("交期、包装或其他说明")} resize="vertical" />
                  </label>
                </div>
              </div>
              <label className="privacy-consent">
                <input type="checkbox" name="privacy_acknowledged" required />
                <span>
                  {t("我已阅读并理解")}
                  <Link to="/privacy" target="_blank" rel="noreferrer">
                    {locale === "en-US" ? t("隐私政策") : "《隐私政策》"}
                  </Link>
                  {locale === "en-US" ? ". " : "；"}
                  {t("我填写的信息将提供给 {store}，仅用于生成和跟进本次报价", { store: storeName })}
                  {contactEmail ? (
                    <>
                      {locale === "en-US" ? " (" : "（"}
                      {t("联系邮箱：{email}", { email: "" })}
                      <a href={`mailto:${contactEmail}`}>{contactEmail}</a>
                      {locale === "en-US" ? ")" : "）"}
                    </>
                  ) : null}
                  {locale === "en-US" ? "." : "。"}
                </span>
              </label>
            </div>
            <div className="quote-form-actions">
              {error && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root>}
              <div className="quote-action-summary">
                <span>{t("{skus} 个 SKU · {items} 件", { skus: lines.length, items: itemCount })}</span>
                <strong>{money(knownTotal, currency)}</strong>
              </div>
              <Button className="quote-submit" type="submit" size="3" loading={submitting} disabled={!lines.length}>
                {t("生成报价草稿")}<ArrowRight size={18} />
              </Button>
            </div>
          </form>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
