import type { TranslationSettingsWriteInput } from "./api";
import type { TranslationApiSettings, TranslationProviderKind, TranslationReasoningEffort } from "./types";

export const ALIYUN_ENDPOINT = "mt.cn-hangzhou.aliyuncs.com";
export const ALIYUN_REGION = "cn-hangzhou";
export const ALIYUN_EDITION = "translate_standard";
export const DEEPLX_MODEL = "DeepLX";
export const TENCENT_TOKENHUB_BASE_URL = "https://tokenhub.tencentmaas.com/v1";
export const TENCENT_TOKENHUB_MODEL = "hy-mt2-plus";

export type TranslationSettingsTab =
  | "runtime"
  | TranslationProviderKind
  | "qwen-batch"
  | "baidu-search";

export interface ProviderDraft {
  baseUrl: string;
  modelName: string;
  regionId: string;
  apiKey: string;
  accessKeyId: string;
  maxTokens: string;
  reasoningEffort: TranslationReasoningEffort;
}

export function defaultProviderDraft(provider: TranslationProviderKind): ProviderDraft {
  return {
    baseUrl: provider === "aliyun-alimt" ? ALIYUN_ENDPOINT : provider === "tencent-tokenhub" ? TENCENT_TOKENHUB_BASE_URL : "",
    modelName: provider === "aliyun-alimt" ? ALIYUN_EDITION : provider === "deeplx" ? DEEPLX_MODEL : provider === "tencent-tokenhub" ? TENCENT_TOKENHUB_MODEL : "",
    regionId: ALIYUN_REGION,
    apiKey: "",
    accessKeyId: "",
    maxTokens: provider === "tencent-tokenhub" ? "4096" : "16384",
    reasoningEffort: provider === "openai-compatible" ? "low" : "none",
  };
}

export function isProviderTab(tab: TranslationSettingsTab): tab is TranslationProviderKind {
  return tab === "openai-compatible" || tab === "deeplx" || tab === "aliyun-alimt" || tab === "tencent-tokenhub";
}

/** Persist only the selected tab's draft; the API still expects the full settings object. */
export function translationSettingsSaveInput(
  tab: TranslationSettingsTab,
  draft: TranslationSettingsWriteInput,
  settings: TranslationApiSettings,
): TranslationSettingsWriteInput {
  const defaults = defaultProviderDraft(settings.provider);
  const persisted: TranslationSettingsWriteInput = {
    provider: settings.provider,
    baseUrl: settings.baseUrl ?? defaults.baseUrl,
    modelName: settings.modelName ?? defaults.modelName,
    regionId: settings.regionId ?? defaults.regionId,
    timeoutSeconds: settings.timeoutSeconds,
    maxTokens: settings.maxTokens,
    requestsPerMinute: settings.requestsPerMinute,
    maxRetryCount: settings.maxRetryCount,
    catalogBatchSize: settings.catalogBatchSize,
    catalogBatchCharacters: settings.catalogBatchCharacters,
    catalogConcurrency: settings.catalogConcurrency,
    catalogExecutionMode: settings.catalogExecutionMode,
    batchBaseUrl: settings.batchBaseUrl,
    batchModelName: settings.batchModelName,
    reasoningEffort: settings.reasoningEffort,
    searchTranslationEnabled: settings.searchTranslationEnabled,
    searchTranslationEndpoint: settings.searchTranslationEndpoint,
    searchTranslationTimeoutSeconds: settings.searchTranslationTimeoutSeconds,
    searchTranslationCacheTtlSeconds: settings.searchTranslationCacheTtlSeconds,
  };

  if (isProviderTab(tab)) return {
    ...persisted,
    provider: tab,
    baseUrl: draft.baseUrl,
    modelName: draft.modelName,
    regionId: draft.regionId,
    apiKey: draft.apiKey,
    accessKeyId: draft.accessKeyId,
    maxTokens: draft.maxTokens,
    reasoningEffort: draft.reasoningEffort,
    catalogExecutionMode: "REALTIME",
  };
  if (tab === "qwen-batch") return {
    ...persisted,
    batchBaseUrl: draft.batchBaseUrl,
    batchModelName: draft.batchModelName,
    batchApiKey: draft.batchApiKey,
  };
  if (tab === "baidu-search") return {
    ...persisted,
    searchTranslationEnabled: draft.searchTranslationEnabled,
    searchTranslationEndpoint: draft.searchTranslationEndpoint,
    searchTranslationTimeoutSeconds: draft.searchTranslationTimeoutSeconds,
    searchTranslationCacheTtlSeconds: draft.searchTranslationCacheTtlSeconds,
    searchTranslationApiKey: draft.searchTranslationApiKey,
    searchTranslationAppId: draft.searchTranslationAppId,
  };
  return {
    ...persisted,
    timeoutSeconds: draft.timeoutSeconds,
    requestsPerMinute: draft.requestsPerMinute,
    maxRetryCount: draft.maxRetryCount,
    catalogBatchSize: draft.catalogBatchSize,
    catalogBatchCharacters: draft.catalogBatchCharacters,
    catalogConcurrency: draft.catalogConcurrency,
    catalogExecutionMode: draft.catalogExecutionMode,
  };
}
