import type {
  CatalogLanguagePack,
  CatalogLanguagePackDescriptor,
  Sku,
  StoreProduct,
  StoreProductDetail,
  StorefrontCategoryOption,
  StorefrontLocale,
} from "../types";

const DATABASE_NAME = "atc-storefront-language-packs";
const DATABASE_VERSION = 1;
const STORE_NAME = "packages";
const memoryPackages = new Map<string, CachedLanguagePack>();
const pendingPackages = new Map<string, Promise<CatalogLanguagePack | undefined>>();

interface CachedLanguagePack {
  key: string;
  slug: string;
  locale: StorefrontLocale;
  version: number;
  contentSha256: string;
  cachedAt: number;
  payload: CatalogLanguagePack;
}

function cacheKey(
  slug: string,
  locale: StorefrontLocale,
  version: number,
  contentSha256: string,
) {
  return `${slug.toLocaleLowerCase()}:${locale}:${version}:${contentSha256}`;
}

function openDatabase(): Promise<IDBDatabase | undefined> {
  if (typeof indexedDB === "undefined") return Promise.resolve(undefined);
  return new Promise((resolve) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        const store = database.createObjectStore(STORE_NAME, { keyPath: "key" });
        store.createIndex("slugLocale", ["slug", "locale"], { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(undefined);
    request.onblocked = () => resolve(undefined);
  });
}

async function readRecord(key: string): Promise<CachedLanguagePack | undefined> {
  const memory = memoryPackages.get(key);
  if (memory) return memory;
  const database = await openDatabase();
  if (!database) return undefined;
  return new Promise((resolve) => {
    const transaction = database.transaction(STORE_NAME, "readonly");
    const request = transaction.objectStore(STORE_NAME).get(key);
    request.onsuccess = () => {
      const value = request.result as CachedLanguagePack | undefined;
      if (value) memoryPackages.set(value.key, value);
      resolve(value);
    };
    request.onerror = () => resolve(undefined);
    transaction.oncomplete = () => database.close();
    transaction.onerror = () => database.close();
  });
}

async function readLatestRecord(
  slug: string,
  locale: StorefrontLocale,
): Promise<CachedLanguagePack | undefined> {
  const normalizedSlug = slug.toLocaleLowerCase();
  const memory = [...memoryPackages.values()]
    .filter((entry) => entry.slug === normalizedSlug && entry.locale === locale)
    .sort((left, right) => right.version - left.version)[0];
  if (memory) return memory;
  const database = await openDatabase();
  if (!database) return undefined;
  return new Promise((resolve) => {
    const transaction = database.transaction(STORE_NAME, "readonly");
    const index = transaction.objectStore(STORE_NAME).index("slugLocale");
    const request = index.getAll(IDBKeyRange.only([normalizedSlug, locale]));
    request.onsuccess = () => {
      const value = (request.result as CachedLanguagePack[])
        .sort((left, right) => right.version - left.version)[0];
      if (value) memoryPackages.set(value.key, value);
      resolve(value);
    };
    request.onerror = () => resolve(undefined);
    transaction.oncomplete = () => database.close();
    transaction.onerror = () => database.close();
  });
}

async function writeRecord(record: CachedLanguagePack) {
  memoryPackages.set(record.key, record);
  const database = await openDatabase();
  if (!database) return;
  await new Promise<void>((resolve) => {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    store.put(record);
    const index = store.index("slugLocale");
    const request = index.getAll(IDBKeyRange.only([record.slug, record.locale]));
    request.onsuccess = () => {
      const stale = (request.result as CachedLanguagePack[])
        .filter((entry) => entry.key !== record.key)
        .sort((left, right) => right.version - left.version)
        .slice(1);
      for (const entry of stale) {
        store.delete(entry.key);
        memoryPackages.delete(entry.key);
      }
    };
    transaction.oncomplete = () => {
      database.close();
      resolve();
    };
    transaction.onerror = () => {
      database.close();
      resolve();
    };
    transaction.onabort = () => {
      database.close();
      resolve();
    };
  });
}

async function sha256(value: string) {
  if (!globalThis.crypto?.subtle) return undefined;
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function validPayload(
  value: unknown,
  descriptor: CatalogLanguagePackDescriptor,
): value is CatalogLanguagePack {
  if (!value || typeof value !== "object") return false;
  const payload = value as Partial<CatalogLanguagePack>;
  return payload.schema === "atc-catalog-language-pack"
    && payload.schema_version === 2
    && payload.target_locale === descriptor.target_locale
    && payload.version === descriptor.version
    && Boolean(payload.products && payload.skus && payload.categories);
}

export async function cachedLanguagePack(
  slug: string,
  descriptor: CatalogLanguagePackDescriptor,
  downloadUrl: string,
): Promise<CatalogLanguagePack | undefined> {
  const normalizedSlug = slug.toLocaleLowerCase();
  const key = cacheKey(
    normalizedSlug,
    descriptor.target_locale,
    descriptor.version,
    descriptor.content_sha256,
  );
  const exact = await readRecord(key);
  if (exact) return exact.payload;
  const pending = pendingPackages.get(key);
  if (pending) return pending;
  const loading = (async () => {
    try {
      const response = await fetch(downloadUrl, {
        cache: "force-cache",
        credentials: "omit",
      });
      if (!response.ok) throw new Error(`language package HTTP ${response.status}`);
      const raw = await response.text();
      const digest = await sha256(raw);
      if (digest && digest !== descriptor.content_sha256) {
        throw new Error("language package checksum mismatch");
      }
      const payload: unknown = JSON.parse(raw);
      if (!validPayload(payload, descriptor)) {
        throw new Error("language package schema mismatch");
      }
      await writeRecord({
        key,
        slug: normalizedSlug,
        locale: descriptor.target_locale,
        version: descriptor.version,
        contentSha256: descriptor.content_sha256,
        cachedAt: Date.now(),
        payload,
      });
      return payload;
    } catch {
      return (await readLatestRecord(normalizedSlug, descriptor.target_locale))?.payload;
    }
  })();
  pendingPackages.set(key, loading);
  try {
    return await loading;
  } finally {
    if (pendingPackages.get(key) === loading) {
      pendingPackages.delete(key);
    }
  }
}

export async function latestCachedLanguagePack(
  slug: string,
  locale: StorefrontLocale,
) {
  return (await readLatestRecord(slug.toLocaleLowerCase(), locale))?.payload;
}

function localizedOptionValues(
  optionValues: Record<string, unknown> | undefined,
  product: CatalogLanguagePack["products"][string] | undefined,
) {
  if (!optionValues || !product) return optionValues;
  const localized: Record<string, unknown> = {};
  for (const [sourceKey, sourceValue] of Object.entries(optionValues)) {
    if (sourceKey === "_sku2quotation") {
      const marker = sourceValue && typeof sourceValue === "object"
        ? { ...(sourceValue as Record<string, unknown>) }
        : sourceValue;
      if (marker && typeof marker === "object") {
        const keys = (marker as Record<string, unknown>).variant_option_keys;
        if (Array.isArray(keys)) {
          (marker as Record<string, unknown>).variant_option_keys = keys.map(
            (key) => product.option_labels[String(key)] || key,
          );
        }
      }
      localized[sourceKey] = marker;
      continue;
    }
    const targetKey = product.option_labels[sourceKey] || sourceKey;
    const sourceText = ["string", "number", "boolean"].includes(typeof sourceValue)
      ? String(sourceValue)
      : undefined;
    localized[targetKey] = sourceText
      ? product.option_values[sourceText] ?? sourceValue
      : sourceValue;
  }
  return localized;
}

export function localizeSku(
  sku: Sku,
  pack: CatalogLanguagePack,
): Sku {
  const translation = pack.skus[sku.id];
  const sourceMatches = Boolean(
    translation
    && (
      !sku.translation_source_hash
      || sku.translation_source_hash === translation.source_hash
    )
    && (sku.product_version === undefined || sku.product_version === translation.product_version)
    && (sku.sku_version === undefined || sku.sku_version === translation.sku_version)
  );
  if (!translation || !sourceMatches) {
    return {
      ...sku,
      source_locale: pack.source_locale,
      locale: pack.target_locale,
      translation_status: "FALLBACK",
    };
  }
  const product = pack.products[translation.product_id || sku.product_id || ""];
  return {
    ...sku,
    name: translation.name || sku.name,
    description: translation.description ?? sku.description,
    category_label: translation.category_label ?? sku.category_label ?? sku.category,
    tags: translation.tags || sku.tags,
    display_tag: translation.display_tag ?? sku.display_tag,
    specification: translation.specification ?? sku.specification,
    option_values: localizedOptionValues(sku.option_values, product),
    source_locale: pack.source_locale,
    locale: pack.target_locale,
    translation_status: "TRANSLATED",
  };
}

export function localizeProduct(
  product: StoreProduct,
  pack: CatalogLanguagePack,
): StoreProduct {
  const translation = pack.products[product.id];
  const sourceMatches = Boolean(
    translation
    && (
      !product.translation_source_hash
      || product.translation_source_hash === translation.source_hash
    )
    && product.product_version === translation.product_version
  );
  if (!translation || !sourceMatches) {
    return {
      ...product,
      source_locale: pack.source_locale,
      locale: pack.target_locale,
      translation_status: "FALLBACK",
    };
  }
  return {
    ...product,
    name: translation.name || product.name,
    description: translation.description ?? product.description,
    category_label: translation.category_label ?? product.category_label ?? product.category,
    tags: translation.tags || product.tags,
    display_tag: translation.display_tag ?? product.display_tag,
    source_locale: pack.source_locale,
    locale: pack.target_locale,
    translation_status: "TRANSLATED",
  };
}

export function localizeProductDetail(
  product: StoreProductDetail,
  pack: CatalogLanguagePack,
): StoreProductDetail {
  return {
    ...localizeProduct(product, pack),
    skus: product.skus.map((sku) => localizeSku(sku, pack)),
  };
}

export function localizeCategoryOptions(
  options: StorefrontCategoryOption[] | undefined,
  pack: CatalogLanguagePack,
) {
  return options?.map((option) => {
    let label: string | undefined = pack.categories[option.value];
    if (!label && !option.parent_id) {
      const child = Object.entries(pack.categories).find(([path]) => (
        path.replace("／", "/").startsWith(`${option.value.replace("／", "/")}/`)
      ));
      label = child?.[1]?.replace("／", "/").split("/")[0];
    }
    return {
      ...option,
      label: label || option.label,
    };
  });
}

export function localizedLocale(pack: CatalogLanguagePack | undefined, fallback?: StorefrontLocale) {
  return pack?.target_locale ?? fallback;
}
