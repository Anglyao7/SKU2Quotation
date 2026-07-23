"""Reconcile the production Keycloak realm through its private Admin API.

The desired realm document is rendered by the host deployment script. Master
administrator credentials are accepted only as two stdin lines (username then
password); they are never accepted through argv or environment variables.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hmac
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import quote

import httpx

from scripts.provision_keycloak_user_interactive import _request, _safe_base_url


REALM_MANAGED_FIELDS = (
    "displayName",
    "enabled",
    "sslRequired",
    "registrationAllowed",
    "registrationEmailAsUsername",
    "loginWithEmailAllowed",
    "duplicateEmailsAllowed",
    "resetPasswordAllowed",
    "rememberMe",
    "bruteForceProtected",
    "permanentLockout",
    "failureFactor",
    "waitIncrementSeconds",
    "maxFailureWaitSeconds",
    "passwordPolicy",
    "otpPolicyType",
    "otpPolicyAlgorithm",
    "otpPolicyDigits",
    "otpPolicyPeriod",
    "eventsEnabled",
    "eventsExpiration",
    "adminEventsEnabled",
    "adminEventsDetailsEnabled",
)
CLIENT_MANAGED_FIELDS = (
    "name",
    "enabled",
    "protocol",
    "publicClient",
    "standardFlowEnabled",
    "directAccessGrantsEnabled",
    "serviceAccountsEnabled",
    "frontchannelLogout",
    "redirectUris",
    "webOrigins",
    "defaultClientScopes",
)
CLIENT_MANAGED_ATTRIBUTES = (
    "pkce.code.challenge.method",
    "post.logout.redirect.uris",
)
BOOTSTRAP_USER_MANAGED_FIELDS = (
    "username",
    "email",
    "enabled",
    "emailVerified",
    "requiredActions",
)


def _desired_configuration(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    realm_name = document.get("realm")
    clients = document.get("clients")
    if realm_name != "atc" or not isinstance(clients, list) or len(clients) != 1:
        raise SystemExit("Rendered Keycloak configuration must contain realm atc and one client.")
    desired_client = clients[0]
    if not isinstance(desired_client, dict) or not desired_client.get("clientId"):
        raise SystemExit("Rendered Keycloak client configuration is invalid.")
    for field in REALM_MANAGED_FIELDS:
        if field not in document:
            raise SystemExit(f"Rendered Keycloak realm is missing managed field {field}.")
    smtp_server = document.get("smtpServer")
    if smtp_server is not None and not isinstance(smtp_server, dict):
        raise SystemExit("Rendered Keycloak SMTP configuration is invalid.")
    for field in CLIENT_MANAGED_FIELDS:
        if field not in desired_client:
            raise SystemExit(f"Rendered Keycloak client is missing managed field {field}.")
    desired_attributes = desired_client.get("attributes")
    if not isinstance(desired_attributes, dict):
        raise SystemExit("Rendered Keycloak client attributes are invalid.")
    for field in CLIENT_MANAGED_ATTRIBUTES:
        if field not in desired_attributes:
            raise SystemExit(f"Rendered Keycloak client is missing managed attribute {field}.")
    secret = desired_client.get("secret")
    if not isinstance(secret, str) or len(secret) < 32:
        raise SystemExit("Rendered Keycloak client secret is invalid.")
    users = document.get("users")
    if not isinstance(users, list) or len(users) != 1 or not isinstance(users[0], dict):
        raise SystemExit("Rendered Keycloak operator email is invalid.")
    desired_user = users[0]
    for field in BOOTSTRAP_USER_MANAGED_FIELDS:
        if field not in desired_user:
            raise SystemExit(f"Rendered Keycloak operator is missing managed field {field}.")
    if (
        not isinstance(desired_user["username"], str)
        or not isinstance(desired_user["email"], str)
        or not isinstance(desired_user["enabled"], bool)
        or not isinstance(desired_user["emailVerified"], bool)
        or not isinstance(desired_user["requiredActions"], list)
    ):
        raise SystemExit("Rendered Keycloak operator configuration is invalid.")
    return document, desired_client


def _stdin_credentials() -> tuple[str, str]:
    values = sys.stdin.read().splitlines()
    if len(values) != 2:
        raise SystemExit("Expected administrator username and password on two stdin lines.")
    username, password = values
    if not username or not password:
        raise SystemExit("Keycloak administrator credentials are required.")
    return username, password


def reconcile(
    *,
    client: httpx.Client,
    base_url: str,
    desired_realm: dict[str, Any],
    desired_client: dict[str, Any],
    admin_username: str,
    admin_password: str,
) -> None:
    token_response = _request(
        client,
        "POST",
        f"{base_url}/realms/master/protocol/openid-connect/token",
        expected={200},
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": admin_username,
            "password": admin_password,
        },
    )
    access_token = token_response.json().get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise SystemExit("Keycloak did not return an administrator access token.")
    headers = {"Authorization": f"Bearer {access_token}"}
    master_realm_path = f"{base_url}/admin/realms/master"
    master_users = _request(
        client,
        "GET",
        f"{master_realm_path}/users",
        expected={200},
        headers=headers,
        params={"username": admin_username, "exact": "true"},
    ).json()
    exact_admins = [
        row
        for row in master_users
        if isinstance(row, dict) and row.get("username") == admin_username
    ]
    if len(exact_admins) != 1 or not exact_admins[0].get("id"):
        raise SystemExit("Expected exactly one Keycloak master administrator.")
    admin_user_path = (
        f"{master_realm_path}/users/{quote(str(exact_admins[0]['id']), safe='')}"
    )
    admin_user = _request(
        client,
        "GET",
        admin_user_path,
        expected={200},
        headers=headers,
    ).json()
    if not isinstance(admin_user, dict):
        raise SystemExit("Keycloak returned an invalid administrator representation.")
    admin_user["email"] = desired_realm["users"][0]["email"]
    admin_user["emailVerified"] = True
    _request(
        client,
        "PUT",
        admin_user_path,
        expected={204},
        headers=headers,
        json=admin_user,
    )

    realm_name = str(desired_realm["realm"])
    realm_path = f"{base_url}/admin/realms/{quote(realm_name, safe='')}"

    current_realm = _request(
        client,
        "GET",
        realm_path,
        expected={200},
        headers=headers,
    ).json()
    if not isinstance(current_realm, dict):
        raise SystemExit("Keycloak returned an invalid realm representation.")
    updated_realm = deepcopy(current_realm)
    for field in REALM_MANAGED_FIELDS:
        updated_realm[field] = desired_realm[field]
    if "smtpServer" in desired_realm:
        updated_realm["smtpServer"] = desired_realm["smtpServer"]
    else:
        updated_realm.pop("smtpServer", None)
    _request(
        client,
        "PUT",
        realm_path,
        expected={204},
        headers=headers,
        json=updated_realm,
    )

    desired_user = desired_realm["users"][0]
    desired_email = str(desired_user["email"]).strip().lower()
    user_rows = _request(
        client,
        "GET",
        f"{realm_path}/users",
        expected={200},
        headers=headers,
        params={"email": desired_email, "exact": "true"},
    ).json()
    exact_users = [
        row
        for row in user_rows
        if isinstance(row, dict)
        and str(row.get("email", "")).strip().lower() == desired_email
    ]
    if len(exact_users) != 1:
        raise SystemExit("Expected exactly one managed Keycloak bootstrap user.")
    user_uuid = str(exact_users[0].get("id", ""))
    if not user_uuid:
        raise SystemExit("Managed Keycloak bootstrap user has no identifier.")
    user_path = f"{realm_path}/users/{quote(user_uuid, safe='')}"
    current_user = _request(
        client,
        "GET",
        user_path,
        expected={200},
        headers=headers,
    ).json()
    if not isinstance(current_user, dict):
        raise SystemExit("Keycloak returned an invalid bootstrap user representation.")
    updated_user = deepcopy(current_user)
    for field in BOOTSTRAP_USER_MANAGED_FIELDS:
        updated_user[field] = desired_user[field]
    _request(
        client,
        "PUT",
        user_path,
        expected={204},
        headers=headers,
        json=updated_user,
    )

    client_id = str(desired_client["clientId"])
    client_rows = _request(
        client,
        "GET",
        f"{realm_path}/clients",
        expected={200},
        headers=headers,
        params={"clientId": client_id},
    ).json()
    exact_clients = [
        row
        for row in client_rows
        if isinstance(row, dict) and row.get("clientId") == client_id
    ]
    if len(exact_clients) != 1:
        raise SystemExit("Expected exactly one managed Keycloak OIDC client.")
    client_uuid = str(exact_clients[0].get("id", ""))
    if not client_uuid:
        raise SystemExit("Managed Keycloak OIDC client has no identifier.")
    client_path = f"{realm_path}/clients/{quote(client_uuid, safe='')}"
    current_client = _request(
        client,
        "GET",
        client_path,
        expected={200},
        headers=headers,
    ).json()
    if not isinstance(current_client, dict):
        raise SystemExit("Keycloak returned an invalid client representation.")
    updated_client = deepcopy(current_client)
    for field in CLIENT_MANAGED_FIELDS:
        updated_client[field] = desired_client[field]
    attributes = dict(current_client.get("attributes") or {})
    for field in CLIENT_MANAGED_ATTRIBUTES:
        attributes[field] = desired_client["attributes"][field]
    updated_client["attributes"] = attributes
    updated_client["secret"] = desired_client["secret"]
    _request(
        client,
        "PUT",
        client_path,
        expected={204},
        headers=headers,
        json=updated_client,
    )

    verified_realm = _request(
        client,
        "GET",
        realm_path,
        expected={200},
        headers=headers,
    ).json()
    for field in REALM_MANAGED_FIELDS:
        verified_value = verified_realm.get(field)
        desired_value = desired_realm[field]
        if verified_value != desired_value:
            raise SystemExit(f"Keycloak realm verification failed for {field}.")
    if "smtpServer" in desired_realm:
        verified_smtp = dict(verified_realm.get("smtpServer") or {})
        desired_smtp = dict(desired_realm["smtpServer"])
        verified_smtp.pop("password", None)
        desired_smtp.pop("password", None)
        if verified_smtp != desired_smtp:
            raise SystemExit("Keycloak realm verification failed for smtpServer.")
    elif verified_realm.get("smtpServer") not in (None, {}):
        raise SystemExit("Keycloak realm verification failed for smtpServer.")
    verified_user = _request(
        client,
        "GET",
        user_path,
        expected={200},
        headers=headers,
    ).json()
    if not isinstance(verified_user, dict):
        raise SystemExit("Keycloak returned an invalid bootstrap user representation.")
    for field in BOOTSTRAP_USER_MANAGED_FIELDS:
        if verified_user.get(field) != desired_user[field]:
            raise SystemExit(f"Keycloak bootstrap user verification failed for {field}.")
    verified_client = _request(
        client,
        "GET",
        client_path,
        expected={200},
        headers=headers,
    ).json()
    for field in CLIENT_MANAGED_FIELDS:
        if verified_client.get(field) != desired_client[field]:
            raise SystemExit(f"Keycloak client verification failed for {field}.")
    verified_attributes = verified_client.get("attributes") or {}
    for field in CLIENT_MANAGED_ATTRIBUTES:
        if verified_attributes.get(field) != desired_client["attributes"][field]:
            raise SystemExit(f"Keycloak client verification failed for {field}.")
    secret_response = _request(
        client,
        "GET",
        f"{client_path}/client-secret",
        expected={200},
        headers=headers,
    ).json()
    current_secret = secret_response.get("value")
    if not isinstance(current_secret, str) or not hmac.compare_digest(
        current_secret,
        str(desired_client["secret"]),
    ):
        raise SystemExit("Keycloak client secret verification failed.")
    if "smtpServer" in desired_realm:
        _request(
            client,
            "POST",
            f"{realm_path}/testSMTPConnection",
            expected={200, 204},
            headers=headers,
            json=desired_realm["smtpServer"],
        )


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--server-url", required=True)
    command.add_argument("--allow-internal-keycloak-http", action="store_true")
    command.add_argument("--realm-config", type=Path, required=True)
    return command


def main() -> None:
    arguments = parser().parse_args()
    base_url = _safe_base_url(
        arguments.server_url,
        allow_internal_keycloak_http=arguments.allow_internal_keycloak_http,
    )
    desired_realm, desired_client = _desired_configuration(arguments.realm_config)
    admin_username, admin_password = _stdin_credentials()
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            reconcile(
                client=client,
                base_url=base_url,
                desired_realm=desired_realm,
                desired_client=desired_client,
                admin_username=admin_username,
                admin_password=admin_password,
            )
    finally:
        admin_password = ""
    print("Keycloak managed realm and OIDC client configuration reconciled.")


if __name__ == "__main__":
    main()
