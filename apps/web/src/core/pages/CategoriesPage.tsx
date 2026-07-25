import { Button } from "@radix-ui/themes";
import { ArrowsClockwise, Cube } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listCategories } from "../api";
import { CategoryManager } from "../components/CategoryManager";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { ProductCategory } from "../types";

export function CategoriesPage() {
  const { t } = useLocale();
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setCategories(await listCategories());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("分类数据加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("商品资料")}
        title={t("分类管理")}
        description={t("维护商品前台与 SKU 商品库共用的两级分类及一级分类颜色；Excel 中的“A/B”会自动归入一级 A 下的二级 B。")}
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
          onChanged={load}
        />
      ) : null}
    </div>
  );
}
