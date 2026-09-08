import { Tabs } from "@radix-ui/themes";
import { FileCode, LinkSimple, Storefront } from "@phosphor-icons/react";
import { useSearchParams } from "react-router-dom";
import { StorefrontFooterSettings } from "./StorefrontFooterSettings";
import { StorefrontCustomPagesSettings } from "./StorefrontCustomPagesSettings";
import { StorefrontCatalogDisplaySettings } from "./StorefrontCatalogDisplaySettings";
import { CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import "./StorefrontManagementPage.css";

export function StorefrontManagementPage() {
  const { t } = useLocale();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const activeTab = requestedTab === "catalog" || requestedTab === "footer" ? requestedTab : "pages";

  const changeTab = (nextTab: string) => {
    const next = new URLSearchParams(searchParams);
    if (nextTab === "pages") next.delete("tab");
    else next.set("tab", nextTab);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="core-page storefront-management-page">
      <CorePageHeading
        eyebrow={t("客户前台")}
        title={t("页面与展示")}
        description={t("统一管理客户在商品前台看到的商家品牌内容、导航与联系入口。")}
      />
      <Tabs.Root className="storefront-management-tabs" value={activeTab} onValueChange={changeTab}>
        <Tabs.List aria-label={t("前台管理功能")}>
          <Tabs.Trigger value="pages"><FileCode />{t("页面与导航")}</Tabs.Trigger>
          <Tabs.Trigger value="catalog"><Storefront />{t("商品排序")}</Tabs.Trigger>
          <Tabs.Trigger value="footer"><LinkSimple />{t("页脚与联系")}</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="pages" className="storefront-management-tab-panel">
          <StorefrontCustomPagesSettings />
        </Tabs.Content>
        <Tabs.Content value="catalog" className="storefront-management-tab-panel">
          <StorefrontCatalogDisplaySettings />
        </Tabs.Content>
        <Tabs.Content value="footer" className="storefront-management-tab-panel">
          <StorefrontFooterSettings />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
