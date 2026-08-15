import {
  Badge,
  Button,
  Card,
  Heading,
  Select,
  Tabs,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowLeft,
  CheckCircle,
  ClipboardText,
  Copy,
  FilePdf,
  FileText,
  FileXls,
  FloppyDisk,
  LockKey,
  Palette,
  PaperPlaneTilt,
  SpinnerGap,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  CoreApiError,
  downloadPublicQuoteDraftDocument,
  getMerchantSettings,
  getPublicQuoteDraft,
  listQuoteExcelTemplates,
  updatePublicQuoteDraftSettings,
  updatePublicQuoteDraftStatus,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { MerchantSettings, PublicQuoteDraft, QuoteExcelTemplate } from "../types";
import type { StorefrontLocale } from "../../types";
import "./QuoteWorkbenchPage.css";

type QuoteDocumentStyle = PublicQuoteDraft["documentStyle"];

const locales: Array<{ value: StorefrontLocale; label: string; flag: string }> = [
  { value: "zh-CN", label: "简体中文", flag: "🇨🇳" },
  { value: "en-US", label: "English", flag: "🇺🇸" },
  { value: "es", label: "Español", flag: "🇪🇸" },
  { value: "tr", label: "Türkçe", flag: "🇹🇷" },
  { value: "ar", label: "العربية", flag: "🇸🇦" },
  { value: "ja", label: "日本語", flag: "🇯🇵" },
  { value: "ko", label: "한국어", flag: "🇰🇷" },
  { value: "pt", label: "Português", flag: "🇵🇹" },
];

const styles: Array<{ value: QuoteDocumentStyle; label: string; color: string }> = [
  { value: "indigo", label: "海军蓝", color: "#314B9B" },
  { value: "emerald", label: "翡翠绿", color: "#087F5B" },
  { value: "gold", label: "鎏金", color: "#B88A25" },
  { value: "slate", label: "石墨灰", color: "#334155" },
  { value: "rose", label: "玫瑰红", color: "#9F3B5B" },
];

function localeLabel(value: StorefrontLocale) {
  const option = locales.find((row) => row.value === value);
  return option ? `${option.flag} ${option.label}` : value;
}

export function QuoteWorkbenchPage() {
  const { quoteDraftId } = useParams<{ quoteDraftId: string }>();
  const navigate = useNavigate();
  const { t } = useLocale();
  const [draft, setDraft] = useState<PublicQuoteDraft>();
  const [templates, setTemplates] = useState<QuoteExcelTemplate[]>([]);
  const [settings, setSettings] = useState<MerchantSettings>();
  const [locale, setLocale] = useState<StorefrontLocale>("zh-CN");
  const [style, setStyle] = useState<QuoteDocumentStyle>("indigo");
  const [templateId, setTemplateId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState<"pdf" | "xlsx" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  const enabledLocales = useMemo(() => {
    const allowed = settings?.storefrontLocales;
    if (!allowed?.length) return locales;
    return locales.filter((row) => allowed.includes(row.value));
  }, [settings?.storefrontLocales]);

  const load = useCallback(async () => {
    if (!quoteDraftId) return;
    setLoading(true);
    setError("");
    try {
      const [nextDraft, nextTemplates, merchantSettings] = await Promise.all([
        getPublicQuoteDraft(quoteDraftId),
        listQuoteExcelTemplates().catch(() => []),
        getMerchantSettings().catch(() => undefined),
      ]);
      setDraft(nextDraft);
      setTemplates(nextTemplates);
      setSettings(merchantSettings);
      setLocale(nextDraft.locale);
      setStyle(nextDraft.documentStyle);
      setTemplateId(nextDraft.quoteTemplateId ?? "");
    } catch (reason) {
      if (reason instanceof CoreApiError && reason.status === 404) {
        setError(t("这条询价单不存在或已被删除。"));
      } else {
        setError(reason instanceof Error ? reason.message : t("报价工作台加载失败"));
      }
    } finally {
      setLoading(false);
    }
  }, [quoteDraftId, t]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (enabledLocales.length && !enabledLocales.some((row) => row.value === locale)) {
      setLocale(enabledLocales[0].value);
    }
  }, [enabledLocales, locale]);

  const save = useCallback(async () => {
    if (!draft) return draft;
    setSaving(true);
    setError("");
    try {
      const next = await updatePublicQuoteDraftSettings(draft.id, {
        locale,
        style,
        templateId: templateId || null,
      });
      setDraft(next);
      return next;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("报价单设置保存失败"));
      return undefined;
    } finally {
      setSaving(false);
    }
  }, [draft, locale, style, templateId, t]);

  const download = async (type: "pdf" | "xlsx") => {
    if (!draft) return;
    setDownloading(type);
    setError("");
    try {
      const saved = await save();
      if (!saved) return;
      await downloadPublicQuoteDraftDocument(saved.id, saved.quoteNumber, type);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("报价文件下载失败"));
    } finally {
      setDownloading(null);
    }
  };

  const confirm = async () => {
    if (!draft) return;
    setConfirming(true);
    setError("");
    try {
      const saved = await save();
      if (!saved) return;
      await updatePublicQuoteDraftStatus(saved.id, "CONFIRMED");
      navigate("/console/quotes");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("报价单确认失败"));
    } finally {
      setConfirming(false);
    }
  };

  const copyNumber = async () => {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(draft.quoteNumber);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setError(t("复制失败，请手动选择报价单编号。"));
    }
  };

  if (loading) return <div className="core-workspace"><CoreLoading label={t("正在打开报价工作台")} /></div>;
  if (error && !draft) return <div className="core-workspace"><CoreError message={error} onRetry={() => void load()} /></div>;
  if (!draft) return null;

  const selectedStyle = styles.find((row) => row.value === style) ?? styles[0];
  const readyTemplates = templates.filter((row) => row.isReady);

  return <div className={`core-workspace quote-workbench quote-workbench--${style}`}>
    <CorePageHeading
      eyebrow={t("多证工作台")}
      title={t("制作报价单")}
      description={t("先完成报价单，其他外贸单证将在后续版本接入。")}
      actions={<Button asChild variant="soft" color="gray"><Link to="/console/quotes"><ArrowLeft />{t("返回询价列表")}</Link></Button>}
    />
    {error ? <CoreError message={error} /> : null}

    <Card className="quote-workbench-toolbar">
      <div className="quote-workbench-number">
        <Text size="1" color="gray">{t("报价单编号")}</Text>
        <div className="quote-number-control"><TextField.Root value={draft.quoteNumber} readOnly /><Button size="1" variant="soft" color="gray" onClick={() => void copyNumber()}><Copy />{copied ? t("已复制") : t("复制")}</Button></div>
      </div>
      <div className="quote-workbench-control">
        <Text size="1" color="gray"><Palette />{t("PDF 样式")}</Text>
        <div className="quote-style-options">{styles.map((option) => <button type="button" key={option.value} className={option.value === style ? "active" : ""} onClick={() => setStyle(option.value)}><span style={{ background: option.color }} />{t(option.label)}</button>)}</div>
      </div>
      <label className="quote-workbench-select"><Text size="1" color="gray">{t("报价语言")}</Text><Select.Root value={locale} onValueChange={(value) => setLocale(value as StorefrontLocale)}><Select.Trigger /><Select.Content position="popper">{enabledLocales.map((option) => <Select.Item key={option.value} value={option.value}>{localeLabel(option.value)}</Select.Item>)}</Select.Content></Select.Root></label>
      <label className="quote-workbench-select"><Text size="1" color="gray">{t("Excel 模板")}</Text><Select.Root value={templateId || "default"} onValueChange={(value) => setTemplateId(value === "default" ? "" : value)}><Select.Trigger /><Select.Content position="popper"><Select.Item value="default">{t("系统默认模板")}</Select.Item>{readyTemplates.map((template) => <Select.Item key={template.id} value={template.id}>{template.name}</Select.Item>)}</Select.Content></Select.Root></label>
      <div className="quote-workbench-actions"><Button variant="soft" disabled={saving} onClick={() => void save()}><FloppyDisk />{t("保存设置")}</Button><Button variant="soft" loading={downloading === "pdf"} onClick={() => void download("pdf")}><FilePdf />PDF</Button><Button loading={downloading === "xlsx"} onClick={() => void download("xlsx")}><FileXls />Excel</Button>{draft.status === "PENDING_CONFIRMATION" ? <Button color="green" loading={confirming} onClick={() => void confirm()}><PaperPlaneTilt />{t("确认并下发")}</Button> : <Badge color="jade"><CheckCircle />{t(draft.status)}</Badge>}</div>
    </Card>

    <Tabs.Root defaultValue="quotation" className="quote-doc-tabs">
      <Tabs.List>
        <Tabs.Trigger value="quotation"><FileText />{t("报价单")}</Tabs.Trigger>
        <Tabs.Trigger value="proforma" disabled><LockKey />{t("形式发票")}</Tabs.Trigger>
        <Tabs.Trigger value="sales-contract" disabled><LockKey />{t("销售合同")}</Tabs.Trigger>
        <Tabs.Trigger value="commercial-invoice" disabled><LockKey />{t("商业发票")}</Tabs.Trigger>
        <Tabs.Trigger value="packing-list" disabled><LockKey />{t("装箱单")}</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="quotation">
        <Card className="quote-preview-card" style={{ "--quote-accent": selectedStyle.color } as React.CSSProperties}>
          <div className="quote-preview-header"><div><Text size="1" color="gray">{localeLabel(locale)}</Text><Heading size="7">{t("报价单")}</Heading><Text size="2" color="gray">{draft.quoteNumber} · {coreDate(draft.createdAt)}</Text></div><Badge style={{ background: selectedStyle.color, color: "white" }}>{t(selectedStyle.label)}</Badge></div>
          <div className="quote-preview-meta"><div><span>{t("客户")}</span><strong>{draft.customerCompany || draft.customerName}</strong></div><div><span>{t("联系人")}</span><strong>{draft.customerName}</strong></div><div><span>{t("有效期")}</span><strong>{coreDate(draft.validUntil)}</strong></div><div><span>{t("币种")}</span><strong>{draft.currency}</strong></div></div>
          <div className="quote-preview-table"><div className="quote-preview-row quote-preview-head"><span>#</span><span>{t("商品 / SKU")}</span><span>{t("数量")}</span><span>{t("单价")}</span><span>{t("小计")}</span></div>{draft.items.map((item) => <div className="quote-preview-row" key={item.id}><span>{item.position}</span><span className="quote-preview-product"><strong>{item.name}</strong><small>{item.skuCode}{item.specification ? ` · ${item.specification}` : ""}</small></span><span>{item.quantity} {item.unitCode}</span><span>{item.currency} {item.unitPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span><strong>{item.currency} {item.lineTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong></div>)}<div className="quote-preview-total"><span>{t("报价合计")}</span><strong>{draft.currency} {draft.total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong></div></div>
          {draft.notes ? <Card className="quote-preview-notes"><ClipboardText /><div><Text size="1" color="gray">{t("客户备注")}</Text><Text as="div">{draft.notes}</Text></div></Card> : null}
          <div className="quote-preview-footer"><Text size="1" color="gray">{draft.disclaimer}</Text><span>{t("当前语言")}: {localeLabel(locale)}</span></div>
        </Card>
      </Tabs.Content>
      {(["proforma", "sales-contract", "commercial-invoice", "packing-list"] as const).map((value) => <Tabs.Content value={value} key={value}><Card className="quote-coming-soon"><LockKey size={28} /><Heading size="4">{t("该单证将在后续版本开放")}</Heading><Text size="2" color="gray">{t("当前先完成报价单的制作、样式设置和文件导出。")}</Text></Card></Tabs.Content>)}
    </Tabs.Root>
  </div>;
}
