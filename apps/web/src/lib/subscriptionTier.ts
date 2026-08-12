import type { TenantSubscriptionTier } from "../types";

export const SUBSCRIPTION_TIER_PRESENTATION: Record<
  TenantSubscriptionTier,
  {
    label: string;
    chineseName: string;
    description: string;
    color: "gray" | "blue" | "violet" | "amber";
  }
> = {
  TRIAL: {
    label: "试用",
    chineseName: "试用",
    description: "默认 1 个月 · 500 SKU",
    color: "gray",
  },
  STANDARD: {
    label: "Standard",
    chineseName: "基础版",
    description: "基础版 · 5000 SKU",
    color: "blue",
  },
  SILVER: {
    label: "Silver",
    chineseName: "进阶版",
    description: "进阶版 · 5000 SKU",
    color: "violet",
  },
  ELITE: {
    label: "Elite",
    chineseName: "企业版",
    description: "企业版 · SKU 不限",
    color: "amber",
  },
};

export function subscriptionTierLabel(tier: TenantSubscriptionTier): string {
  return SUBSCRIPTION_TIER_PRESENTATION[tier].label;
}
