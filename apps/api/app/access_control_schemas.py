from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


ROLE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")


class TenantPermissionSummary(BaseModel):
    code: str
    module: str
    action: str
    description: str | None


class TenantRoleSummary(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    is_system: bool
    status: str
    permission_codes: list[str]
    member_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class TenantMemberRoleSummary(BaseModel):
    id: UUID
    code: str
    name: str
    is_system: bool


class TenantMemberSummary(BaseModel):
    id: UUID
    user_id: UUID
    display_name: str
    email: str | None
    job_title: str | None
    status: str
    permission_version: int = Field(ge=1)
    roles: list[TenantMemberRoleSummary]
    joined_at: datetime | None
    created_at: datetime


class TenantRoleCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permission_codes: list[str] = Field(min_length=1, max_length=100)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper()
        if not ROLE_CODE_PATTERN.fullmatch(normalized):
            raise ValueError("Role code must use uppercase letters, numbers, or underscores.")
        return normalized

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("permission_codes")
    @classmethod
    def unique_permissions(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Permission codes cannot be blank.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Permission codes must be unique.")
        return normalized


class TenantRoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permission_codes: list[str] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("permission_codes")
    @classmethod
    def unique_permissions(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Permission codes cannot be blank.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Permission codes must be unique.")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> "TenantRoleUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one role field must be provided.")
        return self


class TenantMemberRolesUpdateRequest(BaseModel):
    role_ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("role_ids")
    @classmethod
    def unique_roles(cls, values: list[UUID]) -> list[UUID]:
        if len(set(values)) != len(values):
            raise ValueError("Role identifiers must be unique.")
        return values
