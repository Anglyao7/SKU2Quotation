from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class CatalogShareCreate(BaseModel):
    target_type: Literal["PRODUCTS", "CATEGORY"]
    sku_ids: list[UUID] = Field(default_factory=list, max_length=500)
    category_id: UUID | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "CatalogShareCreate":
        if len(self.sku_ids) != len(set(self.sku_ids)):
            raise ValueError("sku ids must be unique")
        if self.target_type == "PRODUCTS":
            if not self.sku_ids or self.category_id is not None:
                raise ValueError("product shares require sku_ids only")
        elif self.category_id is None or self.sku_ids:
            raise ValueError("category shares require category_id only")
        return self


class CatalogShareResponse(BaseModel):
    id: UUID
    token: str
    target_type: Literal["PRODUCTS", "CATEGORY"]
    title: str
    item_count: int = Field(ge=0)
    category_id: UUID | None = None
    category_name: str | None = None
    category_path: str | None = None
    share_path: str
    store_name: str
    store_logo_url: str | None = None
    created_at: datetime
