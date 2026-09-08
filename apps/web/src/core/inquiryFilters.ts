type InquiryRow = { quoteNumber: string; customerName: string; customerCompany?: string; visitorCountryCode?: string; createdAt: string; status: string };
type InquiryFilters = { query: string; status: string; from: string; to: string };

export function filterInquiries<T extends InquiryRow>(rows: T[], filters: InquiryFilters): T[] {
  const query = filters.query.trim().toLocaleLowerCase();
  return rows.filter((row) => {
    const text = [row.quoteNumber, row.customerName, row.customerCompany, row.visitorCountryCode].join(" ").toLocaleLowerCase();
    const created = new Date(row.createdAt);
    const date = Number.isNaN(created.getTime()) ? "" : [created.getFullYear(), String(created.getMonth() + 1).padStart(2, "0"), String(created.getDate()).padStart(2, "0")].join("-");
    return (!query || text.includes(query)) && (!filters.status || row.status === filters.status)
      && (!(filters.from || filters.to) || Boolean(date))
      && (!filters.from || date >= filters.from) && (!filters.to || date <= filters.to);
  });
}

export function paginateInquiries<T>(rows: T[], page: number, pageSize: number) {
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.max(1, Math.min(page, pages));
  return { pages, currentPage, pageRows: rows.slice((currentPage - 1) * pageSize, currentPage * pageSize) };
}
