import { IconButton } from "@radix-ui/themes";
import { ImageSquare } from "@phosphor-icons/react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";
import { api } from "../lib/api";
import type {
  StoreImageSearchResponse,
  StorefrontLocale,
} from "../types";

const MAX_SOURCE_BYTES = 20 * 1024 * 1024;
const TARGET_PNG_BYTES = 2 * 1024 * 1024;
const MAX_IMAGE_EDGE = 1280;
const MAX_IMAGE_PIXELS = 1_800_000;

type DecodedImage = {
  source: CanvasImageSource;
  width: number;
  height: number;
  release: () => void;
};

async function decodeLocalImage(file: File): Promise<DecodedImage> {
  if (typeof createImageBitmap === "function") {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      return {
        source: bitmap,
        width: bitmap.width,
        height: bitmap.height,
        release: () => bitmap.close(),
      };
    } catch {
      // Safari versions without HEIC/createImageBitmap support can still decode via <img>.
    }
  }

  const objectUrl = URL.createObjectURL(file);
  const image = new Image();
  image.decoding = "async";
  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("image-decode-failed"));
      image.src = objectUrl;
    });
    return {
      source: image,
      width: image.naturalWidth,
      height: image.naturalHeight,
      release: () => URL.revokeObjectURL(objectUrl),
    };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}

function canvasToPng(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("png-encode-failed"));
    }, "image/png");
  });
}

function drawResizedImage(
  source: CanvasImageSource,
  width: number,
  height: number,
): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, width);
  canvas.height = Math.max(1, height);
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) throw new Error("canvas-unavailable");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas;
}

async function normalizeSearchImage(file: File): Promise<File> {
  if (!file.size || file.size > MAX_SOURCE_BYTES) {
    throw new Error("图片大小不能超过 20 MB。");
  }
  if (file.type && !file.type.toLowerCase().startsWith("image/")) {
    throw new Error("请选择 JPG、PNG、WebP 或 GIF 图片。");
  }

  let decoded: DecodedImage;
  try {
    decoded = await decodeLocalImage(file);
  } catch {
    throw new Error("图片搜索失败，请稍后重试。");
  }

  try {
    if (!decoded.width || !decoded.height) {
      throw new Error("图片搜索失败，请稍后重试。");
    }
    const initialScale = Math.min(
      1,
      MAX_IMAGE_EDGE / Math.max(decoded.width, decoded.height),
      Math.sqrt(MAX_IMAGE_PIXELS / (decoded.width * decoded.height)),
    );
    let canvas = drawResizedImage(
      decoded.source,
      Math.round(decoded.width * initialScale),
      Math.round(decoded.height * initialScale),
    );
    let png = await canvasToPng(canvas);

    for (let attempt = 0; png.size > TARGET_PNG_BYTES && attempt < 3; attempt += 1) {
      const scale = Math.max(
        0.62,
        Math.min(0.9, Math.sqrt(TARGET_PNG_BYTES / png.size) * 0.92),
      );
      const nextCanvas = drawResizedImage(
        canvas,
        Math.round(canvas.width * scale),
        Math.round(canvas.height * scale),
      );
      canvas.width = 1;
      canvas.height = 1;
      canvas = nextCanvas;
      png = await canvasToPng(canvas);
    }

    if (png.size > MAX_SOURCE_BYTES) {
      throw new Error("图片大小不能超过 20 MB。");
    }
    const basename = file.name.replace(/\.[^.]+$/, "").trim() || "image-search";
    return new File([png], `${basename}.png`, {
      type: "image/png",
      lastModified: Date.now(),
    });
  } finally {
    decoded.release();
  }
}

export type StorefrontImageSearchPhase = (
  "idle" | "preparing" | "searching" | "complete" | "error"
);

export interface StorefrontImageSearchState {
  phase: StorefrontImageSearchPhase;
  previewUrl: string;
  filename: string;
  result?: StoreImageSearchResponse;
  error?: string;
}

export interface StorefrontImageSearchHandle {
  openPicker: () => void;
}

export const StorefrontImageSearch = forwardRef<
  StorefrontImageSearchHandle,
  {
    tenantSlug: string;
    locale: StorefrontLocale;
    shareToken: string;
    active: boolean;
    t: (source: string, values?: Record<string, string | number>) => string;
    onStateChange: (state: StorefrontImageSearchState) => void;
  }
>(function StorefrontImageSearch({
  tenantSlug,
  locale,
  shareToken,
  active,
  t,
  onStateChange,
}, ref) {
  const inputRef = useRef<HTMLInputElement>(null);
  const requestSequence = useRef(0);
  const previewUrlRef = useRef("");

  const clearPreview = useCallback(() => {
    if (!previewUrlRef.current) return;
    URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = "";
  }, []);

  const openPicker = useCallback(() => {
    if (!inputRef.current) return;
    inputRef.current.value = "";
    inputRef.current.click();
  }, []);

  useImperativeHandle(ref, () => ({ openPicker }), [openPicker]);

  useEffect(() => {
    if (active) return;
    requestSequence.current += 1;
    clearPreview();
  }, [active, clearPreview]);

  useEffect(() => () => {
    requestSequence.current += 1;
    clearPreview();
  }, [clearPreview]);

  const searchFile = async (sourceFile: File) => {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    clearPreview();
    onStateChange({
      phase: "preparing",
      previewUrl: "",
      filename: sourceFile.name,
    });
    try {
      const file = await normalizeSearchImage(sourceFile);
      if (requestSequence.current !== sequence) return;
      const previewUrl = URL.createObjectURL(file);
      previewUrlRef.current = previewUrl;
      onStateChange({
        phase: "searching",
        previewUrl,
        filename: file.name,
      });
      const next = await api.searchStoreProductsByImage(
        tenantSlug,
        file,
        locale,
        shareToken || undefined,
      );
      if (requestSequence.current !== sequence) return;
      onStateChange({
        phase: "complete",
        previewUrl,
        filename: file.name,
        result: {
          ...next,
          results: [...next.results].sort((left, right) => (
            right.similarity - left.similarity
            || right.match_percent - left.match_percent
          )),
        },
      });
    } catch (reason) {
      if (requestSequence.current === sequence) {
        onStateChange({
          phase: "error",
          previewUrl: previewUrlRef.current,
          filename: sourceFile.name,
          error: reason instanceof Error
            ? t(reason.message)
            : t("图片搜索失败，请稍后重试。"),
        });
      }
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <>
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept="image/*"
        aria-label={t("选择图片")}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void searchFile(file);
        }}
      />
      <IconButton
        type="button"
        size="1"
        variant="ghost"
        color={active ? "jade" : "gray"}
        className={`store-image-search-button${active ? " is-active" : ""}`}
        aria-label={t("图片搜索")}
        aria-pressed={active}
        title={t("图片搜索")}
        onClick={openPicker}
      >
        <ImageSquare size={18} weight={active ? "fill" : "duotone"} />
      </IconButton>
    </>
  );
});
