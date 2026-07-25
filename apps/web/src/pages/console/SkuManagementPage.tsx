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
  TextArea,
  TextField,
  Tooltip,
} from "@radix-ui/themes";
import {
  CheckCircle,
  FileArrowUp,
  MagnifyingGlass,
  NotePencil,
  Plus,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useOutletContext } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useAuth } from "../../context/AuthContext";
import { api } from "../../lib/api";
import { money } from "../../lib/format";
import type { Sku, SkuImportResult, SkuPayload } from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";

const emptyPayload: SkuPayload = {
  sku_code: "",
  name: "",
  category: "",
  tags: [],
  description: "",
  image_url: "",
  price: null,
  currency: "CNY",
  stock: null,
  active: true,
};

export function SkuManagementPage() {
  const { user } = useAuth();
  const { activeTenantId } = useOutletContext<ConsoleOutletContext>();
  const [skus, setSkus] = useState<Sku[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Sku | "new" | null>(null);
  const [deleting, setDeleting] = useState<Sku | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const isPlatformAdmin = user?.role === "platform_admin";

  const load = useCallback(async () => {
    if (isPlatformAdmin && !activeTenantId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api.getConsoleSkus(search.trim(), page);
      setSkus(data.items);
      setTotal(data.total);
      setPages(data.pages || 0);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "SKU 列表加载失败。");
    } finally {
      setLoading(false);
    }
  }, [activeTenantId, search, page, isPlatformAdmin]);

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 240);
    return () => window.clearTimeout(timeout);
  }, [load]);

  const deleteSku = async () => {
    if (!deleting) return;
    try {
      await api.deleteSku(deleting.id);
      setDeleting(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "SKU 删除失败。");
      setDeleting(null);
    }
  };

  return (
    <div className="console-page">
      <div className="page-heading-row">
        <div><Text size="2" color="gray">商品资料与上下架状态</Text><Heading size="7">SKU 管理</Heading></div>
        <div className="page-actions">
          <Button variant="soft" onClick={() => setImportOpen(true)}><FileArrowUp size={18} />批量导入</Button>
          <Button onClick={() => setEditing("new")}><Plus size={18} />新增 SKU</Button>
        </div>
      </div>

      <div className="toolbar-row">
        <TextField.Root value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索 SKU 编码或名称" className="console-search">
          <TextField.Slot><MagnifyingGlass size={18} /></TextField.Slot>
        </TextField.Root>
        <Text size="2" color="gray">共 {total.toLocaleString("zh-CN")} 条</Text>
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : loading ? <TableSkeleton /> : skus.length === 0 ? (
        <EmptyState title="还没有 SKU" description="新增单个 SKU，或上传 CSV/XLSX 批量导入。" action={<Button onClick={() => setEditing("new")}><Plus size={17} />新增 SKU</Button>} />
      ) : (
        <>
          <div className="desktop-table surface-panel">
            <Table.Root variant="surface" size="2">
              <Table.Header><Table.Row><Table.ColumnHeaderCell>SKU</Table.ColumnHeaderCell><Table.ColumnHeaderCell>商品名称</Table.ColumnHeaderCell><Table.ColumnHeaderCell>类目 / 标签</Table.ColumnHeaderCell><Table.ColumnHeaderCell>价格</Table.ColumnHeaderCell><Table.ColumnHeaderCell>状态</Table.ColumnHeaderCell><Table.ColumnHeaderCell justify="end">操作</Table.ColumnHeaderCell></Table.Row></Table.Header>
              <Table.Body>
                {skus.map((sku) => (
                  <Table.Row key={sku.id}>
                    <Table.RowHeaderCell><Text className="mono-text" size="2" weight="medium">{sku.sku_code}</Text></Table.RowHeaderCell>
                    <Table.Cell><Text size="2" weight="medium">{sku.name}</Text></Table.Cell>
                    <Table.Cell><Text as="div" size="2">{sku.category || "未分类"}</Text><Text as="div" size="1" color="gray" className="table-tags">{sku.tags.slice(0, 3).join(" / ") || "无标签"}</Text></Table.Cell>
                    <Table.Cell><Text size="2" weight="medium">{money(sku.price, sku.currency)}</Text></Table.Cell>
                    <Table.Cell><Badge color={sku.status === "inactive" ? "gray" : "jade"} variant="soft">{sku.status === "inactive" ? "已下架" : "在售"}</Badge></Table.Cell>
                    <Table.Cell justify="end"><div className="table-actions"><Tooltip content="编辑"><IconButton size="1" variant="ghost" color="gray" aria-label={`编辑 ${sku.name}`} onClick={() => setEditing(sku)}><NotePencil size={17} /></IconButton></Tooltip><Tooltip content="删除"><IconButton size="1" variant="ghost" color="red" aria-label={`删除 ${sku.name}`} onClick={() => setDeleting(sku)}><Trash size={17} /></IconButton></Tooltip></div></Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table.Root>
          </div>
          <div className="mobile-data-list">
            {skus.map((sku) => (
              <div className="mobile-data-card" key={sku.id}>
                <div><Text className="mono-text" size="1" color="gray">{sku.sku_code}</Text><Text as="div" size="3" weight="medium">{sku.name}</Text></div>
                <Badge color={sku.status === "inactive" ? "gray" : "jade"} variant="soft">{sku.status === "inactive" ? "已下架" : "在售"}</Badge>
                <Text size="2" color="gray">{sku.category || "未分类"} / {sku.tags.slice(0, 2).join(" / ") || "无标签"}</Text>
                <div className="mobile-card-footer"><Text weight="bold">{money(sku.price, sku.currency)}</Text><div><IconButton variant="ghost" color="gray" aria-label={`编辑 ${sku.name}`} onClick={() => setEditing(sku)}><NotePencil /></IconButton><IconButton variant="ghost" color="red" aria-label={`删除 ${sku.name}`} onClick={() => setDeleting(sku)}><Trash /></IconButton></div></div>
              </div>
            ))}
          </div>
          {pages > 1 && (
            <div className="pagination-row">
              <Button variant="soft" color="gray" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>上一页</Button>
              <Text size="2" color="gray">第 {page} / {pages} 页</Text>
              <Button variant="soft" color="gray" disabled={page >= pages} onClick={() => setPage((current) => current + 1)}>下一页</Button>
            </div>
          )}
        </>
      )}

      <SkuFormDialog sku={editing} onOpenChange={(open) => { if (!open) setEditing(null); }} onSaved={async () => { setEditing(null); await load(); }} />
      <ImportDialog open={importOpen} onOpenChange={setImportOpen} onImported={load} />

      <AlertDialog.Root open={Boolean(deleting)} onOpenChange={(open) => { if (!open) setDeleting(null); }}>
        <AlertDialog.Content>
          <AlertDialog.Title>删除这个 SKU？</AlertDialog.Title>
          <AlertDialog.Description>“{deleting?.name}”将从控制台移除。已有报价记录不会被修改。</AlertDialog.Description>
          <div className="dialog-actions"><AlertDialog.Cancel><Button variant="soft" color="gray">取消</Button></AlertDialog.Cancel><AlertDialog.Action><Button color="red" onClick={() => void deleteSku()}>确认删除</Button></AlertDialog.Action></div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}

function SkuFormDialog({ sku, onOpenChange, onSaved }: { sku: Sku | "new" | null; onOpenChange: (open: boolean) => void; onSaved: () => Promise<void> }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const current = sku && sku !== "new" ? sku : null;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    const data = new FormData(event.currentTarget);
    const numberOrNull = (name: string) => {
      const value = String(data.get(name) || "").trim();
      return value ? Number(value) : null;
    };
    const payload: SkuPayload = {
      ...emptyPayload,
      sku_code: String(data.get("sku_code") || "").trim(),
      name: String(data.get("name") || "").trim(),
      category: String(data.get("category") || "").trim(),
      tags: String(data.get("tags") || "").split(/[,，]/).map((tag) => tag.trim()).filter(Boolean),
      description: String(data.get("description") || "").trim(),
      image_url: String(data.get("image_url") || "").trim(),
      price: numberOrNull("price"),
      currency: String(data.get("currency") || "CNY"),
      stock: numberOrNull("stock"),
      active: String(data.get("status") || "active") === "active",
    };
    try {
      if (current) await api.updateSku(current.id, payload);
      else await api.createSku(payload);
      await onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "SKU 保存失败。");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={Boolean(sku)} onOpenChange={onOpenChange}>
      <Dialog.Content className="form-dialog">
        <Dialog.Title>{current ? "编辑 SKU" : "新增 SKU"}</Dialog.Title>
        <Dialog.Description>每条记录对应前台展示的一个独立 SKU。</Dialog.Description>
        <form className="dialog-form" onSubmit={submit} key={current?.id || "new"}>
          <div className="form-grid">
            <label className="field-group"><Text size="2" weight="medium">SKU 编码 *</Text><TextField.Root name="sku_code" required defaultValue={current?.sku_code} placeholder="例如 CW-001" /></label>
            <label className="field-group"><Text size="2" weight="medium">商品名称 *</Text><TextField.Root name="name" required defaultValue={current?.name} placeholder="请输入商品名称" /></label>
            <label className="field-group"><Text size="2" weight="medium">类目</Text><TextField.Root name="category" defaultValue={current?.category || ""} placeholder="例如 杯壶" /></label>
            <label className="field-group"><Text size="2" weight="medium">标签</Text><TextField.Root name="tags" defaultValue={current?.tags.join("，") || ""} placeholder="户外，便携，保温" /></label>
            <label className="field-group"><Text size="2" weight="medium">价格</Text><TextField.Root name="price" type="number" min="0" step="0.01" defaultValue={current?.price ?? ""} placeholder="0.00" /></label>
            <label className="field-group"><Text size="2" weight="medium">币种</Text><Select.Root name="currency" defaultValue={current?.currency || "CNY"}><Select.Trigger /><Select.Content><Select.Item value="CNY">CNY 人民币</Select.Item><Select.Item value="USD">USD 美元</Select.Item><Select.Item value="EUR">EUR 欧元</Select.Item></Select.Content></Select.Root></label>
            <label className="field-group"><Text size="2" weight="medium">库存</Text><TextField.Root name="stock" type="number" min="0" defaultValue={current?.stock ?? ""} placeholder="可选" /></label>
            <label className="field-group field-span-2"><Text size="2" weight="medium">图片地址</Text><TextField.Root name="image_url" type="url" defaultValue={current?.image_url || ""} placeholder="https://..." /></label>
            <label className="field-group field-span-2"><Text size="2" weight="medium">商品描述</Text><TextArea name="description" defaultValue={current?.description || ""} placeholder="材质、尺寸、包装等说明" /></label>
            <label className="field-group"><Text size="2" weight="medium">状态</Text><Select.Root name="status" defaultValue={current?.status || "active"}><Select.Trigger /><Select.Content><Select.Item value="active">在售</Select.Item><Select.Item value="inactive">下架</Select.Item></Select.Content></Select.Root></label>
          </div>
          {error && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root>}
          <div className="dialog-actions"><Dialog.Close><Button type="button" variant="soft" color="gray">取消</Button></Dialog.Close><Button type="submit" loading={saving}>保存 SKU</Button></div>
        </form>
      </Dialog.Content>
    </Dialog.Root>
  );
}

function ImportDialog({ open, onOpenChange, onImported }: { open: boolean; onOpenChange: (open: boolean) => void; onImported: () => Promise<void> }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<SkuImportResult | null>(null);
  const [error, setError] = useState("");

  const reset = () => { setFile(null); setResult(null); setError(""); if (inputRef.current) inputRef.current.value = ""; };
  const changeOpen = (next: boolean) => { onOpenChange(next); if (!next) reset(); };
  const upload = async () => {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const next = await api.importSkus(file);
      setResult(next);
      await onImported();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "文件导入失败。");
    } finally {
      setUploading(false);
    }
  };
  const created = result?.imported ?? result?.created ?? result?.inserted ?? 0;

  return (
    <Dialog.Root open={open} onOpenChange={changeOpen}>
      <Dialog.Content className="import-dialog">
        <Dialog.Title>批量导入 SKU</Dialog.Title>
        <Dialog.Description>支持 CSV 和 XLSX。相同 SKU 编码会更新现有记录。</Dialog.Description>
        {!result ? (
          <>
            <button type="button" className="file-drop" onClick={() => inputRef.current?.click()}>
              <FileArrowUp size={32} weight="duotone" />
              <strong>{file ? file.name : "选择 SKU 文件"}</strong>
              <span>{file ? `${(file.size / 1024).toFixed(1)} KB` : "CSV 或 XLSX，建议不超过 10 MB"}</span>
            </button>
            <input ref={inputRef} className="visually-hidden" type="file" accept=".csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv" onChange={(event) => setFile(event.target.files?.[0] || null)} />
            {error && <Callout.Root color="red"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error}</Callout.Text></Callout.Root>}
            <div className="dialog-actions"><Dialog.Close><Button variant="soft" color="gray">取消</Button></Dialog.Close><Button disabled={!file} loading={uploading} onClick={() => void upload()}>开始导入</Button></div>
          </>
        ) : (
          <div className="import-result">
            <span className="success-icon"><CheckCircle size={36} weight="duotone" /></span>
            <Heading size="5">导入处理完成</Heading>
            <div className="import-metrics"><div><strong>{created}</strong><span>新增</span></div><div><strong>{result.updated || 0}</strong><span>更新</span></div><div><strong>{result.failed ?? result.errors?.length ?? 0}</strong><span>错误</span></div></div>
            {result.errors?.length ? <div className="import-errors"><Text size="2" weight="medium">错误明细</Text>{result.errors.slice(0, 8).map((item, index) => <div key={index}><span>第 {item.row || "?"} 行</span><span>{item.sku_code || "未识别 SKU"}</span><span>{item.message || item.error || "格式错误"}</span></div>)}</div> : null}
            <Dialog.Close><Button>完成</Button></Dialog.Close>
          </div>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
