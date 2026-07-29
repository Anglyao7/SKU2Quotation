import { Button } from "@radix-ui/themes";
import { ArrowsClockwise, Cube } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getCategoryLayout, listCategories, updateCategoryLayout } from "../api";
import { CategoryManager } from "../components/CategoryManager";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { CategoryLayout, ProductCategory } from "../types";

export function CategoriesPage() {
  const { t } = useLocale();
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [layout, setLayout] = useState<CategoryLayout>({
    allProductsPosition: 0,
    rootCategoryCount: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [categoryRows, categoryLayout] = await Promise.all([
        listCategories(),
        getCategoryLayout(),
      ]);
      setCategories(categoryRows);
      setLayout(categoryLayout);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("分类数据加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const saveAllProductsPosition = useCallback(async (position: number) => {
    const saved = await updateCategoryLayout(position);
    setLayout(saved);
  }, []);

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("商品资料")}
        title={t("分类管理")}
        description={t("一级与二级分类顺序会同步控制前台分类导航和“全部商品”的陈列顺序；拖动“全部商品”只调整入口位置。")}
        actions={<>
          <Button asChild variant="soft" color="gray"><Link to="/console/products"><Cube />{t("SKU 商品库")}</Link></Button>
          <Button variant="soft" disabled={loading} onClick={() => void load()}><ArrowsClockwise />{t("刷新")}</Button>
        </>}
      />
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {loading && !categories.length ? <CoreLoading label={t("正在读取商品分类")} /> : null}
      {categories.length || (!loading && !error) ? (
        <CategoryManager
          categories={categories}
          allProductsPosition={layout.allProductsPosition}
          onChanged={load}
          onAllProductsPositionChanged={saveAllProductsPosition}
        />
      ) : null}
    </div>
  );
}
