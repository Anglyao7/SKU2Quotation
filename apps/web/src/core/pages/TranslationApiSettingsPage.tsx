import {
  Badge,
  Button,
  Card,
  Heading,
  Select,
  Switch,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  FloppyDisk,
  Translate,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import {
  getTranslationSettings,
  updateTranslationSettings,
  type TranslationSettingsWriteInput,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  TranslationApiSettings,
  TranslationProviderKind,
  TranslationReasoningEffort,
} from "../types";


const reasoningOptions: TranslationReasoningEffort[] = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
];

const ALIYUN_ENDPOINT = "mt.cn-hangzhou.aliyuncs.com";
const ALIYUN_REGION = "cn-hangzhou";
const ALIYUN_EDITION = "translate_standard";


export function TranslationApiSettingsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { t } = useLocale();
  const [settings, setSettings] = useState<TranslationApiSettings>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [provider, setProvider] =
    useState<TranslationProviderKind>("openai-compatible");
  const [enabled, setEnabled] = useState(true);
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [accessKeyId, setAccessKeyId] = useState("");
  const [regionId, setRegionId] = useState(ALIYUN_REGION);
  const [timeoutSeconds, setTimeoutSeconds] = useState("20");
  const [maxTokens, setMaxTokens] = useState("16384");
  const [requestsPerMinute, setRequestsPerMinute] = useState("60");
  const [maxRetryCount, setMaxRetryCount] = useState("3");
  const [catalogBatchSize, setCatalogBatchSize] = useState("50");
  const [catalogBatchCharacters, setCatalogBatchCharacters] =
    useState("10000");
  const [reasoningEffort, setReasoningEffort] =
    useState<TranslationReasoningEffort>("low");

  const applySettings = useCallback((next: TranslationApiSettings) => {
    setSettings(next);
    setProvider(
      next.provider === "aliyun-alimt"
        ? "aliyun-alimt"
        : "openai-compatible",
    );
    setEnabled(next.enabled);
    setBaseUrl(next.baseUrl ?? "");
    setModelName(next.modelName ?? "");
    setRegionId(next.regionId ?? ALIYUN_REGION);
    setTimeoutSeconds(String(next.timeoutSeconds));
    setMaxTokens(String(next.maxTokens));
    setRequestsPerMinute(String(next.requestsPerMinute));
    setMaxRetryCount(String(next.maxRetryCount));
    setCatalogBatchSize(String(next.catalogBatchSize));
    setCatalogBatchCharacters(String(next.catalogBatchCharacters));
    setReasoningEffort(next.reasoningEffort);
    setApiKey("");
    setAccessKeyId("");
  }, []);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      applySettings(await getTranslationSettings());
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("翻译 API 配置读取失败"),
      );
    } finally {
      setLoading(false);
    }
  }, [applySettings, t]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const clearResult = () => {
    setMessage("");
    setError("");
  };

  const input = useMemo<TranslationSettingsWriteInput>(() => ({
    provider,
    baseUrl: baseUrl.trim(),
    apiKey: apiKey.trim() || undefined,
    accessKeyId: accessKeyId.trim() || undefined,
    modelName: modelName.trim(),
    regionId: regionId.trim() || undefined,
    timeoutSeconds: Number(timeoutSeconds),
    maxTokens: Number(maxTokens),
    requestsPerMinute: Number(requestsPerMinute),
    maxRetryCount: Number(maxRetryCount),
    catalogBatchSize: Number(catalogBatchSize),
    catalogBatchCharacters: Number(catalogBatchCharacters),
    reasoningEffort,
  }), [
    accessKeyId,
    apiKey,
    baseUrl,
    catalogBatchCharacters,
    catalogBatchSize,
    maxRetryCount,
    maxTokens,
    modelName,
    provider,
    requestsPerMinute,
    reasoningEffort,
    regionId,
    timeoutSeconds,
  ]);

  const isAliyun = provider === "aliyun-alimt";
  const storedCredentialsMatch = settings?.provider === provider;
  const hasSecret = Boolean(
    input.apiKey
      || (storedCredentialsMatch && settings?.apiKeyConfigured)
      || !enabled,
  );
  const hasAccessKeyId = Boolean(
    input.accessKeyId
      || (storedCredentialsMatch && settings?.accessKeyIdConfigured)
      || !enabled,
  );
  const validRpm = Number.isInteger(input.requestsPerMinute)
    && input.requestsPerMinute >= 1
    && input.requestsPerMinute <= 10_000;
  const validRetryCount = Number.isInteger(input.maxRetryCount)
    && input.maxRetryCount >= 0
    && input.maxRetryCount <= 10;
  const validBatchSize = Number.isInteger(input.catalogBatchSize)
    && input.catalogBatchSize >= 1
    && input.catalogBatchSize <= 200;
  const validBatchCharacters = Number.isInteger(input.catalogBatchCharacters)
    && input.catalogBatchCharacters >= 1_000
    && input.catalogBatchCharacters <= 100_000;

  const formValid = Boolean(
    input.baseUrl
      && (isAliyun ? input.regionId : input.modelName)
      && Number.isInteger(input.timeoutSeconds)
      && input.timeoutSeconds >= 1
      && input.timeoutSeconds <= 120
      && validRpm
      && validRetryCount
      && validBatchSize
      && validBatchCharacters
      && (isAliyun || (
        Number.isInteger(input.maxTokens)
        && input.maxTokens >= 512
        && input.maxTokens <= 32768
      ))
      && hasSecret
      && (!isAliyun || hasAccessKeyId),
  );
  const saveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!formValid || saving) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const next = await updateTranslationSettings({ ...input, enabled });
      applySettings(next);
      setMessage(t("翻译 API 配置已保存并立即生效。"));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("翻译 API 配置保存失败"),
      );
    } finally {
      setSaving(false);
    }
  };

  const changeProvider = (next: TranslationProviderKind) => {
    clearResult();
    setProvider(next);
    setApiKey("");
    setAccessKeyId("");
    if (next === "aliyun-alimt") {
      setBaseUrl(ALIYUN_ENDPOINT);
      setModelName(ALIYUN_EDITION);
      setRegionId(ALIYUN_REGION);
      setReasoningEffort("none");
      setMaxTokens("16384");
      return;
    }
    if (provider === "aliyun-alimt") {
      setBaseUrl("");
      setModelName("");
      setRegionId(ALIYUN_REGION);
      setReasoningEffort("low");
    }
  };

  return (
    <div className={embedded ? "core-configuration-embedded" : "core-workspace"}>
      {!embedded ? (
        <CorePageHeading
          eyebrow={t("平台设置")}
          title={t("翻译 API")}
          description={t("管理翻译服务配置。")}
          actions={(
            <Button
              variant="soft"
              color="gray"
              disabled={loading}
              onClick={() => void loadSettings()}
            >
              <ArrowClockwise />
              {t("刷新配置")}
            </Button>
          )}
        />
      ) : null}

      {loading && !settings ? (
        <CoreLoading label={t("正在读取翻译 API 配置")} />
      ) : null}
      {error && !settings ? (
        <CoreError message={error} onRetry={() => void loadSettings()} />
      ) : null}

      {settings ? (
        <>
          <Card className="core-translation-api-card">
            <div className="core-translation-api-heading">
              <span className="core-translation-api-icon">
                <Translate weight="duotone" />
              </span>
              <div>
                <Text size="1" color="gray" as="div">
                  {t(isAliyun ? "阿里云机器翻译" : "OpenAI 兼容接口")}
                </Text>
                <Heading size="5">{t("全局翻译服务")}</Heading>
                <Text size="2" color="gray">
                  {t("选择翻译方式并调整运行参数。")}
                </Text>
              </div>
              <div className="core-translation-api-status">
                <Badge color={settings.enabled ? "jade" : "gray"}>
                  {t(settings.enabled ? "已启用" : "服务已停用")}
                </Badge>
              </div>
            </div>

            <form className="core-translation-api-form" onSubmit={(event) => void saveSettings(event)}>
              <label className="core-translation-api-wide">
                <Text size="1" color="gray">{t("翻译服务商")}</Text>
                <Select.Root
                  value={provider}
                  onValueChange={(value) => {
                    changeProvider(value as TranslationProviderKind);
                  }}
                >
                  <Select.Trigger />
                  <Select.Content>
                    <Select.Item value="aliyun-alimt">
                      {t("阿里云机器翻译（通用版）")}
                    </Select.Item>
                    <Select.Item value="openai-compatible">
                      {t("大模型兼容接口")}
                    </Select.Item>
                  </Select.Content>
                </Select.Root>
                <Text size="1" color="gray">
                  {t(isAliyun
                    ? "适合大批量商品内容翻译。"
                    : "适合需要上下文理解的翻译内容。")}
                </Text>
              </label>

              <div className="core-translation-api-switch">
                <span>
                  <Text size="2" weight="bold" as="div">{t("启用翻译服务")}</Text>
                  <Text size="1" color="gray">
                    {t("关闭后，所有翻译任务将暂停。")}
                  </Text>
                </span>
                <Switch
                  checked={enabled}
                  onCheckedChange={(checked) => {
                    clearResult();
                    setEnabled(checked);
                  }}
                />
              </div>

              {isAliyun ? (
                <>
                  <label>
                    <Text size="1" color="gray">{t("地域")}</Text>
                    <TextField.Root
                      value={regionId}
                      onChange={(event) => {
                        clearResult();
                        setRegionId(event.target.value);
                      }}
                      placeholder={ALIYUN_REGION}
                      required
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("服务 Endpoint")}</Text>
                    <TextField.Root
                      value={baseUrl}
                      onChange={(event) => {
                        clearResult();
                        setBaseUrl(event.target.value);
                      }}
                      placeholder={ALIYUN_ENDPOINT}
                      required
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("AccessKey ID")}</Text>
                    <TextField.Root
                      type="password"
                      autoComplete="new-password"
                      value={accessKeyId}
                      onChange={(event) => {
                        clearResult();
                        setAccessKeyId(event.target.value);
                      }}
                      placeholder={
                        storedCredentialsMatch && settings.accessKeyIdConfigured
                          ? t("已配置 {hint}，留空则保持不变", {
                              hint: settings.accessKeyIdHint ?? "",
                            })
                          : t("请输入 AccessKey ID")
                      }
                      required={enabled && !(
                        storedCredentialsMatch && settings.accessKeyIdConfigured
                      )}
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("AccessKey Secret")}</Text>
                    <TextField.Root
                      type="password"
                      autoComplete="new-password"
                      value={apiKey}
                      onChange={(event) => {
                        clearResult();
                        setApiKey(event.target.value);
                      }}
                      placeholder={
                        storedCredentialsMatch && settings.apiKeyConfigured
                          ? t("已配置 {hint}，留空则保持不变", {
                              hint: settings.apiKeyHint ?? "",
                            })
                          : t("请输入 AccessKey Secret")
                      }
                      required={enabled && !(
                        storedCredentialsMatch && settings.apiKeyConfigured
                      )}
                    />
                  </label>
                </>
              ) : (
                <>
                  <label className="core-translation-api-wide">
                    <Text size="1" color="gray">{t("Base URL")}</Text>
                    <TextField.Root
                      type="url"
                      value={baseUrl}
                      onChange={(event) => {
                        clearResult();
                        setBaseUrl(event.target.value);
                      }}
                      placeholder="https://api.example.com"
                      required
                    />
                    <Text size="1" color="gray">
                      {t("可以填写服务根地址、/v1，或完整的 /v1/chat/completions 地址。")}
                    </Text>
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("模型")}</Text>
                    <TextField.Root
                      value={modelName}
                      onChange={(event) => {
                        clearResult();
                        setModelName(event.target.value);
                      }}
                      placeholder="DeepSeek-V4-Flash-0731"
                      required
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("API Key")}</Text>
                    <TextField.Root
                      type="password"
                      autoComplete="new-password"
                      value={apiKey}
                      onChange={(event) => {
                        clearResult();
                        setApiKey(event.target.value);
                      }}
                      placeholder={
                        storedCredentialsMatch && settings.apiKeyConfigured
                          ? t("已配置 {hint}，留空则保持不变", {
                              hint: settings.apiKeyHint ?? "",
                            })
                          : t("请输入 API Key")
                      }
                      required={enabled && !(
                        storedCredentialsMatch && settings.apiKeyConfigured
                      )}
                    />
                  </label>
                </>
              )}

              <label>
                <Text size="1" color="gray">{t("请求超时（秒）")}</Text>
                <TextField.Root
                  type="number"
                  min="1"
                  max="120"
                  value={timeoutSeconds}
                  onChange={(event) => {
                    clearResult();
                    setTimeoutSeconds(event.target.value);
                  }}
                  required
                />
              </label>

              <label>
                <Text size="1" color="gray">
                  {t("每分钟最大请求数（RPM）")}
                </Text>
                <TextField.Root
                  type="number"
                  min="1"
                  max="10000"
                  value={requestsPerMinute}
                  onChange={(event) => {
                    clearResult();
                    setRequestsPerMinute(event.target.value);
                  }}
                  required
                />
                <Text size="1" color="gray">
                  {t("达到上限后请求会排队等待，已完成的翻译和断点不会丢失。")}
                </Text>
              </label>

              <div className="core-translation-batch-settings core-translation-api-wide">
                <div className="core-translation-batch-heading">
                  <div>
                    <Text size="2" weight="bold" as="div">
                      {t("商品批量翻译")}
                    </Text>
                    <Text size="1" color="gray">
                      {t("同时满足 SKU 数量和字符上限时才会放入同一次请求。")}
                    </Text>
                  </div>
                  <Badge color="blue" variant="soft">
                    {t("全量与增量任务")}
                  </Badge>
                </div>
                <div className="core-translation-batch-fields">
                  <label>
                    <Text size="1" color="gray">
                      {t("每批最多 SKU 数")}
                    </Text>
                    <TextField.Root
                      type="number"
                      min="1"
                      max="200"
                      value={catalogBatchSize}
                      onChange={(event) => {
                        clearResult();
                        setCatalogBatchSize(event.target.value);
                      }}
                      required
                    />
                    <Text size="1" color="gray">
                      {t("默认 50，可设置 1–200。")}
                    </Text>
                  </label>
                  <label>
                    <Text size="1" color="gray">
                      {t("单批字符上限")}
                    </Text>
                    <TextField.Root
                      type="number"
                      min="1000"
                      max="100000"
                      step="1000"
                      value={catalogBatchCharacters}
                      onChange={(event) => {
                        clearResult();
                        setCatalogBatchCharacters(event.target.value);
                      }}
                      required
                    />
                    <Text size="1" color="gray">
                      {t("默认 10,000，超出后自动拆分，不会丢失断点。")}
                    </Text>
                  </label>
                  <label>
                    <Text size="1" color="gray">
                      {t("失败后最多重试次数")}
                    </Text>
                    <TextField.Root
                      type="number"
                      min="0"
                      max="10"
                      value={maxRetryCount}
                      onChange={(event) => {
                        clearResult();
                        setMaxRetryCount(event.target.value);
                      }}
                      required
                    />
                    <Text size="1" color="gray">
                      {t("仅临时错误会自动重试；次数不包含首次请求，建议设置为 2–3。")}
                    </Text>
                  </label>
                </div>
              </div>

              {!isAliyun ? (
                <>
                  <label>
                    <Text size="1" color="gray">{t("最大输出 Tokens")}</Text>
                    <TextField.Root
                      type="number"
                      min="512"
                      max="32768"
                      step="128"
                      value={maxTokens}
                      onChange={(event) => {
                        clearResult();
                        setMaxTokens(event.target.value);
                      }}
                      required
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("推理强度")}</Text>
                    <Select.Root
                      value={reasoningEffort}
                      onValueChange={(value) => {
                        clearResult();
                        setReasoningEffort(value as TranslationReasoningEffort);
                      }}
                    >
                      <Select.Trigger />
                      <Select.Content>
                        {reasoningOptions.map((option) => (
                          <Select.Item key={option} value={option}>
                            {t(option)}
                          </Select.Item>
                        ))}
                      </Select.Content>
                    </Select.Root>
                  </label>
                </>
              ) : null}

              <div className="core-translation-api-actions">
                <Button
                  type="submit"
                  size="3"
                  disabled={!formValid || saving}
                >
                  <FloppyDisk />
                  {t(saving ? "保存中…" : "保存并生效")}
                </Button>
              </div>
            </form>

            {message ? <Text size="2" color="green">{message}</Text> : null}
            {error && settings ? <Text size="2" color="red">{error}</Text> : null}
          </Card>

        </>
      ) : null}
    </div>
  );
}
