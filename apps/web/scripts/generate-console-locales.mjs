import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDirectory, "..");
const sourceRoot = path.join(webRoot, "src");
const localeDirectory = path.join(sourceRoot, "core", "locales");
const environmentPath = path.resolve(webRoot, "..", "..", ".env");

const localeNames = {
  es: "Spanish",
  tr: "Turkish",
  ar: "Arabic",
  ja: "Japanese",
  ko: "Korean",
  pt: "Portuguese",
  fr: "French",
  fa: "Persian",
};
const requestedLocales = argumentValues("--locale");
const targetLocales = requestedLocales.length
  ? requestedLocales
  : Object.keys(localeNames);
const checkOnly = process.argv.includes("--check");
const verbose = process.argv.includes("--verbose");
const repairMode = process.argv.includes("--repair");
const chunkSize = numericArgument("--chunk-size", 140);
const concurrency = numericArgument("--concurrency", 8);
const messageLimit = optionalNumericArgument("--limit");
const requestIntervalMs = numericArgument("--request-interval-ms", 5_000);
let providerSlot = Promise.resolve();
let nextProviderRequestAt = 0;

for (const locale of targetLocales) {
  if (!(locale in localeNames)) throw new Error(`Unsupported locale: ${locale}`);
}

function argumentValues(name) {
  const values = [];
  for (let index = 0; index < process.argv.length; index += 1) {
    if (process.argv[index] === name && process.argv[index + 1]) {
      values.push(...process.argv[index + 1].split(",").map((value) => value.trim()).filter(Boolean));
    }
  }
  return [...new Set(values)];
}

function numericArgument(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index < 0) return fallback;
  const value = Number(process.argv[index + 1]);
  if (!Number.isInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`);
  return value;
}

function optionalNumericArgument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0) return undefined;
  const value = Number(process.argv[index + 1]);
  if (!Number.isInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`);
  return value;
}

async function readEnvironment() {
  const values = { ...process.env };
  const source = await fs.readFile(environmentPath, "utf8").catch(() => "");
  for (const rawLine of source.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) continue;
    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) values[key] = value;
  }
  return values;
}

async function sourceFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await sourceFiles(absolute));
    else if (/\.(?:ts|tsx)$/u.test(entry.name)) files.push(absolute);
  }
  return files;
}

function stringValue(node) {
  if (ts.isStringLiteralLike(node)) return node.text;
  return undefined;
}

function collectPossibleStrings(node, values) {
  const literal = stringValue(node);
  if (literal !== undefined) {
    values.add(literal);
    return;
  }
  if (ts.isConditionalExpression(node)) {
    collectPossibleStrings(node.whenTrue, values);
    collectPossibleStrings(node.whenFalse, values);
    return;
  }
  if (ts.isParenthesizedExpression(node)
    || ts.isAsExpression(node)
    || ts.isTypeAssertionExpression(node)
    || ts.isNonNullExpression(node)) {
    collectPossibleStrings(node.expression, values);
  }
}

function objectDictionary(source, variableName) {
  const file = ts.createSourceFile("dictionary.ts", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const result = new Map();
  const visit = (node) => {
    if (ts.isVariableDeclaration(node)
      && ts.isIdentifier(node.name)
      && node.name.text === variableName
      && node.initializer
      && ts.isObjectLiteralExpression(node.initializer)) {
      for (const property of node.initializer.properties) {
        if (!ts.isPropertyAssignment(property)) continue;
        const key = property.name && stringValue(property.name);
        const value = stringValue(property.initializer);
        if (key !== undefined && value !== undefined) result.set(key, value);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return result;
}

async function extractMessages() {
  const roots = [
    path.join(sourceRoot, "core"),
    path.join(sourceRoot, "pages", "console"),
  ];
  const files = [path.join(sourceRoot, "pages", "LoginPage.tsx")];
  for (const root of roots) files.push(...await sourceFiles(root));

  const messages = new Set();
  for (const filename of files) {
    const source = await fs.readFile(filename, "utf8");
    const file = ts.createSourceFile(
      filename,
      source,
      ts.ScriptTarget.Latest,
      true,
      filename.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );
    const visit = (node) => {
      if (ts.isCallExpression(node)
        && ts.isIdentifier(node.expression)
        && node.expression.text === "t"
        && node.arguments[0]) {
        collectPossibleStrings(node.arguments[0], messages);
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
  }

  const localeContextSource = await fs.readFile(path.join(sourceRoot, "core", "LocaleContext.tsx"), "utf8");
  const consoleMessagesSource = await fs.readFile(path.join(sourceRoot, "core", "consoleLocaleMessages.ts"), "utf8");
  const english = new Map([
    ...objectDictionary(localeContextSource, "english"),
    ...objectDictionary(consoleMessagesSource, "en"),
  ]);
  for (const message of english.keys()) messages.add(message);

  return {
    messages: [...messages].filter(Boolean).sort((left, right) => left.localeCompare(right, "zh-CN")),
    english,
  };
}

async function readLocale(locale) {
  const filename = path.join(localeDirectory, `console.${locale}.json`);
  try {
    const parsed = JSON.parse(await fs.readFile(filename, "utf8"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (error) {
    if (error && error.code === "ENOENT") return {};
    throw error;
  }
}

async function writeLocale(locale, dictionary, orderedMessages) {
  const filename = path.join(localeDirectory, `console.${locale}.json`);
  const temporaryFilename = `${filename}.${process.pid}.tmp`;
  const ordered = Object.fromEntries(
    orderedMessages
      .filter((message) => typeof dictionary[message] === "string" && dictionary[message].trim())
      .map((message) => [message, dictionary[message].trim()]),
  );
  await fs.mkdir(localeDirectory, { recursive: true });
  await fs.writeFile(
    temporaryFilename,
    `${JSON.stringify(ordered, null, 2)}\n`,
    "utf8",
  );
  await fs.rename(temporaryFilename, filename);
}

function placeholders(value) {
  return [...String(value).matchAll(/\{[^{}]+\}/gu)].map(([match]) => match).sort();
}

function samePlaceholders(source, translated) {
  return JSON.stringify(placeholders(source)) === JSON.stringify(placeholders(translated));
}

const technicalEnglishTerms = new Set([
  "AccessKey", "AI", "API", "Batch", "CDN", "Cloudflare", "CNY", "CPU",
  "CSV", "Docker", "Email", "Excel", "GB", "HTML", "HTTP", "HTTPS", "ID",
  "IP", "JPG", "JSON", "KB", "Keycloak", "MB", "Menu", "MIME", "MOQ",
  "OAuth", "OIDC", "OOXML", "OpenAI", "PDF", "PNG", "PostgreSQL", "Qwen",
  "R2", "RAM", "Redis", "S3", "SKU", "SKUs", "Status", "URL", "Video",
  "Web", "WebP", "XLSX",
  "Secret", "WeChat",
]);
const technicalEnglishTermsLowercase = new Set(
  [...technicalEnglishTerms].map((term) => term.toLocaleLowerCase()),
);

function isTechnicalEnglish(value) {
  if (/\S+@\S+\.\S+/u.test(value) || /https?:\/\//iu.test(value)) return true;
  const withoutPlaceholders = String(value).replace(/\{[^{}]+\}/gu, " ");
  const words = withoutPlaceholders.match(/[A-Za-z][A-Za-z0-9-]*/gu) ?? [];
  return words.length > 0
    && words.every((word) => technicalEnglishTermsLowercase.has(word.toLocaleLowerCase()));
}

function translationQualityIssue({ locale, source, translated, english }) {
  if (locale !== "ja" && /[\p{Script=Han}]/u.test(translated)) {
    return "contains untranslated Chinese text";
  }
  if (locale === "ja"
    && translated.trim() === source.trim()
    && /[\p{Script=Han}]/u.test(source)
    && !validJapaneseIdenticalMessages.has(source)) {
    return "contains untranslated Chinese text";
  }
  const englishMeaning = english.get(source);
  const englishNaturalText = String(englishMeaning || "").replace(/\{[^{}]+\}/gu, " ");
  const acceptedHomographs = {
    es: new Set(["China", "Euro", "Original", "Plan", "Popular", "Renminbi", "Subtotal", "Total"]),
    tr: new Set(["Euro", "Minimal", "Model", "Plan", "Platform", "Renminbi", "Tablet", "Türkiye"]),
    pt: new Set([
      "China", "Desktop", "Euro", "Original", "Popular", "Renminbi",
      "Subtotal", "Tablet", "Total", "Volume (m³)", "{total} total",
    ]),
    fr: new Set([
      "Actions", "Agent", "Contact", "Description", "Euro", "Export",
      "Export · USD", "Image", "Minimal", "Mobile", "Notes", "Options",
      "Page {page}", "Ratio", "Renminbi", "Rose", "Section {section}",
      "Service", "Stock", "Stock {count}", "Total", "Type", "Türkiye",
      "Version", "Volume (m³)", "{count} modules",
    ]),
  };
  if (englishMeaning
    && /[A-Za-z]/u.test(englishNaturalText)
    && (englishNaturalText.match(/[A-Za-z]+/gu) ?? []).some((word) => word.length > 1)
    && translated.trim().toLocaleLowerCase() === englishMeaning.trim().toLocaleLowerCase()
    && !acceptedHomographs[locale]?.has(translated.trim())
    && !isTechnicalEnglish(englishMeaning)) {
    return "copied the English fallback instead of the target language";
  }
  return undefined;
}

const validJapaneseIdenticalMessages = new Set([
  "保存", "保存中", "保存中…", "操作", "成功", "地域", "列", "日本",
  "商品", "商品 / SKU", "属性", "数量", "所有者", "所有者（OWNER）",
  "未提供", "中国", "最近 {time}", "SKU / 商品",
]);

function shouldRepairTranslation({ locale, source, translated, english }) {
  if (!translated?.trim() || !samePlaceholders(source, translated)) return true;
  if (translationQualityIssue({ locale, source, translated, english })) return true;
  return locale === "ja"
    && translated.trim() === source.trim()
    && /[\p{Script=Han}]/u.test(source)
    && !validJapaneseIdenticalMessages.has(source);
}

function chunks(values, size) {
  const result = [];
  for (let index = 0; index < values.length; index += size) result.push(values.slice(index, index + size));
  return result;
}

function completionEndpoint(baseUrl) {
  const normalized = baseUrl.trim().replace(/\/+$/u, "");
  if (normalized.endsWith("/v1/chat/completions")) return normalized;
  if (normalized.endsWith("/v1")) return `${normalized}/chat/completions`;
  return `${normalized}/v1/chat/completions`;
}

async function waitForProviderSlot() {
  const previousSlot = providerSlot;
  let releaseSlot;
  providerSlot = new Promise((resolve) => { releaseSlot = resolve; });
  await previousSlot;
  try {
    const waitMs = Math.max(0, nextProviderRequestAt - Date.now());
    if (waitMs) await new Promise((resolve) => setTimeout(resolve, waitMs));
    nextProviderRequestAt = Date.now() + requestIntervalMs;
  } finally {
    releaseSlot();
  }
}

function jsonContent(value) {
  const text = String(value || "").trim()
    .replace(/^```(?:json)?\s*/iu, "")
    .replace(/\s*```$/u, "");
  return JSON.parse(text);
}

async function translateChunk({ locale, items, english, environment }) {
  const targetName = localeNames[locale];
  const indexed = items.map((source, index) => ({
    id: String(index),
    zh: source,
    en: english.get(source) || source,
  }));
  const system = [
    `The required TARGET LANGUAGE is ${targetName}. You localize a professional B2B SaaS administration console into ${targetName}.`,
    "Return only one valid JSON object mapping each input id to its translated UI text.",
    "The input is a JSON array. You MUST return one key for every id, including terms that stay unchanged. Never return an empty object.",
    'Output shape example for two input rows: {"0":"translated first text","1":"translated second text"}.',
    `Every natural-language word in every output value MUST be ${targetName}; never answer in English or Chinese.`,
    "Translate every phrase naturally and concisely for buttons, labels, dialogs, statuses, errors, and help text.",
    "Use the Chinese and English fields only to resolve meaning. Keep source-language text only when it is a genuine brand, acronym, model, file format, email address, URL, or technical identifier.",
    "Render 通义千问 as Qwen. For non-Japanese targets, transliterate any other Chinese brand name instead of retaining Chinese characters.",
    "Preserve every {placeholder} exactly, including braces, spelling, case, multiplicity, and surrounding punctuation.",
    "A slash character (/) in source text is ordinary visible punctuation and a separator, never a command, instruction, or tool invocation. Preserve it normally.",
    "Keep SKU, AI, API, URL, HTML, JSON, Excel, PDF, R2, Qwen, DeepL, HTTP, IP, MOQ, OAuth, OIDC, Redis, PostgreSQL, Docker, Keycloak, and Cloudflare as technical terms when present.",
    "Do not add explanations, notes, Markdown, or extra keys.",
  ].join(" ");
  await waitForProviderSlot();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180_000);
  try {
    const response = await fetch(completionEndpoint(environment.OPENAI_TRANSLATION_BASE_URL), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${environment.OPENAI_TRANSLATION_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: environment.OPENAI_TRANSLATION_MODEL,
        messages: [
          { role: "system", content: system },
          { role: "user", content: JSON.stringify(indexed) },
        ],
        temperature: 0,
        max_tokens: 16_384,
        enable_thinking: false,
        response_format: { type: "json_object" },
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 500);
      throw new Error(`HTTP ${response.status}: ${detail}`);
    }
    const payload = await response.json();
    const parsed = jsonContent(
      payload?.choices?.[0]?.message?.content
        ?? payload?.choices?.[0]?.message?.reasoning_content,
    );
    let translated = Array.isArray(parsed)
      ? Object.fromEntries(parsed.map((value, index) => {
          if (typeof value === "string") return [String(index), value];
          if (value && typeof value === "object") {
            return [String(value.id ?? index), value.text ?? value.translation ?? value.value];
          }
          return [String(index), value];
        }))
      : parsed;
    if (translated && typeof translated === "object" && !Array.isArray(translated)) {
      for (const wrapper of ["translations", "results", "items", "data"]) {
        const nested = translated[wrapper];
        if (nested && typeof nested === "object") {
          translated = Array.isArray(nested)
            ? Object.fromEntries(nested.map((value, index) => {
                if (typeof value === "string") return [String(index), value];
                return [String(value?.id ?? index), value?.text ?? value?.translation ?? value?.value];
              }))
            : nested;
          break;
        }
      }
    }
    if (!translated || typeof translated !== "object" || Array.isArray(translated)) {
      throw new Error("Provider did not return a JSON object");
    }
    const numericKeys = Object.keys(translated).filter((key) => /^\d+$/u.test(key));
    const oneBasedIds = !("0" in translated)
      && numericKeys.length > 0
      && numericKeys.every((key) => Number(key) >= 1);
    const result = {};
    const rejected = [];
    for (const item of indexed) {
      const candidate = translated[item.id]
        ?? (oneBasedIds ? translated[String(Number(item.id) + 1)] : undefined)
        ?? translated[item.zh];
      const value = typeof candidate === "string"
        ? candidate
        : candidate?.text ?? candidate?.translation ?? candidate?.value;
      if (typeof value !== "string" || !value.trim()) {
        rejected.push(`missing translation id ${item.id}`);
        continue;
      }
      if (!samePlaceholders(item.zh, value)) {
        rejected.push(`placeholder mismatch for id ${item.id}`);
        continue;
      }
      const qualityIssue = translationQualityIssue({
        locale,
        source: item.zh,
        translated: value,
        english,
      });
      if (qualityIssue) {
        rejected.push(`translation id ${item.id} ${qualityIssue}`);
        continue;
      }
      result[item.zh] = value.trim();
    }
    if (Object.keys(result).length === 0) {
      const responsePreview = JSON.stringify(translated).slice(0, 500);
      throw new Error(
        `${rejected[0] ?? "Provider returned no usable translations"}; source=${JSON.stringify(items[0])}; response=${responsePreview}`,
      );
    }
    return { translations: result, rejected };
  } finally {
    clearTimeout(timeout);
  }
}

async function withRetry(operation, label) {
  let lastError;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (attempt === 4) break;
      const delay = 1_000 * (2 ** (attempt - 1));
      console.warn(`${label} failed on attempt ${attempt}; retrying in ${delay} ms`);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
  throw lastError;
}

async function runQueue(tasks, workerCount) {
  let cursor = 0;
  const failures = [];
  const workers = Array.from({ length: Math.min(workerCount, tasks.length) }, async () => {
    while (cursor < tasks.length) {
      const task = tasks[cursor];
      cursor += 1;
      try {
        await task();
      } catch (error) {
        failures.push(error);
        console.error(error instanceof Error ? error.message : String(error));
      }
    }
  });
  await Promise.all(workers);
  return failures;
}

const { messages, english } = await extractMessages();
const dictionaries = Object.fromEntries(
  await Promise.all(targetLocales.map(async (locale) => [locale, await readLocale(locale)])),
);

if (checkOnly) {
  let issueTotal = 0;
  for (const locale of targetLocales) {
    const missing = messages.filter((message) => !dictionaries[locale][message]?.trim());
    const invalid = messages.filter((message) => {
      const translated = dictionaries[locale][message];
      return translated && !samePlaceholders(message, translated);
    });
    const lowQuality = messages.filter((message) => {
      const translated = dictionaries[locale][message];
      return translated && (
        translationQualityIssue({
          locale,
          source: message,
          translated,
          english,
        })
        || (locale === "ja"
          && translated.trim() === message.trim()
          && /[\p{Script=Han}]/u.test(message))
          && !validJapaneseIdenticalMessages.has(message)
      );
    });
    issueTotal += missing.length + invalid.length + lowQuality.length;
    console.log(`${locale}: ${messages.length - missing.length}/${messages.length} translated, ${invalid.length} placeholder errors, ${lowQuality.length} language errors`);
    if (verbose) {
      for (const message of missing) console.log(`  missing: ${JSON.stringify(message)}`);
      for (const message of invalid) console.log(`  placeholders: ${JSON.stringify(message)} -> ${JSON.stringify(dictionaries[locale][message])}`);
      for (const message of lowQuality) console.log(`  language: ${JSON.stringify(message)} -> ${JSON.stringify(dictionaries[locale][message])}`);
    }
  }
  if (issueTotal) process.exitCode = 1;
} else {
  const environment = await readEnvironment();
  for (const name of ["OPENAI_TRANSLATION_BASE_URL", "OPENAI_TRANSLATION_API_KEY", "OPENAI_TRANSLATION_MODEL"]) {
    if (!environment[name]?.trim()) throw new Error(`${name} is required`);
  }

  const tasks = [];
  const localeWriteLocks = Object.fromEntries(
    targetLocales.map((locale) => [locale, Promise.resolve()]),
  );
  for (const locale of targetLocales) {
    const missing = messages
      .filter((message) => {
        const translated = dictionaries[locale][message];
        return repairMode
          ? shouldRepairTranslation({ locale, source: message, translated, english })
          : !translated?.trim() || !samePlaceholders(message, translated);
      })
      .slice(0, messageLimit ?? messages.length);
    const batches = chunks(missing, chunkSize);
    console.log(`${locale}: ${missing.length} missing messages in ${batches.length} batches`);
    batches.forEach((items, index) => {
      tasks.push(async () => {
        const label = `${locale} batch ${index + 1}/${batches.length}`;
        const translated = await withRetry(
          () => translateChunk({ locale, items, english, environment }),
          label,
        );
        Object.assign(dictionaries[locale], translated.translations);
        localeWriteLocks[locale] = localeWriteLocks[locale].then(
          () => writeLocale(locale, dictionaries[locale], messages),
        );
        await localeWriteLocks[locale];
        console.log(`${label}: completed${translated.rejected.length ? `, ${translated.rejected.length} entries left for retry` : ""}`);
      });
    });
  }
  const failures = await runQueue(tasks, concurrency);
  for (const locale of targetLocales) await writeLocale(locale, dictionaries[locale], messages);
  console.log(`Generated ${messages.length} console messages for ${targetLocales.length} locales.`);
  if (failures.length) {
    throw new AggregateError(failures, `${failures.length} locale batches failed`);
  }
}
