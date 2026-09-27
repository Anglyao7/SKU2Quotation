from __future__ import annotations

from uuid import uuid4

from app.product_center_models import AttributeDefinitionRow
from app.product_supplier_models import ProductAttributeRow, ProductRow
from app.services.product_description_attributes import (
    ProductDescriptionAttributeSynchronizer,
    description_attribute_definition_key,
    extract_description_attributes,
)


def test_extract_description_attributes_handles_common_catalog_format() -> None:
    description = """材质：食品级 ABS、HDPE 冰盒
餐数: 6 餐；单餐容量：200ml
适用对象：2 月龄以上猫
产品尺寸：12.6×10.5×8.3in
材 质：食品级 PP
https://example.com/image.jpg
普通商品介绍，不是属性字段"""

    assert extract_description_attributes(description) == (
        ("材质", "食品级 ABS、HDPE 冰盒；食品级 PP"),
        ("餐数", "6 餐"),
        ("单餐容量", "200ml"),
        ("适用对象", "2 月龄以上猫"),
        ("产品尺寸", "12.6×10.5×8.3in"),
    )


def test_extract_description_attributes_splits_inline_fields_without_line_breaks() -> None:
    description = (
        "材质:ABS 支持系统:适用于IOS 11.0版本和Android 14版本 "
        "证书:符合CE&ROHS&FCC要求蓝牙版本:蓝牙4.0无线距离:10-15米"
    )

    assert extract_description_attributes(description) == (
        ("材质", "ABS"),
        ("支持系统", "适用于IOS 11.0版本和Android 14版本"),
        ("证书", "符合CE&ROHS&FCC要求"),
        ("蓝牙版本", "蓝牙4.0"),
        ("无线距离", "10-15米"),
    )


def test_extract_description_attributes_keeps_urls_and_times_in_values() -> None:
    description = "链接：https://example.com/a 颜色：白色 时间：12:30"

    assert extract_description_attributes(description) == (
        ("链接", "https://example.com/a"),
        ("颜色", "白色"),
        ("时间", "12:30"),
    )


def test_extract_description_attributes_keeps_full_inline_label_after_number() -> None:
    assert extract_description_attributes("输入电压:12V输出功率:5W 13位编码:1234567890123") == (
        ("输入电压", "12V"),
        ("输出功率", "5W"),
        ("13位编码", "1234567890123"),
    )


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class _AttributeSession:
    def __init__(
        self,
        definitions: list[AttributeDefinitionRow] | None = None,
        attributes: list[ProductAttributeRow] | None = None,
    ) -> None:
        self.scalar_results = [definitions or [], attributes or []]
        self.added: list[object] = []
        self.deleted: list[object] = []

    def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(self.scalar_results.pop(0) if self.scalar_results else [])

    def add(self, row: object) -> None:
        self.added.append(row)

    def flush(self) -> None:
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid4()

    def delete(self, row: object) -> None:
        self.deleted.append(row)


def test_sync_reuses_definitions_and_preserves_confirmed_values() -> None:
    tenant_id = uuid4()
    session = _AttributeSession()
    first = ProductRow(
        id=uuid4(),
        tenant_id=tenant_id,
        name="自动属性商品一",
        status="ACTIVE",
    )
    second = ProductRow(
        id=uuid4(),
        tenant_id=tenant_id,
        name="自动属性商品二",
        status="ACTIVE",
    )
    synchronizer = ProductDescriptionAttributeSynchronizer(
        session,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        product_ids={first.id, second.id},
    )

    assert synchronizer.sync(first, "材质：ABS\n装箱数：4pcs/ctn")
    assert synchronizer.sync(second, "材 质：HDPE")
    definitions = [
        row for row in session.added if isinstance(row, AttributeDefinitionRow)
    ]
    assert sorted(row.display_name for row in definitions) == ["材质", "装箱数"]
    material = next(row for row in definitions if row.display_name == "材质")
    first_material = next(
        row
        for row in session.added
        if isinstance(row, ProductAttributeRow)
        and row.product_id == first.id
        and row.attribute_definition_id == material.id
    )
    second_material = next(
        row
        for row in session.added
        if isinstance(row, ProductAttributeRow)
        and row.product_id == second.id
        and row.attribute_definition_id == material.id
    )
    assert first_material.value_text == "ABS"
    assert second_material.value_text == "HDPE"

    first_material.value_text = "商家确认材质"
    first_material.review_status = "CONFIRMED"
    assert synchronizer.sync(first, "材质：新导入值\n装箱数：4pcs/ctn") is False
    assert first_material.value_text == "商家确认材质"

    assert synchronizer.sync(second, "")
    assert second_material in session.deleted


def test_sync_repairs_previous_inline_value_without_creating_duplicate_material() -> None:
    tenant_id = uuid4()
    product = ProductRow(id=uuid4(), tenant_id=tenant_id, name="蓝牙商品", status="ACTIVE")
    description = "材质:ABS 支持系统:IOS 11.0 证书:CE蓝牙版本:蓝牙4.0无线距离:10米"
    material_definition = AttributeDefinitionRow(
        id=uuid4(),
        tenant_id=tenant_id,
        category_id=None,
        attribute_key=description_attribute_definition_key("材质"),
        display_name="材质",
        data_type="TEXT",
        status="ACTIVE",
    )
    material = ProductAttributeRow(
        id=uuid4(),
        tenant_id=tenant_id,
        product_id=product.id,
        attribute_definition_id=material_definition.id,
        attribute_key=material_definition.attribute_key,
        value_text=description.removeprefix("材质:"),
        review_status="AI_SUGGESTED",
    )
    session = _AttributeSession([material_definition], [material])
    synchronizer = ProductDescriptionAttributeSynchronizer(
        session,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        product_ids={product.id},
    )

    assert synchronizer.sync(product, description)
    assert material.value_text == "ABS"
    attributes = [
        row for row in session.added if isinstance(row, ProductAttributeRow)
    ]
    assert len(attributes) == 4
    assert synchronizer.sync(product, description) is False
