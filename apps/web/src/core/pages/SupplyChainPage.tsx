import {
  AlertDialog,
  Badge,
  Button,
  Card,
  Dialog,
  Select,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowsClockwise,
  EnvelopeSimple,
  Factory,
  Globe,
  MagnifyingGlass,
  MapPin,
  PencilSimple,
  Phone,
  Plus,
  Trash,
  User,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  createSupplyChainPartner,
  deleteSupplyChainPartner,
  listSupplyChainPartners,
  updateSupplyChainPartner,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  SupplyChainPage,
  SupplyChainPartner,
  SupplyChainPartnerInput,
  SupplyChainStatus,
} from "../types";
import "./SupplyChainPage.css";


const emptyPage: SupplyChainPage = {
  items: [],
  total: 0,
  page: 1,
  pageSize: 30,
  pages: 0,
};

interface SupplyChainForm extends SupplyChainPartnerInput {
  status: "ACTIVE" | "INACTIVE";
}

const emptyForm = (): SupplyChainForm => ({
  name: "",
  contactName: "",
  phone: "",
  email: "",
  whatsapp: "",
  wechat: "",
  countryRegion: "",
  address: "",
  website: "",
  businessScope: "",
  notes: "",
  status: "ACTIVE",
});

function partnerForm(partner: SupplyChainPartner): SupplyChainForm {
  return {
    name: partner.name,
    contactName: partner.contactName || "",
    phone: partner.phone || "",
    email: partner.email || "",
    whatsapp: partner.whatsapp || "",
    wechat: partner.wechat || "",
    countryRegion: partner.countryRegion || "",
    address: partner.address || "",
    website: partner.website || "",
    businessScope: partner.businessScope || "",
    notes: partner.notes || "",
    status: partner.status === "ACTIVE" ? "ACTIVE" : "INACTIVE",
  };
}

function statusLabel(status: SupplyChainStatus) {
  if (status === "ACTIVE") return "合作中";
  if (status === "INACTIVE") return "已停用";
  if (status === "BLOCKED") return "已暂停";
  return "已归档";
}

function statusColor(status: SupplyChainStatus): "jade" | "amber" | "gray" | "red" {
  if (status === "ACTIVE") return "jade";
  if (status === "BLOCKED") return "red";
  if (status === "INACTIVE") return "amber";
  return "gray";
}

function formatDate(value: string, locale: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function SupplyChainPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const canManage = hasPermission("supplier.manage");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [status, setStatus] = useState<"" | "ACTIVE" | "INACTIVE" | "BLOCKED">("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(30);
  const [result, setResult] = useState<SupplyChainPage>(emptyPage);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selected, setSelected] = useState<SupplyChainPartner>();
  const [form, setForm] = useState<SupplyChainForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<SupplyChainPartner>();
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await listSupplyChainPartners({
        query: debouncedQuery || undefined,
        status: status || undefined,
        page,
        pageSize,
      });
      setResult(next);
      if (next.pages && page > next.pages) setPage(next.pages);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("供应链加载失败"));
    } finally {
      setLoading(false);
    }
  }, [debouncedQuery, page, pageSize, status, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setSelected(undefined);
    setForm(emptyForm());
    setFormError("");
    setDialogOpen(true);
  };

  const openEdit = (partner: SupplyChainPartner) => {
    setSelected(partner);
    setForm(partnerForm(partner));
    setFormError("");
    setDialogOpen(true);
  };

  const setField = <K extends keyof SupplyChainForm>(
    field: K,
    value: SupplyChainForm[K],
  ) => setForm((current) => ({ ...current, [field]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.name.trim()) {
      setFormError(t("请填写工厂或合作方名称。"));
      return;
    }
    if (form.email && !/^\S+@\S+\.\S+$/.test(form.email)) {
      setFormError(t("请输入有效的邮箱地址。"));
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      if (selected) await updateSupplyChainPartner(selected, form);
      else await createSupplyChainPartner(form);
      setDialogOpen(false);
      await load();
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : t("供应链资料保存失败"));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteSupplyChainPartner(pendingDelete.id);
      setPendingDelete(undefined);
      await load();
    } catch (caught) {
      setPendingDelete(undefined);
      setError(caught instanceof Error ? caught.message : t("供应链删除失败"));
    } finally {
      setDeleting(false);
    }
  };

  const firstItem = result.total ? (result.page - 1) * result.pageSize + 1 : 0;
  const lastItem = Math.min(result.total, result.page * result.pageSize);

  return (
    <div className="core-workspace supply-chain-workspace">
      <CorePageHeading
        eyebrow={t("经营")}
        title={t("供应链")}
        actions={canManage ? <Button onClick={openCreate}><Plus />{t("新增供应链")}</Button> : undefined}
      />

      <Card className="supply-chain-toolbar">
        <TextField.Root
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("搜索工厂、联系人、电话或邮箱")}
          aria-label={t("搜索供应链")}
        >
          <TextField.Slot><MagnifyingGlass /></TextField.Slot>
        </TextField.Root>
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as typeof status);
            setPage(1);
          }}
          aria-label={t("按合作状态筛选")}
        >
          <option value="">{t("全部状态")}</option>
          <option value="ACTIVE">{t("合作中")}</option>
          <option value="INACTIVE">{t("已停用")}</option>
          <option value="BLOCKED">{t("已暂停")}</option>
        </select>
        <Button variant="soft" color="gray" disabled={loading} onClick={() => void load()}>
          <ArrowsClockwise />{t("刷新")}
        </Button>
      </Card>

      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {loading && !result.items.length ? <CoreLoading label={t("正在读取供应链")} /> : null}
      {!loading && !result.items.length && !error ? (
        <CoreEmpty
          title={t(debouncedQuery || status ? "没有符合条件的供应链" : "还没有供应链资料")}
          description={t(debouncedQuery || status ? "请调整搜索或筛选条件。" : "新增工厂或合作方后，可在这里统一维护联系方式。")}
          action={canManage && !debouncedQuery && !status ? <Button onClick={openCreate}><Plus />{t("新增供应链")}</Button> : undefined}
        />
      ) : null}

      {result.items.length ? (
        <Card className="supply-chain-table-card">
          <div className="supply-chain-summary">
            <Text size="2">{t("共 {total} 条 · 当前 {start}–{end}", {
              total: result.total,
              start: firstItem,
              end: lastItem,
            })}</Text>
            {loading ? <Text size="1" color="gray">{t("正在更新结果…")}</Text> : null}
          </div>
          <div className="supply-chain-table-scroll">
            <table className="supply-chain-table">
              <thead>
                <tr>
                  <th>{t("工厂 / 合作方")}</th>
                  <th>{t("联系人")}</th>
                  <th>{t("联系方式")}</th>
                  <th>{t("地区")}</th>
                  <th>{t("关联商品")}</th>
                  <th>{t("状态")}</th>
                  <th>{t("更新时间")}</th>
                  <th>{t("操作")}</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((partner) => (
                  <tr key={partner.id}>
                    <td data-label={t("工厂 / 合作方")}>
                      <span className="supply-chain-name-cell">
                        <span className="supply-chain-icon"><Factory weight="duotone" /></span>
                        <span><strong>{partner.name}</strong><small>{partner.businessScope || partner.code}</small></span>
                      </span>
                    </td>
                    <td data-label={t("联系人")}>
                      <span className="supply-chain-quiet-line"><User />{partner.contactName || "—"}</span>
                    </td>
                    <td data-label={t("联系方式")}>
                      <span className="supply-chain-contact-cell">
                        <span><Phone />{partner.phone || partner.whatsapp || "—"}</span>
                        {partner.email ? <small><EnvelopeSimple />{partner.email}</small> : null}
                      </span>
                    </td>
                    <td data-label={t("地区")}>
                      <span className="supply-chain-quiet-line"><MapPin />{partner.countryRegion || "—"}</span>
                    </td>
                    <td data-label={t("关联商品")}>
                      <strong>{t("{products} 个商品 / {skus} 个 SKU", {
                        products: partner.activeProducts,
                        skus: partner.activeSkus,
                      })}</strong>
                    </td>
                    <td data-label={t("状态")}>
                      <Badge color={statusColor(partner.status)}>{t(statusLabel(partner.status))}</Badge>
                    </td>
                    <td data-label={t("更新时间")}>{formatDate(partner.updatedAt, locale)}</td>
                    <td data-label={t("操作")}>
                      {canManage ? <span className="supply-chain-row-actions">
                        <Button size="1" variant="ghost" color="gray" onClick={() => openEdit(partner)}>
                          <PencilSimple />{t("编辑")}
                        </Button>
                        <Button size="1" variant="ghost" color="red" onClick={() => setPendingDelete(partner)}>
                          <Trash />{t("删除")}
                        </Button>
                      </span> : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="supply-chain-pagination">
            <label>
              <span>{t("每页")}</span>
              <select value={pageSize} onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(1);
              }}>
                <option value="30">30</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </select>
            </label>
            <span>{t("第 {page} / {pages} 页", { page: result.page, pages: Math.max(1, result.pages) })}</span>
            <div>
              <Button size="1" variant="soft" color="gray" disabled={page <= 1 || loading} onClick={() => setPage((current) => current - 1)}>{t("上一页")}</Button>
              <Button size="1" variant="soft" color="gray" disabled={page >= result.pages || loading} onClick={() => setPage((current) => current + 1)}>{t("下一页")}</Button>
            </div>
          </div>
        </Card>
      ) : null}

      <Dialog.Root open={dialogOpen} onOpenChange={(open) => {
        if (!saving) setDialogOpen(open);
      }}>
        <Dialog.Content className="supply-chain-dialog">
          <Dialog.Title>{t(selected ? "编辑供应链" : "新增供应链")}</Dialog.Title>
          <form onSubmit={(event) => void submit(event)}>
            <div className="supply-chain-form-scroll">
              <section className="supply-chain-form-section">
                <Text size="2" weight="bold">{t("基本资料")}</Text>
                <div className="supply-chain-form-grid">
                  <label className="supply-chain-field supply-chain-field-wide">
                    <span>{t("工厂或合作方名称")} *</span>
                    <TextField.Root autoFocus value={form.name} onChange={(event) => setField("name", event.target.value)} placeholder={t("例如：广州星河包装厂")} />
                  </label>
                  <label className="supply-chain-field">
                    <span>{t("联系人")}</span>
                    <TextField.Root value={form.contactName} onChange={(event) => setField("contactName", event.target.value)} />
                  </label>
                  <label className="supply-chain-field">
                    <span>{t("电话")}</span>
                    <TextField.Root value={form.phone} onChange={(event) => setField("phone", event.target.value)} />
                  </label>
                  <label className="supply-chain-field">
                    <span>{t("邮箱")}</span>
                    <TextField.Root type="email" value={form.email} onChange={(event) => setField("email", event.target.value)} />
                  </label>
                  <label className="supply-chain-field">
                    <span>WhatsApp</span>
                    <TextField.Root value={form.whatsapp} onChange={(event) => setField("whatsapp", event.target.value)} />
                  </label>
                  <label className="supply-chain-field">
                    <span>{t("微信")}</span>
                    <TextField.Root value={form.wechat} onChange={(event) => setField("wechat", event.target.value)} />
                  </label>
                  <label className="supply-chain-field">
                    <span>{t("国家 / 地区")}</span>
                    <TextField.Root value={form.countryRegion} onChange={(event) => setField("countryRegion", event.target.value)} />
                  </label>
                  <label className="supply-chain-field supply-chain-field-wide">
                    <span>{t("地址")}</span>
                    <TextField.Root value={form.address} onChange={(event) => setField("address", event.target.value)} />
                  </label>
                  <label className="supply-chain-field supply-chain-field-wide">
                    <span>{t("网站")}</span>
                    <TextField.Root value={form.website} onChange={(event) => setField("website", event.target.value)} placeholder="https://" >
                      <TextField.Slot><Globe /></TextField.Slot>
                    </TextField.Root>
                  </label>
                </div>
              </section>

              <section className="supply-chain-form-section">
                <Text size="2" weight="bold">{t("合作信息")}</Text>
                <label className="supply-chain-field">
                  <span>{t("主营产品 / 服务")}</span>
                  <TextArea rows={3} value={form.businessScope} onChange={(event) => setField("businessScope", event.target.value)} />
                </label>
                <label className="supply-chain-field">
                  <span>{t("备注")}</span>
                  <TextArea rows={3} value={form.notes} onChange={(event) => setField("notes", event.target.value)} />
                </label>
                {selected ? <label className="supply-chain-field supply-chain-status-field">
                  <span>{t("合作状态")}</span>
                  <Select.Root value={form.status} onValueChange={(value) => setField("status", value as SupplyChainForm["status"])}>
                    <Select.Trigger />
                    <Select.Content>
                      <Select.Item value="ACTIVE">{t("合作中")}</Select.Item>
                      <Select.Item value="INACTIVE">{t("已停用")}</Select.Item>
                    </Select.Content>
                  </Select.Root>
                </label> : null}
              </section>
            </div>
            {formError ? <div className="supply-chain-form-error">{formError}</div> : null}
            <div className="supply-chain-dialog-actions">
              <Dialog.Close><Button type="button" variant="soft" color="gray" disabled={saving}>{t("取消")}</Button></Dialog.Close>
              <Button type="submit" loading={saving}>{t("保存")}</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root open={Boolean(pendingDelete)} onOpenChange={(open) => {
        if (!open && !deleting) setPendingDelete(undefined);
      }}>
        <AlertDialog.Content maxWidth="480px">
          <AlertDialog.Title>{t("删除供应链？")}</AlertDialog.Title>
          <AlertDialog.Description>
            {t("将删除“{name}”。已关联商品的供应链不能删除，可改为停用。", {
              name: pendingDelete?.name || "",
            })}
          </AlertDialog.Description>
          <div className="core-dialog-actions">
            <AlertDialog.Cancel><Button variant="soft" color="gray" disabled={deleting}>{t("取消")}</Button></AlertDialog.Cancel>
            <Button color="red" loading={deleting} onClick={() => void remove()}>{t("确认删除")}</Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}
