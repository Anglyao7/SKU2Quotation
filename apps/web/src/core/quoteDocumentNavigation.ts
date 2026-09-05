const documentTabs = ["quotation", "proforma", "sales-contract", "commercial-invoice", "packing-list", "customs-declaration"] as const;
export type QuoteDocumentTab = typeof documentTabs[number];

export function quoteDocumentTab(search: URLSearchParams): QuoteDocumentTab {
  const value = search.get("document");
  return documentTabs.find((tab) => tab === value) ?? "quotation";
}

export function quoteDocumentSearch(search: URLSearchParams, document: QuoteDocumentTab): URLSearchParams {
  const next = new URLSearchParams(search);
  next.set("document", document);
  return next;
}

export function quoteDocumentHref(draftId: string, document: QuoteDocumentTab): string {
  return `/console/quotes/${encodeURIComponent(draftId)}/workbench?${quoteDocumentSearch(new URLSearchParams(), document)}`;
}
