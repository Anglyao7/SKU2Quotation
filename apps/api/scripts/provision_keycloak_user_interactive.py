"""Interactively provision one invited Keycloak user without secret-bearing argv.

Run this through the production one-off Compose service, or from a trusted
operator workstation with an approved private Keycloak administration path.
Administrator and temporary-user passwords are read from the terminal with
echo disabled, kept only in memory, and never sent to the application API.
"""

from __future__ import annotations

import argparse
from getpass import getpass
from urllib.parse import quote, urlparse

import httpx


def _safe_base_url(value: str, *, allow_internal_keycloak_http: bool = False) -> str:
    parsed = urlparse(value.rstrip("/"))
    if parsed.username or parsed.password or not parsed.hostname:
        raise SystemExit("Keycloak URL must not contain credentials.")
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    internal_service = (
        allow_internal_keycloak_http
        and parsed.hostname == "keycloak"
        and parsed.scheme == "http"
        and parsed.port == 8080
    )
    if parsed.scheme != "https" and not (
        (local and parsed.scheme == "http") or internal_service
    ):
        raise SystemExit(
            "Keycloak URL must use HTTPS; HTTP is restricted to localhost or "
            "the explicitly enabled Docker service target."
        )
    return value.rstrip("/")


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    expected: set[int],
    **kwargs: object,
) -> httpx.Response:
    response = client.request(method, url, **kwargs)
    if response.status_code not in expected:
        raise SystemExit(
            f"Keycloak request failed ({response.status_code}); inspect Keycloak audit logs."
        )
    return response


def provision(arguments: argparse.Namespace) -> None:
    base_url = _safe_base_url(
        arguments.server_url,
        allow_internal_keycloak_http=arguments.allow_internal_keycloak_http,
    )
    email = arguments.email.strip().lower()
    display_name = arguments.display_name.strip()
    if email.count("@") != 1 or not display_name:
        raise SystemExit("A valid invited email and non-empty display name are required.")

    admin_password = getpass("Keycloak administrator password: ")
    if not admin_password:
        raise SystemExit("Administrator password is required.")

    with httpx.Client(timeout=15, follow_redirects=False) as client:
        token_response = _request(
            client,
            "POST",
            f"{base_url}/realms/{quote(arguments.admin_realm, safe='')}/protocol/openid-connect/token",
            expected={200},
            data={
                "grant_type": "password",
                "client_id": arguments.admin_client_id,
                "username": arguments.admin_username,
                "password": admin_password,
            },
        )
        access_token = token_response.json().get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SystemExit("Keycloak did not return an administrator access token.")
        headers = {"Authorization": f"Bearer {access_token}"}
        admin_root = f"{base_url}/admin/realms/{quote(arguments.realm, safe='')}"
        lookup = _request(
            client,
            "GET",
            f"{admin_root}/users",
            expected={200},
            headers=headers,
            params={"email": email, "exact": "true"},
        ).json()
        exact = [
            row
            for row in lookup
            if isinstance(row, dict) and str(row.get("email", "")).strip().lower() == email
        ]
        if len(exact) > 1:
            raise SystemExit("Multiple Keycloak users use this email; resolve the ambiguity first.")

        if exact:
            user_id = str(exact[0]["id"])
            print(f"Existing Keycloak identity found for {email}; no password was changed.")
        else:
            temporary_password = getpass("Temporary user password (12+ characters): ")
            confirmation = getpass("Repeat temporary user password: ")
            if temporary_password != confirmation or len(temporary_password) < 12:
                raise SystemExit("Temporary passwords did not match or were shorter than 12 characters.")
            create_response = _request(
                client,
                "POST",
                f"{admin_root}/users",
                expected={201},
                headers=headers,
                json={
                    "username": email,
                    "email": email,
                    "firstName": display_name,
                    "enabled": True,
                    "emailVerified": False,
                    "requiredActions": ["VERIFY_EMAIL", "UPDATE_PASSWORD", "CONFIGURE_TOTP"],
                },
            )
            location = create_response.headers.get("location", "")
            user_id = location.rstrip("/").rsplit("/", 1)[-1]
            if not user_id:
                raise SystemExit("Keycloak created the user but did not return its identifier.")
            _request(
                client,
                "PUT",
                f"{admin_root}/users/{quote(user_id, safe='')}/reset-password",
                expected={204},
                headers=headers,
                json={
                    "type": "password",
                    "value": temporary_password,
                    "temporary": True,
                },
            )
            print(f"Created disabled-by-policy login identity for {email}; emailVerified remains false.")

        if arguments.send_actions_email:
            params: dict[str, str] = {}
            if arguments.login_client_id:
                params["client_id"] = arguments.login_client_id
            if arguments.redirect_uri:
                params["redirect_uri"] = arguments.redirect_uri
            _request(
                client,
                "PUT",
                f"{admin_root}/users/{quote(user_id, safe='')}/execute-actions-email",
                expected={204},
                headers=headers,
                params=params,
                json=["VERIFY_EMAIL", "UPDATE_PASSWORD", "CONFIGURE_TOTP"],
            )
            print("Verification/setup email requested. Login remains blocked until Keycloak verifies it.")
        else:
            print(
                "SMTP action email was not requested. Keep emailVerified=false until an operator "
                "verifies mailbox ownership out of band, records the evidence, and marks it verified "
                "in Keycloak Admin Console. This manual attestation is less auditable than SMTP."
            )


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--server-url",
        required=True,
        help="Keycloak base URL; use HTTPS unless running in the isolated ops network.",
    )
    command.add_argument(
        "--allow-internal-keycloak-http",
        action="store_true",
        help="Allow only the Docker DNS target http://keycloak:8080.",
    )
    command.add_argument("--realm", required=True, help="Application realm")
    command.add_argument("--admin-realm", default="master")
    command.add_argument("--admin-client-id", default="admin-cli")
    command.add_argument("--admin-username", default="admin")
    command.add_argument("--email", required=True, help="Exact email already invited in the SaaS")
    command.add_argument("--display-name", required=True)
    command.add_argument("--send-actions-email", action="store_true")
    command.add_argument("--login-client-id")
    command.add_argument("--redirect-uri")
    return command


def main() -> None:
    provision(parser().parse_args())


if __name__ == "__main__":
    main()
