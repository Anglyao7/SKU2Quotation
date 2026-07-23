from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from scripts.reconcile_keycloak_realm import (
    BOOTSTRAP_USER_MANAGED_FIELDS,
    CLIENT_MANAGED_ATTRIBUTES,
    CLIENT_MANAGED_FIELDS,
    REALM_MANAGED_FIELDS,
    _desired_configuration,
    reconcile,
)


def test_desired_configuration_accepts_compact_realm_without_smtp(
    tmp_path: Path,
) -> None:
    realm = {
        "realm": "atc",
        "users": [
            {
                "username": "owner@example.cn",
                "email": "owner@example.cn",
                "enabled": True,
                "emailVerified": True,
                "requiredActions": [],
            }
        ],
        **{field: f"desired-{field}" for field in REALM_MANAGED_FIELDS},
        "clients": [
            {
                "clientId": "atc-web",
                "secret": "a" * 64,
                **{
                    field: f"desired-{field}"
                    for field in CLIENT_MANAGED_FIELDS
                },
                "attributes": {
                    field: f"desired-{field}"
                    for field in CLIENT_MANAGED_ATTRIBUTES
                },
            }
        ],
    }
    path = tmp_path / "compact-realm.json"
    path.write_text(json.dumps(realm), encoding="utf-8")

    desired_realm, desired_client = _desired_configuration(path)

    assert "smtpServer" not in desired_realm
    assert desired_client["clientId"] == "atc-web"


@pytest.mark.parametrize("smtp_enabled", [True, False])
def test_reconcile_updates_only_managed_realm_and_client_configuration(
    smtp_enabled: bool,
) -> None:
    desired_realm = {
        "realm": "atc",
        "users": [
            {
                "username": "owner@example.cn",
                "email": "owner@example.cn",
                "enabled": True,
                "emailVerified": True,
                "requiredActions": [],
            }
        ],
        **{field: f"desired-{field}" for field in REALM_MANAGED_FIELDS},
    }
    desired_realm.update(
        {
            "enabled": True,
            "registrationAllowed": False,
            "eventsEnabled": True,
            "eventsExpiration": 2592000,
            "adminEventsEnabled": True,
            "adminEventsDetailsEnabled": True,
        }
    )
    if smtp_enabled:
        desired_realm["smtpServer"] = {
                "host": "smtp.example.cn",
                "port": "587",
                "from": "no-reply@example.cn",
                "replyTo": "support@example.cn",
                "auth": "true",
                "user": "no-reply@example.cn",
                "password": "smtp-app-password",
                "starttls": "true",
                "ssl": "false",
        }
    desired_client = {
        "clientId": "atc-web",
        "secret": "a" * 64,
        **{field: f"desired-{field}" for field in CLIENT_MANAGED_FIELDS},
        "attributes": {
            field: f"desired-{field}" for field in CLIENT_MANAGED_ATTRIBUTES
        },
    }
    desired_client.update(
        {
            "enabled": True,
            "publicClient": False,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": True,
            "serviceAccountsEnabled": False,
            "frontchannelLogout": True,
            "redirectUris": [
                "https://catalog.example.cn/login/callback",
                "https://catalog.example.cn/login",
            ],
            "webOrigins": ["https://catalog.example.cn"],
            "defaultClientScopes": ["openid", "profile", "email"],
        }
    )
    state = {
        "realm": {
            "id": "atc",
            "realm": "atc",
            "enabled": False,
            "operatorCustomRealmField": "preserved",
            "smtpServer": {"host": "old-smtp.example.cn"},
        },
        "client": {
            "id": "client-uuid",
            "clientId": "atc-web",
            "enabled": False,
            "attributes": {"operator.custom": "preserved"},
        },
        "master_admin": {
            "id": "master-admin-uuid",
            "username": "atc-admin",
            "email": None,
            "emailVerified": False,
        },
        "realm_user": {
            "id": "realm-user-uuid",
            "username": "owner@example.cn",
            "email": "owner@example.cn",
            "enabled": True,
            "emailVerified": False,
            "requiredActions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
            "operatorCustomUserField": "preserved",
        },
    }
    smtp_tests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/realms/master/protocol/openid-connect/token":
            assert b"password=master-secret" in request.content
            return httpx.Response(200, json={"access_token": "admin-token"})
        assert request.headers["authorization"] == "Bearer admin-token"
        if path == "/admin/realms/master/users" and request.method == "GET":
            assert request.url.params["username"] == "atc-admin"
            return httpx.Response(200, json=[state["master_admin"]])
        if (
            path == "/admin/realms/master/users/master-admin-uuid"
            and request.method == "GET"
        ):
            return httpx.Response(200, json=state["master_admin"])
        if (
            path == "/admin/realms/master/users/master-admin-uuid"
            and request.method == "PUT"
        ):
            state["master_admin"] = json.loads(request.content)
            return httpx.Response(204)
        if path == "/admin/realms/atc" and request.method == "GET":
            return httpx.Response(200, json=state["realm"])
        if path == "/admin/realms/atc" and request.method == "PUT":
            state["realm"] = json.loads(request.content)
            return httpx.Response(204)
        if path == "/admin/realms/atc/users" and request.method == "GET":
            assert request.url.params["email"] == "owner@example.cn"
            assert request.url.params["exact"] == "true"
            return httpx.Response(200, json=[state["realm_user"]])
        if (
            path == "/admin/realms/atc/users/realm-user-uuid"
            and request.method == "GET"
        ):
            return httpx.Response(200, json=state["realm_user"])
        if (
            path == "/admin/realms/atc/users/realm-user-uuid"
            and request.method == "PUT"
        ):
            state["realm_user"] = json.loads(request.content)
            return httpx.Response(204)
        if path == "/admin/realms/atc/clients" and request.method == "GET":
            assert request.url.params["clientId"] == "atc-web"
            return httpx.Response(
                200,
                json=[{"id": "client-uuid", "clientId": "atc-web"}],
            )
        if path == "/admin/realms/atc/clients/client-uuid" and request.method == "GET":
            return httpx.Response(200, json=state["client"])
        if path == "/admin/realms/atc/clients/client-uuid" and request.method == "PUT":
            state["client"] = json.loads(request.content)
            return httpx.Response(204)
        if path == "/admin/realms/atc/clients/client-uuid/client-secret":
            return httpx.Response(200, json={"value": desired_client["secret"]})
        if path == "/admin/realms/atc/testSMTPConnection":
            assert smtp_enabled
            assert json.loads(request.content) == desired_realm["smtpServer"]
            smtp_tests.append(json.loads(request.content))
            return httpx.Response(204)
        raise AssertionError(f"unexpected Keycloak request: {request.method} {path}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reconcile(
            client=client,
            base_url="https://identity.example.cn",
            desired_realm=deepcopy(desired_realm),
            desired_client=deepcopy(desired_client),
            admin_username="atc-admin",
            admin_password="master-secret",
        )

    assert state["realm"]["operatorCustomRealmField"] == "preserved"
    assert state["master_admin"]["email"] == "owner@example.cn"
    assert state["master_admin"]["emailVerified"] is True
    assert state["realm_user"]["operatorCustomUserField"] == "preserved"
    for field in BOOTSTRAP_USER_MANAGED_FIELDS:
        assert state["realm_user"][field] == desired_realm["users"][0][field]
    for field in REALM_MANAGED_FIELDS:
        assert state["realm"][field] == desired_realm[field]
    if smtp_enabled:
        assert state["realm"]["smtpServer"] == desired_realm["smtpServer"]
        assert smtp_tests == [desired_realm["smtpServer"]]
    else:
        assert "smtpServer" not in state["realm"]
        assert smtp_tests == []
    assert state["client"]["attributes"]["operator.custom"] == "preserved"
    for field in CLIENT_MANAGED_FIELDS:
        assert state["client"][field] == desired_client[field]
    for field in CLIENT_MANAGED_ATTRIBUTES:
        assert (
            state["client"]["attributes"][field]
            == desired_client["attributes"][field]
        )
    assert state["client"]["secret"] == desired_client["secret"]
