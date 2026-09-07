import { Badge, Button, Switch, Text, TextField } from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowSquareOut,
  CaretLeft,
  CaretRight,
  Fire,
  MagnifyingGlass,
  Package,
  PushPin,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  batchUpdateProductsPinned,
  getMerchantSettings,
  listProductCatalog,
  updateMerchantSettings,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { useToast } from "../ToastContext";
import type { MerchantSettings, ProductListPage } from "../types";

const EMPTY_PRODUCTS: ProductListPage = {
  items: [],
  page: 1,
  pageSize: 20,
  total: 0,
  pages: 0,
};

export function StorefrontCatalogDisplaySettings() {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const { notify } = useToast();
  const canEditProducts = hasPermission("product.edit");
  const [merchant, setMerchant] = useState<MerchantSettings>();
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsError, setSettingsError] = useState("");
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [products, setProducts] = useState<ProductListPage>(EMPTY_PRODUCTS);
  const [productsLoading, setProductsLoading] = useState(true);
  const [productsError, setProductsError] = useState("");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [page, setPage] = useState(1);
  const [savingProductId, setSavingProductId] = useState("");

  const loadSettings = useCallback(async () => {
    setSettingsLoading(true);
    setSettingsError("");
    try {
      setMerchant(await getMerchantSettings());
    } catch (caught) {
      setSettingsError(caught instanceof Error ? caught.message : t("商品展示设置加载失败"));
    } finally {
      setSettingsLoading(false);
    }
  }, [t]);

  const loadProducts = useCallback(async () => {
    setProductsLoading(true);
    setProductsError("");
    try {
      setProducts(await listProductCatalog({
        q: debouncedQuery.trim() || undefined,
        statuses: ["ACTIVE"],
        page,
        pageSize: 20,
      }));
    } catch (caught) {
      setProductsError(caught instanceof Error ? caught.message : t("商品展示清单加载失败"));
    } finally {
      setProductsLoading(false);
    }
  }, [debouncedQuery, page, t]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 240);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    void loadProducts();
  }, [loadProducts]);

  const toggleHotProducts = async (enabled: boolean) => {
    if (!merchant || settingsSaving) return;
    const previous = merchant.hotProductsEnabled;
    setMerchant({ ...merchant, hotProductsEnabled: enabled });
    setSettingsSaving(true);
    try {
      setMerchant(await updateMerchantSettings({ hotProductsEnabled: enabled }));
      notify(t("已保存并更新前台"), { kind: "success" });
    } catch (caught) {
      setMerchant((current) => current ? { ...current, hotProductsEnabled: previous } : current);
      notify(
        caught instanceof Error ? caught.message : t("热门商品设置保存失败，请重试。"),
        { kind: "error" },
      );
    } finally {
      setSettingsSaving(false);
    }
  };

  const togglePinnedProduct = async (productId: string, pinned: boolean) => {
    if (!canEditProducts || savingProductId) return;
    setSavingProductId(productId);
    setProducts((current) => ({
      ...current,
      items: current.items.map((item) => (
        item.id === productId ? { ...item, isPinned: pinned } : item
      )),
    }));
    try {
      const result = await batchUpdateProductsPinned([productId], pinned);
      if (result.failedCount) throw new Error(t("商品优先顺序保存失败"));
      notify(t(pinned ? "商品已加入手动优先" : "商品已取消手动优先"), { kind: "success" });
    } catch (caught) {
      setProducts((current) => ({
        ...current,
        items: current.items.map((item) => (
          item.id === productId ? { ...item, isPinned: !pinned } : item
        )),
      }));
      notify(
        caught instanceof Error ? caught.message : t("商品优先顺序保存失败"),
        { kind: "error" },
      );
    } finally {
      setSavingProductId("");
    }
  };

  return (
    <section className="storefront-catalog-settings" aria-labelledby="storefront-catalog-settings-title">
      <div className="storefront-catalog-intro">
        <div>
          <Text size="1" color="gray">{t("商品首页")}</Text>
          <h2 id="storefront-catalog-settings-title">{t("商品展示与排序")}</h2>
          <p>{t("控制默认商品列表的排序方式，并手动指定需要优先展示的商品。")}</p>
        </div>
        <div className="storefront-catalog-intro-actions">
          {merchant ? (
            <Button asChild variant="soft">
              <Link to={merchant.storefrontPath} target="_blank" rel="noreferrer">
                <ArrowSquareOut />{t("预览商品前台")}
              </Link>
            </Button>
          ) : null}
          <Button
            variant="soft"
            color="gray"
            disabled={settingsLoading || productsLoading}
            onClick={() => void Promise.all([loadSettings(), loadProducts()])}
          >
            <ArrowClockwise />{t("刷新")}
          </Button>
        </div>
      </div>

      {settingsLoading ? <CoreLoading label={t("正在加载商品展示设置")} /> : null}
      {settingsError ? <CoreError message={settingsError} onRetry={() => void loadSettings()} /> : null}

      {!settingsLoading && merchant ? (
        <article className="storefront-display-strategy">
          <span className="storefront-display-strategy-icon"><Fire weight="duotone" /></span>
          <div>
            <div className="storefront-display-strategy-heading">
              <strong>{t("自动爆款排序")}</strong>
              <Badge color={merchant.hotProductsEnabled ? "jade" : "gray"}>
                {t(merchant.hotProductsEnabled ? "已开启" : "未开启")}
              </Badge>
            </div>
            <p>{t("开启后，访客进入“全部商品”时会优先看到近 90 天浏览与下单热度更高的商品；搜索和分类顺序不受影响。")}</p>
            <small><PushPin weight="fill" />{t("手动指定的商品始终排在自动爆款之前。")}</small>
          </div>
          <Switch
            checked={merchant.hotProductsEnabled}
            disabled={settingsSaving}
            onCheckedChange={(enabled) => void toggleHotProducts(enabled)}
            aria-label={t("爆款优先展示")}
          />
        </article>
      ) : null}

      <div className="storefront-priority-editor">
        <header>
          <div>
            <Text size="1" color="gray">{t("人工编辑")}</Text>
            <h3>{t("手动优先商品")}</h3>
            <p>{t("搜索并开启商品右侧的开关，该商品会覆盖自动热度并优先出现在前台。")}</p>
          </div>
          <TextField.Root
            value={query}
            placeholder={t("搜索商品名称或产品编码")}
            aria-label={t("搜索可优先展示的商品")}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
          >
            <TextField.Slot><MagnifyingGlass /></TextField.Slot>
          </TextField.Root>
        </header>

        {productsError ? <CoreError message={productsError} onRetry={() => void loadProducts()} /> : null}
        {productsLoading && !products.items.length ? <CoreLoading label={t("正在加载商品清单")} /> : null}
        {!productsLoading && !productsError && !products.items.length ? (
          <div className="storefront-priority-empty">
            <Package weight="duotone" />
            <strong>{t(query.trim() ? "没有符合条件的商品" : "暂无可展示商品")}</strong>
            <span>{t(query.trim() ? "请更换商品名称或产品编码后重试。" : "商品上架后会出现在这里。")}</span>
          </div>
        ) : null}

        {products.items.length ? (
          <div className={`storefront-priority-list${productsLoading ? " is-loading" : ""}`}>
            {products.items.map((product) => (
              <article className="storefront-priority-row" key={product.id}>
                <span className="storefront-priority-image">
                  {product.primaryImageUrl ? <img src={product.primaryImageUrl} alt="" /> : <Package weight="duotone" />}
                </span>
                <div className="storefront-priority-copy">
                  <strong title={product.name}>{product.name}</strong>
                  <small>{product.productCode || t("未设置产品编码")} · {product.category || t("未分类")}</small>
                </div>
                {product.isPinned ? <Badge color="jade"><PushPin weight="fill" />{t("手动优先")}</Badge> : null}
                <label className="storefront-priority-toggle">
                  <span>{t(product.isPinned ? "已优先" : "设为优先")}</span>
                  <Switch
                    checked={product.isPinned}
                    disabled={!canEditProducts || Boolean(savingProductId)}
                    onCheckedChange={(pinned) => void togglePinnedProduct(product.id, pinned)}
                    aria-label={t("设置商品 {name} 的前台优先状态", { name: product.name })}
                  />
                </label>
              </article>
            ))}
          </div>
        ) : null}

        {products.pages > 1 ? (
          <footer className="storefront-priority-pagination">
            <span>{t("第 {page} / {pages} 页 · 共 {total} 个商品", {
              page: products.page,
              pages: products.pages,
              total: products.total,
            })}</span>
            <div>
              <Button variant="soft" color="gray" disabled={page <= 1 || productsLoading} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                <CaretLeft />{t("上一页")}
              </Button>
              <Button variant="soft" color="gray" disabled={page >= products.pages || productsLoading} onClick={() => setPage((value) => value + 1)}>
                {t("下一页")}<CaretRight />
              </Button>
            </div>
          </footer>
        ) : null}
        {!canEditProducts ? <Text size="1" color="gray">{t("仅商家所有者或管理员可以修改。")}</Text> : null}
      </div>
    </section>
  );
}
