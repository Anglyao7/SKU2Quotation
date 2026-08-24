import {
  Badge,
  Button,
  Dialog,
  Skeleton,
  Text,
} from "@radix-ui/themes";
import {
  ArrowRight,
  Camera,
  CheckCircle,
  ImageSquare,
  UploadSimple,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { money } from "../lib/format";
import type {
  StoreImageSearchResponse,
  StorefrontLocale,
} from "../types";

const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

export function StorefrontImageSearch({
  tenantSlug,
  locale,
  shareToken,
  sharedQuery,
  t,
  onOpenDetails,
}: {
  tenantSlug: string;
  locale: StorefrontLocale;
  shareToken: string;
  sharedQuery: string;
  t: (source: string, values?: Record<string, string | number>) => string;
  onOpenDetails: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const requestSequence = useRef(0);
  const [open, setOpen] = useState(false);
  const [previewUrl, setPreviewUrl] = useState("");
  const [filename, setFilename] = useState("");
  const [result, setResult] = useState<StoreImageSearchResponse>();
  const [searching, setSearching] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const searchFile = async (file: File) => {
    if (!ACCEPTED_TYPES.has(file.type)) {
      setError(t("请选择 JPG、PNG、WebP 或 GIF 图片。"));
      return;
    }
    if (!file.size || file.size > MAX_UPLOAD_BYTES) {
      setError(t("图片大小不能超过 20 MB。"));
      return;
    }
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    setOpen(true);
    setError("");
    setResult(undefined);
    setSearching(true);
    setFilename(file.name);
    setPreviewUrl(URL.createObjectURL(file));
    try {
      const next = await api.searchStoreProductsByImage(
        tenantSlug,
        file,
        locale,
        shareToken || undefined,
      );
      if (requestSequence.current === sequence) setResult(next);
    } catch (reason) {
      if (requestSequence.current === sequence) {
        setError(reason instanceof Error ? reason.message : t("图片搜索失败，请稍后重试。"));
      }
    } finally {
      if (requestSequence.current === sequence) setSearching(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const confidenceLabel = (confidence: "HIGH" | "MEDIUM" | "REFERENCE") => (
    confidence === "HIGH"
      ? t("高度相似")
      : confidence === "MEDIUM"
        ? t("较为相似")
        : t("参考匹配")
  );

  const changeOpen = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (nextOpen) return;
    requestSequence.current += 1;
    setSearching(false);
    setDragActive(false);
    setPreviewUrl("");
    setFilename("");
    setResult(undefined);
    setError("");
  };

  return (
    <Dialog.Root open={open} onOpenChange={changeOpen}>
      <Dialog.Trigger>
        <Button type="button" size="3" variant="soft" className="store-image-search-trigger">
          <Camera size={19} weight="duotone" />
          <span>{t("图片搜索")}</span>
        </Button>
      </Dialog.Trigger>
      <Dialog.Content className="store-image-search-dialog" maxWidth="980px">
        <div className="store-image-search-heading">
          <span className="store-image-search-mark"><ImageSquare weight="duotone" /></span>
          <div>
            <Dialog.Title>{t("上传图片查找相似商品")}</Dialog.Title>
            <Dialog.Description>{t("系统会比较商品视觉特征，并按匹配度给出当前店铺可购买的商品。")}</Dialog.Description>
          </div>
        </div>

        <div className="store-image-search-layout">
          <section className="store-image-search-input-panel" aria-label={t("搜索图片")}>
            <input
              ref={inputRef}
              className="sr-only"
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void searchFile(file);
              }}
            />
            <button
              type="button"
              className={`store-image-dropzone${dragActive ? " is-dragging" : ""}${previewUrl ? " has-preview" : ""}`}
              onClick={() => inputRef.current?.click()}
              onDragEnter={(event) => { event.preventDefault(); setDragActive(true); }}
              onDragOver={(event) => { event.preventDefault(); setDragActive(true); }}
              onDragLeave={(event) => { event.preventDefault(); setDragActive(false); }}
              onDrop={(event) => {
                event.preventDefault();
                setDragActive(false);
                const file = event.dataTransfer.files?.[0];
                if (file) void searchFile(file);
              }}
            >
              {previewUrl ? (
                <img src={previewUrl} alt={t("待搜索图片预览")} />
              ) : (
                <span className="store-image-dropzone-empty">
                  <UploadSimple size={28} weight="duotone" />
                  <strong>{t("选择或拖入一张图片")}</strong>
                  <small>{t("JPG、PNG、WebP 或 GIF，最大 20 MB")}</small>
                </span>
              )}
            </button>
            {filename ? <Text size="1" color="gray" className="store-image-search-filename">{filename}</Text> : null}
            <Button type="button" variant="soft" color="gray" onClick={() => inputRef.current?.click()} disabled={searching}>
              <UploadSimple />{t(previewUrl ? "更换图片" : "选择图片")}
            </Button>
            <Text size="1" color="gray">{t("客户图片只用于本次检索，不会加入商家的商品知识库。")}</Text>
          </section>

          <section className="store-image-search-result-panel" aria-live="polite" aria-busy={searching}>
            <div className="store-image-result-heading">
              <div>
                <Text size="1" color="gray">{t("视觉匹配")}</Text>
                <strong>{searching ? t("正在分析图片") : result?.results.length ? t("找到 {count} 个相似商品", { count: result.results.length }) : t("搜索结果")}</strong>
              </div>
              {result?.results.length ? <Badge color="jade"><CheckCircle weight="fill" />{t("已按匹配度排序")}</Badge> : null}
            </div>

            {searching ? (
              <div className="store-image-result-skeletons">
                {[0, 1, 2].map((value) => (
                  <div className="store-image-result-skeleton" key={value}>
                    <Skeleton width="86px" height="86px" />
                    <span><Skeleton width="72%" height="18px" /><Skeleton width="48%" height="14px" /><Skeleton width="36%" height="18px" /></span>
                  </div>
                ))}
                <Text size="2" color="gray">{t("正在生成查询向量，并与店铺商品图片进行相似度计算…")}</Text>
              </div>
            ) : error ? (
              <div className="store-image-result-state is-error">
                <WarningCircle size={28} weight="duotone" />
                <strong>{t("暂时无法完成图片搜索")}</strong>
                <Text size="2" color="gray">{error}</Text>
                <Button variant="soft" onClick={() => inputRef.current?.click()}>{t("重新选择图片")}</Button>
              </div>
            ) : result?.results.length ? (
              <div className="store-image-result-list">
                {result.results.map((item) => {
                  const product = item.product;
                  return (
                    <article className="store-image-result-item" key={product.id}>
                      <Link
                        to={`/${encodeURIComponent(tenantSlug)}/products/${encodeURIComponent(product.id)}${sharedQuery}`}
                        state={{ fromStorefrontCatalog: true }}
                        className="store-image-result-media"
                        onClick={() => { onOpenDetails(); changeOpen(false); }}
                        onPointerEnter={() => void api.prefetchStoreProduct(tenantSlug, product.id, locale, shareToken || undefined)}
                      >
                        {product.image_url ? <img src={product.image_url} alt={product.name} /> : <ImageSquare size={30} />}
                      </Link>
                      <div className="store-image-result-copy">
                        <span className="store-image-result-score">
                          <Badge color={item.confidence === "HIGH" ? "jade" : item.confidence === "MEDIUM" ? "blue" : "gray"}>{confidenceLabel(item.confidence)}</Badge>
                          <strong>{item.match_percent.toFixed(1)}%</strong>
                        </span>
                        <Link
                          to={`/${encodeURIComponent(tenantSlug)}/products/${encodeURIComponent(product.id)}${sharedQuery}`}
                          state={{ fromStorefrontCatalog: true }}
                          onClick={() => { onOpenDetails(); changeOpen(false); }}
                        >{product.name}</Link>
                        <Text size="2" weight="bold" className="price-text">{money(product.price_from, product.currency)}</Text>
                      </div>
                      <Button asChild size="2" variant="soft">
                        <Link
                          to={`/${encodeURIComponent(tenantSlug)}/products/${encodeURIComponent(product.id)}${sharedQuery}`}
                          state={{ fromStorefrontCatalog: true }}
                          onClick={() => { onOpenDetails(); changeOpen(false); }}
                        >{t("查看")}<ArrowRight /></Link>
                      </Button>
                    </article>
                  );
                })}
              </div>
            ) : previewUrl && result ? (
              <div className="store-image-result-state">
                <ImageSquare size={30} weight="duotone" />
                <strong>{t("暂时没有可比较的商品图片")}</strong>
                <Text size="2" color="gray">{t(result.status === "INDEX_EMPTY"
                  ? "当前店铺还没有可搜索的图片向量，请联系商家更新图片索引。"
                  : "请换一张图片重试，或使用文字搜索。")}</Text>
              </div>
            ) : (
              <div className="store-image-result-state">
                <Camera size={30} weight="duotone" />
                <strong>{t("先选择一张参考图片")}</strong>
                <Text size="2" color="gray">{t("适合用商品照片、截图或实拍图查找视觉上接近的商品。")}</Text>
              </div>
            )}
          </section>
        </div>
      </Dialog.Content>
    </Dialog.Root>
  );
}
