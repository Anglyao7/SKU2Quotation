import { Badge, Button, Switch, Text, TextField } from "@radix-ui/themes";
import { ArrowClockwise, ArrowDown, ArrowSquareOut, ArrowUp, ArrowsLeftRight, CaretLeft, CaretRight, Columns, CurrencyDollar, Desktop, DeviceMobile, Fire, MagnifyingGlass, Package, PushPin, Rows, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  batchUpdateProductsPinned, getMerchantSettings, getStorefrontSorting, listStorefrontSortingProducts,
  updateMerchantSettings, updateStorefrontCategoryPriority,
  type StorefrontSortingSettings, type StorefrontSortingProductPage,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { canManageOwnStorefront } from "../storefrontPermissions";
import { CoreError, CoreLoading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { useToast } from "../ToastContext";
import type { MerchantSettings } from "../types";

const EMPTY_PRODUCTS: StorefrontSortingProductPage = { items: [], page: 1, page_size: 20, total: 0, pages: 0 };

export function StorefrontCatalogDisplaySettings() {
  const { hasPermission, profile } = useCoreAuth();
  const { t } = useLocale();
  const { notify } = useToast();
  const membershipId = profile?.context.membershipId;
  const canManage = canManageOwnStorefront(profile?.context.accountScope, hasPermission);
  const canEditProducts = profile?.context.accountScope === "CUSTOMER_SUBACCOUNT" ? canManage : hasPermission("product.edit");
  const [merchant, setMerchant] = useState<MerchantSettings>();
  const [sorting, setSorting] = useState<StorefrontSortingSettings>();
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsError, setSettingsError] = useState("");
  const [busy, setBusy] = useState("");
  const [products, setProducts] = useState(EMPTY_PRODUCTS);
  const [productsLoading, setProductsLoading] = useState(true);
  const [productsError, setProductsError] = useState("");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [page, setPage] = useState(1);
  const [categoryQuery, setCategoryQuery] = useState("");
  const requestId = useRef(0);
  const settingsRequestId = useRef(0);

  const loadSettings = useCallback(async () => {
    const id = ++settingsRequestId.current;
    setSettingsLoading(true);
    setSettingsError("");
    try {
      const [settings, order] = await Promise.all([getMerchantSettings(), getStorefrontSorting()]);
      if (id !== settingsRequestId.current) return;
      setMerchant(settings);
      setSorting(order);
    } catch (caught) {
      if (id === settingsRequestId.current) setSettingsError(caught instanceof Error ? caught.message : t("商品展示设置加载失败"));
    } finally {
      if (id === settingsRequestId.current) setSettingsLoading(false);
    }
  }, [membershipId, t]);

  const loadProducts = useCallback(async () => {
    const id = ++requestId.current;
    setProductsLoading(true);
    setProductsError("");
    try {
      const result = await listStorefrontSortingProducts({ q: debouncedQuery.trim(), page, pageSize: 20 });
      if (id === requestId.current) setProducts(result);
    } catch (caught) {
      if (id === requestId.current) setProductsError(caught instanceof Error ? caught.message : t("商品展示清单加载失败"));
    } finally {
      if (id === requestId.current) setProductsLoading(false);
    }
  }, [debouncedQuery, page, membershipId, t]);

  useEffect(() => { void loadSettings(); return () => { settingsRequestId.current += 1; }; }, [loadSettings]);
  useEffect(() => { void loadProducts(); return () => { requestId.current += 1; }; }, [loadProducts]);
  useEffect(() => {
    const timer = window.setTimeout(() => { setDebouncedQuery(query); setPage(1); }, 240);
    return () => window.clearTimeout(timer);
  }, [query]);

  const refreshFirstPage = async () => {
    if (page !== 1) setPage(1);
    else await loadProducts();
  };

  const toggleHotProducts = async (enabled: boolean) => {
    if (!merchant || busy || !canManage) return;
    setBusy("hot");
    try {
      setMerchant(await updateMerchantSettings({ hotProductsEnabled: enabled }));
      await refreshFirstPage();
      notify(t("已保存并更新前台"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("热门商品设置保存失败，请重试。"), { kind: "error" });
    } finally { setBusy(""); }
  };

  const saveCategoryLayoutMode = async (mode: MerchantSettings["storefrontCategoryLayoutMode"]) => {
    if (!merchant || busy || !canManage || mode === merchant.storefrontCategoryLayoutMode) return;
    setBusy("category-layout");
    try {
      setMerchant(await updateMerchantSettings({ storefrontCategoryLayoutMode: mode }));
      notify(t("已保存并更新前台"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("前台展示方式保存失败，请重试。"), { kind: "error" });
    } finally { setBusy(""); }
  };

  const togglePricesVisible = async (visible: boolean) => {
    if (!merchant || busy || !canManage) return;
    setBusy("prices");
    try {
      setMerchant(await updateMerchantSettings({ storefrontPricesVisible: visible }));
      notify(t("已保存并更新前台"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("价格显示设置保存失败，请重试。"), { kind: "error" });
    } finally { setBusy(""); }
  };

  const togglePinnedProduct = async (productId: string, pinned: boolean) => {
    if (!canEditProducts || busy) return;
    setBusy(productId);
    try {
      const result = await batchUpdateProductsPinned([productId], pinned);
      if (result.failedCount) throw new Error(t("商品优先顺序保存失败"));
      await loadProducts();
      notify(t("已保存并更新前台"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("商品优先顺序保存失败"), { kind: "error" });
    } finally { setBusy(""); }
  };

  const saveCategories = async (ids: string[]) => {
    if (busy || !canManage) return;
    setBusy("categories");
    try {
      setSorting(await updateStorefrontCategoryPriority(ids));
      await refreshFirstPage();
      notify(t("已保存并更新前台"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("商品优先顺序保存失败"), { kind: "error" });
    } finally { setBusy(""); }
  };

  const priorityIds = sorting?.priority_category_ids ?? [];
  const selectedCategories = priorityIds.flatMap((id) => sorting?.categories.find((item) => item.id === id) ?? []);
  const availableCategories = (sorting?.categories ?? []).filter((item) => !priorityIds.includes(item.id) && item.path.toLocaleLowerCase().includes(categoryQuery.trim().toLocaleLowerCase()));
  const moveCategory = (index: number, direction: number) => {
    const ids = [...priorityIds];
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    void saveCategories(ids);
  };

  return (
    <section className="storefront-catalog-settings" aria-labelledby="storefront-catalog-settings-title">
      <div className="storefront-catalog-intro">
        <div>
          <Text size="1" color="gray">{t("商品首页")}</Text>
          <h2 id="storefront-catalog-settings-title">{t("商品排序")}</h2>
          <p>{t("手动优先 → 自动爆款 → 优先分类 → 其余商品")}</p>
        </div>
        <div className="storefront-catalog-intro-actions">
          {merchant ? <Button asChild variant="soft"><Link to={merchant.storefrontPath} target="_blank" rel="noreferrer"><ArrowSquareOut />{t("预览商品前台")}</Link></Button> : null}
          <Button variant="soft" color="gray" disabled={Boolean(busy) || settingsLoading || productsLoading} onClick={() => void Promise.all([loadSettings(), loadProducts()])}><ArrowClockwise />{t("刷新")}</Button>
        </div>
      </div>
      {settingsLoading ? <CoreLoading label={t("正在加载商品展示设置")} /> : null}
      {settingsError ? <CoreError message={settingsError} onRetry={() => void loadSettings()} /> : null}
      {!settingsLoading && !settingsError && merchant && sorting ? <>
        <article className="storefront-display-strategy">
          <span className="storefront-display-strategy-icon"><Fire weight="duotone" /></span>
          <div>
            <div className="storefront-display-strategy-heading"><strong>{t("自动爆款排序")}</strong><Badge color={merchant.hotProductsEnabled ? "jade" : "gray"}>{t(merchant.hotProductsEnabled ? "已开启" : "未开启")}</Badge></div>
            <p>{t("近 90 天热度前 {count} 个商品自动设为优先；可在下方取消或追加。", { count: sorting.auto_hot_limit })}</p>
            <small><PushPin weight="fill" />{t("取消的自动优先会被记住；关闭此功能保留手动优先。")}</small>
          </div>
          <Switch checked={merchant.hotProductsEnabled} disabled={Boolean(busy) || !canManage} onCheckedChange={(enabled) => void toggleHotProducts(enabled)} aria-label={t("爆款优先展示")} />
        </article>
        <section className="storefront-category-layout-settings" aria-labelledby="storefront-category-layout-title">
          <div>
            <Text size="1" color="gray">{t("分类展示")}</Text>
            <h3 id="storefront-category-layout-title">{t("前台分类布局")}</h3>
            <p>{t("自动模式会让手机使用竖向分类、电脑使用横向分类；也可以固定一种布局，或交给访客自行切换。")}</p>
          </div>
          <div className="storefront-category-layout-options" role="group" aria-label={t("前台分类布局") }>
            <Button
              type="button"
              variant={merchant.storefrontCategoryLayoutMode === "AUTO" ? "soft" : "ghost"}
              color={merchant.storefrontCategoryLayoutMode === "AUTO" ? "jade" : "gray"}
              disabled={Boolean(busy) || !canManage}
              aria-pressed={merchant.storefrontCategoryLayoutMode === "AUTO"}
              onClick={() => void saveCategoryLayoutMode("AUTO")}
            >
              <DeviceMobile />{t("按设备自动")}
            </Button>
            <Button
              type="button"
              variant={merchant.storefrontCategoryLayoutMode === "VISITOR" ? "soft" : "ghost"}
              color={merchant.storefrontCategoryLayoutMode === "VISITOR" ? "jade" : "gray"}
              disabled={Boolean(busy) || !canManage}
              aria-pressed={merchant.storefrontCategoryLayoutMode === "VISITOR"}
              onClick={() => void saveCategoryLayoutMode("VISITOR")}
            >
              <ArrowsLeftRight />{t("访客自行切换")}
            </Button>
            <Button
              type="button"
              variant={merchant.storefrontCategoryLayoutMode === "HORIZONTAL" ? "soft" : "ghost"}
              color={merchant.storefrontCategoryLayoutMode === "HORIZONTAL" ? "jade" : "gray"}
              disabled={Boolean(busy) || !canManage}
              aria-pressed={merchant.storefrontCategoryLayoutMode === "HORIZONTAL"}
              onClick={() => void saveCategoryLayoutMode("HORIZONTAL")}
            >
              <Rows />{t("始终横向")}
            </Button>
            <Button
              type="button"
              variant={merchant.storefrontCategoryLayoutMode === "VERTICAL" ? "soft" : "ghost"}
              color={merchant.storefrontCategoryLayoutMode === "VERTICAL" ? "jade" : "gray"}
              disabled={Boolean(busy) || !canManage}
              aria-pressed={merchant.storefrontCategoryLayoutMode === "VERTICAL"}
              onClick={() => void saveCategoryLayoutMode("VERTICAL")}
            >
              <Columns />{t("始终竖向")}
            </Button>
          </div>
          <small className="storefront-category-layout-note"><Desktop />{t("当前设置仅影响客户前台的分类导航，不影响后台操作界面。")}</small>
        </section>
        <section className="storefront-display-strategy storefront-price-visibility-settings" aria-labelledby="storefront-price-visibility-title">
          <span className="storefront-display-strategy-icon"><CurrencyDollar weight="duotone" /></span>
          <div>
            <div className="storefront-display-strategy-heading"><strong id="storefront-price-visibility-title">{t("前台价格显示")}</strong><Badge color={merchant.storefrontPricesVisible ? "jade" : "gray"}>{t(merchant.storefrontPricesVisible ? "显示价格" : "暂不显示价格")}</Badge></div>
            <p>{t("关闭后，客户前台不会显示商品价格，但仍可以选择商品并提交报价请求。")}</p>
          </div>
          <Switch checked={merchant.storefrontPricesVisible} disabled={Boolean(busy) || !canManage} onCheckedChange={(visible) => void togglePricesVisible(visible)} aria-label={t("客户前台显示商品价格")} />
        </section>
        <section className="storefront-category-priority" aria-labelledby="category-priority-title">
          <header><h3 id="category-priority-title">{t("优先分类")}</h3><p>{t("只调整全部商品中的顺序，包含子分类和额外关联分类，不改变分类导航。")}</p></header>
          <div className="storefront-category-priority-controls">
            <TextField.Root value={categoryQuery} placeholder={t("搜索分类")} aria-label={t("搜索分类")} onChange={(event) => setCategoryQuery(event.target.value)}><TextField.Slot><MagnifyingGlass /></TextField.Slot></TextField.Root>
            <select aria-label={t("添加优先分类")} value="" disabled={Boolean(busy) || !canManage || priorityIds.length >= 100} onChange={(event) => { if (event.target.value) void saveCategories([...priorityIds, event.target.value]); }}>
              <option value="">{t("添加优先分类")}</option>
              {availableCategories.map((item) => <option key={item.id} value={item.id}>{item.path}</option>)}
            </select>
          </div>
          {selectedCategories.length ? <ol className="storefront-category-priority-list">{selectedCategories.map((item, index) => <li key={item.id}>
            <span className="storefront-category-priority-position">{index + 1}</span><strong title={item.path}>{item.path}</strong>
            <div>
              <Button variant="ghost" color="gray" disabled={Boolean(busy) || !canManage || index === 0} aria-label={t("上移") + " " + item.path} onClick={() => moveCategory(index, -1)}><ArrowUp /></Button>
              <Button variant="ghost" color="gray" disabled={Boolean(busy) || !canManage || index === selectedCategories.length - 1} aria-label={t("下移") + " " + item.path} onClick={() => moveCategory(index, 1)}><ArrowDown /></Button>
              <Button variant="ghost" color="gray" disabled={Boolean(busy) || !canManage} aria-label={t("移除") + " " + item.path} onClick={() => void saveCategories(priorityIds.filter((id) => id !== item.id))}><X /></Button>
            </div>
          </li>)}</ol> : <Text size="2" color="gray">{t("尚未设置优先分类")}</Text>}
        </section>
      </> : null}
      <div className="storefront-priority-editor">
        <header>
          <div><Text size="1" color="gray">{t("人工编辑")}</Text><h3>{t("商品优先顺序")}</h3><p>{t("与前台全部商品使用同一排序；自动爆款已勾选，可直接调整。")}</p></div>
          <TextField.Root value={query} placeholder={t("搜索商品名称或产品编码")} aria-label={t("搜索可优先展示的商品")} onChange={(event) => setQuery(event.target.value)}><TextField.Slot><MagnifyingGlass /></TextField.Slot></TextField.Root>
        </header>
        {productsError ? <CoreError message={productsError} onRetry={() => void loadProducts()} /> : null}
        {productsLoading && !products.items.length ? <CoreLoading label={t("正在加载商品清单")} /> : null}
        {!productsLoading && !productsError && !products.items.length ? <div className="storefront-priority-empty"><Package weight="duotone" /><strong>{t(query.trim() ? "没有符合条件的商品" : "暂无可展示商品")}</strong><span>{t(query.trim() ? "请更换商品名称或产品编码后重试。" : "商品上架后会出现在这里。")}</span></div> : null}
        {products.items.length ? <div className={"storefront-priority-list" + (productsLoading ? " is-loading" : "")} aria-busy={productsLoading}>
          {products.items.map((product) => <article className="storefront-priority-row" key={product.id}>
            <span className="storefront-priority-image">{product.image_url ? <img src={product.image_url} alt="" loading="lazy" /> : <Package weight="duotone" />}</span>
            <div className="storefront-priority-copy"><strong title={product.name}>{product.name}</strong><small>{product.product_code || t("未设置产品编码")} · {product.category || t("未分类")}</small></div>
            <span className="storefront-priority-source">{product.priority_source ? <Badge color={product.priority_source === "HOT" ? "orange" : "jade"}>{product.priority_source === "HOT" ? <Fire weight="fill" /> : <PushPin weight="fill" />}{t(product.priority_source === "HOT" ? "自动爆款" : "手动优先")}</Badge> : product.is_hot_candidate ? <Badge color="gray">{t("已取消自动优先")}</Badge> : null}</span>
            <label className="storefront-priority-toggle"><span>{t(product.is_prioritized ? "已优先" : "设为优先")}</span><Switch checked={product.is_prioritized} disabled={!canEditProducts || Boolean(busy) || productsLoading} onCheckedChange={(pinned) => void togglePinnedProduct(product.id, pinned)} aria-label={t("设置商品 {name} 的前台优先状态", { name: product.name })} /></label>
          </article>)}
        </div> : null}
        {products.pages > 1 ? <footer className="storefront-priority-pagination"><span>{t("第 {page} / {pages} 页 · 共 {total} 个商品", { page: products.page, pages: products.pages, total: products.total })}</span><div>
          <Button variant="soft" color="gray" disabled={page <= 1 || productsLoading || Boolean(busy)} onClick={() => setPage((value) => Math.max(1, value - 1))}><CaretLeft />{t("上一页")}</Button>
          <Button variant="soft" color="gray" disabled={page >= products.pages || productsLoading || Boolean(busy)} onClick={() => setPage((value) => value + 1)}>{t("下一页")}<CaretRight /></Button>
        </div></footer> : null}
      </div>
    </section>
  );
}
