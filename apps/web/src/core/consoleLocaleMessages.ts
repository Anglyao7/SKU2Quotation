import type { UiLocale } from "./types";
import arGenerated from "./locales/console.ar.json";
import esGenerated from "./locales/console.es.json";
import faGenerated from "./locales/console.fa.json";
import frGenerated from "./locales/console.fr.json";
import jaGenerated from "./locales/console.ja.json";
import koGenerated from "./locales/console.ko.json";
import ptGenerated from "./locales/console.pt.json";
import ruGenerated from "./locales/console.ru.json";
import trGenerated from "./locales/console.tr.json";

type ConsoleDictionary = Record<string, string>;

const en: ConsoleDictionary = {
  "子账号价格显示为 0": "Show subaccount prices as 0",
  "开启后，不受主账号价格变动影响。": "When enabled, changes to the main account price will not affect it.",
  "价格已隐藏（显示为 0）": "Prices hidden (shown as 0)",
  "价格为 0": "Prices are 0",
  "子账号前台已隐藏价格": "Prices are hidden on the subaccount storefront",
  "报价单商品": "Quotation items",
  "报价单中暂无商品": "No products in this quotation",
  "从报价单移除商品": "Remove product from quotation",
  "从当前账号可见的已发布 SKU 中选择": "Select from published SKUs visible to this account",
  "当前售价": "Current price",
  "没有找到可添加的已发布 SKU": "No published SKUs are available to add",
  "确认移除": "Remove",
  "确认移除 {name}？保存后，预览和导出文件会同步更新。": "Remove {name}? The preview and exports will update after saving.",
  "商品库加载失败": "Could not load the product catalog",
  "商品删除失败": "Could not remove the product",
  "商品添加失败": "Could not add the product",
  "商品已从报价单移除。": "Product removed from the quotation.",
  "商品已加入报价单。": "Product added to the quotation.",
  "搜索商品名称或 SKU 编码": "Search by product name or SKU code",
  "添加商品": "Add product",
  "已添加": "Added",
  "箱数": "Cartons",
  "点击选择语言，保存后生效。": "Click to select languages, then save.",
  "已选中": "Selected",
  "未选中": "Not selected",
  "暂不可选": "Unavailable",
  "已选中 · 固定保留": "Selected · Always enabled",
  "语言包未发布": "Language pack not published",
  "无权限修改": "Read-only",
  "标签列表加载失败。": "Could not load tags.", "操作失败。": "The operation failed.", "标签删除失败。": "Could not delete the tag.",
  "请先从侧边栏选择一个租户，再管理标签。": "Select a merchant from the sidebar before managing tags.",
  "新建标签": "New tag", "编辑标签": "Edit tag", "标签名称": "Tag name", "标签分类": "Tag category", "使用次数": "Usage", "不分类": "Uncategorized",
  "状态标签": "Status tag", "特性标签": "Feature tag", "场景标签": "Use-case tag", "优势标签": "Benefit tag", "还没有标签": "No tags yet",
  "创建第一个标签，用于标记和分类您的商品。": "Create the first tag to label and organize products.", "例如：Hot / 畅销 / 防水": "For example: Hot / Best seller / Waterproof",
  "确定要删除标签“{name}”吗？": "Delete the tag “{name}”?", "此标签已被 {count} 个商品使用": "This tag is used by {count} products",
  "HTML 页面必须支持响应式布局": "The HTML page must be responsive", "客户主要通过手机访问，请在上传前同时检查三种宽度。": "Most customers visit on mobile. Check all three widths before uploading.",
  "手机": "Mobile", "平板": "Tablet", "桌面": "Desktop", "加入响应式 viewport 声明": "Add a responsive viewport declaration",
  "避免固定页面宽度；图片和视频请使用 max-width: 100%": "Avoid fixed page widths; use max-width: 100% for images and videos",
  "按钮和链接需适合触屏，正文不要依赖鼠标悬停才能查看": "Make buttons and links touch-friendly, and do not hide body content behind hover interactions",
};

const es: ConsoleDictionary = {
  "工作": "Trabajo", "概览": "Resumen", "网站监测": "Analítica web", "AI 搜索": "Búsqueda con IA",
  "AI 搜索管理": "Configuración de búsqueda IA", "图片搜索管理": "Configuración de búsqueda por imagen",
  "商品": "Productos", "SKU 商品库": "Catálogo de SKU", "分类管理": "Categorías", "标签管理": "Etiquetas", "多语言": "Idiomas",
  "经营": "Operaciones", "进销存": "Inventario", "供应链": "Cadena de suministro", "前台管理": "Tienda", "公告管理": "Anuncios", "客服管理": "Atención al cliente",
  "销售": "Ventas", "询盘": "Consultas", "报价": "Cotizaciones", "报价模板": "Plantillas de cotización",
  "智能体管理": "Agentes de IA", "智能体列表": "Agentes", "知识库管理": "Bases de conocimiento",
  "平台": "Plataforma", "商家管理": "Comerciantes", "身份管理": "Identidades", "商家翻译": "Traducciones", "系统监控": "Estado del sistema", "数据监控": "Analítica", "配置中心": "Configuración",
  "设置": "Ajustes", "个人中心": "Perfil", "子账号管理": "Subcuentas", "当前工作区": "Espacio actual", "选择租户": "Elegir espacio",
  "账户与安全": "Cuenta y seguridad", "退出登录": "Cerrar sesión", "切换语言": "Cambiar idioma", "控制台导航": "Navegación del panel",
  "SKU 商品库加载失败": "No se pudo cargar el catálogo", "搜索商品库": "Buscar en el catálogo", "全部状态": "Todos los estados", "刷新": "Actualizar",
  "新建商品": "Nuevo producto", "导入与撤回": "Importar y deshacer", "图片": "Imagen", "商品列表": "Lista de productos", "商品详情": "Detalles",
  "分类": "Categoría", "标签": "Etiquetas", "当前价格": "Precio actual", "状态": "Estado", "更新时间": "Actualizado", "操作": "Acciones",
  "在售": "Activo", "待审核": "Pendiente", "草稿": "Borrador", "已归档": "Archivado", "未分类": "Sin categoría", "未设置": "Sin configurar",
  "保存": "Guardar", "取消": "Cancelar", "关闭": "Cerrar", "重试": "Reintentar", "上一页": "Anterior", "下一页": "Siguiente",
  "登录商家工作台": "Iniciar sesión en el panel", "使用账号、邮箱或手机号登录": "Inicia sesión con tu cuenta, correo o teléfono", "登录账号": "Cuenta", "账号、邮箱或手机号": "Cuenta, correo o teléfono", "密码": "Contraseña", "请输入密码": "Introduce la contraseña", "登录工作台": "Iniciar sesión", "选择工作区": "Elegir espacio", "确认本次使用的商家空间": "Confirma el espacio que quieres usar", "当前账号没有可用的商家空间。": "Esta cuenta no tiene espacios disponibles.", "当前成员": "Miembro actual", "早上好": "Buenos días", "下午好": "Buenas tardes", "晚上好": "Buenas noches",
};

const tr: ConsoleDictionary = {
  "工作": "Çalışma", "概览": "Genel bakış", "网站监测": "Web analitiği", "AI 搜索": "Yapay zekâ arama",
  "AI 搜索管理": "Yapay zekâ arama ayarları", "图片搜索管理": "Görsel arama ayarları",
  "商品": "Ürünler", "SKU 商品库": "SKU kataloğu", "分类管理": "Kategoriler", "标签管理": "Etiketler", "多语言": "Diller",
  "经营": "Operasyonlar", "进销存": "Stok", "供应链": "Tedarik zinciri", "前台管理": "Mağaza", "公告管理": "Duyurular", "客服管理": "Müşteri hizmetleri",
  "销售": "Satış", "询盘": "Talepler", "报价": "Teklifler", "报价模板": "Teklif şablonları",
  "智能体管理": "Yapay zekâ ajanları", "智能体列表": "Ajanlar", "知识库管理": "Bilgi tabanları",
  "平台": "Platform", "商家管理": "Satıcılar", "身份管理": "Kimlikler", "商家翻译": "Çeviriler", "系统监控": "Sistem durumu", "数据监控": "Analitik", "配置中心": "Yapılandırma",
  "设置": "Ayarlar", "个人中心": "Profil", "子账号管理": "Alt hesaplar", "当前工作区": "Geçerli çalışma alanı", "选择租户": "Çalışma alanı seç",
  "账户与安全": "Hesap ve güvenlik", "退出登录": "Çıkış yap", "切换语言": "Dili değiştir", "控制台导航": "Panel menüsü",
  "SKU 商品库加载失败": "Katalog yüklenemedi", "搜索商品库": "Katalogda ara", "全部状态": "Tüm durumlar", "刷新": "Yenile",
  "新建商品": "Yeni ürün", "导入与撤回": "İçe aktar ve geri al", "图片": "Görsel", "商品列表": "Ürün listesi", "商品详情": "Ürün ayrıntıları",
  "分类": "Kategori", "标签": "Etiketler", "当前价格": "Güncel fiyat", "状态": "Durum", "更新时间": "Güncellendi", "操作": "İşlemler",
  "在售": "Aktif", "待审核": "İncelemede", "草稿": "Taslak", "已归档": "Arşivlendi", "未分类": "Kategorisiz", "未设置": "Ayarlanmadı",
  "保存": "Kaydet", "取消": "İptal", "关闭": "Kapat", "重试": "Yeniden dene", "上一页": "Önceki", "下一页": "Sonraki",
  "登录商家工作台": "Satıcı paneline giriş", "使用账号、邮箱或手机号登录": "Hesap, e-posta veya telefonla giriş yapın", "登录账号": "Hesap", "账号、邮箱或手机号": "Hesap, e-posta veya telefon", "密码": "Şifre", "请输入密码": "Şifrenizi girin", "登录工作台": "Giriş yap", "选择工作区": "Çalışma alanı seç", "确认本次使用的商家空间": "Kullanacağınız çalışma alanını onaylayın", "当前账号没有可用的商家空间。": "Bu hesap için kullanılabilir çalışma alanı yok.", "当前成员": "Geçerli üye", "早上好": "Günaydın", "下午好": "İyi günler", "晚上好": "İyi akşamlar",
};

const ar: ConsoleDictionary = {
  "工作": "العمل", "概览": "نظرة عامة", "网站监测": "تحليلات الموقع", "AI 搜索": "بحث الذكاء الاصطناعي",
  "AI 搜索管理": "إعدادات بحث الذكاء الاصطناعي", "图片搜索管理": "إعدادات البحث بالصور",
  "商品": "المنتجات", "SKU 商品库": "كتالوج SKU", "分类管理": "الفئات", "标签管理": "الوسوم", "多语言": "اللغات",
  "经营": "العمليات", "进销存": "المخزون", "供应链": "سلسلة التوريد", "前台管理": "المتجر", "公告管理": "الإعلانات", "客服管理": "خدمة العملاء",
  "销售": "المبيعات", "询盘": "الاستفسارات", "报价": "عروض الأسعار", "报价模板": "قوالب عروض الأسعار",
  "智能体管理": "وكلاء الذكاء الاصطناعي", "智能体列表": "الوكلاء", "知识库管理": "قواعد المعرفة",
  "平台": "المنصة", "商家管理": "التجار", "身份管理": "الهويات", "商家翻译": "الترجمات", "系统监控": "حالة النظام", "数据监控": "التحليلات", "配置中心": "الإعدادات",
  "设置": "الإعدادات", "个人中心": "الملف الشخصي", "子账号管理": "الحسابات الفرعية", "当前工作区": "مساحة العمل الحالية", "选择租户": "اختر مساحة العمل",
  "账户与安全": "الحساب والأمان", "退出登录": "تسجيل الخروج", "切换语言": "تغيير اللغة", "控制台导航": "قائمة لوحة التحكم",
  "SKU 商品库加载失败": "تعذر تحميل الكتالوج", "搜索商品库": "البحث في الكتالوج", "全部状态": "كل الحالات", "刷新": "تحديث",
  "新建商品": "منتج جديد", "导入与撤回": "استيراد وتراجع", "图片": "الصورة", "商品列表": "قائمة المنتجات", "商品详情": "تفاصيل المنتج",
  "分类": "الفئة", "标签": "الوسوم", "当前价格": "السعر الحالي", "状态": "الحالة", "更新时间": "آخر تحديث", "操作": "الإجراءات",
  "在售": "نشط", "待审核": "قيد المراجعة", "草稿": "مسودة", "已归档": "مؤرشف", "未分类": "غير مصنف", "未设置": "غير مضبوط",
  "保存": "حفظ", "取消": "إلغاء", "关闭": "إغلاق", "重试": "إعادة المحاولة", "上一页": "السابق", "下一页": "التالي",
  "登录商家工作台": "تسجيل الدخول إلى لوحة التاجر", "使用账号、邮箱或手机号登录": "سجّل الدخول بالحساب أو البريد أو الهاتف", "登录账号": "الحساب", "账号、邮箱或手机号": "الحساب أو البريد أو الهاتف", "密码": "كلمة المرور", "请输入密码": "أدخل كلمة المرور", "登录工作台": "تسجيل الدخول", "选择工作区": "اختيار مساحة العمل", "确认本次使用的商家空间": "أكد مساحة العمل التي ستستخدمها", "当前账号没有可用的商家空间。": "لا توجد مساحة عمل متاحة لهذا الحساب.", "当前成员": "العضو الحالي", "早上好": "صباح الخير", "下午好": "مساء الخير", "晚上好": "مساء الخير",
};

const ja: ConsoleDictionary = {
  "工作": "ワークスペース", "概览": "概要", "网站监测": "サイト分析", "AI 搜索": "AI検索", "AI 搜索管理": "AI検索設定", "图片搜索管理": "画像検索設定",
  "商品": "商品", "SKU 商品库": "SKU商品台帳", "分类管理": "カテゴリ管理", "标签管理": "タグ管理", "多语言": "多言語",
  "经营": "運営", "进销存": "在庫管理", "供应链": "サプライチェーン", "前台管理": "ストア管理", "公告管理": "お知らせ管理", "客服管理": "カスタマーサポート",
  "销售": "販売", "询盘": "問い合わせ", "报价": "見積", "报价模板": "見積テンプレート",
  "智能体管理": "AIエージェント", "智能体列表": "エージェント一覧", "知识库管理": "ナレッジベース",
  "平台": "プラットフォーム", "商家管理": "販売者管理", "身份管理": "権限管理", "商家翻译": "翻訳管理", "系统监控": "システム監視", "数据监控": "データ分析", "配置中心": "設定センター",
  "设置": "設定", "个人中心": "プロフィール", "子账号管理": "サブアカウント", "当前工作区": "現在のワークスペース", "选择租户": "ワークスペースを選択",
  "账户与安全": "アカウントとセキュリティ", "退出登录": "ログアウト", "切换语言": "言語を変更", "控制台导航": "管理画面ナビゲーション",
  "SKU 商品库加载失败": "商品台帳を読み込めませんでした", "搜索商品库": "商品台帳を検索", "全部状态": "すべての状態", "刷新": "更新",
  "新建商品": "商品を作成", "导入与撤回": "インポートと取り消し", "图片": "画像", "商品列表": "商品一覧", "商品详情": "商品詳細",
  "分类": "カテゴリ", "标签": "タグ", "当前价格": "現在価格", "状态": "状態", "更新时间": "更新日時", "操作": "操作",
  "在售": "販売中", "待审核": "審査待ち", "草稿": "下書き", "已归档": "アーカイブ済み", "未分类": "未分類", "未设置": "未設定",
  "保存": "保存", "取消": "キャンセル", "关闭": "閉じる", "重试": "再試行", "上一页": "前へ", "下一页": "次へ",
  "登录商家工作台": "販売者管理画面にログイン", "使用账号、邮箱或手机号登录": "アカウント・メール・電話番号でログイン", "登录账号": "アカウント", "账号、邮箱或手机号": "アカウント、メールまたは電話番号", "密码": "パスワード", "请输入密码": "パスワードを入力", "登录工作台": "ログイン", "选择工作区": "ワークスペースを選択", "确认本次使用的商家空间": "使用するワークスペースを確認してください", "当前账号没有可用的商家空间。": "利用可能なワークスペースがありません。", "当前成员": "現在のメンバー", "早上好": "おはようございます", "下午好": "こんにちは", "晚上好": "こんばんは",
};

const ko: ConsoleDictionary = {
  "工作": "워크스페이스", "概览": "개요", "网站监测": "사이트 분석", "AI 搜索": "AI 검색", "AI 搜索管理": "AI 검색 설정", "图片搜索管理": "이미지 검색 설정",
  "商品": "상품", "SKU 商品库": "SKU 상품 목록", "分类管理": "카테고리 관리", "标签管理": "태그 관리", "多语言": "다국어",
  "经营": "운영", "进销存": "재고 관리", "供应链": "공급망", "前台管理": "스토어 관리", "公告管理": "공지 관리", "客服管理": "고객 지원",
  "销售": "판매", "询盘": "문의", "报价": "견적", "报价模板": "견적 템플릿",
  "智能体管理": "AI 에이전트", "智能体列表": "에이전트 목록", "知识库管理": "지식베이스",
  "平台": "플랫폼", "商家管理": "판매자 관리", "身份管理": "권한 관리", "商家翻译": "번역 관리", "系统监控": "시스템 모니터링", "数据监控": "데이터 분석", "配置中心": "설정 센터",
  "设置": "설정", "个人中心": "프로필", "子账号管理": "하위 계정", "当前工作区": "현재 워크스페이스", "选择租户": "워크스페이스 선택",
  "账户与安全": "계정 및 보안", "退出登录": "로그아웃", "切换语言": "언어 변경", "控制台导航": "관리자 메뉴",
  "SKU 商品库加载失败": "상품 목록을 불러오지 못했습니다", "搜索商品库": "상품 목록 검색", "全部状态": "전체 상태", "刷新": "새로고침",
  "新建商品": "새 상품", "导入与撤回": "가져오기 및 취소", "图片": "이미지", "商品列表": "상품 목록", "商品详情": "상품 상세",
  "分类": "카테고리", "标签": "태그", "当前价格": "현재 가격", "状态": "상태", "更新时间": "업데이트", "操作": "작업",
  "在售": "판매 중", "待审核": "검토 대기", "草稿": "초안", "已归档": "보관됨", "未分类": "미분류", "未设置": "설정 안 됨",
  "保存": "저장", "取消": "취소", "关闭": "닫기", "重试": "다시 시도", "上一页": "이전", "下一页": "다음",
  "登录商家工作台": "판매자 관리자 로그인", "使用账号、邮箱或手机号登录": "계정, 이메일 또는 전화번호로 로그인", "登录账号": "계정", "账号、邮箱或手机号": "계정, 이메일 또는 전화번호", "密码": "비밀번호", "请输入密码": "비밀번호를 입력하세요", "登录工作台": "로그인", "选择工作区": "워크스페이스 선택", "确认本次使用的商家空间": "사용할 워크스페이스를 확인하세요", "当前账号没有可用的商家空间。": "이 계정에 사용 가능한 워크스페이스가 없습니다.", "当前成员": "현재 사용자", "早上好": "좋은 아침입니다", "下午好": "안녕하세요", "晚上好": "좋은 저녁입니다",
};

const pt: ConsoleDictionary = {
  "工作": "Trabalho", "概览": "Visão geral", "网站监测": "Análise do site", "AI 搜索": "Pesquisa com IA", "AI 搜索管理": "Configuração da pesquisa IA", "图片搜索管理": "Configuração da pesquisa por imagem",
  "商品": "Produtos", "SKU 商品库": "Catálogo de SKU", "分类管理": "Categorias", "标签管理": "Etiquetas", "多语言": "Idiomas",
  "经营": "Operações", "进销存": "Estoque", "供应链": "Cadeia de suprimentos", "前台管理": "Loja", "公告管理": "Anúncios", "客服管理": "Atendimento",
  "销售": "Vendas", "询盘": "Consultas", "报价": "Cotações", "报价模板": "Modelos de cotação",
  "智能体管理": "Agentes de IA", "智能体列表": "Agentes", "知识库管理": "Bases de conhecimento",
  "平台": "Plataforma", "商家管理": "Lojistas", "身份管理": "Identidades", "商家翻译": "Traduções", "系统监控": "Status do sistema", "数据监控": "Análises", "配置中心": "Configuração",
  "设置": "Configurações", "个人中心": "Perfil", "子账号管理": "Subcontas", "当前工作区": "Espaço atual", "选择租户": "Escolher espaço",
  "账户与安全": "Conta e segurança", "退出登录": "Sair", "切换语言": "Mudar idioma", "控制台导航": "Navegação do painel",
  "SKU 商品库加载失败": "Não foi possível carregar o catálogo", "搜索商品库": "Pesquisar no catálogo", "全部状态": "Todos os status", "刷新": "Atualizar",
  "新建商品": "Novo produto", "导入与撤回": "Importar e desfazer", "图片": "Imagem", "商品列表": "Lista de produtos", "商品详情": "Detalhes",
  "分类": "Categoria", "标签": "Etiquetas", "当前价格": "Preço atual", "状态": "Status", "更新时间": "Atualizado", "操作": "Ações",
  "在售": "Ativo", "待审核": "Em análise", "草稿": "Rascunho", "已归档": "Arquivado", "未分类": "Sem categoria", "未设置": "Não definido",
  "保存": "Salvar", "取消": "Cancelar", "关闭": "Fechar", "重试": "Tentar novamente", "上一页": "Anterior", "下一页": "Próxima",
  "登录商家工作台": "Entrar no painel do lojista", "使用账号、邮箱或手机号登录": "Entre com conta, e-mail ou telefone", "登录账号": "Conta", "账号、邮箱或手机号": "Conta, e-mail ou telefone", "密码": "Senha", "请输入密码": "Digite a senha", "登录工作台": "Entrar", "选择工作区": "Escolher espaço", "确认本次使用的商家空间": "Confirme o espaço que deseja usar", "当前账号没有可用的商家空间。": "Esta conta não possui espaços disponíveis.", "当前成员": "Membro atual", "早上好": "Bom dia", "下午好": "Boa tarde", "晚上好": "Boa noite",
};

const fr: ConsoleDictionary = {
  "工作": "Travail", "概览": "Vue d’ensemble", "网站监测": "Analyse du site", "AI 搜索": "Recherche IA", "AI 搜索管理": "Paramètres de recherche IA", "图片搜索管理": "Paramètres de recherche par image",
  "商品": "Produits", "SKU 商品库": "Catalogue SKU", "分类管理": "Catégories", "标签管理": "Étiquettes", "多语言": "Langues",
  "经营": "Opérations", "进销存": "Stocks", "供应链": "Chaîne logistique", "前台管理": "Boutique", "公告管理": "Annonces", "客服管理": "Service client",
  "销售": "Ventes", "询盘": "Demandes", "报价": "Devis", "报价模板": "Modèles de devis",
  "智能体管理": "Agents IA", "智能体列表": "Agents", "知识库管理": "Bases de connaissances",
  "平台": "Plateforme", "商家管理": "Marchands", "身份管理": "Identités", "商家翻译": "Traductions", "系统监控": "État du système", "数据监控": "Analyses", "配置中心": "Configuration",
  "设置": "Paramètres", "个人中心": "Profil", "子账号管理": "Sous-comptes", "当前工作区": "Espace actuel", "选择租户": "Choisir un espace",
  "账户与安全": "Compte et sécurité", "退出登录": "Se déconnecter", "切换语言": "Changer de langue", "控制台导航": "Navigation du tableau de bord",
  "SKU 商品库加载失败": "Impossible de charger le catalogue", "搜索商品库": "Rechercher dans le catalogue", "全部状态": "Tous les statuts", "刷新": "Actualiser",
  "新建商品": "Nouveau produit", "导入与撤回": "Importer et annuler", "图片": "Image", "商品列表": "Liste des produits", "商品详情": "Détails",
  "分类": "Catégorie", "标签": "Étiquettes", "当前价格": "Prix actuel", "状态": "Statut", "更新时间": "Mis à jour", "操作": "Actions",
  "在售": "Actif", "待审核": "À vérifier", "草稿": "Brouillon", "已归档": "Archivé", "未分类": "Sans catégorie", "未设置": "Non défini",
  "保存": "Enregistrer", "取消": "Annuler", "关闭": "Fermer", "重试": "Réessayer", "上一页": "Précédent", "下一页": "Suivant",
  "登录商家工作台": "Connexion au tableau de bord", "使用账号、邮箱或手机号登录": "Connectez-vous avec votre compte, e-mail ou téléphone", "登录账号": "Compte", "账号、邮箱或手机号": "Compte, e-mail ou téléphone", "密码": "Mot de passe", "请输入密码": "Saisissez le mot de passe", "登录工作台": "Se connecter", "选择工作区": "Choisir un espace", "确认本次使用的商家空间": "Confirmez l’espace à utiliser", "当前账号没有可用的商家空间。": "Aucun espace n’est disponible pour ce compte.", "当前成员": "Membre actuel", "早上好": "Bonjour", "下午好": "Bonjour", "晚上好": "Bonsoir",
};

const fa: ConsoleDictionary = {
  "工作": "کار", "概览": "نمای کلی", "网站监测": "تحلیل وب‌سایت", "AI 搜索": "جستجوی هوش مصنوعی", "AI 搜索管理": "تنظیمات جستجوی هوش مصنوعی", "图片搜索管理": "تنظیمات جستجوی تصویری",
  "商品": "محصولات", "SKU 商品库": "کاتالوگ SKU", "分类管理": "دسته‌بندی‌ها", "标签管理": "برچسب‌ها", "多语言": "زبان‌ها",
  "经营": "عملیات", "进销存": "موجودی", "供应链": "زنجیره تأمین", "前台管理": "فروشگاه", "公告管理": "اعلان‌ها", "客服管理": "پشتیبانی مشتری",
  "销售": "فروش", "询盘": "درخواست‌ها", "报价": "پیش‌فاکتورها", "报价模板": "قالب‌های پیش‌فاکتور",
  "智能体管理": "عامل‌های هوش مصنوعی", "智能体列表": "عامل‌ها", "知识库管理": "پایگاه‌های دانش",
  "平台": "پلتفرم", "商家管理": "فروشندگان", "身份管理": "هویت‌ها", "商家翻译": "ترجمه‌ها", "系统监控": "وضعیت سیستم", "数据监控": "تحلیل داده", "配置中心": "پیکربندی",
  "设置": "تنظیمات", "个人中心": "پروفایل", "子账号管理": "حساب‌های فرعی", "当前工作区": "فضای کاری فعلی", "选择租户": "انتخاب فضای کاری",
  "账户与安全": "حساب و امنیت", "退出登录": "خروج", "切换语言": "تغییر زبان", "控制台导航": "پیمایش داشبورد",
  "SKU 商品库加载失败": "بارگذاری کاتالوگ ممکن نشد", "搜索商品库": "جستجو در کاتالوگ", "全部状态": "همه وضعیت‌ها", "刷新": "تازه‌سازی",
  "新建商品": "محصول جدید", "导入与撤回": "ورود و بازگردانی", "图片": "تصویر", "商品列表": "فهرست محصولات", "商品详情": "جزئیات محصول",
  "分类": "دسته‌بندی", "标签": "برچسب‌ها", "当前价格": "قیمت فعلی", "状态": "وضعیت", "更新时间": "به‌روزرسانی", "操作": "عملیات",
  "在售": "فعال", "待审核": "در انتظار بررسی", "草稿": "پیش‌نویس", "已归档": "بایگانی‌شده", "未分类": "بدون دسته", "未设置": "تنظیم نشده",
  "保存": "ذخیره", "取消": "لغو", "关闭": "بستن", "重试": "تلاش دوباره", "上一页": "قبلی", "下一页": "بعدی",
  "登录商家工作台": "ورود به داشبورد فروشنده", "使用账号、邮箱或手机号登录": "با حساب، ایمیل یا تلفن وارد شوید", "登录账号": "حساب", "账号、邮箱或手机号": "حساب، ایمیل یا تلفن", "密码": "رمز عبور", "请输入密码": "رمز عبور را وارد کنید", "登录工作台": "ورود", "选择工作区": "انتخاب فضای کاری", "确认本次使用的商家空间": "فضای کاری مورد استفاده را تأیید کنید", "当前账号没有可用的商家空间。": "برای این حساب فضای کاری در دسترس نیست.", "当前成员": "عضو فعلی", "早上好": "صبح بخیر", "下午好": "عصر بخیر", "晚上好": "شب بخیر",
};

const ru: ConsoleDictionary = {
  "已启用 {count} 种": "Включено {count} языков", "已锁定 {count}": "Заблокировано {count}",
  "ACTIVE": "Активен", "API Key": "Ключ API", "APPROVED": "Одобрено", "ARCHIVED": "В архиве",
  "Batch API Key": "Ключ Batch API", "Batch Base URL": "Базовый URL Batch", "DRAFT": "Черновик", "English": "Английский",
  "FAILED": "Ошибка", "high": "высокий", "INACTIVE": "Неактивен", "low": "низкий", "medium": "средний", "minimal": "минимальный", "none": "нет", "PAUSED": "Приостановлено", "QUEUED": "В очереди", "RUNNING": "Выполняется",
  "商品名称": "Название товара", "商品编码": "Код товара", "商品属性": "Атрибуты товара", "商品详情中的所有属性都可以在这里维护": "Здесь можно поддерживать все атрибуты из сведений о товаре", "添加属性": "Добавить атрибут", "属性名称": "Название атрибута", "属性值": "Значение атрибута", "重量单位": "Единица веса", "规格字段": "Поля характеристик", "添加规格": "Добавить характеристику", "规格名称": "Название характеристики", "规格值": "Значение характеристики", "删除规格": "Удалить характеристику", "删除属性": "Удалить атрибут", "暂无商品属性": "Атрибутов товара нет", "文本": "Текст", "数字": "Число", "布尔值": "Логическое значение", "保存商品": "Сохранить товар", "商品名称不能为空。": "Название товара не может быть пустым.", "属性名称不能为空。": "Название атрибута не может быть пустым.", "编辑商品": "Редактировать товар",
  "工作": "Рабочая область", "概览": "Обзор", "网站监测": "Аналитика сайта", "AI 搜索": "Поиск с ИИ",
  "AI 搜索管理": "Настройки поиска с ИИ", "图片搜索管理": "Настройки поиска по изображениям",
  "商品": "Товары", "SKU 商品库": "Каталог SKU", "分类管理": "Категории", "标签管理": "Метки", "多语言": "Языки",
  "经营": "Операции", "进销存": "Управление запасами", "供应链": "Цепочка поставок", "前台管理": "Магазин", "公告管理": "Объявления", "客服管理": "Поддержка клиентов",
  "销售": "Продажи", "询盘": "Запросы", "报价": "Котировки", "报价模板": "Шаблоны котировок",
  "智能体管理": "ИИ-агенты", "智能体列表": "Агенты", "知识库管理": "Базы знаний",
  "平台": "Платформа", "商家管理": "Продавцы", "身份管理": "Управление удостоверениями", "商家翻译": "Переводы продавцов", "系统监控": "Состояние системы", "数据监控": "Аналитика", "配置中心": "Центр настроек",
  "设置": "Настройки", "个人中心": "Профиль", "子账号管理": "Дочерние аккаунты", "当前工作区": "Текущая рабочая область", "选择租户": "Выбрать рабочую область",
  "账户与安全": "Аккаунт и безопасность", "退出登录": "Выйти", "切换语言": "Сменить язык", "控制台导航": "Навигация панели",
  "SKU 商品库加载失败": "Не удалось загрузить каталог", "搜索商品库": "Поиск в каталоге", "全部状态": "Все статусы", "刷新": "Обновить",
  "新建商品": "Новый товар", "导入与撤回": "Импорт и отмена", "图片": "Изображение", "商品列表": "Список товаров", "商品详情": "Сведения о товаре",
  "分类": "Категория", "标签": "Метки", "当前价格": "Текущая цена", "状态": "Статус", "更新时间": "Обновлено", "操作": "Действия",
  "在售": "В продаже", "待审核": "На проверке", "草稿": "Черновик", "已归档": "В архиве", "未分类": "Без категории", "未设置": "Не настроено",
  "保存": "Сохранить", "取消": "Отмена", "关闭": "Закрыть", "重试": "Повторить", "上一页": "Назад", "下一页": "Далее",
  "登录商家工作台": "Войти в панель продавца", "使用账号、邮箱或手机号登录": "Войдите по аккаунту, электронной почте или телефону", "登录账号": "Аккаунт", "账号、邮箱或手机号": "Аккаунт, электронная почта или телефон", "密码": "Пароль", "请输入密码": "Введите пароль", "登录工作台": "Войти", "选择工作区": "Выберите рабочую область", "确认本次使用的商家空间": "Подтвердите рабочую область для этого сеанса", "当前账号没有可用的商家空间。": "Для этого аккаунта нет доступных рабочих областей.", "当前成员": "Текущий участник", "早上好": "Доброе утро", "下午好": "Добрый день", "晚上好": "Добрый вечер",
  "从平台语言库为当前商家添加或移除前台语言。中文固定保留，未发布语言包的语言会在发布后显示给客户。": "Добавляйте и удаляйте языки витрины для текущего продавца из библиотеки языков платформы. Китайский язык включён постоянно; языки появятся у клиентов после публикации языкового пакета.",
  "待发布": "Ожидает публикации", "固定": "Всегда включён", "客户可见语言": "Языки, видимые клиентам", "前台语言已保存。": "Языки витрины сохранены.", "添加语言": "Добавить язык", "语言库": "Библиотека языков", "语言配置读取失败。": "Не удалось загрузить настройки языков.", "正在读取语言配置…": "Загрузка настроек языков…",
  "俄语": "Русский", "Русский": "Русский", "保存前台语言": "Сохранить языки витрины", "选择展示语言": "Выберите языки для показа", "已选中": "Выбрано", "未选中": "Не выбрано", "暂不可选": "Недоступно", "语言包未发布": "Языковой пакет не опубликован", "无权限修改": "Только чтение",
  "客户前台": "Витрина клиента", "去商品前台": "Открыть витрину", "商品前台": "Витрина товаров", "处理报价": "Обработать котировку", "报价工作台": "Рабочая область котировок", "报价单": "Котировка", "正式报价": "Официальная котировка", "客户前台草稿": "Черновики витрины клиента",
  "正在读取翻译历史记录…": "Загрузка истории переводов…", "翻译中": "Перевод выполняется", "继续翻译": "Продолжить перевод", "全量翻译": "Полный перевод", "翻译新增与变更": "Перевести новые и изменённые", "翻译批次": "Пакеты перевода", "请求中": "Запрос выполняется", "已完成": "Завершено", "失败待重试": "Ошибка — повторить", "从断点继续": "Продолжить с контрольной точки",
};

const dictionaries: Partial<Record<UiLocale, ConsoleDictionary>> = {
  "en-US": en,
  es: { ...esGenerated, ...es },
  tr: { ...trGenerated, ...tr },
  ar: { ...arGenerated, ...ar },
  ja: { ...jaGenerated, ...ja },
  ko: { ...koGenerated, ...ko },
  pt: { ...ptGenerated, ...pt },
  ru: { ...ruGenerated, ...ru },
  fr: { ...frGenerated, ...fr },
  fa: { ...faGenerated, ...fa },
};

export function consoleLocaleMessage(locale: UiLocale, source: string): string | undefined {
  return dictionaries[locale]?.[source];
}
