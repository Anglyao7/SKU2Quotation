from decimal import Decimal

from .models import ImportJob, JobStatus, Product, ReviewField, ReviewItem, Supplier


SUPPLIERS = [
    Supplier(id="SUP-001", name="青禾宠物用品", category="饮水与喂食", active_skus=426, review_count=18, freshness="今天", health="good"),
    Supplier(id="SUP-002", name="远航户外宠物制品", category="围栏与玩具", active_skus=182, review_count=6, freshness="2 天前", health="good"),
    Supplier(id="SUP-003", name="云宠智能设备", category="智能硬件", active_skus=71, review_count=12, freshness="11 天前", health="warning"),
]

IMPORT_JOBS = [
    ImportJob(id="JOB-260717-08", filename="2026_新品参展表.xlsx", supplier="青禾宠物用品", detected_type="OOXML / WPS DISPIMG", status=JobStatus.NEEDS_REVIEW, progress=100, products=111, warnings=17, created_at="14:36"),
    ImportJob(id="JOB-260717-07", filename="出口报价表.xlsx", supplier="远航户外宠物制品", detected_type="OLE / Legacy XLS", status=JobStatus.PARSING, progress=68, products=0, warnings=1, created_at="14:22"),
]

PRODUCTS = [
    Product(id="SKU-24018", name="宠物无线饮水机（不锈钢款）", model="AQ-320S", category="饮水与喂食", supplier="青禾宠物用品", price=Decimal("72"), currency="CNY", moq=100, updated="今天", image_status="SOURCE", tags=["3L", "不锈钢", "无线水泵"]),
    Product(id="SKU-18211", name="八片带门宠物围栏", model="PF-8G01", category="围栏与玩具", supplier="远航户外宠物制品", price=Decimal("148"), currency="CNY", moq=1, updated="2 天前", image_status="APPROVED", tags=["90×61cm", "8片", "可折叠"]),
    Product(id="SKU-31008", name="智能宠物喂食器 6L", model="SF-6L20", category="智能硬件", supplier="云宠智能设备", price=Decimal("196"), currency="CNY", moq=200, updated="11 天前", image_status="SOURCE", tags=["6L", "APP", "双频Wi-Fi"]),
]

REVIEWS = [
    ReviewItem(
        id="REV-001", name="宠物无线饮水机", model="AQ-320", supplier="青禾宠物用品", source="产品表格_2026.xlsx", location="Sheet1 · 第 3 行", image_status="SOURCE",
        fields=[
            ReviewField(key="name", label="产品名称", source="宠物无线饮水机 不锈钢款", normalized="宠物无线饮水机（不锈钢款）", confidence=0.98),
            ReviewField(key="size", label="产品尺寸", source="19.5*19.5*16.5", normalized="19.5 × 19.5 × 16.5 cm", confidence=0.94),
        ],
    )
]
