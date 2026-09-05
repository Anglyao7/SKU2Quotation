import type { StorefrontLocale } from "../types";
import type { PackingListItem, PackingListSettings, PublicQuoteDraft, PublicQuoteDraftItem } from "./types";

const labels: Record<StorefrontLocale, string[]> = {
  "zh-CN": ["装箱单", "货号", "13位编码", "箱数", "名称", "总数量", "每箱件数", "尾箱毛重（kg）", "按订单自动计算", "缺少包装资料", "补填后自动计算", "装箱资料", "恢复自动箱数", "数字必须有效且不能为负数；箱数必须为正整数。", "编码应为空或13位数字。", "箱数不足以容纳订单数量。", "装箱尺寸请填写完整的长、宽、高。", "已按整箱毛重估算尾箱，可填写实际尾箱毛重。"],
  "en-US": ["PACKING LIST", "Article No.", "13-digit code", "Cartons", "Name", "Total quantity", "Units per carton", "Last carton gross weight (kg)", "Calculated from order", "Missing packing details", "Calculated once completed", "Packing details", "Use automatic carton count", "Enter valid non-negative numbers; cartons must be a positive integer.", "Leave the code blank or enter 13 digits.", "Cartons cannot hold the ordered quantity.", "Enter all three carton dimensions.", "The last carton uses a full-carton weight estimate. Enter its actual weight if available."],
  es: ["LISTA DE EMPAQUE", "N.º de artículo", "Código de 13 dígitos", "Cajas", "Nombre", "Cantidad total", "Unidades por caja", "Peso bruto de última caja (kg)", "Calculado del pedido", "Faltan datos de embalaje", "Se calculará al completar", "Datos de embalaje", "Usar número automático de cajas", "Introduzca números válidos no negativos; las cajas deben ser un entero positivo.", "Deje el código vacío o introduzca 13 dígitos.", "Las cajas no admiten la cantidad pedida.", "Complete las tres dimensiones.", "La última caja usa el peso estimado de una caja completa; indique el peso real si lo conoce."],
  tr: ["ÇEKİ LİSTESİ", "Ürün no.", "13 haneli kod", "Koli sayısı", "Ad", "Toplam miktar", "Koli başına adet", "Son koli brüt ağırlığı (kg)", "Siparişten hesaplanır", "Eksik ambalaj bilgileri", "Tamamlanınca hesaplanır", "Ambalaj bilgileri", "Otomatik koli sayısını kullan", "Geçerli, negatif olmayan sayılar girin; koli sayısı pozitif tam sayı olmalıdır.", "Kodu boş bırakın veya 13 rakam girin.", "Koliler sipariş miktarı için yetersiz.", "Üç koli ölçüsünü de girin.", "Son koli için tam koli ağırlığı tahmin edilir; biliniyorsa gerçek ağırlığı girin."],
  ar: ["قائمة التعبئة", "رقم الصنف", "رمز من 13 رقمًا", "عدد الكراتين", "الاسم", "الكمية الإجمالية", "وحدات لكل كرتون", "وزن آخر كرتون الإجمالي (كغ)", "محسوب من الطلب", "بيانات تعبئة ناقصة", "يُحسب بعد استكمال البيانات", "بيانات التعبئة", "استخدام العدد التلقائي للكراتين", "أدخل أرقامًا صالحة غير سالبة؛ يجب أن يكون عدد الكراتين عددًا صحيحًا موجبًا.", "اترك الرمز فارغًا أو أدخل 13 رقمًا.", "الكراتين لا تستوعب كمية الطلب.", "أدخل أبعاد الكرتون الثلاثة.", "يُقدّر وزن آخر كرتون بوزن كرتون كامل؛ أدخل الوزن الفعلي إن توفر."],
  ja: ["梱包明細書", "品番", "13桁コード", "箱数", "名称", "総数量", "入数", "最終箱の総重量（kg）", "注文から自動計算", "梱包情報が不足", "入力後に自動計算", "梱包情報", "箱数を自動計算に戻す", "有効な非負数を入力してください。箱数は正の整数です。", "コードは空欄または13桁の数字にしてください。", "注文数量に対して箱数が不足しています。", "縦・横・高さをすべて入力してください。", "最終箱は満箱の重量で推定しています。実際の重量が分かる場合は入力してください。"],
  ko: ["포장 명세서", "품번", "13자리 코드", "상자 수", "명칭", "총수량", "상자당 수량", "마지막 상자 총중량 (kg)", "주문에서 자동 계산", "포장 정보 누락", "입력 후 자동 계산", "포장 정보", "자동 상자 수 사용", "유효한 0 이상의 숫자를 입력하세요. 상자 수는 양의 정수여야 합니다.", "코드를 비워 두거나 13자리 숫자를 입력하세요.", "주문 수량에 비해 상자가 부족합니다.", "상자의 길이, 너비, 높이를 모두 입력하세요.", "마지막 상자는 가득 찬 상자 무게로 추정합니다. 실제 무게를 알면 입력하세요."],
  pt: ["LISTA DE EMBALAGEM", "N.º do artigo", "Código de 13 dígitos", "Caixas", "Nome", "Quantidade total", "Unidades por caixa", "Peso bruto da última caixa (kg)", "Calculado pelo pedido", "Faltam dados de embalagem", "Calculado após preencher", "Dados de embalagem", "Usar quantidade automática de caixas", "Insira números válidos não negativos; caixas devem ser um inteiro positivo.", "Deixe o código vazio ou insira 13 dígitos.", "As caixas não comportam a quantidade pedida.", "Preencha as três dimensões.", "A última caixa usa o peso estimado de uma caixa cheia; informe o peso real, se disponível."],
  fr: ["LISTE DE COLISAGE", "Réf. article", "Code à 13 chiffres", "Colis", "Nom", "Quantité totale", "Unités par colis", "Poids brut du dernier colis (kg)", "Calculé selon la commande", "Données de colisage manquantes", "Calculé après saisie", "Données de colisage", "Calcul automatique des colis", "Saisissez des nombres valides non négatifs ; le nombre de colis doit être un entier positif.", "Laissez le code vide ou saisissez 13 chiffres.", "Les colis ne peuvent pas contenir la quantité commandée.", "Saisissez les trois dimensions du colis.", "Le dernier colis utilise le poids estimé d’un colis plein ; saisissez son poids réel si connu."],
  fa: ["فهرست بسته‌بندی", "شماره کالا", "کد ۱۳ رقمی", "تعداد کارتن", "نام", "تعداد کل", "تعداد در هر کارتن", "وزن ناخالص آخرین کارتن (کیلوگرم)", "محاسبه از سفارش", "اطلاعات بسته‌بندی ناقص", "محاسبه پس از تکمیل", "اطلاعات بسته‌بندی", "استفاده از تعداد خودکار کارتن", "اعداد معتبر نامنفی وارد کنید؛ تعداد کارتن باید عدد صحیح مثبت باشد.", "کد را خالی بگذارید یا ۱۳ رقم وارد کنید.", "کارتن‌ها برای تعداد سفارش کافی نیستند.", "هر سه بعد کارتن را وارد کنید.", "وزن آخرین کارتن برابر کارتن پر تخمین زده می‌شود؛ در صورت اطلاع وزن واقعی را وارد کنید."],
};
export function packingText(locale: StorefrontLocale, index: number) { return labels[locale]?.[index] ?? labels["en-US"][index]; }
export function packingNumber(value: string, zero = false): number | null {
  if (!/^\d+(?:\.\d*)?$/.test(value.trim())) return null;
  const result = Number(value);
  return Number.isFinite(result) && (zero ? result >= 0 : result > 0) ? result : null;
}
export function packingCalculation(row: PackingListItem, order: PublicQuoteDraftItem) {
  const packing = packingNumber(row.packingQuantity);
  const lengths = [row.cartonLength, row.cartonWidth, row.cartonHeight].map((value) => packingNumber(value));
  const volume = lengths.every((value) => value !== null) ? lengths.reduce<number>((product, value) => product * value!, 1) / 1_000_000 : packingNumber(row.cartonVolume);
  const automaticCartons = packing ? Math.ceil(order.quantity / packing - 1e-10) : null;
  const cartons = row.cartonCount.trim() ? packingNumber(row.cartonCount) : automaticCartons;
  const gross = packingNumber(row.grossWeight, true);
  const lastGross = packingNumber(row.lastCartonGrossWeight, true);
  return { packing, volume, cartons, automaticCartons, gross, quantity: order.quantity, partial: Boolean(packing && automaticCartons && packing * automaticCartons > order.quantity + 1e-8), totalVolume: volume !== null && cartons !== null ? volume * cartons : null, totalGrossWeight: gross !== null && cartons !== null ? gross * (cartons - (lastGross === null ? 0 : 1)) + (lastGross ?? 0) : null };
}
export function packingErrors(settings: PackingListSettings, orders: PublicQuoteDraftItem[], locale: StorefrontLocale): string[] {
  const errors: string[] = [];
  if (!settings.packingListNumber.trim() || !/^\d{4}-\d{2}-\d{2}$/.test(settings.issueDate)) errors.push(`${packingText(locale, 0)}: ID / Date`);
  for (const row of settings.items) {
    const order = orders.find((item) => item.id === row.itemId);
    if (!order) continue;
    const prefix = `${row.articleNumber || order.skuCode}: `;
    if (row.barcode.trim() && !/^\d{13}$/.test(row.barcode.trim())) errors.push(prefix + packingText(locale, 14));
    const positive = [row.packingQuantity, row.cartonLength, row.cartonWidth, row.cartonHeight, row.cartonVolume];
    if (positive.some((value) => value.trim() && packingNumber(value) === null)
      || [row.grossWeight, row.lastCartonGrossWeight].some((value) => value.trim() && packingNumber(value, true) === null)
      || (row.cartonCount.trim() && (!Number.isInteger(Number(row.cartonCount)) || packingNumber(row.cartonCount) === null))) errors.push(prefix + packingText(locale, 13));
    const dimensions = [row.cartonLength, row.cartonWidth, row.cartonHeight].filter((value) => value.trim()).length;
    if (dimensions > 0 && dimensions < 3) errors.push(prefix + packingText(locale, 16));
    const calc = packingCalculation(row, order);
    if (calc.packing && calc.cartons && calc.cartons * calc.packing + 1e-8 < order.quantity) errors.push(prefix + packingText(locale, 15));
  }
  return errors;
}
export function packingFormat(value: number | null) { return value === null ? "—" : Number(value.toFixed(6)).toLocaleString("en-US", { maximumFractionDigits: 6 }); }

const studioLabels: Record<StorefrontLocale, [string, string, string, string]> = {
  "zh-CN": ["单证设置", "卖方资料", "买方资料", "实时预览"],
  "en-US": ["Document settings", "Seller details", "Buyer details", "Live preview"],
  es: ["Ajustes del documento", "Datos del vendedor", "Datos del comprador", "Vista previa en vivo"],
  tr: ["Belge ayarları", "Satıcı bilgileri", "Alıcı bilgileri", "Canlı önizleme"],
  ar: ["إعدادات المستند", "بيانات البائع", "بيانات المشتري", "معاينة مباشرة"],
  ja: ["書類設定", "売主情報", "買主情報", "リアルタイムプレビュー"],
  ko: ["문서 설정", "판매자 정보", "구매자 정보", "실시간 미리보기"],
  pt: ["Configurações do documento", "Dados do vendedor", "Dados do comprador", "Prévia em tempo real"],
  fr: ["Paramètres du document", "Coordonnées du vendeur", "Coordonnées de l’acheteur", "Aperçu en direct"],
  fa: ["تنظیمات سند", "اطلاعات فروشنده", "اطلاعات خریدار", "پیش‌نمایش زنده"],
};
export function packingStudioText(locale: StorefrontLocale, index: number) { return studioLabels[locale]?.[index] ?? studioLabels["en-US"][index]; }

export function packingParties(value: PackingListSettings, draft: PublicQuoteDraft, sellerName: string) {
  return {
    seller: { name: value.sellerName ?? sellerName, contact: value.sellerContact ?? "", phone: value.sellerPhone ?? "", email: value.sellerEmail ?? "", address: value.sellerAddress },
    buyer: { name: value.buyerName ?? (draft.customerCompany || draft.customerName), contact: value.buyerContact ?? draft.customerName, phone: value.buyerPhone ?? draft.customerPhone ?? "", email: value.buyerEmail ?? draft.customerEmail ?? "", address: value.buyerAddress },
  };
}
