import { CubeFocus } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { BRAND_NAME_ZH } from "../brand";

export function Brand({
  compact = false,
  subtitle = "SKU 报价工作台",
}: {
  compact?: boolean;
  subtitle?: string;
}) {
  return (
    <Link to="/" className="brand" aria-label={`${BRAND_NAME_ZH}首页`}>
      <span className="brand-mark"><CubeFocus size={22} weight="duotone" /></span>
      {!compact && (
        <span className="brand-copy">
          <strong>{BRAND_NAME_ZH}</strong>
          <small>{subtitle}</small>
        </span>
      )}
    </Link>
  );
}
