import { FilePdf, FileXls } from "@phosphor-icons/react";
import { useLocale } from "../LocaleContext";
import type { DocumentPreviewMode } from "../documentExcelPreview";
import "./DocumentExcelPreview.css";

export function DocumentPreviewModeSwitch({ value, onChange }: { value: DocumentPreviewMode; onChange: (value: DocumentPreviewMode) => void }) {
  const { t } = useLocale();
  return <div className="document-preview-mode-switch" role="group" aria-label={t("预览格式")}>
    <button type="button" aria-pressed={value === "pdf"} onClick={() => onChange("pdf")}><FilePdf size={17} />PDF</button>
    <button type="button" aria-pressed={value === "excel"} onClick={() => onChange("excel")}><FileXls size={17} />Excel</button>
  </div>;
}
