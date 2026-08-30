import {
  Badge,
  Button,
  Card,
  Dialog,
  Heading,
  Spinner,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  CaretLeft,
  CaretRight,
  MagnifyingGlass,
  PencilSimple,
  Translate,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { STOREFRONT_LANGUAGE_OPTIONS } from "../../lib/storefrontLocale";
import type { StorefrontLocale } from "../../types";
import {
  getCatalogTranslationProduct,
  listCatalogTranslationProducts,
  updateCatalogTranslationProduct,
} from "../api";
import type {
  CatalogLocalizedProductContent,
  CatalogLocalizedSkuContent,
  CatalogTranslationEntryStatus,
  CatalogTranslationProductDetail,
  CatalogTranslationProductListPage,
} from "../types";
import { useLocale } from "../LocaleContext";
import { ToastNotice } from "../ToastContext";

const emptyPage: CatalogTranslationProductListPage = {
  items: [],
  page: 1,
  pageSize: 30,
  total: 0,
  pages: 0,
};

const statusCopy: Record<CatalogTranslationEntryStatus, string> = {
  TRANSLATED: "自动译文",
  MISSING: "缺少译文",
  STALE: "原文已变更",
  MANUAL: "人工微调",
};

const statusColor: Record<CatalogTranslationEntryStatus, "green" | "red" | "amber" | "blue"> = {
  TRANSLATED: "green",
  MISSING: "red",
  STALE: "amber",
  MANUAL: "blue",
};

function MappingEditor({
  title,
  source,
  value,
  onChange,
}: {
  title: string;
  source: Record<string, string>;
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  const entries = Object.entries(source);
  if (!entries.length) return null;
  return (
    <section className="catalog-translation-mapping">
      <Text size="2" weight="bold">{title}</Text>
      <div>
        {entries.map(([key, sourceValue]) => (
          <label key={key}>
            <span>{sourceValue || key}</span>
            <TextField.Root
              value={value[key] ?? sourceValue}
              onChange={(event) => onChange({ ...value, [key]: event.target.value })}
              aria-label={`${title} ${sourceValue || key}`}
            />
          </label>
        ))}
      </div>
    </section>
  );
}

export function CatalogTranslationEditor({
  tenantId,
  locale,
  packageVersion,
}: {
  tenantId: string;
  locale: StorefrontLocale;
  packageVersion?: number;
}) {
  const { t } = useLocale();
  const languageLabel = STOREFRONT_LANGUAGE_OPTIONS.find(
    (language) => language.code === locale,
  )?.label ?? locale;
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<CatalogTranslationProductListPage>(emptyPage);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [detail, setDetail] = useState<CatalogTranslationProductDetail>();
  const [productDraft, setProductDraft] = useState<CatalogLocalizedProductContent>();
  const [skuDrafts, setSkuDrafts] = useState<CatalogLocalizedSkuContent[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [loadingProductId, setLoadingProductId] = useState<string>();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setResult(await listCatalogTranslationProducts({
        targetLocale: locale,
        tenantId,
        q: debouncedQuery || undefined,
        page,
        pageSize: 30,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("商品译文读取失败。"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setDetail(undefined);
    setPage(1);
  }, [locale, tenantId]);

  useEffect(() => {
    void load();
    // A published package version invalidates the visible wording snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, tenantId, debouncedQuery, page, packageVersion]);

  const editProduct = async (productId: string) => {
    setDetailLoading(true);
    setLoadingProductId(productId);
    setError("");
    setSuccess("");
    try {
      const next = await getCatalogTranslationProduct(productId, locale, tenantId);
      setDetail(next);
      setProductDraft({
        ...next.translation,
        tags: [...next.translation.tags],
        specifications: { ...next.translation.specifications },
        optionLabels: { ...next.translation.optionLabels },
        optionValues: { ...next.translation.optionValues },
      });
      setSkuDrafts(next.skus.map((sku) => ({
        ...sku.translation,
        tags: [...sku.translation.tags],
      })));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("商品译文读取失败。"));
    } finally {
      setDetailLoading(false);
      setLoadingProductId(undefined);
    }
  };

  const updateSku = (skuId: string, patch: Partial<CatalogLocalizedSkuContent>) => {
    setSkuDrafts((current) => current.map((sku) => (
      sku.skuId === skuId ? { ...sku, ...patch } : sku
    )));
  };

  const save = async () => {
    if (!detail || !productDraft || saving) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const updated = await updateCatalogTranslationProduct(
        detail.id,
        locale,
        detail.sourceHash,
        Object.fromEntries(detail.skus.map((sku) => [sku.id, sku.sourceHash])),
        productDraft,
        skuDrafts,
        tenantId,
      );
      setDetail(updated);
      setProductDraft({ ...updated.translation });
      setSkuDrafts(updated.skus.map((sku) => ({ ...sku.translation })));
      setSuccess(t("人工译文已保存并发布为语言包 v{version}。", {
        version: updated.packageVersion ?? "—",
      }));
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("人工译文保存失败。"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="catalog-translation-editor">
      <div className="catalog-translation-editor-heading">
        <span><Translate weight="duotone" /></span>
        <div>
          <Text size="1" color="gray">{t("管理员工具")}</Text>
          <Heading size="5">{t("商品译文微调")}</Heading>
          <Text size="2" color="gray">
            {t("按语言查看当前前台商品；人工修改保存后立即发布新语言包，并优先于自动译文。")}
          </Text>
        </div>
        <TextField.Root
          className="catalog-translation-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("搜索商品名称或编码")}
        >
          <TextField.Slot><MagnifyingGlass /></TextField.Slot>
        </TextField.Root>
      </div>

      {error ? <ToastNotice kind="error" message={error} /> : null}
      {success ? <ToastNotice kind="success" message={success} /> : null}

      {loading ? (
        <div className="language-history-loading">
          <Spinner size="3" />
          <Text color="gray">{t("正在读取商品译文列表")}</Text>
        </div>
      ) : result.items.length ? (
        <div className="catalog-translation-table-wrap">
          <table className="catalog-translation-table">
            <thead>
              <tr>
                <th>{t("商品原文")}</th>
                <th>{t("当前译文")}</th>
                <th>{t("分类")}</th>
                <th>{t("状态")}</th>
                <th aria-label={t("操作")} />
              </tr>
            </thead>
            <tbody>
              {result.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <strong>{item.sourceName}</strong>
                    <small>{item.productCode ?? t("未设置商品编码")} · {item.skuCount} SKUs</small>
                  </td>
                  <td>{item.translatedName || <span className="catalog-translation-missing">{t("尚无译文")}</span>}</td>
                  <td>{item.translatedCategory || item.sourceCategory || "—"}</td>
                  <td><Badge color={statusColor[item.status]}>{t(statusCopy[item.status])}</Badge></td>
                  <td>
                    <Button
                      size="1"
                      variant="soft"
                      loading={detailLoading && loadingProductId === item.id}
                      disabled={detailLoading}
                      onClick={() => void editProduct(item.id)}
                    >
                      <PencilSimple />{t("微调")}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="catalog-translation-empty">
          <Text weight="bold">{t("没有找到商品")}</Text>
          <Text size="2" color="gray">{t("当前列表只显示已发布到客户前台的商品。")}</Text>
        </div>
      )}

      <div className="catalog-translation-pagination">
        <Text size="1" color="gray">
          {t("共 {count} 个商品", { count: result.total })}
          {result.packageVersion ? ` · v${result.packageVersion}` : ` · ${t("语言包未配置")}`}
        </Text>
        <span>
          <Button size="1" variant="soft" disabled={page <= 1 || loading} onClick={() => setPage((value) => value - 1)}><CaretLeft /></Button>
          <Text size="1">{result.page} / {Math.max(1, result.pages)}</Text>
          <Button size="1" variant="soft" disabled={page >= result.pages || loading} onClick={() => setPage((value) => value + 1)}><CaretRight /></Button>
        </span>
      </div>

      <Dialog.Root open={Boolean(detail && productDraft)} onOpenChange={(open) => {
        if (!open && !saving) {
          setDetail(undefined);
          setProductDraft(undefined);
          setSkuDrafts([]);
        }
      }}>
        <Dialog.Content className="catalog-translation-dialog" maxWidth="1080px">
          {detail && productDraft ? (
            <>
              <Dialog.Title>{t("微调 {language} 译文", { language: languageLabel })}</Dialog.Title>
              <Dialog.Description>
                {detail.source.name} · {detail.productCode ?? t("未设置商品编码")}
              </Dialog.Description>

              <div className="catalog-translation-compare-grid">
                <section>
                  <Text size="1" color="gray">{t("中文原文")}</Text>
                  <strong>{detail.source.name}</strong>
                  <p>{detail.source.description || t("无商品描述")}</p>
                  <small>{detail.source.categoryLabel || t("未分类")}</small>
                </section>
                <section className="is-editable">
                  <label>
                    <Text size="1" color="gray">{t("商品名称")}</Text>
                    <TextField.Root value={productDraft.name} onChange={(event) => setProductDraft({ ...productDraft, name: event.target.value })} />
                  </label>
                  <label>
                    <Text size="1" color="gray">{t("分类译文")}</Text>
                    <TextField.Root value={productDraft.categoryLabel ?? ""} onChange={(event) => setProductDraft({ ...productDraft, categoryLabel: event.target.value })} />
                  </label>
                  <label className="is-wide">
                    <Text size="1" color="gray">{t("商品描述")}</Text>
                    <TextArea rows={6} resize="vertical" value={productDraft.description ?? ""} onChange={(event) => setProductDraft({ ...productDraft, description: event.target.value })} />
                  </label>
                  <label>
                    <Text size="1" color="gray">{t("标签（逗号分隔）")}</Text>
                    <TextField.Root value={productDraft.tags.join(", ")} onChange={(event) => setProductDraft({ ...productDraft, tags: event.target.value.split(/[,，]/).map((value) => value.trim()).filter(Boolean) })} />
                  </label>
                  <label>
                    <Text size="1" color="gray">{t("展示标签")}</Text>
                    <TextField.Root value={productDraft.displayTag ?? ""} onChange={(event) => setProductDraft({ ...productDraft, displayTag: event.target.value })} />
                  </label>
                </section>
              </div>

              <div className="catalog-translation-mapping-grid">
                <MappingEditor title={t("规格名称")} source={detail.source.specifications} value={productDraft.specifications} onChange={(value) => setProductDraft({ ...productDraft, specifications: value })} />
                <MappingEditor title={t("选项名称")} source={detail.source.optionLabels} value={productDraft.optionLabels} onChange={(value) => setProductDraft({ ...productDraft, optionLabels: value })} />
                <MappingEditor title={t("选项值")} source={detail.source.optionValues} value={productDraft.optionValues} onChange={(value) => setProductDraft({ ...productDraft, optionValues: value })} />
              </div>

              <section className="catalog-translation-skus">
                <div>
                  <Heading size="3">{t("SKU 译文")}</Heading>
                  <Text size="1" color="gray">{t("商品下的 SKU 名称与规格也会一并写入语言包。")}</Text>
                </div>
                {detail.skus.map((sku) => {
                  const draft = skuDrafts.find((item) => item.skuId === sku.id);
                  if (!draft) return null;
                  return (
                    <details key={sku.id} className="catalog-translation-sku-row">
                      <summary>
                        <span><strong>{sku.skuCode}</strong><small>{sku.source.name}</small></span>
                        <Badge color={statusColor[sku.status]}>{t(statusCopy[sku.status])}</Badge>
                      </summary>
                      <div>
                        <label><Text size="1" color="gray">{t("SKU 名称")}</Text><TextField.Root value={draft.name} onChange={(event) => updateSku(sku.id, { name: event.target.value })} /></label>
                        <label><Text size="1" color="gray">{t("规格译文")}</Text><TextField.Root value={draft.specification ?? ""} onChange={(event) => updateSku(sku.id, { specification: event.target.value })} /></label>
                        <label><Text size="1" color="gray">{t("分类译文")}</Text><TextField.Root value={draft.categoryLabel ?? ""} onChange={(event) => updateSku(sku.id, { categoryLabel: event.target.value })} /></label>
                        <label><Text size="1" color="gray">{t("标签（逗号分隔）")}</Text><TextField.Root value={draft.tags.join(", ")} onChange={(event) => updateSku(sku.id, { tags: event.target.value.split(/[,，]/).map((value) => value.trim()).filter(Boolean) })} /></label>
                        <label className="is-wide"><Text size="1" color="gray">{t("SKU 描述")}</Text><TextArea rows={4} resize="vertical" value={draft.description ?? ""} onChange={(event) => updateSku(sku.id, { description: event.target.value })} /></label>
                      </div>
                    </details>
                  );
                })}
              </section>

              <div className="catalog-translation-dialog-actions">
                <Dialog.Close><Button variant="soft" color="gray" disabled={saving}>{t("取消")}</Button></Dialog.Close>
                <Button loading={saving} disabled={!productDraft.name.trim() || skuDrafts.some((sku) => !sku.name.trim())} onClick={() => void save()}>{t("保存并发布语言包")}</Button>
              </div>
            </>
          ) : null}
        </Dialog.Content>
      </Dialog.Root>
    </Card>
  );
}
