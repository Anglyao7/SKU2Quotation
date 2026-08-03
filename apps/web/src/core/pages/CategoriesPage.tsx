import { Button, Card, Dialog, Text } from "@radix-ui/themes";
import {
  ArrowsClockwise,
  CheckCircle,
  DownloadSimple,
  FileArrowUp,
  FileXls,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  CATEGORY_TEMPLATE_DOWNLOAD_URL,
  CoreApiError,
  getCategoryLayout,
  importCategories,
  listCategories,
  updateCategoryLayout,
  type CategoryImportResult,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CategoryManager } from "../components/CategoryManager";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { CategoryLayout, ProductCategory } from "../types";

interface CategoryImportIssue {
  row_number?: number | null;
  column?: string;
  message?: string;
}

function categoryImportIssues(reason: unknown): CategoryImportIssue[] {
  if (!(reason instanceof CoreApiError) || !reason.details || typeof reason.details !== "object") return [];
  const detail = (reason.details as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return [];
  const issues = (detail as { issues?: unknown }).issues;
  return Array.isArray(issues)
    ? issues.filter((issue): issue is CategoryImportIssue => Boolean(issue) && typeof issue === "object")
    : [];
}

export function CategoriesPage() {
  const { t } = useLocale();
  const { hasPermission } = useCoreAuth();
  const canImport = hasPermission("product.edit");
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [layout, setLayout] = useState<CategoryLayout>({
    allProductsPosition: 0,
    rootCategoryCount: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File>();
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");
  const [importIssues, setImportIssues] = useState<CategoryImportIssue[]>([]);
  const [importResult, setImportResult] = useState<CategoryImportResult>();
  const importInputRef = useRef<HTMLInputElement | null>(null);

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

  const openImport = () => {
    setImportFile(undefined);
    setImportError("");
    setImportIssues([]);
    setImportOpen(true);
  };

  const chooseImportFile = (file?: File) => {
    setImportError("");
    setImportIssues([]);
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setImportFile(undefined);
      setImportError(t("分类导入只支持 .xlsx 文件。"));
      return;
    }
    setImportFile(file);
  };

  const submitImport = async () => {
    if (!importFile || importing) return;
    setImporting(true);
    setImportError("");
    setImportIssues([]);
    try {
      const result = await importCategories(importFile);
      setImportResult(result);
      setImportOpen(false);
      setImportFile(undefined);
      await load();
    } catch (reason) {
      setImportError(reason instanceof Error ? reason.message : t("分类导入失败，请检查文件后重试。"));
      setImportIssues(categoryImportIssues(reason));
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("商品资料")}
        title={t("分类管理")}
        description={t("拖动即可排序，点击分类直接修改；前台会自动同步。")}
        actions={(
          <>
            {canImport ? (
              <Button asChild variant="soft" color="gray">
                <a href={CATEGORY_TEMPLATE_DOWNLOAD_URL} download="分类模板.xlsx">
                  <DownloadSimple />{t("下载分类模板")}
                </a>
              </Button>
            ) : null}
            {canImport ? <Button onClick={openImport}><FileArrowUp />{t("导入分类")}</Button> : null}
            <Button variant="soft" color="gray" disabled={loading} onClick={() => void load()}>
              <ArrowsClockwise />{t("刷新")}
            </Button>
          </>
        )}
      />
      {importResult ? (
        <Card className="core-category-import-result" role="status">
          <CheckCircle weight="fill" />
          <div>
            <Text weight="bold" as="div">{t("分类导入完成")}</Text>
            <Text size="2" color="gray">
              {t("新增 {primary} 个一级分类、{secondary} 个二级分类；已有 {existing} 个分类自动跳过。", {
                primary: importResult.primaryCreated,
                secondary: importResult.secondaryCreated,
                existing: importResult.primaryExisting + importResult.secondaryExisting,
              })}
            </Text>
            {importResult.duplicateRowsIgnored ? (
              <Text size="1" color="gray">
                {t("另有 {count} 行重复记录已忽略。", { count: importResult.duplicateRowsIgnored })}
              </Text>
            ) : null}
          </div>
          <Button size="1" variant="ghost" color="gray" onClick={() => setImportResult(undefined)} aria-label={t("关闭")}><X /></Button>
        </Card>
      ) : null}
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

      <Dialog.Root
        open={importOpen}
        onOpenChange={(open) => {
          if (importing) return;
          setImportOpen(open);
        }}
      >
        <Dialog.Content className="core-category-import-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="gray">{t("分类批量导入")}</Text>
              <Dialog.Title>{t("导入分类")}</Dialog.Title>
              <Dialog.Description>
                {t("A 列填写一级分类，B 列填写二级分类；B 列留空时只创建一级分类。工作表名称不限。")}
              </Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" disabled={importing} onClick={() => setImportOpen(false)} aria-label={t("关闭")}><X /></Button>
          </div>

          <Card className="core-category-import-rules">
            <FileXls size={28} />
            <div>
              <Text weight="bold" as="div">{t("按两列模板增量合并")}</Text>
              <Text size="2" color="gray">
                {t("同一一级分类可以重复多行并包含多个二级分类；已有分类不会重复创建，未写入模板的分类也不会被删除。")}
              </Text>
            </div>
          </Card>

          <input
            ref={importInputRef}
            hidden
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => {
              chooseImportFile(event.target.files?.[0]);
              event.currentTarget.value = "";
            }}
          />
          <button
            className="core-category-import-file"
            type="button"
            disabled={importing}
            onClick={() => importInputRef.current?.click()}
          >
            <span><FileArrowUp /></span>
            <span>
              <strong>{importFile?.name ?? t("选择分类文件")}</strong>
              <small>
                {importFile
                  ? `${(importFile.size / 1024).toFixed(importFile.size >= 1024 ? 0 : 1)} KB`
                  : t("支持包含“一级分类、二级分类”两列的 .xlsx 文件，工作表名称不限")}
              </small>
            </span>
            <span>{t(importFile ? "重新选择" : "选择文件")}</span>
          </button>

          {importError ? (
            <div className="core-category-import-error" role="alert">
              <WarningCircle />
              <div>
                <strong>{importError}</strong>
                {importIssues.length ? (
                  <ul>
                    {importIssues.slice(0, 8).map((issue, index) => (
                      <li key={`${issue.row_number ?? "file"}-${issue.column ?? "column"}-${index}`}>
                        {issue.row_number ? t("第 {row} 行", { row: issue.row_number }) : t("文件")}
                        {issue.column ? ` · ${issue.column}` : ""}
                        {issue.message ? `：${issue.message}` : ""}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </div>
          ) : null}

          <div className="core-dialog-actions">
            <Button asChild variant="soft" color="gray">
              <a href={CATEGORY_TEMPLATE_DOWNLOAD_URL} download="分类模板.xlsx"><DownloadSimple />{t("下载模板")}</a>
            </Button>
            <Button variant="soft" color="gray" disabled={importing} onClick={() => setImportOpen(false)}>{t("取消")}</Button>
            <Button loading={importing} disabled={!importFile || importing} onClick={() => void submitImport()}>
              <FileArrowUp />{t(importing ? "正在导入…" : "开始导入")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}
