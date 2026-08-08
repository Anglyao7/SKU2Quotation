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
  CheckCircle,
  FloppyDisk,
  Key,
  PlugsConnected,
  ShieldCheck,
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
  testTranslationSettings,
  updateTranslationSettings,
  type TranslationSettingsWriteInput,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  TranslationApiSettings,
  TranslationApiTestResult,
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


export function TranslationApiSettingsPage() {
  const { locale, t } = useLocale();
  const [settings, setSettings] = useState<TranslationApiSettings>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [testResult, setTestResult] = useState<TranslationApiTestResult>();
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
    setTestResult(undefined);
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
    reasoningEffort,
  }), [
    accessKeyId,
    apiKey,
    baseUrl,
    maxTokens,
    modelName,
    provider,
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

  const formValid = Boolean(
    input.baseUrl
      && (isAliyun ? input.regionId : input.modelName)
      && Number.isInteger(input.timeoutSeconds)
      && input.timeoutSeconds >= 1
      && input.timeoutSeconds <= 120
      && (isAliyun || (
        Number.isInteger(input.maxTokens)
        && input.maxTokens >= 512
        && input.maxTokens <= 32768
      ))
      && hasSecret
      && (!isAliyun || hasAccessKeyId),
  );
  const canTest = Boolean(
    input.baseUrl
      && (isAliyun ? input.regionId : input.modelName)
      && (input.apiKey || (storedCredentialsMatch && settings?.apiKeyConfigured))
      && (!isAliyun || (
        input.accessKeyId
        || (storedCredentialsMatch && settings?.accessKeyIdConfigured)
      )),
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
      setTestResult(undefined);
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

  const testConnection = async () => {
    if (!canTest || testing) return;
    setTesting(true);
    setError("");
    setMessage("");
    setTestResult(undefined);
    try {
      setTestResult(await testTranslationSettings(input));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("翻译 API 连接测试失败"),
      );
    } finally {
      setTesting(false);
    }
  };

  const sourceLabel = settings?.source === "database"
    ? t("后台配置")
    : settings?.source === "environment"
      ? t("环境变量")
      : t("未配置");

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
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("平台设置")}
        title={t("翻译 API")}
        description={t(
          "统一管理商品、分类与客服翻译使用的模型接口；配置对所有商家立即生效。",
        )}
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
                  {t(isAliyun
                    ? "使用机器翻译通用版与批量接口，优先降低商品翻译等待时间。"
                    : "调用 /v1/chat/completions，支持自定义 Base URL 与模型。")}
                </Text>
              </div>
              <div className="core-translation-api-status">
                <Badge color={settings.enabled ? "jade" : "gray"}>
                  {t(settings.enabled ? "已启用" : "服务已停用")}
                </Badge>
                <Badge color={settings.source === "database" ? "blue" : "gray"}>
                  {sourceLabel}
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
                    ? "商品字段会优先通过批量翻译接口提交；单次最多 50 段文本。"
                    : "保留现有大模型翻译能力，适合需要更强上下文理解的内容。")}
                </Text>
              </label>

              <div className="core-translation-api-switch">
                <span>
                  <Text size="2" weight="bold" as="div">{t("启用翻译服务")}</Text>
                  <Text size="1" color="gray">
                    {t("关闭后，前台商品翻译、后台翻译任务与客服翻译都会停止调用。")}
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
                  type="button"
                  size="3"
                  variant="soft"
                  disabled={!canTest || testing || saving}
                  onClick={() => void testConnection()}
                >
                  <PlugsConnected />
                  {t(testing ? "测试中…" : "测试连接")}
                </Button>
                <Button
                  type="submit"
                  size="3"
                  disabled={!formValid || saving || testing}
                >
                  <FloppyDisk />
                  {t(saving ? "保存中…" : "保存并生效")}
                </Button>
                <Text size="1" color="gray">
                  {t(isAliyun
                    ? "AccessKey ID 与 Secret 都会加密保存，接口不会返回明文。"
                    : "新密钥会加密保存，后台与接口都不会再显示明文。")}
                </Text>
              </div>
            </form>

            {testResult ? (
              <div className="core-translation-api-test-result" role="status">
                <CheckCircle weight="fill" />
                <span>
                  <Text size="2" weight="bold" as="div">
                    {t("连接成功 · {latency} ms", {
                      latency: testResult.latencyMs.toLocaleString(locale),
                    })}
                  </Text>
                  <Text size="1" color="gray" as="div">
                    {testResult.translatedText}
                  </Text>
                </span>
              </div>
            ) : null}
            {message ? <Text size="2" color="green">{message}</Text> : null}
            {error && settings ? <Text size="2" color="red">{error}</Text> : null}
          </Card>

          <div className="core-translation-api-notes">
            <section>
              <ShieldCheck weight="duotone" />
              <div>
                <Text size="1" color="gray">{t("权限与密钥")}</Text>
                <Heading size="3">{t("仅平台管理员可见")}</Heading>
                <p>{t("商家成员无法读取或修改翻译配置，所有访问凭据只以密文写入数据库。")}</p>
              </div>
            </section>
            <section>
              <Key weight="duotone" />
              <div>
                <Text size="1" color="gray">{t("生效范围")}</Text>
                <Heading size="3">{t("一处配置，全站共用")}</Heading>
                <p>{t("商品名称、描述、分类、标签与客服消息均使用这套配置；已有翻译缓存不受影响。")}</p>
              </div>
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
