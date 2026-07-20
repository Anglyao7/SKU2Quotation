import { CubeFocus } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

export function Brand({
  compact = false,
  subtitle = "SKU 报价工作台",
}: {
  compact?: boolean;
  subtitle?: string;
}) {
  return (
    <Link to="/" className="brand" aria-label="澄湾选品首页">
      <span className="brand-mark"><CubeFocus size={22} weight="duotone" /></span>
      {!compact && (
        <span className="brand-copy">
          <strong>澄湾选品</strong>
          <small>{subtitle}</small>
        </span>
      )}
    </Link>
  );
}
