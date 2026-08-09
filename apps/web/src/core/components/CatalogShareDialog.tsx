import { Button, Callout, Dialog, Spinner, Text } from "@radix-ui/themes";
import {
  ArrowSquareOut,
  Check,
  Copy,
  DownloadSimple,
  LinkSimple,
  QrCode,
  ShareNetwork,
  X,
} from "@phosphor-icons/react";
import QRCode from "qrcode";
import { useEffect, useMemo, useState } from "react";

import { createCatalogShare } from "../api";
import { useLocale } from "../LocaleContext";
import type { CatalogShare } from "../types";

export type CatalogShareTarget =
  | { type: "PRODUCTS"; skuIds: string[] }
  | { type: "CATEGORY"; categoryId: string; categoryName: string };

interface CatalogShareDialogProps {
  open: boolean;
  target?: CatalogShareTarget;
  onOpenChange: (open: boolean) => void;
}

function absoluteShareUrl(path: string) {
  return new URL(path, window.location.origin).toString();
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

async function downloadShareCard(
  share: CatalogShare,
  shareUrl: string,
  qrDataUrl: string,
) {
  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = 1440;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas is unavailable");

  const background = context.createLinearGradient(0, 0, 1080, 1440);
  background.addColorStop(0, "#17112e");
  background.addColorStop(0.55, "#2d1b69");
  background.addColorStop(1, "#12101d");
  context.fillStyle = background;
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.strokeStyle = "rgba(212, 175, 55, 0.78)";
  context.lineWidth = 3;
  context.strokeRect(54, 54, 972, 1332);
  context.fillStyle = "rgba(255, 255, 255, 0.08)";
  context.fillRect(92, 112, 896, 1216);

  context.textAlign = "center";
  context.fillStyle = "#d4af37";
  context.font = '600 30px "Noto Sans SC", sans-serif';
  context.fillText("智贸云 · 商品分享", 540, 205);
  context.fillStyle = "#ffffff";
  context.font = '700 56px "Noto Serif SC", serif';
  context.fillText(fitCanvasText(context, share.storeName, 820), 540, 302);
  context.fillStyle = "rgba(255,255,255,.78)";
  context.font = '400 34px "Noto Sans SC", sans-serif';
  context.fillText(fitCanvasText(context, share.title, 820), 540, 372);

  context.fillStyle = "#ffffff";
  context.fillRect(226, 454, 628, 628);
  const qrImage = await imageFromUrl(qrDataUrl);
  context.drawImage(qrImage, 248, 476, 584, 584);

  context.fillStyle = "#d4af37";
  context.font = '600 30px "Noto Sans SC", sans-serif';
  context.fillText(`${share.itemCount} 件商品`, 540, 1162);
  context.fillStyle = "rgba(255,255,255,.9)";
  context.font = '500 30px "Noto Sans SC", sans-serif';
  context.fillText("扫码查看商家精选商品", 540, 1220);
  context.fillStyle = "rgba(255,255,255,.5)";
  context.font = '400 21px "Noto Sans SC", sans-serif';
  context.fillText(fitCanvasText(context, shareUrl, 820), 540, 1278);

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("Unable to create share card");
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${share.storeName}-${share.title}-分享名片.png`.replace(/[\\/:*?"<>|]/g, "-");
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
  const { t } = useLocale();
  const [share, setShare] = useState<CatalogShare>();
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const shareUrl = useMemo(
    () => (share ? absoluteShareUrl(share.sharePath) : ""),
    [share],
  );

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
        ? { targetType: "PRODUCTS", skuIds: target.skuIds }
        : { targetType: "CATEGORY", categoryId: target.categoryId },
    )
      .then(async (created) => {
        const url = absoluteShareUrl(created.sharePath);
        const qr = await QRCode.toDataURL(url, {
          width: 640,
          margin: 2,
          errorCorrectionLevel: "H",
          color: { dark: "#17112eff", light: "#ffffffff" },
        });
        if (!active) return;
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
  }, [open, target, t]);

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
      await downloadShareCard(share, shareUrl, qrDataUrl);
    } catch {
      setError(t("分享名片生成失败，请稍后重试。"));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content className="core-catalog-share-dialog" maxWidth="900px">
        <div className="core-dialog-heading">
          <div>
            <Text size="1" color="gray">{t("商品前台")}</Text>
            <Dialog.Title>{t("分享商品")}</Dialog.Title>
            <Dialog.Description>{t("复制专属链接，或下载带商家信息的二维码名片。")}</Dialog.Description>
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

        {error ? (
          <Callout.Root color="red" role="alert">
            <Callout.Icon><ShareNetwork /></Callout.Icon>
            <Callout.Text>{error}</Callout.Text>
          </Callout.Root>
        ) : null}

        {share && qrDataUrl ? (
          <div className="core-catalog-share-layout">
            <section className="core-catalog-share-card" aria-label={t("二维码分享名片预览")}>
              <div className="core-catalog-share-brand">
                {share.storeLogoUrl ? <img src={share.storeLogoUrl} alt="" /> : <span><QrCode weight="duotone" /></span>}
                <div>
                  <small>{t("商品分享名片")}</small>
                  <strong>{share.storeName}</strong>
                </div>
              </div>
              <div className="core-catalog-share-qr"><img src={qrDataUrl} alt={t("商品分享二维码")} /></div>
              <div className="core-catalog-share-card-copy">
                <strong>{share.title}</strong>
                <span>{t("共 {count} 件商品", { count: share.itemCount })}</span>
                <small>{t("扫码查看商家精选商品")}</small>
              </div>
            </section>

            <section className="core-catalog-share-actions">
              <div>
                <Text size="1" color="gray">{t("分享范围")}</Text>
                <Text size="5" weight="bold" as="div">{share.title}</Text>
                <Text size="2" color="gray">{t("访客只能在本次分享范围内浏览商品。")}</Text>
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
