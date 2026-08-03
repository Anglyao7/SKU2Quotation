import {
  AlertDialog,
  Badge,
  Button,
  Card,
  Heading,
  Select,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowsClockwise,
  CheckCircle,
  DownloadSimple,
  FileArrowUp,
  FileXls,
  FloppyDisk,
  MagicWand,
  Star,
  Table,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteQuoteExcelTemplate,
  downloadSystemDefaultQuoteTemplate,
  listQuoteExcelTemplates,
  reparseQuoteExcelTemplate,
  updateQuoteExcelTemplate,
  uploadQuoteExcelTemplate,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  QuoteExcelTemplate,
  QuoteTemplateField,
} from "../types";
import "./QuoteTemplatesPage.css";


const UNMAPPED = "__unmapped__";

const systemFields: Array<{ value: QuoteTemplateField; label: string; group: string }> = [
  { value: "serial_number", label: "序号", group: "商品明细" },
  { value: "sku_code", label: "SKU 编码", group: "商品明细" },
  { value: "product_name", label: "商品名称", group: "商品明细" },
  { value: "description", label: "商品描述", group: "商品明细" },
  { value: "specification", label: "商品规格", group: "商品明细" },
  { value: "category", label: "商品分类", group: "商品明细" },
  { value: "tags", label: "商品标签", group: "商品明细" },
  { value: "product_image", label: "商品图片", group: "商品明细" },
  { value: "quantity", label: "数量", group: "报价数据" },
  { value: "unit_code", label: "单位", group: "报价数据" },
  { value: "packing_quantity", label: "装箱数量", group: "包装物流" },
  { value: "carton_dimensions", label: "装箱尺寸", group: "包装物流" },
  { value: "gross_weight", label: "毛重（kg）", group: "包装物流" },
  { value: "carton_volume", label: "立方（m³）", group: "包装物流" },
  { value: "unit_price", label: "单价", group: "报价数据" },
  { value: "line_total", label: "总价", group: "报价数据" },
  { value: "total_volume", label: "总立方（m³）", group: "包装物流" },
  { value: "total_gross_weight", label: "总毛重（kg）", group: "包装物流" },
  { value: "currency", label: "币种", group: "报价数据" },
  { value: "quote_number", label: "报价单号", group: "报价信息" },
  { value: "quote_date", label: "报价日期", group: "报价信息" },
  { value: "customer_name", label: "客户姓名", group: "客户信息" },
  { value: "customer_company", label: "客户公司", group: "客户信息" },
  { value: "customer_email", label: "客户邮箱", group: "客户信息" },
  { value: "customer_phone", label: "客户电话", group: "客户信息" },
  { value: "notes", label: "报价备注", group: "报价信息" },
];

interface EditorDraft {
  name: string;
  sheetName: string;
  headerRow: number;
  mappings: Partial<Record<string, QuoteTemplateField>>;
}

function editorDraft(template: QuoteExcelTemplate): EditorDraft {
  return {
    name: template.name,
    sheetName: template.sheetName,
    headerRow: template.headerRow,
    mappings: { ...template.columnMappings },
  };
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function QuoteTemplatesPage() {
  const { t } = useLocale();
  const inputRef = useRef<HTMLInputElement>(null);
  const [templates, setTemplates] = useState<QuoteExcelTemplate[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState<EditorDraft>();
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [downloadingDefault, setDownloadingDefault] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reparsing, setReparsing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [error, setError] = useState("");

  const selected = useMemo(
    () => templates.find((template) => template.id === selectedId),
    [selectedId, templates],
  );
  const mappedCount = draft ? Object.values(draft.mappings).filter(Boolean).length : 0;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await listQuoteExcelTemplates();
      setTemplates(rows);
      setSelectedId((current) => (
        rows.some((row) => row.id === current)
          ? current
          : rows.find((row) => row.isDefault)?.id || rows[0]?.id || ""
      ));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("报价模板加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    setDraft(selected ? editorDraft(selected) : undefined);
  }, [selected?.id, selected?.version]);

  const replaceTemplate = (next: QuoteExcelTemplate) => {
    setTemplates((current) => {
      const rows = current.some((row) => row.id === next.id)
        ? current.map((row) => row.id === next.id ? next : (
          next.isDefault ? { ...row, isDefault: false } : row
        ))
        : [next, ...current];
      return rows.sort((left, right) => Number(right.isDefault) - Number(left.isDefault));
    });
    setSelectedId(next.id);
  };

  const upload = async (file?: File) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setError(t("这里只支持 .xlsx 格式的 Excel 报价单。"));
      return;
    }
    setUploading(true);
    setError("");
    try {
      replaceTemplate(await uploadQuoteExcelTemplate(file));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("报价模板上传失败"));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const downloadDefault = async () => {
    setDownloadingDefault(true);
    setError("");
    try {
      await downloadSystemDefaultQuoteTemplate();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("默认报价模板下载失败"));
    } finally {
      setDownloadingDefault(false);
    }
  };

  const save = async (makeDefault: boolean) => {
    if (!selected || !draft || !draft.name.trim() || mappedCount === 0) return;
    setSaving(true);
    setError("");
    try {
      replaceTemplate(await updateQuoteExcelTemplate(selected.id, {
        name: draft.name.trim(),
        columnMappings: draft.mappings,
        isDefault: selected.isDefault || makeDefault,
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("报价模板保存失败"));
    } finally {
      setSaving(false);
    }
  };

  const reparse = async () => {
    if (!selected || !draft || !draft.sheetName || draft.headerRow < 1) return;
    setReparsing(true);
    setError("");
    try {
      replaceTemplate(await reparseQuoteExcelTemplate(
        selected.id,
        draft.sheetName,
        draft.headerRow,
      ));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("重新识别表头失败"));
    } finally {
      setReparsing(false);
    }
  };

  const remove = async () => {
    if (!selected) return;
    setDeleting(true);
    setError("");
    try {
      await deleteQuoteExcelTemplate(selected.id);
      setDeleteOpen(false);
      const remaining = templates.filter((row) => row.id !== selected.id);
      setTemplates(remaining);
      setSelectedId(remaining.find((row) => row.isDefault)?.id || remaining[0]?.id || "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("报价模板删除失败"));
    } finally {
      setDeleting(false);
    }
  };

  return <div className="core-workspace quote-template-workspace">
    <CorePageHeading
      eyebrow={t("报价设置")}
      title={t("报价单模板")}
      description={t("上传商家自己的 Excel 报价单，确认表头后把模板列映射到系统字段。客户下载时会自动沿用默认模板的原始版式。")}
      actions={<>
        <input
          ref={inputRef}
          className="quote-template-file-input"
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(event) => void upload(event.target.files?.[0])}
        />
        <Button size="3" variant="soft" color="gray" loading={downloadingDefault} onClick={() => void downloadDefault()}>
          <DownloadSimple />{t("下载系统默认模板")}
        </Button>
        <Button size="3" loading={uploading} onClick={() => inputRef.current?.click()}>
          <FileArrowUp />{t(uploading ? "正在解析" : "上传 Excel")}
        </Button>
      </>}
    />

    {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
    {loading && !templates.length ? <CoreLoading label={t("正在读取报价模板")} /> : null}

    {!loading && !templates.length ? <Card className="quote-template-empty-card">
      <CoreEmpty
        title={t("还没有自定义报价单")}
        description={t("上传一份现有 .xlsx 报价单，系统会识别工作表、表头和示例数据，并预先匹配常见字段。")}
        action={<Button size="3" onClick={() => inputRef.current?.click()}><FileXls />{t("上传第一份模板")}</Button>}
      />
    </Card> : null}

    {templates.length ? <div className="quote-template-layout">
      <aside className="quote-template-list" aria-label={t("报价模板列表")}>
        <div className="quote-template-list-heading">
          <div><Text size="2" weight="bold">{t("模板")}</Text><Text size="1" color="gray">{t("{count} 份", { count: templates.length })}</Text></div>
          <Button size="1" variant="ghost" color="gray" onClick={() => inputRef.current?.click()}><FileArrowUp />{t("新增")}</Button>
        </div>
        {templates.map((template) => <button
          type="button"
          key={template.id}
          className={`quote-template-list-item ${template.id === selectedId ? "active" : ""}`}
          onClick={() => setSelectedId(template.id)}
        >
          <span className="quote-template-file-icon"><FileXls weight="duotone" /></span>
          <span className="quote-template-list-copy">
            <strong>{template.name}</strong>
            <small>{template.columns.length} {t("列")} · {formatBytes(template.byteSize)}</small>
          </span>
          {template.isDefault ? <Badge color="amber"><Star weight="fill" />{t("默认")}</Badge> : template.isReady ? <Badge color="jade">{t("已映射")}</Badge> : <Badge color="gray">{t("待设置")}</Badge>}
        </button>)}
      </aside>

      <section className="quote-template-editor">
        {selected && draft ? <>
          <div className="quote-template-editor-heading">
            <div>
              <div className="quote-template-title-row">
                <Heading size="6">{selected.name}</Heading>
                {selected.isDefault ? <Badge color="amber" size="2"><Star weight="fill" />{t("当前默认模板")}</Badge> : null}
              </div>
              <Text size="2" color="gray">{selected.originalFilename} · {t("更新于 {time}", { time: coreDate(selected.updatedAt) })}</Text>
            </div>
            <Button variant="ghost" color="red" onClick={() => setDeleteOpen(true)}><Trash />{t("删除")}</Button>
          </div>

          <div className="quote-template-steps" aria-label={t("设置进度")}>
            <span className="complete"><CheckCircle weight="fill" />{t("文件已解析")}</span>
            <span className={mappedCount ? "complete" : ""}><MagicWand weight={mappedCount ? "fill" : "regular"} />{t("映射 {mapped}/{total}", { mapped: mappedCount, total: selected.columns.length })}</span>
            <span className={selected.isDefault ? "complete" : ""}><Star weight={selected.isDefault ? "fill" : "regular"} />{t("设为默认")}</span>
          </div>

          <Card className="quote-template-source-card">
            <label>
              <Text size="1" color="gray">{t("模板名称")}</Text>
              <TextField.Root value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            </label>
            <label>
              <Text size="1" color="gray">{t("商品明细工作表")}</Text>
              <Select.Root value={draft.sheetName} onValueChange={(value) => setDraft({ ...draft, sheetName: value })}>
                <Select.Trigger />
                <Select.Content>{selected.sheetNames.map((name) => <Select.Item key={name} value={name}>{name}</Select.Item>)}</Select.Content>
              </Select.Root>
            </label>
            <label>
              <Text size="1" color="gray">{t("表头所在行")}</Text>
              <TextField.Root type="number" min="1" value={String(draft.headerRow)} onChange={(event) => setDraft({ ...draft, headerRow: Math.max(1, Number(event.target.value) || 1) })} />
            </label>
            <Button variant="soft" color="gray" loading={reparsing} onClick={() => void reparse()}><ArrowsClockwise />{t("重新识别")}</Button>
          </Card>

          <div className="quote-template-map-heading">
            <div><Heading size="4">{t("列映射")}</Heading><Text size="2" color="gray">{t("左侧是模板中的原列，右侧选择导出时要写入的系统数据。未映射列会保持为空。")}</Text></div>
            <Badge color={mappedCount ? "jade" : "gray"} size="2"><Table />{t("已映射 {count} 列", { count: mappedCount })}</Badge>
          </div>

          <div className="quote-template-map-table">
            <div className="quote-template-map-header"><span>{t("模板列")}</span><span>{t("示例内容")}</span><span>{t("对应系统字段")}</span></div>
            {selected.columns.map((column) => {
              const mapped = draft.mappings[column.key];
              return <div className={`quote-template-map-row ${mapped ? "mapped" : ""}`} key={column.key}>
                <div className="quote-template-column-name"><Badge variant="solid" color={mapped ? "blue" : "gray"}>{column.key}</Badge><span><strong>{column.header}</strong>{column.suggestedField ? <small><MagicWand />{t("已智能匹配")}</small> : null}</span></div>
                <Text size="2" color="gray" className="quote-template-sample">{column.samples[0] || t("暂无示例")}</Text>
                <Select.Root value={mapped || UNMAPPED} onValueChange={(value) => {
                  const mappings = { ...draft.mappings };
                  if (value === UNMAPPED) delete mappings[column.key];
                  else mappings[column.key] = value as QuoteTemplateField;
                  setDraft({ ...draft, mappings });
                }}>
                  <Select.Trigger className="quote-template-field-select" />
                  <Select.Content position="popper">
                    <Select.Item value={UNMAPPED}>{t("不填充数据（保留空列）")}</Select.Item>
                    {Array.from(new Set(systemFields.map((field) => field.group))).map((group) => <Select.Group key={group}>
                      <Select.Label>{t(group)}</Select.Label>
                      {systemFields.filter((field) => field.group === group).map((field) => <Select.Item key={field.value} value={field.value}>{t(field.label)}</Select.Item>)}
                    </Select.Group>)}
                  </Select.Content>
                </Select.Root>
              </div>;
            })}
          </div>

          <div className="quote-template-editor-actions">
            {mappedCount === 0 ? <Text size="2" color="amber"><WarningCircle />{t("至少映射一列后才能保存。")}</Text> : <Text size="2" color="gray">{selected.isDefault ? t("保存后，新的报价下载会立即使用这套映射。") : t("保存为默认后，客户下载 Excel 时会使用这份模板。")}</Text>}
            <div>
              {!selected.isDefault ? <Button variant="soft" color="gray" disabled={!mappedCount || !draft.name.trim()} loading={saving} onClick={() => void save(false)}><FloppyDisk />{t("仅保存映射")}</Button> : null}
              <Button disabled={!mappedCount || !draft.name.trim()} loading={saving} onClick={() => void save(!selected.isDefault)}>{selected.isDefault ? <FloppyDisk /> : <Star weight="fill" />}{t(selected.isDefault ? "保存修改" : "保存并设为默认")}</Button>
            </div>
          </div>
        </> : null}
      </section>
    </div> : null}

    <AlertDialog.Root open={deleteOpen} onOpenChange={setDeleteOpen}>
      <AlertDialog.Content>
        <AlertDialog.Title>{t("删除报价模板")}</AlertDialog.Title>
        <AlertDialog.Description>{t("删除“{name}”后无法恢复；如果它是默认模板，系统会暂时改用标准报价单。", { name: selected?.name || "" })}</AlertDialog.Description>
        <div className="core-dialog-actions">
          <AlertDialog.Cancel><Button variant="soft" color="gray" disabled={deleting}>{t("取消")}</Button></AlertDialog.Cancel>
          <Button color="red" loading={deleting} onClick={() => void remove()}>{t("确认删除")}</Button>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>
  </div>;
}
