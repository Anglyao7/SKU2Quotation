import type { CSSProperties } from "react";
import { FileXls } from "@phosphor-icons/react";
import { excelCellText, excelSheetWidth, type DocumentExcelSheet } from "../documentExcelPreview";
import "./DocumentExcelPreview.css";

export function DocumentExcelPreview({ sheet, scale, accent = "#087F5B" }: { sheet: DocumentExcelSheet; scale: number; accent?: string }) {
  return <div className="document-excel" style={{ width: excelSheetWidth(sheet), zoom: scale, "--sheet-accent": accent } as CSSProperties} dir={sheet.rtl ? "rtl" : "ltr"}>
    <table aria-label={`Excel · ${sheet.name}`}>
      <colgroup><col style={{ width: 42 }} />{sheet.columns.map((width, index) => <col key={index} style={{ width: width * 7 + 5 }} />)}</colgroup>
      <thead><tr><th aria-label="#" />{sheet.columns.map((_, index) => <th scope="col" key={index}>{String.fromCharCode(65 + index)}</th>)}</tr></thead>
      <tbody>{sheet.rows.map((row, index) => <tr key={index} className={`document-excel-row--${row.kind}`} style={row.height ? { height: row.height } : undefined}>
        <th scope="row" className="document-excel-row-number">{index + 1}</th>
        {row.cells.map((cell, cellIndex) => <td key={cellIndex} colSpan={cell.span} className={[cell.label ? "is-label" : "", typeof cell.value === "number" ? "is-number" : ""].filter(Boolean).join(" ")}>
          {cell.imageUrl ? <img src={cell.imageUrl} alt={cell.imageAlt ?? ""} loading="lazy" /> : excelCellText(cell)}
        </td>)}
      </tr>)}</tbody>
    </table>
    <div className="document-excel-sheet-tab"><FileXls size={18} /><span>{sheet.name}</span></div>
  </div>;
}
