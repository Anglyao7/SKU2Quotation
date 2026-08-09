"""Locale-aware labels and unit names used by public quotation documents."""

from __future__ import annotations

from typing import Final

from ..storefront_locales import normalize_storefront_locale


QUOTE_FIELD_LABEL_KEYS: Final[dict[str, str]] = {
    "serial_number": "serial_number",
    "sku_code": "sku_code",
    "product_name": "product_name",
    "description": "description",
    "specification": "specification",
    "category": "category",
    "tags": "tags",
    "product_image": "image",
    "quantity": "quantity",
    "unit_code": "unit",
    "packing_quantity": "packing_quantity",
    "carton_dimensions": "carton_dimensions",
    "gross_weight": "gross_weight",
    "carton_volume": "carton_volume",
    "unit_price": "unit_price",
    "line_total": "line_total",
    "total_volume": "total_volume",
    "total_gross_weight": "total_gross_weight",
    "currency": "currency",
    "quote_number": "quote_number",
    "quote_date": "quote_date",
    "customer_name": "customer",
    "customer_company": "company",
    "customer_email": "email",
    "customer_phone": "phone",
    "notes": "notes",
}


_STRINGS: Final[dict[str, dict[str, str]]] = {
    "zh-CN": {
        "document_title": "报价单",
        "merchant": "商家",
        "quote_number": "报价单号",
        "customer": "客户",
        "submitted_date": "提交日期",
        "company": "客户公司",
        "valid_until": "有效期",
        "email": "邮箱",
        "phone": "电话",
        "currency": "币种",
        "serial_number": "序号",
        "image": "图片",
        "sku_code": "SKU",
        "product_name": "商品名称",
        "description": "商品描述",
        "specification": "规格",
        "category": "分类",
        "tags": "标签",
        "quantity": "数量",
        "unit": "单位",
        "packing_quantity": "装箱数量",
        "carton_dimensions": "装箱尺寸",
        "gross_weight": "毛重(kg)",
        "carton_volume": "立方(m³)",
        "unit_price": "单价",
        "line_total": "总价",
        "total_volume": "总立方(m³)",
        "total_gross_weight": "总毛重(kg)",
        "total": "合计",
        "notes": "备注",
        "merchant_contact": "商家联系方式",
        "quote_date": "报价日期",
        "sheet_name": "报价单",
        "separator": "、",
    },
    "en-US": {
        "document_title": "QUOTATION",
        "merchant": "Merchant",
        "quote_number": "Quotation No.",
        "customer": "Customer",
        "submitted_date": "Submitted",
        "company": "Company",
        "valid_until": "Valid Until",
        "email": "Email",
        "phone": "Phone",
        "currency": "Currency",
        "serial_number": "No.",
        "image": "Image",
        "sku_code": "SKU",
        "product_name": "Product",
        "description": "Description",
        "specification": "Specification",
        "category": "Category",
        "tags": "Tags",
        "quantity": "Quantity",
        "unit": "Unit",
        "packing_quantity": "Units / Carton",
        "carton_dimensions": "Carton Size",
        "gross_weight": "Gross Weight (kg)",
        "carton_volume": "Volume (m³)",
        "unit_price": "Unit Price",
        "line_total": "Amount",
        "total_volume": "Total Volume (m³)",
        "total_gross_weight": "Total Gross Weight (kg)",
        "total": "Total",
        "notes": "Notes",
        "merchant_contact": "Merchant Contact",
        "quote_date": "Quotation Date",
        "sheet_name": "Quotation",
        "separator": ", ",
    },
    "es": {
        "document_title": "COTIZACIÓN",
        "merchant": "Vendedor",
        "quote_number": "N.º de cotización",
        "customer": "Cliente",
        "submitted_date": "Fecha de envío",
        "company": "Empresa",
        "valid_until": "Válida hasta",
        "email": "Correo electrónico",
        "phone": "Teléfono",
        "currency": "Moneda",
        "serial_number": "N.º",
        "image": "Imagen",
        "sku_code": "SKU",
        "product_name": "Producto",
        "description": "Descripción",
        "specification": "Especificación",
        "category": "Categoría",
        "tags": "Etiquetas",
        "quantity": "Cantidad",
        "unit": "Unidad",
        "packing_quantity": "Unidades / caja",
        "carton_dimensions": "Medidas de la caja",
        "gross_weight": "Peso bruto (kg)",
        "carton_volume": "Volumen (m³)",
        "unit_price": "Precio unitario",
        "line_total": "Importe",
        "total_volume": "Volumen total (m³)",
        "total_gross_weight": "Peso bruto total (kg)",
        "total": "Total",
        "notes": "Notas",
        "merchant_contact": "Contacto del vendedor",
        "quote_date": "Fecha de cotización",
        "sheet_name": "Cotización",
        "separator": ", ",
    },
    "tr": {
        "document_title": "FİYAT TEKLİFİ",
        "merchant": "Satıcı",
        "quote_number": "Teklif No.",
        "customer": "Müşteri",
        "submitted_date": "Gönderim tarihi",
        "company": "Şirket",
        "valid_until": "Geçerlilik tarihi",
        "email": "E-posta",
        "phone": "Telefon",
        "currency": "Para birimi",
        "serial_number": "No.",
        "image": "Görsel",
        "sku_code": "SKU",
        "product_name": "Ürün",
        "description": "Açıklama",
        "specification": "Özellik",
        "category": "Kategori",
        "tags": "Etiketler",
        "quantity": "Miktar",
        "unit": "Birim",
        "packing_quantity": "Koli adedi",
        "carton_dimensions": "Koli ölçüsü",
        "gross_weight": "Brüt ağırlık (kg)",
        "carton_volume": "Hacim (m³)",
        "unit_price": "Birim fiyat",
        "line_total": "Tutar",
        "total_volume": "Toplam hacim (m³)",
        "total_gross_weight": "Toplam brüt ağırlık (kg)",
        "total": "Toplam",
        "notes": "Notlar",
        "merchant_contact": "Satıcı iletişim",
        "quote_date": "Teklif tarihi",
        "sheet_name": "Fiyat Teklifi",
        "separator": ", ",
    },
    "ar": {
        "document_title": "عرض سعر",
        "merchant": "البائع",
        "quote_number": "رقم عرض السعر",
        "customer": "العميل",
        "submitted_date": "تاريخ التقديم",
        "company": "الشركة",
        "valid_until": "صالح حتى",
        "email": "البريد الإلكتروني",
        "phone": "الهاتف",
        "currency": "العملة",
        "serial_number": "الرقم",
        "image": "الصورة",
        "sku_code": "SKU",
        "product_name": "المنتج",
        "description": "الوصف",
        "specification": "المواصفات",
        "category": "الفئة",
        "tags": "الوسوم",
        "quantity": "الكمية",
        "unit": "الوحدة",
        "packing_quantity": "العدد في الكرتون",
        "carton_dimensions": "أبعاد الكرتون",
        "gross_weight": "الوزن الإجمالي (كجم)",
        "carton_volume": "الحجم (م³)",
        "unit_price": "سعر الوحدة",
        "line_total": "الإجمالي",
        "total_volume": "الحجم الكلي (م³)",
        "total_gross_weight": "الوزن الإجمالي الكلي (كجم)",
        "total": "المجموع",
        "notes": "ملاحظات",
        "merchant_contact": "بيانات البائع",
        "quote_date": "تاريخ عرض السعر",
        "sheet_name": "عرض سعر",
        "separator": "، ",
    },
    "ja": {
        "document_title": "見積書",
        "merchant": "販売者",
        "quote_number": "見積番号",
        "customer": "お客様",
        "submitted_date": "提出日",
        "company": "会社名",
        "valid_until": "有効期限",
        "email": "メール",
        "phone": "電話",
        "currency": "通貨",
        "serial_number": "番号",
        "image": "画像",
        "sku_code": "SKU",
        "product_name": "商品名",
        "description": "商品説明",
        "specification": "仕様",
        "category": "カテゴリー",
        "tags": "タグ",
        "quantity": "数量",
        "unit": "単位",
        "packing_quantity": "梱包数",
        "carton_dimensions": "梱包サイズ",
        "gross_weight": "総重量 (kg)",
        "carton_volume": "容積 (m³)",
        "unit_price": "単価",
        "line_total": "金額",
        "total_volume": "総容積 (m³)",
        "total_gross_weight": "総重量合計 (kg)",
        "total": "合計",
        "notes": "備考",
        "merchant_contact": "販売者連絡先",
        "quote_date": "見積日",
        "sheet_name": "見積書",
        "separator": "、",
    },
    "ko": {
        "document_title": "견적서",
        "merchant": "판매자",
        "quote_number": "견적 번호",
        "customer": "고객",
        "submitted_date": "제출일",
        "company": "회사",
        "valid_until": "유효 기간",
        "email": "이메일",
        "phone": "전화",
        "currency": "통화",
        "serial_number": "번호",
        "image": "이미지",
        "sku_code": "SKU",
        "product_name": "상품명",
        "description": "상품 설명",
        "specification": "규격",
        "category": "분류",
        "tags": "태그",
        "quantity": "수량",
        "unit": "단위",
        "packing_quantity": "포장 수량",
        "carton_dimensions": "포장 크기",
        "gross_weight": "총중량 (kg)",
        "carton_volume": "부피 (m³)",
        "unit_price": "단가",
        "line_total": "금액",
        "total_volume": "총부피 (m³)",
        "total_gross_weight": "총중량 합계 (kg)",
        "total": "합계",
        "notes": "비고",
        "merchant_contact": "판매자 연락처",
        "quote_date": "견적일",
        "sheet_name": "견적서",
        "separator": ", ",
    },
    "pt": {
        "document_title": "COTAÇÃO",
        "merchant": "Vendedor",
        "quote_number": "N.º da cotação",
        "customer": "Cliente",
        "submitted_date": "Data de envio",
        "company": "Empresa",
        "valid_until": "Válida até",
        "email": "E-mail",
        "phone": "Telefone",
        "currency": "Moeda",
        "serial_number": "N.º",
        "image": "Imagem",
        "sku_code": "SKU",
        "product_name": "Produto",
        "description": "Descrição",
        "specification": "Especificação",
        "category": "Categoria",
        "tags": "Etiquetas",
        "quantity": "Quantidade",
        "unit": "Unidade",
        "packing_quantity": "Unidades / caixa",
        "carton_dimensions": "Dimensões da caixa",
        "gross_weight": "Peso bruto (kg)",
        "carton_volume": "Volume (m³)",
        "unit_price": "Preço unitário",
        "line_total": "Valor total",
        "total_volume": "Volume total (m³)",
        "total_gross_weight": "Peso bruto total (kg)",
        "total": "Total",
        "notes": "Observações",
        "merchant_contact": "Contato do vendedor",
        "quote_date": "Data da cotação",
        "sheet_name": "Cotação",
        "separator": ", ",
    },
}


_UNIT_TRANSLATIONS: Final[dict[str, dict[str, str]]] = {
    "piece": {
        "zh-CN": "件", "en-US": "pcs", "es": "uds.", "tr": "adet",
        "ar": "قطعة", "ja": "個", "ko": "개", "pt": "un.",
    },
    "set": {
        "zh-CN": "套", "en-US": "sets", "es": "juegos", "tr": "set",
        "ar": "طقم", "ja": "セット", "ko": "세트", "pt": "conj.",
    },
    "pair": {
        "zh-CN": "对", "en-US": "pairs", "es": "pares", "tr": "çift",
        "ar": "زوج", "ja": "組", "ko": "쌍", "pt": "pares",
    },
    "box": {
        "zh-CN": "盒", "en-US": "boxes", "es": "cajas", "tr": "kutu",
        "ar": "علبة", "ja": "箱", "ko": "상자", "pt": "caixas",
    },
    "carton": {
        "zh-CN": "箱", "en-US": "cartons", "es": "cartones", "tr": "koli",
        "ar": "كرتون", "ja": "カートン", "ko": "카톤", "pt": "caixas",
    },
}


_UNIT_ALIASES: Final[dict[str, str]] = {
    "pc": "piece", "pcs": "piece", "piece": "piece", "pieces": "piece",
    "unit": "piece", "units": "piece", "个": "piece", "件": "piece",
    "set": "set", "sets": "set", "套": "set",
    "pair": "pair", "pairs": "pair", "对": "pair",
    "box": "box", "boxes": "box", "盒": "box",
    "carton": "carton", "cartons": "carton", "ctn": "carton", "箱": "carton",
}


def quote_locale(value: str | None) -> str:
    return normalize_storefront_locale(value) or "zh-CN"


def quote_text(locale: str | None, key: str) -> str:
    normalized = quote_locale(locale)
    return _STRINGS.get(normalized, _STRINGS["zh-CN"]).get(
        key,
        _STRINGS["zh-CN"].get(key, key),
    )


def quote_field_label(locale: str | None, field: str) -> str:
    return quote_text(locale, QUOTE_FIELD_LABEL_KEYS.get(field, field))


def quote_label_aliases(key: str) -> set[str]:
    return {
        strings.get(key, "").strip()
        for strings in _STRINGS.values()
        if strings.get(key, "").strip()
    }


def localize_known_quote_template_label(value: str, locale: str | None) -> str:
    """Translate recognized system labels without rewriting merchant prose."""

    target_locale = quote_locale(locale)
    label_keys = {
        "document_title",
        "merchant",
        "quote_number",
        "customer",
        "submitted_date",
        "company",
        "valid_until",
        "email",
        "phone",
        "currency",
        "total",
        "notes",
        "quote_date",
        *QUOTE_FIELD_LABEL_KEYS.values(),
    }
    stripped = value.strip()
    if stripped in {"报价单 / QUOTATION", "QUOTATION / 报价单"}:
        return value.replace(stripped, quote_text(target_locale, "document_title"), 1)
    for key in label_keys:
        target = quote_text(target_locale, key)
        source_labels = quote_label_aliases(key)
        if stripped in source_labels:
            return value.replace(stripped, target, 1)
        if "{{" in stripped:
            for source_label in sorted(source_labels, key=len, reverse=True):
                if stripped.startswith(source_label):
                    suffix = stripped[len(source_label):]
                    return value.replace(stripped, f"{target}{suffix}", 1)
    return value


def quote_headers(locale: str | None) -> tuple[str, ...]:
    return tuple(
        quote_field_label(locale, field)
        for field in (
            "serial_number",
            "product_image",
            "sku_code",
            "product_name",
            "quantity",
            "unit_code",
            "packing_quantity",
            "carton_dimensions",
            "gross_weight",
            "carton_volume",
            "unit_price",
            "line_total",
            "total_volume",
            "total_gross_weight",
        )
    )


def localize_quote_unit(locale: str | None, unit_code: str | None) -> str:
    raw = str(unit_code or "piece").strip() or "piece"
    canonical = _UNIT_ALIASES.get(raw.casefold())
    if canonical is None:
        return raw
    normalized_locale = quote_locale(locale)
    return _UNIT_TRANSLATIONS[canonical].get(normalized_locale, raw)


def quote_is_rtl(locale: str | None) -> bool:
    return quote_locale(locale) == "ar"
