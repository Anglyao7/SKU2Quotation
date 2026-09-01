import { localizeSkuOptionValues } from "../lib/storefrontLanguagePack";
import type { CatalogLanguagePack } from "../types";
import type {
  CoreProduct,
  ProductAttribute,
  ProductCategory,
  ProductDetail,
  ProductListPage,
  ProductSku,
} from "./types";

function normalizedCategoryPath(value: string): string {
  return value.replaceAll("／", "/").trim();
}

export function localizeProductCategories(
  categories: ProductCategory[],
  pack: CatalogLanguagePack | undefined,
): ProductCategory[] {
  if (!pack) return categories;
  return categories.map((category) => {
    const sourcePath = normalizedCategoryPath(category.path || category.name);
    let localizedPath: string | undefined = pack.categories[sourcePath]
      || pack.categories[category.path || ""]
      || pack.categories[category.name];
    if (!localizedPath && !category.parentId) {
      localizedPath = Object.entries(pack.categories).find(([path]) => (
        normalizedCategoryPath(path).startsWith(`${sourcePath}/`)
      ))?.[1]?.replaceAll("／", "/").split("/")[0];
    }
    if (!localizedPath) return category;
    const normalized = normalizedCategoryPath(localizedPath);
    return {
      ...category,
      name: normalized.split("/").at(-1) || category.name,
      path: normalized,
    };
  });
}

function translatedProduct(
  product: CoreProduct,
  pack: CatalogLanguagePack | undefined,
) {
  const translation = pack?.products[product.id];
  return translation?.product_version === product.currentVersion
    ? translation
    : undefined;
}

export function localizeCoreProduct(
  product: CoreProduct,
  pack: CatalogLanguagePack | undefined,
): CoreProduct {
  const translation = translatedProduct(product, pack);
  if (!translation) return product;
  return {
    ...product,
    name: translation.name || product.name,
    model: translation.specifications[product.model] || product.model,
    category: translation.category_label || product.category,
    tags: translation.tags.length ? translation.tags : product.tags,
  };
}

export function localizeCoreProductPage(
  page: ProductListPage,
  pack: CatalogLanguagePack | undefined,
): ProductListPage {
  if (!pack) return page;
  return {
    ...page,
    items: page.items.map((product) => localizeCoreProduct(product, pack)),
  };
}

function localizeAttribute(
  attribute: ProductAttribute,
  productTranslation: CatalogLanguagePack["products"][string] | undefined,
): ProductAttribute {
  if (!productTranslation) return attribute;
  const value = typeof attribute.value === "string"
    ? productTranslation.option_values[attribute.value] || attribute.value
    : attribute.value;
  return {
    ...attribute,
    key: productTranslation.option_labels[attribute.key] || attribute.key,
    value,
  };
}

function localizeProductSku(
  sku: ProductSku,
  productId: string,
  productVersion: number,
  pack: CatalogLanguagePack,
): ProductSku {
  const translation = pack.skus[sku.id];
  if (
    !translation
    || translation.product_id !== productId
    || translation.product_version !== productVersion
    || translation.sku_version !== sku.version
  ) return sku;
  return {
    ...sku,
    name: translation.name || sku.name,
    optionValues: localizeSkuOptionValues(
      sku.optionValues,
      pack.products[productId],
    ) as ProductSku["optionValues"],
  };
}

export function localizeCoreProductDetail(
  product: ProductDetail,
  pack: CatalogLanguagePack | undefined,
): ProductDetail {
  if (!pack) return product;
  const translation = translatedProduct(product, pack);
  if (!translation) return product;
  const localizedCore = localizeCoreProduct(product, pack);
  return {
    ...product,
    ...localizedCore,
    description: translation.description ?? product.description,
    attributes: product.attributes.map((attribute) => (
      localizeAttribute(attribute, translation)
    )),
    skus: product.skus.map((sku) => (
      localizeProductSku(sku, product.id, product.currentVersion, pack)
    )),
  };
}
