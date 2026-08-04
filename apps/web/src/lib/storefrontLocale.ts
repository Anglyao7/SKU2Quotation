import type { StorefrontLocale } from "../types";
import { localizedStorefrontMessages } from "./storefrontMessages";

export interface StorefrontLanguageOption {
  code: StorefrontLocale;
  label: string;
  shortLabel: string;
  flag: string;
  direction: "ltr" | "rtl";
}

export const STOREFRONT_LANGUAGE_OPTIONS: readonly StorefrontLanguageOption[] = [
  { code: "zh-CN", label: "简体中文", shortLabel: "中", flag: "🇨🇳", direction: "ltr" },
  { code: "en-US", label: "English", shortLabel: "EN", flag: "🇺🇸", direction: "ltr" },
  { code: "es", label: "Español", shortLabel: "ES", flag: "🇪🇸", direction: "ltr" },
  { code: "tr", label: "Türkçe", shortLabel: "TR", flag: "🇹🇷", direction: "ltr" },
  { code: "ar", label: "العربية", shortLabel: "ع", flag: "🇸🇦", direction: "rtl" },
  { code: "ja", label: "日本語", shortLabel: "日", flag: "🇯🇵", direction: "ltr" },
  { code: "ko", label: "한국어", shortLabel: "한", flag: "🇰🇷", direction: "ltr" },
  { code: "pt", label: "Português", shortLabel: "PT", flag: "🇵🇹", direction: "ltr" },
] as const;

const languageByCode = new Map(
  STOREFRONT_LANGUAGE_OPTIONS.map((language) => [language.code, language]),
);

const localeAliases: Record<string, StorefrontLocale> = {
  zh: "zh-CN",
  "zh-cn": "zh-CN",
  en: "en-US",
  "en-us": "en-US",
  es: "es",
  "es-es": "es",
  tr: "tr",
  "tr-tr": "tr",
  ar: "ar",
  "ar-sa": "ar",
  ja: "ja",
  "ja-jp": "ja",
  ko: "ko",
  "ko-kr": "ko",
  pt: "pt",
  "pt-pt": "pt",
  "pt-br": "pt",
};

export function normalizeStorefrontLocale(value?: string | null): StorefrontLocale {
  return localeAliases[String(value || "").replaceAll("_", "-").toLocaleLowerCase()]
    ?? "zh-CN";
}

export function storefrontLocaleQuery(locale: StorefrontLocale) {
  return locale === "zh-CN" ? "" : `?lang=${encodeURIComponent(locale)}`;
}

export function storefrontDirection(locale: StorefrontLocale): "ltr" | "rtl" {
  return languageByCode.get(locale)?.direction ?? "ltr";
}

export function storefrontLanguage(locale: StorefrontLocale) {
  return languageByCode.get(locale) ?? STOREFRONT_LANGUAGE_OPTIONS[0];
}

const english: Record<string, string> = {
  "SKU 商品目录": "SKU Catalog",
  "商品目录": "Product Catalog",
  "由智贸云提供": "Powered by Zhimao Cloud",
  "查找商品": "Find products",
  "输入 SKU、商品特征或使用场景，AI 会结合类目与标签查找": "Search by SKU, product features, or use case. AI combines categories and tags.",
  "切换到左侧分类": "Move categories to the left",
  "切换到顶部分类": "Move categories to the top",
  "左侧分类": "Left categories",
  "顶部分类": "Top categories",
  "清除筛选": "Clear filters",
  "搜索 SKU、名称、规格或使用场景": "Search SKU, name, specification, or use case",
  "清除搜索": "Clear search",
  "搜索中……": "Searching……",
  "按两级分类筛选": "Filter by two-level categories",
  "一级分类": "Primary",
  "二级分类": "Secondary",
  "全部商品": "All products",
  "全部二级": "All subcategories",
  "该分类暂无二级分类": "No subcategories in this category",
  "暂无二级分类": "No subcategories",
  "商品分类": "Categories",
  "筛选结果": "Filtered results",
  "爆款优先": "Bestsellers first",
  "根据近 90 天浏览与下单热度优先展示，手动置顶商品仍排在最前。":
    "Prioritized by views and orders from the last 90 days. Manually pinned products remain first.",
  "全部 SKU": "All SKUs",
  "点击商品查看可选规格与 SKU。": "Open a product to view its available options and SKUs.",
  "在商品卡片上直接加入清单或调整数量。": "Add products to your quote list or adjust quantities directly.",
  "正在查找": "Searching",
  "{count} 条结果": "{count} results",
  "商品加载失败。": "Products could not be loaded.",
  "没有匹配的 SKU": "No matching SKUs",
  "没有匹配的商品": "No matching products",
  "换一个关键词、使用场景或分类，再试一次。": "Try another keyword, use case, or category.",
  "商品分页": "Product pagination",
  "上一页": "Previous",
  "下一页": "Next",
  "第 {page} 页": "Page {page}",
  "第 {page} / {pages} 页": "Page {page} of {pages}",
  "商品与报价由 {store} 提供，报价草稿须经商家确认。": "Products and pricing are provided by {store}. Quote drafts require merchant confirmation.",
  "隐私政策": "Privacy Policy",
  "选择语言": "Choose language",
  "中文": "Chinese",
  "英文": "English",
  "切换深色模式": "Switch to dark mode",
  "切换浅色模式": "Switch to light mode",
  "商家公告": "Merchant announcement",
  "关闭公告": "Close announcement",
  "关闭滚动字幕": "Dismiss ticker",
  "我知道了": "Got it",
  "以后不显示": "Don't show again",
  "查看商品": "View product",
  "相关商品": "Related products",
  "完整刷新或开始新会话后，公告会重新出现": "The announcement returns after a full reload or a new session.",
  "查看 {name} 商品详情": "View details for {name}",
  "{count} 个可选 SKU": "{count} available SKUs",
  "1 个 SKU": "1 SKU",
  "查看规格": "View options",
  "暂无图片": "No image",
  "已选 {quantity}": "{quantity} selected",
  "参考单价": "Reference price",
  "{name} 已选数量": "Selected quantity for {name}",
  "减少 {name} 数量": "Decrease quantity for {name}",
  "增加 {name} 数量": "Increase quantity for {name}",
  "已选": "Selected",
  "将 {name} 加入报价清单": "Add {name} to quote list",
  "加入清单": "Add",
  "返回商品目录": "Back to catalog",
  "{store} 商品目录首页": "{store} catalog home",
  "{store} 标志": "{store} logo",
  "商品描述": "Description",
  "商品": "Product",
  "{count} 个 SKU": "{count} SKUs",
  "商家暂未补充详细描述。": "No detailed description has been provided yet.",
  "查看完整描述": "View full description",
  "收起描述": "Collapse description",
  "商品标签": "Product tags",
  "参考价格区间": "Reference price range",
  "商品规格": "Product options",
  "款式": "Style",
  "选择规格": "Choose options",
  "选择规格组合后即可加入报价清单。": "Choose an option combination, then add it to your quote list.",
  "已选 SKU": "Selected SKU",
  "标准款": "Standard",
  "已加入": "Added",
  "已选 {quantity} 件，再加一件": "{quantity} selected — add one more",
  "加入报价清单": "Add to quote list",
  "最终价格与交期以商家确认后的正式报价为准。": "Final price and lead time are subject to the merchant’s confirmed quotation.",
  "报价清单": "Quote list",
  "查看报价清单，已选 {skus} 个 SKU，共 {items} 件": "View quote list: {skus} SKUs, {items} items",
  "已选 {skus} 个 SKU · 共 {items} 件": "{skus} SKUs · {items} items",
  "查看清单": "View list",
  "选品报价": "Product quotation",
  "生成报价单": "Create quotation",
  "确认商品数量并填写客户信息。": "Confirm quantities and enter customer details.",
  "添加商品后，即可生成报价草稿。": "Add products to create a quote draft.",
  "添加商品后，即可生成报价单。": "Add products to create a quotation.",
  "关闭报价清单": "Close quote list",
  "报价单已生成": "Quotation created",
  "可以下载 Excel 或 PDF 文件。": "You can now download the Excel or PDF file.",
  "报价确认提醒": "Quotation confirmation",
  "本次报价需由商家确认后生效，请以商家后续确认的最终版本为准。": "This quotation takes effect after merchant confirmation. Please use the final version confirmed by the merchant.",
  "知道了": "Got it",
  "下载 PDF": "Download PDF",
  "下载 Excel": "Download Excel",
  "继续选品": "Continue shopping",
  "报价清单还是空的": "Your quote list is empty",
  "从商品列表中选择需要报价的 SKU，再回来确认数量并生成报价草稿。": "Select the SKUs you need, then return to confirm quantities and create a quote draft.",
  "从商品列表中选择需要报价的 SKU，再回来确认数量并生成报价单。": "Select the SKUs you need, then return to confirm quantities and create a quotation.",
  "继续浏览商品": "Continue browsing",
  "已选商品": "Selected products",
  "{skus} 个 SKU，共 {items} 件": "{skus} SKUs, {items} items",
  "清空": "Clear",
  "减少数量": "Decrease quantity",
  "增加数量": "Increase quantity",
  "商品参考合计": "Estimated product total",
  "最终报价以商家确认为准": "Subject to merchant confirmation",
  "按已选数量计算": "Calculated from selected quantities",
  "客户信息": "Customer details",
  "用于生成本次报价草稿": "Used to create this quote draft",
  "用于生成本次报价单": "Used to create this quotation",
  "客户姓名 *": "Contact name *",
  "请输入客户姓名": "Enter contact name",
  "公司名称": "Company",
  "请输入公司名称": "Enter company name",
  "客户邮箱": "Email",
  "报价备注": "Quote notes",
  "交期、包装或其他说明": "Lead time, packaging, or other requirements",
  "我已阅读并理解": "I have read and understood ",
  "我填写的信息将提供给 {store}，仅用于生成和跟进本次报价": "My information will be shared with {store} only to create and follow up on this quotation",
  "联系邮箱：{email}": "Contact email: {email}",
  "{skus} 个 SKU · {items} 件": "{skus} SKUs · {items} items",
  "生成报价草稿": "Create quote draft",
  "提交并生成报价单": "Submit and create quotation",
  "请先阅读并确认隐私政策。": "Please read and accept the Privacy Policy.",
  "报价单生成失败，请稍后重试。": "The quotation could not be created. Please try again.",
  "文件下载失败，请稍后重试。": "The file could not be downloaded. Please try again.",
  "在线客服": "Customer support",
  "AI 智能客服": "AI Customer Support",
  "AI 自动回复筹备中 · 当前由商家人工回复": "AI replies are coming soon · A merchant agent will reply for now",
  "关闭客服窗口": "Close support",
  "打开 AI 智能客服": "Open AI customer support",
  "消息加载失败，请稍后重试。": "Messages could not be loaded. Please try again.",
  "消息发送失败，请稍后重试。": "Your message could not be sent. Please try again.",
  "本次会话已结束。": "This conversation has ended.",
  "发起新的咨询": "Start a new conversation",
  "请输入您想咨询的商品或问题…": "Ask about a product or enter your question…",
  "客服消息": "Support message",
  "发送消息": "Send message",
  "消息会发送给商家客服，回复可能需要一些时间。": "Your message is sent to the merchant. A reply may take some time.",
  "我": "Me",
  "商家快捷入口": "Merchant shortcut",
};

export function storefrontText(
  locale: StorefrontLocale,
  source: string,
  values: Record<string, string | number> = {},
) {
  let result = locale === "zh-CN"
    ? source
    : locale === "en-US"
      ? english[source] ?? source
      : localizedStorefrontMessages[source]?.[locale] ?? english[source] ?? source;
  for (const [key, value] of Object.entries(values)) {
    result = result.replaceAll(`{${key}}`, String(value));
  }
  return result;
}
