import { Button, Card, Heading, Spinner, Text } from "@radix-ui/themes";
import { ArrowClockwise, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useLocale } from "./LocaleContext";

export function CorePageHeading({ eyebrow, title, description, actions }: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="core-heading">
      <div>
        <Text size="2" color="gray">{eyebrow}</Text>
        <Heading size="7">{title}</Heading>
        <Text size="2" color="gray">{description}</Text>
      </div>
      {actions ? <div className="core-heading-actions">{actions}</div> : null}
    </div>
  );
}

export function CoreLoading({ label = "正在加载" }: { label?: string }) {
  const { t } = useLocale();
  return <Card className="core-state"><Spinner size="3" /><Text size="2" color="gray">{t(label)}</Text></Card>;
}

export function CoreError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { t } = useLocale();
  return (
    <Card className="core-state core-error">
      <WarningCircle size={28} />
      <div><Text weight="bold" as="div">{t("暂时无法完成请求")}</Text><Text size="2" color="gray">{t(message)}</Text></div>
      {onRetry ? <Button variant="soft" color="gray" onClick={onRetry}><ArrowClockwise />{t("重试")}</Button> : null}
    </Card>
  );
}

export function CoreEmpty({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <Card className="core-state"><Text weight="bold" as="div">{title}</Text><Text size="2" color="gray">{description}</Text>{action}</Card>;
}

export function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function coreDate(value?: string) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(document.documentElement.lang || "zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
