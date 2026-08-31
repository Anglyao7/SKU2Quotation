import {
  AlertDialog,
  Badge,
  Button,
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
  Image as ImageIcon,
  Minus,
  Plus,
  ShoppingCartSimple,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { money, quoteNumber } from "../lib/format";
import { storefrontBasePath } from "../lib/storefrontAccount";
import { storefrontLocaleQuery, storefrontText } from "../lib/storefrontLocale";
import { notifyStorefrontQuotesChanged } from "../lib/storefrontVisitor";
import { ToastNotice } from "../core/ToastContext";
import type {
  CreateQuoteInput,
  Quote,
  Sku,
  StorefrontLocale,
  StorefrontSupportAction,
} from "../types";

export interface CartLine {
  sku: Sku;
  quantity: number;
  note?: string;
}

interface CartDrawerProps {
  slug: string;
  accountId?: string;
  accountKey?: string;
  storeName: string;
  contactEmail?: string | null;
  contactImages?: Array<Pick<StorefrontSupportAction, "image_url" | "label">>;
  lines: CartLine[];
  onQuantity: (skuId: string, quantity: number) => void;
  onNote: (skuId: string, note: string) => void;
  onClear: () => void;
  locale: StorefrontLocale;
}

function QuoteContactMethods({
  contactEmail,
  contactImages,
  locale,
}: {
  contactEmail?: string | null;
  contactImages?: Array<Pick<StorefrontSupportAction, "image_url" | "label">>;
  locale: StorefrontLocale;
}) {
  const t = (source: string, values?: Record<string, string | number>) => storefrontText(locale, source, values);
  const images = Array.from(new Map(
    (contactImages || [])
      .map((item) => ({
        src: item.image_url?.trim() || "",
        label: item.label?.trim() || t("商家联系方式"),
      }))
      .filter((item) => item.src)
      .map((item) => [item.src, item]),
  ).values());
  const email = contactEmail?.trim();

  return (
    <div className="quote-contact-panel">
      <div className="quote-contact-heading">
        <Text as="div" size="2" weight="medium">{t("需要帮助？可以直接联系我们")}</Text>
        <Text as="div" size="1" color="gray">{t("商家确认报价或需要补充信息时，会通过以下方式与您沟通。")}</Text>
      </div>
      {email ? (
        <a className="quote-contact-email" href={`mailto:${email}`}>
          <span>{t("联系邮箱")}</span>
          <strong>{email}</strong>
        </a>
      ) : null}
      {images.length ? (
        <div className="quote-contact-images" aria-label={t("商家联系方式图片")}>
          {images.map((item) => (
            <div className="quote-contact-image" key={item.src}>
              <img src={item.src} alt={item.label} loading="lazy" decoding="async" />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      ) : null}
      {!email && !images.length ? <Text size="1" color="gray">{t("商家暂未提供公开联系方式，请留意个人中心中的报价进度。")}</Text> : null}
    </div>
  );
}

function CartLineImage({ sku }: { sku: Sku }) {
  const [imageFailed, setImageFailed] = useState(!sku.image_url);

  useEffect(() => {
    setImageFailed(!sku.image_url);
  }, [sku.image_url]);

  return sku.image_url && !imageFailed ? (
    <img
      src={sku.image_url}
      alt={sku.name}
      onError={() => setImageFailed(true)}
    />
  ) : (
    <span className="cart-line-image-placeholder" aria-hidden="true">
      <ImageIcon size={21} />
    </span>
  );
}

export function CartDrawer({ slug, accountId, accountKey, storeName, contactEmail, contactImages, lines, onQuantity, onNote, onClear, locale }: CartDrawerProps) {
  const [open, setOpen] = useState(false);
  const [reviewReminderOpen, setReviewReminderOpen] = useState(false);
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
  const isChinese = locale === "zh-CN";
  const visitorCenterHref = `${storefrontBasePath(slug, accountKey)}/me${storefrontLocaleQuery(locale)}`;
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );
  const quoteApproved = quote?.status === "CONFIRMED" || quote?.status === "COMPLETED";

  useEffect(() => {
    if (!quote || quote.status !== "PENDING_CONFIRMATION") return;
    let disposed = false;
    const refresh = async () => {
      try {
        const rows = await api.listStorefrontVisitorQuotes(slug);
        if (disposed) return;
        const current = rows.find((row) => row.id === quote.id);
        if (!current || current.status === "PENDING_CONFIRMATION") return;
        setQuote((previous) => previous ? {
          ...previous,
          status: current.status,
          total_amount: current.total_amount,
          total: current.total_amount,
          updated_at: current.updated_at,
        } : previous);
        if (current.status === "CONFIRMED" || current.status === "COMPLETED") {
          setReviewReminderOpen(true);
        }
      } catch {
        // The quote can still be viewed while a background status refresh fails.
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [quote?.id, quote?.status, slug]);

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
      locale,
      customer_name: String(data.get("customer_name") || "").trim(),
      customer_company: String(data.get("customer_company") || "").trim() || undefined,
      customer_email: String(data.get("customer_email") || "").trim() || undefined,
      customer_phone: String(data.get("customer_phone") || "").trim() || undefined,
      notes: String(data.get("notes") || "").trim() || undefined,
      privacy_acknowledged: true,
      items: lines.map((line) => ({
        sku_id: line.sku.id,
        quantity: line.quantity,
        customer_note: line.note?.trim() || undefined,
      })),
    };
    try {
      const createdQuote = await api.createStoreQuote(slug, payload, accountId);
      setQuote(createdQuote);
      onClear();
      notifyStorefrontQuotesChanged(slug);
      setReviewReminderOpen(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("报价单生成失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDownload = async (type: "pdf" | "xlsx") => {
    if (!quote) return;
    if (!quoteApproved) {
      setError(t("商家确认报价后才可以下载文件。"));
      return;
    }
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
    <>
    <Dialog.Root open={open} onOpenChange={handleOpen}>
      <Dialog.Trigger>
        <Button className="cart-trigger" size="3">
          <ShoppingCartSimple size={19} weight="bold" />
          <span className="cart-trigger-label">{t("报价清单")}</span>
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
              {t(lines.length > 0 ? "确认商品数量并填写客户信息。" : "添加商品后，即可生成报价单。")}
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
              <Text as="div" size="5" weight="bold">{t("报价单已生成")}</Text>
              <Text as="div" size="2" color="gray">{quoteApproved ? t("商家已确认报价，现在可以下载 PDF 或 Excel。") : t("报价已提交，商家确认后才可以下载 PDF 或 Excel。")}</Text>
              <Text as="div" size="2" color="gray" className="mono-text">{quoteNumber(quote)}</Text>
            </div>
            {error && <ToastNotice kind="error" message={error} />}
            <QuoteContactMethods contactEmail={contactEmail} contactImages={contactImages} locale={locale} />
            {quoteApproved ? (
              <div className="download-actions">
                <Button size="3" onClick={() => void handleDownload("pdf")} loading={downloading === "pdf"}>
                  <FilePdf size={19} />{t("下载 PDF")}
                </Button>
                <Button size="3" variant="soft" onClick={() => void handleDownload("xlsx")} loading={downloading === "xlsx"}>
                  <FileXls size={19} />{t("下载 Excel")}
                </Button>
              </div>
            ) : null}
            <Button asChild size="3" variant="soft">
              <Link to={visitorCenterHref}>{t("前往个人中心")}</Link>
            </Button>
            <Button variant="ghost" color="gray" onClick={() => setOpen(false)}>{t("继续选品")}</Button>
          </div>
        ) : lines.length === 0 ? (
          <div className="drawer-empty">
            <span className="drawer-empty-icon"><ShoppingCartSimple size={34} weight="duotone" /></span>
            <Text size="4" weight="medium" className="drawer-empty-title">{t("报价清单还是空的")}</Text>
            <Text size="2" color="gray" className="drawer-empty-copy">{t("从商品列表中选择需要报价的 SKU，再回来确认数量并生成报价单。")}</Text>
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
                {lines.map(({ sku, quantity, note }) => (
                  <div className="cart-line" key={sku.id}>
                    <CartLineImage sku={sku} />
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
                    <label className="cart-line-note">
                      <Text as="span" size="1" color="gray">{t("商品备注（选填）")}</Text>
                      <TextArea
                        value={note || ""}
                        onChange={(event) => onNote(sku.id, event.target.value)}
                        maxLength={1000}
                        rows={2}
                        resize="vertical"
                        placeholder={t("例如颜色偏好、印刷要求或包装说明")}
                        aria-label={t("{name} 的商品备注", { name: sku.name })}
                      />
                    </label>
                  </div>
                ))}
              </div>

              <div className="quote-total-row">
                <Text color="gray" size="2">{t("商品参考合计")}</Text>
                <div>
                  <Text color="gray" size="1" as="div">{t("按已选数量计算")}</Text>
                  <Text weight="bold" size="4">{money(knownTotal, currency)}</Text>
                </div>
              </div>

              <div className="quote-customer-section">
                <div className="cart-section-heading">
                  <div>
                    <Text size="2" weight="medium">{t("客户信息")}</Text>
                    <Text size="1" color="gray">{t("用于生成本次报价单")}</Text>
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
                  <label className="field-group">
                    <Text as="span" size="2" weight="medium">{t("客户邮箱")}</Text>
                    <TextField.Root name="customer_email" type="email" placeholder="name@company.com" autoComplete="email" />
                  </label>
                  <label className="field-group">
                    <Text as="span" size="2" weight="medium">{t("联系电话")}</Text>
                    <TextField.Root name="customer_phone" type="tel" placeholder={t("电话或 WhatsApp")} autoComplete="tel" />
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
                    {isChinese ? "《隐私政策》" : t("隐私政策")}
                  </Link>
                  {isChinese ? "；" : ". "}
                  {t("我填写的信息将提供给 {store}，仅用于生成和跟进本次报价", { store: storeName })}
                  {contactEmail ? (
                    <>
                      {isChinese ? "（" : " ("}
                      {t("联系邮箱：{email}", { email: "" })}
                      <a href={`mailto:${contactEmail}`}>{contactEmail}</a>
                      {isChinese ? "）" : ")"}
                    </>
                  ) : null}
                  {isChinese ? "。" : "."}
                </span>
              </label>
            </div>
            <div className="quote-form-actions">
              {error && <ToastNotice kind="error" message={error} />}
              <div className="quote-action-summary">
                <span>{t("{skus} 个 SKU · {items} 件", { skus: lines.length, items: itemCount })}</span>
                <strong>{money(knownTotal, currency)}</strong>
              </div>
              <Button className="quote-submit" type="submit" size="3" loading={submitting} disabled={!lines.length}>
                {t("提交并生成报价单")}<ArrowRight size={18} />
              </Button>
            </div>
          </form>
        )}
      </Dialog.Content>
    </Dialog.Root>
    <AlertDialog.Root open={reviewReminderOpen} onOpenChange={setReviewReminderOpen}>
      <AlertDialog.Content maxWidth="460px">
        <AlertDialog.Title>{quoteApproved ? t("报价已通过") : t("报价已提交")}</AlertDialog.Title>
        <AlertDialog.Description>
          {quoteApproved
            ? t("商家已经审核通过这份报价，您现在可以下载 PDF 或 Excel 文件。")
            : t("本次报价需由商家确认后生效，请以商家后续确认的最终版本为准。")}
        </AlertDialog.Description>
        <QuoteContactMethods contactEmail={contactEmail} contactImages={contactImages} locale={locale} />
        {quoteApproved ? (
          <div className="download-actions quote-review-dialog-downloads">
            <Button size="2" onClick={() => void handleDownload("pdf")} loading={downloading === "pdf"}><FilePdf />{t("下载 PDF")}</Button>
            <Button size="2" variant="soft" onClick={() => void handleDownload("xlsx")} loading={downloading === "xlsx"}><FileXls />{t("下载 Excel")}</Button>
          </div>
        ) : null}
        <div className="core-dialog-actions quote-review-dialog-actions">
          <AlertDialog.Action>
            <Button onClick={() => setReviewReminderOpen(false)}>{t("知道了")}</Button>
          </AlertDialog.Action>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>
    </>
  );
}
