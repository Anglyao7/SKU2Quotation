from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field, SecretStr, field_validator


class LoginRequest(BaseModel):
    grant_type: Literal["authorization_code"] = "authorization_code"
    provider: str = Field(min_length=1, max_length=50)
    authorization_code: str = Field(min_length=1, max_length=500)
    code_verifier: str = Field(min_length=43, max_length=128)
    redirect_uri: str = Field(min_length=1, max_length=1000)
    nonce: str | None = Field(default=None, min_length=32, max_length=200)
    device_label: str | None = Field(default=None, max_length=120)


class PasswordLoginRequest(BaseModel):
    """A password grant whose secret is verified only by the identity provider."""

    grant_type: Literal["password"]
    identifier: str
    password: SecretStr
    device_label: str | None = Field(default=None, max_length=120)

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 320
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in normalized
            )
        ):
            raise ValueError("identifier is invalid")
        return normalized


def _default_login_grant_type(value: object) -> object:
    """Keep pre-grant_type authorization-code clients backward compatible."""

    if isinstance(value, dict) and "grant_type" not in value:
        return {**value, "grant_type": "authorization_code"}
    return value


AuthLoginRequest = Annotated[
    Annotated[
        LoginRequest | PasswordLoginRequest,
        Field(discriminator="grant_type"),
    ],
    BeforeValidator(_default_login_grant_type),
]


class AuthPublicConfig(BaseModel):
    provider: Literal["local_fake", "enterprise_oidc"]
    client_id: str | None = None
    authorization_endpoint: str | None = None
    end_session_endpoint: str | None = None
    post_logout_redirect_uri: str | None = None
    scopes: list[str] = Field(default_factory=list)
    code_challenge_method: Literal["S256"] = "S256"


class TenantContextRequest(BaseModel):
    membership_id: UUID


class AuthUser(BaseModel):
    id: UUID
    display_name: str
    email: str | None
    is_platform_admin: bool


class AuthContext(BaseModel):
    tenant_id: UUID | None
    membership_id: UUID | None
    tenant_name: str | None
    tenant_slug: str | None
    default_workspace: str | None


class MembershipSummary(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    status: str


class AuthTokenData(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    csrf_token: str
    session_id: UUID
    requires_tenant_selection: bool
    user: AuthUser
    context: AuthContext


class AuthTokenResponse(BaseModel):
    data: AuthTokenData


class MeResponse(BaseModel):
    user: AuthUser
    context: AuthContext
    memberships: list[MembershipSummary]


class PermissionResponse(BaseModel):
    membership_id: UUID
    permission_version: int
    permissions: list[str]
