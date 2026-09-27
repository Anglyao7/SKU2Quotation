import assert from "node:assert/strict";
import { test } from "node:test";
import {
  defaultProviderDraft,
  translationSettingsSaveInput,
} from "../src/core/translationSettingsTabs.ts";

const settings = {
  source: "database",
  provider: "deeplx",
  enabled: true,
  modelName: "DeepLX",
  timeoutSeconds: 100,
  maxTokens: 16384,
  requestsPerMinute: 8,
  maxRetryCount: 3,
  catalogBatchSize: 25,
  catalogBatchCharacters: 5000,
  catalogConcurrency: 3,
  catalogExecutionMode: "REALTIME",
  reasoningEffort: "none",
  apiKeyConfigured: true,
  accessKeyIdConfigured: false,
  batchBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  batchModelName: "qwen3.7-flash-2026-07-15",
  batchApiKeyConfigured: true,
  searchTranslationSource: "database",
  searchTranslationEnabled: true,
  searchTranslationEndpoint: "https://fanyi-api.baidu.com/ait/api/aiTextTranslate",
  searchTranslationTimeoutSeconds: 8,
  searchTranslationCacheTtlSeconds: 86400,
  searchTranslationApiKeyConfigured: true,
  searchTranslationAppIdConfigured: true,
};

const draft = {
  provider: "openai-compatible",
  baseUrl: "https://new-provider.example/v1",
  modelName: "new-model",
  apiKey: "unsubmitted-provider-key",
  accessKeyId: "unsubmitted-access-key",
  regionId: "other-region",
  timeoutSeconds: 240,
  maxTokens: 4096,
  requestsPerMinute: 50,
  maxRetryCount: 5,
  catalogBatchSize: 80,
  catalogBatchCharacters: 20000,
  catalogConcurrency: 8,
  catalogExecutionMode: "QWEN_BATCH",
  batchBaseUrl: "https://new-batch.example/v1",
  batchModelName: "new-batch-model",
  batchApiKey: "new-batch-key",
  reasoningEffort: "low",
  searchTranslationEnabled: false,
  searchTranslationEndpoint: "https://new-search.example/translate",
  searchTranslationTimeoutSeconds: 12,
  searchTranslationCacheTtlSeconds: 3600,
  searchTranslationApiKey: "new-search-key",
  searchTranslationAppId: "new-search-app-id",
};

test("runtime saves execution limits without switching providers or search settings", () => {
  const result = translationSettingsSaveInput("runtime", draft, settings);
  assert.equal(result.provider, "deeplx");
  assert.equal(result.catalogExecutionMode, "QWEN_BATCH");
  assert.equal(result.requestsPerMinute, 50);
  assert.equal(result.batchBaseUrl, settings.batchBaseUrl);
  assert.equal(result.searchTranslationEnabled, true);
  assert.equal(result.apiKey, undefined);
  assert.equal(result.batchApiKey, undefined);
});

test("Qwen saves only its Batch profile", () => {
  const result = translationSettingsSaveInput("qwen-batch", draft, settings);
  assert.equal(result.provider, "deeplx");
  assert.equal(result.catalogExecutionMode, "REALTIME");
  assert.equal(result.requestsPerMinute, 8);
  assert.equal(result.batchModelName, "new-batch-model");
  assert.equal(result.batchApiKey, "new-batch-key");
  assert.equal(result.searchTranslationEnabled, true);
  assert.equal(result.apiKey, undefined);
});

test("Baidu search saves without changing the catalog translation provider", () => {
  const result = translationSettingsSaveInput("baidu-search", draft, settings);
  assert.equal(result.provider, "deeplx");
  assert.equal(result.catalogExecutionMode, "REALTIME");
  assert.equal(result.searchTranslationEnabled, false);
  assert.equal(result.searchTranslationTimeoutSeconds, 12);
  assert.equal(result.searchTranslationApiKey, "new-search-key");
  assert.equal(result.batchApiKey, undefined);
  assert.equal(result.apiKey, undefined);
});

test("realtime provider saves its own credentials without overwriting Batch or Baidu", () => {
  const result = translationSettingsSaveInput("openai-compatible", draft, settings);
  assert.equal(result.provider, "openai-compatible");
  assert.equal(result.baseUrl, "https://new-provider.example/v1");
  assert.equal(result.apiKey, "unsubmitted-provider-key");
  assert.equal(result.requestsPerMinute, 8);
  assert.equal(result.catalogExecutionMode, "REALTIME");
  assert.equal(result.batchBaseUrl, settings.batchBaseUrl);
  assert.equal(result.searchTranslationEndpoint, settings.searchTranslationEndpoint);
  assert.equal(result.searchTranslationApiKey, undefined);
});

test("selecting a realtime provider switches catalog execution from Batch", () => {
  const batchSettings = { ...settings, catalogExecutionMode: "QWEN_BATCH" };
  const result = translationSettingsSaveInput("tencent-tokenhub", {
    ...draft,
    provider: "tencent-tokenhub",
    baseUrl: "https://tokenhub.tencentmaas.com/v1",
    modelName: "hy-mt2-plus",
  }, batchSettings);
  assert.equal(result.provider, "tencent-tokenhub");
  assert.equal(result.catalogExecutionMode, "REALTIME");
  assert.equal(result.batchBaseUrl, settings.batchBaseUrl);
  assert.equal(result.searchTranslationEnabled, true);
});

test("provider defaults are separate from the active provider draft", () => {
  assert.equal(defaultProviderDraft("aliyun-alimt").baseUrl, "mt.cn-hangzhou.aliyuncs.com");
  assert.equal(defaultProviderDraft("deeplx").modelName, "DeepLX");
  assert.equal(defaultProviderDraft("openai-compatible").baseUrl, "");
  assert.equal(defaultProviderDraft("tencent-tokenhub").baseUrl, "https://tokenhub.tencentmaas.com/v1");
  assert.equal(defaultProviderDraft("tencent-tokenhub").modelName, "hy-mt2-plus");
});
