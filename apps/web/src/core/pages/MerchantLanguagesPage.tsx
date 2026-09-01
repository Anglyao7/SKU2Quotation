import { CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { StorefrontLanguageSettings } from "./StorefrontLanguageSettings";

export function MerchantLanguagesPage() {
  const { t } = useLocale();

  return (
    <div className="core-page merchant-languages-page">
      <CorePageHeading
        eyebrow={t("商品资料")}
        title={t("多语言")}
        description={t("管理访客在商品前台可以选择的语言；绿色表示正在展示，未配置语言包时请联系平台管理员。")}
      />
      <StorefrontLanguageSettings />
    </div>
  );
}
