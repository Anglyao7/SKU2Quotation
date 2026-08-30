import { StorefrontFooterSettings } from "./StorefrontFooterSettings";
import { StorefrontCustomPagesSettings } from "./StorefrontCustomPagesSettings";
import { CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import "./StorefrontManagementPage.css";

export function StorefrontManagementPage() {
  const { t } = useLocale();

  return (
    <div className="core-page storefront-management-page">
      <CorePageHeading
        eyebrow={t("客户前台")}
        title={t("前台管理")}
        description={t("统一管理客户在商品前台看到的商家品牌内容、导航与联系入口。")}
      />
      <StorefrontCustomPagesSettings />
      <StorefrontFooterSettings />
    </div>
  );
}
