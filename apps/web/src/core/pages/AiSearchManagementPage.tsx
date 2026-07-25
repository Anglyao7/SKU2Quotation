import { AlertDialog, Badge, Button, Card, Heading, Progress, Text } from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowsClockwise,
  Database,
  MagnifyingGlass,
  Sparkle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  getKnowledgeIndexStatus,
  rebuildKnowledgeIndex,
  updateKnowledgeIndex,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { KnowledgeIndexStatus } from "../types";

export function AiSearchManagementPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const canManageIndex = hasPermission("product.edit");
  const [status, setStatus] = useState<KnowledgeIndexStatus>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "incremental" | "full">("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [rebuildOpen, setRebuildOpen] = useState(false);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setStatus(await getKnowledgeIndexStatus());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能索引状态读取失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const updateIndex = async (fullRebuild: boolean) => {
    if (!canManageIndex || busy) return;
    setBusy(fullRebuild ? "full" : "incremental");
    setError("");
    setMessage("");
    try {
      const next = fullRebuild
        ? await rebuildKnowledgeIndex()
        : await updateKnowledgeIndex();
      setStatus(next);
      const processed = next.processedProducts ?? 0;
      setMessage(
        fullRebuild
          ? t("全量重建完成，共重新处理 {count} 个商品。", { count: processed.toLocaleString(locale) })
          : processed
            ? t("增量更新完成，本次处理 {count} 个商品。", { count: processed.toLocaleString(locale) })
            : t("当前没有需要更新的商品。"),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能索引更新失败"));
      await loadStatus();
    } finally {
      setBusy("");
    }
  };

  const indexedPercent = useMemo(() => {
    if (!status?.totalProducts) return 0;
    return Math.round((status.indexedProducts / status.totalProducts) * 100);
  }, [status]);

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("AI 搜索")}
        title={t("AI 搜索管理")}
        description={t("控制当前商家商品知识的向量索引。商品导入和编辑不会自动产生模型费用，由你决定何时更新。")}
        actions={(
          <>
            <Button asChild variant="soft" color="gray">
              <Link to="/console/ai-search"><MagnifyingGlass />{t("打开 AI 搜索")}</Link>
            </Button>
            <Button variant="soft" color="gray" disabled={loading || Boolean(busy)} onClick={() => void loadStatus()}>
              <ArrowClockwise />{t("刷新状态")}
            </Button>
          </>
        )}
      />

      {loading && !status ? <CoreLoading label={t("正在核对商品与智能索引")} /> : null}
      {error && !status ? <CoreError message={error} onRetry={() => void loadStatus()} /> : null}

      {status ? (
        <>
          <Card className="core-ai-index-overview" aria-live="polite">
            <div className="core-ai-index-heading">
              <span className="core-index-icon"><Database /></span>
              <div>
                <Text size="1" color="gray" as="div">{t("当前商家索引")}</Text>
                <Heading size="5">
                  {status.pendingProducts
                    ? t("{count} 个商品等待更新", { count: status.pendingProducts.toLocaleString(locale) })
                    : t("商品索引已是最新")}
                </Heading>
              </div>
              <Badge color={status.pendingProducts ? "amber" : "jade"}>
                {t(status.pendingProducts ? "需要同步" : "可正常搜索")}
              </Badge>
            </div>

            <div className="core-ai-index-progress">
              <span>
                <Text size="2" color="gray">{t("索引覆盖")}</Text>
                <Text size="2" weight="bold">
                  {status.indexedProducts.toLocaleString(locale)} / {status.totalProducts.toLocaleString(locale)}
                </Text>
              </span>
              <Progress value={indexedPercent} />
            </div>

            <div className="core-ai-index-actions">
              {canManageIndex ? (
                <>
                  <Button
                    size="3"
                    disabled={status.pendingProducts === 0 || Boolean(busy)}
                    onClick={() => void updateIndex(false)}
                  >
                    <Sparkle />
                    {t(busy === "incremental" ? "正在更新…" : "更新智能索引")}
                  </Button>
                  <Button
                    size="3"
                    variant="soft"
                    color="gray"
                    disabled={!status.totalProducts || Boolean(busy)}
                    onClick={() => setRebuildOpen(true)}
                  >
                    <ArrowsClockwise />
                    {t(busy === "full" ? "正在重建…" : "全量重建索引")}
                  </Button>
                </>
              ) : (
                <Text size="2" color="gray">{t("当前账号可查看索引状态，但没有商品编辑权限，无法执行更新。")}</Text>
              )}
            </div>

            {busy ? <Text size="1" color="gray">{t("索引任务正在执行，请保持当前页面打开。")}</Text> : null}
            {message ? <Text size="2" color="green">{message}</Text> : null}
            {error ? <Text size="2" color="red">{error}</Text> : null}
          </Card>

          <div className="core-ai-index-details">
            <section>
              <Text size="1" color="gray">{t("建议操作")}</Text>
              <Heading size="4">{t("通常只需增量更新")}</Heading>
              <p>{t("导入新商品，或修改商品名称、描述、分类与标签后，使用“更新智能索引”即可。系统只处理发生变化的商品。")}</p>
            </section>
            <section>
              <Text size="1" color="gray">{t("模型配置")}</Text>
              <dl>
                <div><dt>{t("模型")}</dt><dd>{status.modelName}</dd></div>
                <div><dt>{t("向量维度")}</dt><dd>{status.dimensions.toLocaleString(locale)}</dd></div>
                <div><dt>{t("提供方")}</dt><dd>{status.modelProvider}</dd></div>
                <div><dt>{t("模型版本")}</dt><dd>{status.modelVersion}</dd></div>
              </dl>
            </section>
          </div>
        </>
      ) : null}

      <AlertDialog.Root open={rebuildOpen} onOpenChange={setRebuildOpen}>
        <AlertDialog.Content maxWidth="480px">
          <AlertDialog.Title>{t("全量重建智能索引？")}</AlertDialog.Title>
          <AlertDialog.Description size="2">
            {t("系统会使用当前的 {model}，重新向量化当前商家的全部 {count} 个商品。通常仅在更换模型或索引异常时使用。", {
              model: status?.modelName ?? "Embedding",
              count: status ? status.totalProducts.toLocaleString(locale) : "0",
            })}
          </AlertDialog.Description>
          <div className="core-dialog-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray" disabled={Boolean(busy)}>{t("取消")}</Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button disabled={Boolean(busy)} onClick={() => void updateIndex(true)}>
                <ArrowsClockwise />{t("确认全量重建")}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}
