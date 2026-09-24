"""Deterministic extraction and synchronization for description attributes."""

from __future__ import annotations

import re
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..product_center_models import AttributeDefinitionRow
from ..product_supplier_models import ProductAttributeRow, ProductRow


_LINE_PATTERN = re.compile(r"^\s*([^:：\r\n;；]{1,100}?)\s*[:：]\s*(.*?)\s*$")
_KEY_NORMALIZE_PATTERN = re.compile(r"[\s_\-/:：,.，。()（）\[\]【】]+")


def description_attribute_key(value: object) -> str:
    return _KEY_NORMALIZE_PATTERN.sub("", str(value or "").casefold().strip())


def description_attribute_definition_key(display_name: str) -> str:
    digest = sha256(description_attribute_key(display_name).encode("utf-8")).hexdigest()[:20]
    return f"auto_{digest}"


def extract_description_attributes(
    description: str | None,
) -> tuple[tuple[str, str], ...]:
    """Extract unique ``name: value`` pairs while preserving source values."""

    if not description or not description.strip():
        return ()
    result: list[tuple[str, str]] = []
    by_key: dict[str, int] = {}
    fragments = re.split(
        r"[\r\n]+|[;；](?=\s*[^:：;；\r\n]{1,100}\s*[:：])",
        description,
    )
    for fragment in fragments:
        match = _LINE_PATTERN.match(fragment)
        if match is None:
            continue
        name = re.sub(r"\s+", " ", match.group(1)).strip(" -_：:")
        value = re.sub(r"\s+", " ", match.group(2)).strip()
        normalized_name = description_attribute_key(name)
        if (
            not normalized_name
            or normalized_name in {"http", "https"}
            or not value
            or len(name) > 100
            or len(value) > 4000
        ):
            continue
        existing_index = by_key.get(normalized_name)
        if existing_index is None:
            by_key[normalized_name] = len(result)
            result.append((name, value))
            continue
        previous_name, previous_value = result[existing_index]
        values = [part.strip() for part in re.split(r"[；;]", previous_value) if part.strip()]
        if value not in values:
            result[existing_index] = (previous_name, f"{previous_value}；{value}")
    return tuple(result)


def _attribute_value(row: ProductAttributeRow) -> object:
    for value in (row.value_text, row.value_number, row.value_boolean, row.value_json):
        if value is not None:
            return value
    return None


def _set_text_value(row: ProductAttributeRow, value: str) -> None:
    row.value_text = value
    row.value_number = None
    row.value_boolean = None
    row.value_json = None


class ProductDescriptionAttributeSynchronizer:
    """Cache definitions and values while synchronizing one or many products."""

    def __init__(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        product_ids: set[UUID],
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.definitions = list(
            session.scalars(
                select(AttributeDefinitionRow).where(
                    AttributeDefinitionRow.tenant_id == tenant_id,
                    AttributeDefinitionRow.category_id.is_(None),
                )
            ).all()
        )
        self.definitions_by_name = {
            description_attribute_key(row.display_name): row
            for row in self.definitions
            if row.deleted_at is None
        }
        self.definitions_by_key = {
            row.attribute_key: row
            for row in self.definitions
            if row.deleted_at is None
        }
        self.automatic_definition_ids = {
            row.id
            for row in self.definitions
            if row.deleted_at is None and row.attribute_key.startswith("auto_")
        }
        self.attributes_by_product: dict[
            UUID, dict[UUID, ProductAttributeRow]
        ] = {product_id: {} for product_id in product_ids}
        self.loaded_product_ids: set[UUID] = set()
        if product_ids and self.automatic_definition_ids:
            self._load_products(product_ids)

    def _load_products(self, product_ids: set[UUID]) -> None:
        """Load existing automatic values once, keeping large imports bounded."""

        pending = product_ids - self.loaded_product_ids
        if not pending:
            return
        if self.automatic_definition_ids:
            for row in self.session.scalars(
                select(ProductAttributeRow).where(
                    ProductAttributeRow.tenant_id == self.tenant_id,
                    ProductAttributeRow.product_id.in_(pending),
                    ProductAttributeRow.attribute_definition_id.in_(
                        self.automatic_definition_ids
                    ),
                )
            ).all():
                if row.attribute_definition_id is not None:
                    self.attributes_by_product.setdefault(row.product_id, {})[
                        row.attribute_definition_id
                    ] = row
        self.loaded_product_ids.update(pending)

    def _definition(self, display_name: str) -> tuple[AttributeDefinitionRow, bool]:
        normalized_name = description_attribute_key(display_name)
        definition = self.definitions_by_name.get(normalized_name)
        if definition is None:
            definition = self.definitions_by_key.get(
                description_attribute_definition_key(display_name)
            )
        if definition is not None:
            return definition, False
        definition = AttributeDefinitionRow(
            tenant_id=self.tenant_id,
            category_id=None,
            attribute_key=description_attribute_definition_key(display_name),
            display_name=display_name,
            data_type="TEXT",
            unit_code=None,
            enum_values=None,
            is_required=False,
            is_variant=False,
            is_filterable=True,
            is_matchable=True,
            status="ACTIVE",
            version=1,
        )
        self.session.add(definition)
        self.session.flush()
        self.definitions.append(definition)
        self.definitions_by_name[normalized_name] = definition
        self.definitions_by_key[definition.attribute_key] = definition
        self.automatic_definition_ids.add(definition.id)
        return definition, True

    def sync(
        self,
        product: ProductRow,
        description: str | None,
        *,
        protected_attribute_ids: set[UUID] | None = None,
    ) -> bool:
        """Synchronize auto values without overwriting merchant-confirmed data."""

        protected_ids = protected_attribute_ids or set()
        existing_by_definition = self.attributes_by_product.setdefault(product.id, {})
        changed = False
        desired_definition_ids: set[UUID] = set()
        extracted = extract_description_attributes(description)
        for display_name, _value in extracted:
            definition, created = self._definition(display_name)
            changed = changed or created
            desired_definition_ids.add(definition.id)
        # Definitions may have been created above, so load existing values only
        # after the complete automatic definition set is known.
        self._load_products({product.id})
        existing_by_definition = self.attributes_by_product.setdefault(product.id, {})
        for display_name, value in extracted:
            definition = self.definitions_by_name[description_attribute_key(display_name)]
            attribute = existing_by_definition.get(definition.id)
            if attribute is None:
                attribute = ProductAttributeRow(
                    tenant_id=self.tenant_id,
                    product_id=product.id,
                    attribute_definition_id=definition.id,
                    attribute_key=definition.attribute_key,
                    confidence=Decimal("1"),
                    review_status="AI_SUGGESTED",
                )
                _set_text_value(attribute, value)
                self.session.add(attribute)
                existing_by_definition[definition.id] = attribute
                changed = True
                continue
            if attribute.id in protected_ids or attribute.review_status != "AI_SUGGESTED":
                continue
            if (
                attribute.attribute_key != definition.attribute_key
                or _attribute_value(attribute) != value
            ):
                attribute.attribute_key = definition.attribute_key
                _set_text_value(attribute, value)
                attribute.confidence = Decimal("1")
                changed = True

        for definition_id, attribute in list(existing_by_definition.items()):
            if (
                attribute.id not in protected_ids
                and definition_id in self.automatic_definition_ids
                and definition_id not in desired_definition_ids
                and attribute.review_status == "AI_SUGGESTED"
            ):
                self.session.delete(attribute)
                existing_by_definition.pop(definition_id, None)
                changed = True
        return changed


def sync_product_description_attributes(
    session: Session,
    *,
    tenant_id: UUID,
    product: ProductRow,
    description: str | None,
    protected_attribute_ids: set[UUID] | None = None,
) -> bool:
    synchronizer = ProductDescriptionAttributeSynchronizer(
        session,
        tenant_id=tenant_id,
        product_ids={product.id},
    )
    return synchronizer.sync(
        product,
        description,
        protected_attribute_ids=protected_attribute_ids,
    )
