import { Button, Dialog, Spinner, Text } from "@radix-ui/themes";
import {
  ArrowSquareOut,
  Check,
  Copy,
  DownloadSimple,
  LinkSimple,
  X,
} from "@phosphor-icons/react";
import QRCode from "qrcode";
import { useEffect, useMemo, useState } from "react";

import { createCatalogShare } from "../api";
import { useLocale } from "../LocaleContext";
import { ToastNotice } from "../ToastContext";
import type { CatalogShare, CatalogShareLogoPosition } from "../types";

export type CatalogShareTarget =
  | { type: "PRODUCTS"; productIds: string[] }
  | { type: "CATEGORY"; categoryId: string; categoryName: string }
  | { type: "STOREFRONT" };

interface CatalogShareDialogProps {
  open: boolean;
  target?: CatalogShareTarget;
  onOpenChange: (open: boolean) => void;
}

function absoluteShareUrl(path: string, locale: string) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set("lang", locale);
  return url.toString();
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const input = document.createElement("textarea");
  input.value = value;
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  document.execCommand("copy");
  input.remove();
}

function fitCanvasText(
  context: CanvasRenderingContext2D,
  value: string,
  maxWidth: number,
) {
  if (context.measureText(value).width <= maxWidth) return value;
  let result = value;
  while (result.length > 1 && context.measureText(`${result}…`).width > maxWidth) {
    result = result.slice(0, -1);
  }
  return `${result}…`;
}

async function imageFromUrl(url: string) {
  return await new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = url;
  });
}

async function remoteImageFromUrl(url: string) {
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) throw new Error("Unable to load logo");
  const objectUrl = URL.createObjectURL(await response.blob());
  try {
    return await imageFromUrl(objectUrl);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function drawContainedImage(
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  x: number,
  y: number,
  width: number,
  height: number,
) {
  const scale = Math.min(width / image.naturalWidth, height / image.naturalHeight);
  const drawWidth = image.naturalWidth * scale;
  const drawHeight = image.naturalHeight * scale;
  context.drawImage(
    image,
    x + (width - drawWidth) / 2,
    y + (height - drawHeight) / 2,
    drawWidth,
    drawHeight,
  );
}

function drawCoverImage(
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  width: number,
  height: number,
  opacity = 1,
) {
  const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight);
  const drawWidth = image.naturalWidth * scale;
  const drawHeight = image.naturalHeight * scale;
  const previousAlpha = context.globalAlpha;
  context.globalAlpha = opacity;
  context.drawImage(
    image,
    (width - drawWidth) / 2,
    (height - drawHeight) / 2,
    drawWidth,
    drawHeight,
  );
  context.globalAlpha = previousAlpha;
}

async function downloadShareCard(
  share: CatalogShare,
  qrDataUrl: string,
  backgroundImageUrl?: string,
) {
  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = 1350;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas is unavailable");

  if (backgroundImageUrl) {
    const backgroundImage = await imageFromUrl(backgroundImageUrl);
    drawCoverImage(context, backgroundImage, canvas.width, canvas.height, 0.34);
    context.fillStyle = "rgba(14, 10, 28, .58)";
    context.fillRect(0, 0, canvas.width, canvas.height);
  } else {
    const background = context.createLinearGradient(0, 0, 1080, 1350);
    background.addColorStop(0, "#161121");
    background.addColorStop(0.58, "#2d1b69");
    background.addColorStop(1, "#20152f");
    context.fillStyle = background;
    context.fillRect(0, 0, canvas.width, canvas.height);
  }

  const glow = context.createRadialGradient(860, 110, 0, 860, 110, 520);
  glow.addColorStop(0, "rgba(212, 175, 55, .19)");
  glow.addColorStop(1, "rgba(212, 175, 55, 0)");
  context.fillStyle = glow;
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.strokeStyle = "rgba(212, 175, 55, 0.58)";
  context.lineWidth = 2;
  context.strokeRect(52, 52, 976, 1246);

  const hasLogo = share.logoPosition !== "NONE" && Boolean(share.storeLogoUrl);
  if (hasLogo && share.storeLogoUrl) {
    const logoSize = 142;
    const logoX = share.logoPosition === "TOP_LEFT" ? 92 : 846;
    const logoY = 90;
    context.fillStyle = "rgba(255,255,255,.94)";
    context.beginPath();
    context.roundRect(logoX, logoY, logoSize, logoSize, 22);
    context.fill();
    const logoImage = await remoteImageFromUrl(share.storeLogoUrl);
    drawContainedImage(context, logoImage, logoX + 14, logoY + 14, logoSize - 28, logoSize - 28);
  }

  const merchantNameY = share.logoPosition === "TOP_RIGHT" && hasLogo ? 292 : 174;
  context.textAlign = "right";
  context.fillStyle = "#ffffff";
  context.font = '600 50px "Noto Serif SC", serif';
  context.fillText(fitCanvasText(context, share.storeName, hasLogo ? 680 : 760), 946, merchantNameY);
  if (share.storeSubtitle) {
    context.fillStyle = "rgba(255,255,255,.68)";
    context.font = '400 27px "Noto Sans SC", sans-serif';
    context.fillText(fitCanvasText(context, share.storeSubtitle, hasLogo ? 680 : 760), 946, merchantNameY + 52);
  }

  context.fillStyle = "rgba(255,255,255,.96)";
  context.fillRect(250, 440, 580, 580);
  const qrImage = await imageFromUrl(qrDataUrl);
  context.drawImage(qrImage, 278, 468, 524, 524);

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("Unable to create share card");
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${share.storeName}-分享名片.png`.replace(/[\\/:*?"<>|]/g, "-");
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function CatalogShareDialog({
  open,
  target,
  onOpenChange,
}: CatalogShareDialogProps) {
  const { locale, t } = useLocale();
  const [share, setShare] = useState<CatalogShare>();
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [backgroundImageUrl, setBackgroundImageUrl] = useState("");
  const [backgroundMode, setBackgroundMode] = useState<"color" | "image">("color");
  const [logoPosition, setLogoPosition] = useState<CatalogShareLogoPosition>("NONE");
  const [availableLogoUrl, setAvailableLogoUrl] = useState("");
  const shareUrl = useMemo(
    () => (share ? absoluteShareUrl(share.sharePath, locale) : ""),
    [share, locale],
  );

  useEffect(() => {
    if (!open) {
      setLogoPosition("NONE");
      setAvailableLogoUrl("");
      setBackgroundMode("color");
      setBackgroundImageUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return "";
      });
    }
  }, [open]);

  useEffect(() => {
    if (!open || !target) return;
    let active = true;
    setLoading(true);
    setError("");
    setShare(undefined);
    setQrDataUrl("");
    setCopied(false);
    void createCatalogShare(
      target.type === "PRODUCTS"
        ? { targetType: "PRODUCTS", productIds: target.productIds, logoPosition }
        : target.type === "CATEGORY"
        ? { targetType: "CATEGORY", categoryId: target.categoryId, logoPosition }
        : { targetType: "STOREFRONT", logoPosition },
    )
      .then(async (created) => {
        const url = absoluteShareUrl(created.sharePath, locale);
        const qr = await QRCode.toDataURL(url, {
          width: 640,
          margin: 2,
          errorCorrectionLevel: "H",
          color: { dark: "#17112eff", light: "#ffffffff" },
        });
        if (!active) return;
        setAvailableLogoUrl(created.storeLogoUrl ?? "");
        setShare(created);
        setQrDataUrl(qr);
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : t("分享链接生成失败，请稍后重试。"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [logoPosition, open, target, locale, t]);

  const handleCopy = async () => {
    if (!shareUrl) return;
    try {
      await copyText(shareUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setError(t("无法复制链接，请手动选择链接复制。"));
    }
  };

  const handleDownload = async () => {
    if (!share || !shareUrl || !qrDataUrl || downloading) return;
    setDownloading(true);
    setError("");
    try {
      await downloadShareCard(share, qrDataUrl, backgroundMode === "image" ? backgroundImageUrl : undefined);
    } catch {
      setError(t("分享名片生成失败，请稍后重试。"));
    } finally {
      setDownloading(false);
    }
  };

  const handleBackgroundFile = (file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("请选择图片文件作为名片背景。");
      return;
    }
    setBackgroundImageUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return URL.createObjectURL(file);
    });
    setBackgroundMode("image");
    setError("");
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content className="core-catalog-share-dialog" maxWidth="900px">
        <div className="core-dialog-heading">
          <div>
            <Text size="1" color="gray">{t("商品前台")}</Text>
            <Dialog.Title>
              {target?.type === "STOREFRONT"
                ? `${t("商品前台")} · ${t("分享链接")}`
                : t(target?.type === "CATEGORY" ? "分享分类" : "分享商品")}
            </Dialog.Title>
            <Dialog.Description>
              {target?.type === "STOREFRONT"
                ? "二维码和链接会展示当前商家前台的全部商品。"
                : t("二维码和链接只展示本次选择的商品。")}
            </Dialog.Description>
          </div>
          <Button variant="ghost" color="gray" onClick={() => onOpenChange(false)} aria-label={t("关闭")}>
            <X />
          </Button>
        </div>

        {loading ? (
          <div className="core-catalog-share-loading" role="status">
            <Spinner size="3" />
            <Text>{t("正在生成专属分享链接…")}</Text>
          </div>
        ) : null}

        {error ? <ToastNotice kind="error" message={error} /> : null}

        {availableLogoUrl ? (
        <section className="core-catalog-share-branding" aria-labelledby="catalog-share-branding-title">
          <div>
            <Text id="catalog-share-branding-title" size="2" weight="bold">{t("名片 Logo")}</Text>
            <Text size="1" color="gray">
              {availableLogoUrl
                ? t("选择本次分享名片是否展示 Logo，以及 Logo 的位置。")
                : t("当前未上传商家 Logo，可在账户与商家资料中上传。")}
            </Text>
          </div>
          <div className="core-catalog-share-logo-options" role="radiogroup" aria-label={t("名片 Logo 位置")}>
            {([
              ["NONE", t("不带 Logo")],
              ["TOP_LEFT", t("左上角")],
              ["TOP_RIGHT", t("右上角")],
            ] as Array<[CatalogShareLogoPosition, string]>).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={logoPosition === value ? "is-selected" : ""}
                role="radio"
                aria-checked={logoPosition === value}
                disabled={loading || (value !== "NONE" && !availableLogoUrl)}
                onClick={() => setLogoPosition(value)}
              >
                <span className={`core-catalog-share-logo-option-preview is-${value.toLowerCase().replace("_", "-")}`}>
                  {value !== "NONE" ? <i /> : null}
                </span>
                {label}
              </button>
            ))}
          </div>
        </section>
        ) : null}

        {share ? (
          <section className="core-catalog-share-background" aria-labelledby="catalog-share-background-title">
            <div>
              <Text id="catalog-share-background-title" size="2" weight="bold">名片背景</Text>
              <Text size="1" color="gray">建议使用 4:5 图片（例如 1080×1350），图片会按比例裁切并置于底层，不遮挡商家名和二维码。</Text>
            </div>
            <div className="core-catalog-share-background-actions">
              <label className={`core-catalog-share-background-option${backgroundMode === "color" ? " is-selected" : ""}`}>
                <input type="radio" name="catalog-share-background" checked={backgroundMode === "color"} onChange={() => setBackgroundMode("color")} />
                <span>色彩背景</span>
              </label>
              <label className={`core-catalog-share-background-option${backgroundMode === "image" ? " is-selected" : ""}`}>
                <input type="radio" name="catalog-share-background" checked={backgroundMode === "image"} onChange={() => setBackgroundMode("image")} />
                <span>上传图片</span>
              </label>
              <label className="core-catalog-share-background-upload">
                <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => handleBackgroundFile(event.target.files?.[0])} />
                {backgroundImageUrl ? "更换背景图" : t("上传图片")}
              </label>
              {backgroundImageUrl ? <Button size="1" variant="ghost" color="gray" onClick={() => { URL.revokeObjectURL(backgroundImageUrl); setBackgroundImageUrl(""); setBackgroundMode("color"); }}>清除</Button> : null}
            </div>
          </section>
        ) : null}

        {share && qrDataUrl ? (
          <div className="core-catalog-share-layout">
            <section
              className={`core-catalog-share-card${backgroundMode === "image" && backgroundImageUrl ? " has-background-image" : ""}`}
              style={backgroundMode === "image" && backgroundImageUrl ? { backgroundImage: `url("${backgroundImageUrl}")` } : undefined}
              aria-label={t("二维码分享名片预览")}
            >
              {share.logoPosition !== "NONE" && share.storeLogoUrl ? (
                <div className={`core-catalog-share-logo is-${share.logoPosition.toLowerCase().replace("_", "-")}`}>
                  <img src={share.storeLogoUrl} alt={t("{store} Logo", { store: share.storeName })} />
                </div>
              ) : null}
              <div className={`core-catalog-share-merchant${share.logoPosition === "TOP_RIGHT" && share.storeLogoUrl ? " has-top-right-logo" : ""}${share.logoPosition === "TOP_LEFT" && share.storeLogoUrl ? " has-top-left-logo" : ""}`}>
                <strong>{share.storeName}</strong>
                {share.storeSubtitle ? <span>{share.storeSubtitle}</span> : null}
              </div>
              <div className="core-catalog-share-qr"><img src={qrDataUrl} alt={t("商品分享二维码")} /></div>
            </section>

            <section className="core-catalog-share-actions">
              <div>
                <Text size="1" color="gray">{t("分享内容")}</Text>
                <Text size="5" weight="bold" as="div">{share.targetType === "PRODUCTS" && share.itemCount > 1 ? t("{count} 件商品精选", { count: share.itemCount }) : share.targetType === "STOREFRONT" ? t("商品前台") : share.title}</Text>
                <Text size="2" color="gray">{t("共 {count} 件商品", { count: share.itemCount })}</Text>
              </div>
              <label className="core-catalog-share-link">
                <span><LinkSimple />{t("分享链接")}</span>
                <input value={shareUrl} readOnly onFocus={(event) => event.currentTarget.select()} />
              </label>
              <div className="core-catalog-share-action-row">
                <Button onClick={() => void handleCopy()}>{copied ? <Check /> : <Copy />}{copied ? t("已复制") : t("复制链接")}</Button>
                <Button variant="soft" onClick={() => window.open(shareUrl, "_blank", "noopener,noreferrer")}><ArrowSquareOut />{t("打开预览")}</Button>
                <Button variant="soft" color="amber" loading={downloading} onClick={() => void handleDownload()}><DownloadSimple />{t("下载二维码名片")}</Button>
              </div>
            </section>
          </div>
        ) : null}
      </Dialog.Content>
    </Dialog.Root>
  );
}
