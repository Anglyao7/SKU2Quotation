import { Button, Card, Skeleton, Text } from "@radix-ui/themes";
import { ArrowClockwise, Package, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useLocale } from "../core/LocaleContext";

type FixedCopyTranslator = (
  source: string,
  values?: Record<string, string | number>,
) => string;

export function ErrorState({
  message,
  onRetry,
  translate,
}: {
  message: string;
  onRetry?: () => void;
  translate?: FixedCopyTranslator;
}) {
  const { t: consoleTranslate } = useLocale();
  const t = translate ?? consoleTranslate;
  return (
    <Card className="state-card" variant="surface">
      <WarningCircle size={30} weight="duotone" />
      <div>
        <Text weight="medium" as="div">{t("内容加载失败")}</Text>
        <Text color="gray" size="2" as="div">{message}</Text>
      </div>
      {onRetry && (
        <Button variant="soft" onClick={onRetry}><ArrowClockwise size={17} />{t("重新加载")}</Button>
      )}
    </Card>
  );
}

export function EmptyState({
  title = "这里还没有内容",
  description = "添加第一条数据后，它会显示在这里。",
  action,
  translate,
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
  translate?: FixedCopyTranslator;
}) {
  const { t: consoleTranslate } = useLocale();
  const t = translate ?? consoleTranslate;
  return (
    <div className="empty-state">
      <span className="empty-icon"><Package size={34} weight="duotone" /></span>
      <Text weight="medium" size="3">{t(title)}</Text>
      <Text color="gray" size="2">{t(description)}</Text>
      {action}
    </div>
  );
}

export function ProductGridSkeleton({
  count = 8,
  translate,
}: {
  count?: number;
  translate?: FixedCopyTranslator;
}) {
  const { t: consoleTranslate } = useLocale();
  const t = translate ?? consoleTranslate;
  return (
    <div className="sku-grid" aria-label={t("商品加载中")} aria-busy="true">
      {Array.from({ length: count }, (_, index) => (
        <Card key={index} className="sku-card skeleton-card">
          <Skeleton className="skeleton-image" />
          <div className="skeleton-body">
            <Skeleton height="20px" width="84%" />
            <Skeleton height="20px" width="62%" />
            <div className="skeleton-row">
              <Skeleton height="20px" width="54%" />
              <Skeleton height="32px" width="32px" />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  const { t } = useLocale();
  return (
    <div className="table-skeleton" aria-label={t("数据加载中")} aria-busy="true">
      {Array.from({ length: rows }, (_, index) => (
        <div className="table-skeleton-row" key={index}>
          <Skeleton height="18px" width={`${52 + (index % 3) * 10}%`} />
          <Skeleton height="18px" width="18%" />
        </div>
      ))}
    </div>
  );
}
