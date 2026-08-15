"""Interactively provision one invited Keycloak user without secret-bearing argv.

Run this through the production one-off Compose service, or from a trusted
operator workstation with an approved private Keycloak administration path.
Administrator and initial-user passwords are read from the terminal with echo
disabled, kept only in memory, and never sent to the application API.
"""

from __future__ import annotations

import argparse
from getpass import getpass
import re
from urllib.parse import quote, urlparse

import httpx


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
E164_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")
BLOCKING_PASSWORD_ACTIONS = {"UPDATE_PASSWORD", "CONFIGURE_TOTP"}


def _normalized_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        raise SystemExit("A valid invited email is required.")
    return email


def _login_identifier(value: str | None, *, invited_email: str) -> str:
    identifier = (value or invited_email).strip()
    if "@" in identifier:
        normalized = _normalized_email(identifier)
        if normalized != invited_email:
            raise SystemExit("An email login identifier must match the invited email.")
        return normalized
    if not E164_PATTERN.fullmatch(identifier):
        raise SystemExit(
            "Login identifier must be the invited email or an E.164 phone number."
        )
    return identifier


def _valid_password(value: str, *identity_candidates: str) -> bool:
    del identity_candidates
    return len(value) == 6 and value.isascii() and value.isdigit()


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
    email = _normalized_email(arguments.email)
    username = _login_identifier(arguments.username, invited_email=email)
    display_name = arguments.display_name.strip()
    if not display_name:
        raise SystemExit("A non-empty display name is required.")

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

        username_lookup = _request(
            client,
            "GET",
            f"{admin_root}/users",
            expected={200},
            headers=headers,
            params={"username": username, "exact": "true"},
        ).json()
        username_conflicts = [
            row
            for row in username_lookup
            if isinstance(row, dict)
            and str(row.get("username", "")).casefold() == username.casefold()
            and str(row.get("email", "")).strip().lower() != email
        ]
        if username_conflicts:
            raise SystemExit("The requested login identifier already belongs to another user.")

        email_verified = bool(arguments.email_verified)
        if exact:
            user_id = str(exact[0]["id"])
            user_path = f"{admin_root}/users/{quote(user_id, safe='')}"
            current_user = _request(
                client,
                "GET",
                user_path,
                expected={200},
                headers=headers,
            ).json()
            if not isinstance(current_user, dict):
                raise SystemExit("Keycloak returned an invalid user representation.")
            email_verified = email_verified or current_user.get("emailVerified") is True
            required_actions = [
                action
                for action in current_user.get("requiredActions", [])
                if action not in BLOCKING_PASSWORD_ACTIONS
                and (action != "VERIFY_EMAIL" or not email_verified)
            ]
            if not email_verified and "VERIFY_EMAIL" not in required_actions:
                required_actions.append("VERIFY_EMAIL")
            current_user.update(
                {
                    "username": username,
                    "email": email,
                    "enabled": True,
                    "emailVerified": email_verified,
                    "requiredActions": required_actions,
                }
            )
            _request(
                client,
                "PUT",
                user_path,
                expected={204},
                headers=headers,
                json=current_user,
            )
            print(
                f"Existing Keycloak identity updated for {email}; "
                "its password was not changed."
            )
        else:
            initial_password = getpass("Initial user password: ")
            confirmation = getpass("Repeat initial user password: ")
            if initial_password != confirmation or not _valid_password(
                initial_password,
                username,
                email,
                email.split("@", 1)[0],
            ):
                raise SystemExit(
                    "Passwords must match and contain exactly six ASCII digits."
                )
            create_response = _request(
                client,
                "POST",
                f"{admin_root}/users",
                expected={201},
                headers=headers,
                json={
                    "username": username,
                    "email": email,
                    "firstName": display_name,
                    "enabled": True,
                    "emailVerified": email_verified,
                    "requiredActions": [] if email_verified else ["VERIFY_EMAIL"],
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
                    "value": initial_password,
                    "temporary": False,
                },
            )
            print(f"Created Keycloak password identity for {email}.")

        if arguments.send_actions_email and not email_verified:
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
                json=["VERIFY_EMAIL"],
            )
            print("Verification email requested. Login remains blocked until Keycloak verifies it.")
        elif not email_verified:
            print(
                "SMTP action email was not requested. Keep emailVerified=false until an operator "
                "verifies mailbox ownership out of band, records the evidence, and marks it verified "
                "in Keycloak Admin Console. This manual attestation is less auditable than SMTP."
            )
        else:
            print("Email ownership is recorded as verified; direct password login is enabled.")


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
    command.add_argument(
        "--username",
        help="Login name: the invited email or an E.164 phone number",
    )
    command.add_argument("--display-name", required=True)
    command.add_argument(
        "--email-verified",
        action="store_true",
        help="Operator attests that mailbox ownership was verified out of band",
    )
    command.add_argument("--send-actions-email", action="store_true")
    command.add_argument("--login-client-id")
    command.add_argument("--redirect-uri")
    return command


def main() -> None:
    provision(parser().parse_args())


if __name__ == "__main__":
    main()
