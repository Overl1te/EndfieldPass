"""Cloud sync and OAuth integration utilities.

This module provides provider-specific helpers for:
1. Building OAuth authorization URLs.
2. Exchanging/refreshing OAuth tokens.
3. Syncing one canonical JSON file to/from cloud storage.

All raised errors use ``CloudIntegrationError`` with user-facing messages.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from urllib.parse import urlencode
from urllib.parse import urlparse

import requests
from django.conf import settings


SYNC_FOLDER_NAME = "EndfieldPass"
SYNC_FILE_NAME = "history-latest.json"
DIRECT_IMPORT_MAX_BYTES = 5 * 1024 * 1024
DIRECT_IMPORT_MAX_REDIRECTS = 5

SYNC_PROVIDER_CHOICES = (
    ("google_drive", "Google Drive"),
)

CLOUD_PROVIDER_CHOICES = (
    ("google_drive", "Google Drive"),
    ("url", "Other (direct JSON URL)"),
)


class CloudIntegrationError(Exception):
    """Raised when cloud import/export or OAuth operation fails."""


def _is_public_ip_address(value: str) -> bool:
    try:
        ip_value = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return bool(ip_value.is_global)


def _validate_direct_import_host(hostname: str):
    host = str(hostname or "").strip().rstrip(".").lower()
    if not host:
        raise CloudIntegrationError("Direct import URL must include host.")
    if host in {"localhost", "localhost.localdomain"}:
        raise CloudIntegrationError("Direct import URL points to local network and is blocked.")
    if host.endswith(".local"):
        raise CloudIntegrationError("Direct import URL points to local network and is blocked.")

    if _is_public_ip_address(host):
        return

    # If host is an IP but not public, block explicitly.
    try:
        ip_value = ipaddress.ip_address(host)
        if not ip_value.is_global:
            raise CloudIntegrationError("Direct import URL points to private network and is blocked.")
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise CloudIntegrationError("Failed to resolve direct import URL host.") from exc

    addresses = {str(info[4][0] or "").strip() for info in infos if info and len(info) > 4 and info[4]}
    if not addresses:
        raise CloudIntegrationError("Failed to resolve direct import URL host.")

    for address in addresses:
        if not _is_public_ip_address(address):
            raise CloudIntegrationError("Direct import URL points to private network and is blocked.")


def _validate_direct_import_url(remote_ref: str):
    parsed = urlparse(str(remote_ref or "").strip())
    if parsed.scheme not in {"https", "http"}:
        raise CloudIntegrationError("Direct import requires URL starting with http:// or https://")
    if parsed.scheme != "https" and not bool(getattr(settings, "DEBUG", False)):
        raise CloudIntegrationError("Direct import via plain HTTP is disabled.")
    if parsed.username or parsed.password:
        raise CloudIntegrationError("Direct import URL with credentials is not allowed.")
    if not parsed.hostname:
        raise CloudIntegrationError("Direct import URL must include host.")
    _validate_direct_import_host(parsed.hostname)
    return parsed


def _extract_error_text(response):
    """Extract the most useful error text from an HTTP response."""
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "").strip()

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or payload.get("message") or "").strip()
        if isinstance(error, str):
            return error.strip()
        return str(payload.get("message") or payload.get("description") or "").strip()
    return ""


def _raise_cloud_error(response, action_message):
    """Raise a normalized CloudIntegrationError from an HTTP response."""
    detail = _extract_error_text(response)
    if detail:
        raise CloudIntegrationError(f"{action_message} (HTTP {response.status_code}): {detail}")
    raise CloudIntegrationError(f"{action_message} (HTTP {response.status_code}).")


def _request(method, url, action_message, **kwargs):
    """Perform an HTTP request and normalize request-level exceptions."""
    try:
        return requests.request(method, url, **kwargs)
    except requests.RequestException as exc:
        raise CloudIntegrationError(f"{action_message}: {exc}") from exc


def _payload_to_json_bytes(payload):
    """Serialize payload to pretty UTF-8 JSON bytes."""
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _json_from_response(response, invalid_json_message):
    """Parse JSON from response and raise CloudIntegrationError on failure."""
    try:
        return response.json()
    except ValueError:
        try:
            return json.loads(response.content.decode("utf-8"))
        except Exception as exc:
            raise CloudIntegrationError(invalid_json_message) from exc


def _normalize_token_payload(payload):
    """Validate and normalize OAuth token payload structure."""
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise CloudIntegrationError("Provider did not return access token.")

    expires_in_raw = payload.get("expires_in")
    try:
        expires_in = int(expires_in_raw or 0)
    except (TypeError, ValueError):
        expires_in = 0

    return {
        "access_token": access_token,
        "refresh_token": str(payload.get("refresh_token") or "").strip(),
        "token_type": str(payload.get("token_type") or "").strip(),
        "expires_in": max(expires_in, 0),
    }


def _normalize_scope(scope, fallback):
    raw_scope = str(scope or "").strip()
    if not raw_scope:
        raw_scope = fallback
    return " ".join(part for part in raw_scope.replace(",", " ").split() if part)


def build_oauth_authorization_url(provider, client_id, redirect_uri, state, scope=""):
    """Build provider OAuth authorization URL."""
    normalized = (provider or "").strip().lower()
    if normalized == "google_drive":
        scope_value = _normalize_scope(scope, "https://www.googleapis.com/auth/drive.file")
        query = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scope_value,
                "state": state,
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    if normalized == "yandex_disk":
        scope_value = _normalize_scope(scope, "cloud_api:disk.app_folder")
        query = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": scope_value,
                "force_confirm": "yes",
            }
        )
        return f"https://oauth.yandex.ru/authorize?{query}"

    raise CloudIntegrationError("Unknown cloud provider.")


def exchange_oauth_code(provider, client_id, client_secret, redirect_uri, code):
    """Exchange OAuth authorization code for access/refresh tokens."""
    normalized = (provider or "").strip().lower()
    if normalized == "google_drive":
        response = _request(
            "POST",
            "https://oauth2.googleapis.com/token",
            "Failed to complete Google Drive OAuth authorization",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=40,
        )
    elif normalized == "yandex_disk":
        response = _request(
            "POST",
            "https://oauth.yandex.ru/token",
            "Failed to complete Yandex Disk OAuth authorization",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
            timeout=40,
        )
    else:
        raise CloudIntegrationError("Unknown cloud provider.")

    if response.status_code >= 300:
        _raise_cloud_error(response, "Provider rejected OAuth authorization")
    return _normalize_token_payload(_json_from_response(response, "Provider returned invalid OAuth response JSON."))


def refresh_oauth_token(provider, client_id, client_secret, refresh_token):
    """Refresh expired access token using refresh token."""
    normalized = (provider or "").strip().lower()
    if not refresh_token:
        raise CloudIntegrationError("Cloud session has expired. Reconnect your account.")

    if normalized == "google_drive":
        response = _request(
            "POST",
            "https://oauth2.googleapis.com/token",
            "Failed to refresh Google Drive OAuth token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=40,
        )
    elif normalized == "yandex_disk":
        response = _request(
            "POST",
            "https://oauth.yandex.ru/token",
            "Failed to refresh Yandex Disk OAuth token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=40,
        )
    else:
        raise CloudIntegrationError("Unknown cloud provider.")

    if response.status_code >= 300:
        _raise_cloud_error(response, "Provider rejected token refresh")
    payload = _normalize_token_payload(_json_from_response(response, "Provider returned invalid token refresh JSON."))
    if not payload["refresh_token"]:
        payload["refresh_token"] = refresh_token
    return payload


def _google_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _google_escape_query(value):
    return str(value or "").replace("\\", "\\\\").replace("'", "\\'")


def _google_find_folder_id(token):
    query = (
        f"name='{_google_escape_query(SYNC_FOLDER_NAME)}' "
        "and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    response = _request(
        "GET",
        "https://www.googleapis.com/drive/v3/files",
        "Failed to list Google Drive folders",
        headers=_google_headers(token),
        params={"q": query, "fields": "files(id,name)", "pageSize": 1},
        timeout=40,
    )
    if response.status_code >= 300:
        _raise_cloud_error(response, "Failed to list Google Drive folders")
    files = (_json_from_response(response, "Google Drive returned invalid folder list JSON.") or {}).get("files") or []
    if files:
        return files[0].get("id", "")
    return ""


def _google_create_folder(token):
    response = _request(
        "POST",
        "https://www.googleapis.com/drive/v3/files",
        "Failed to create Google Drive folder",
        headers={
            **_google_headers(token),
            "Content-Type": "application/json",
        },
        params={"fields": "id,name"},
        data=json.dumps({"name": SYNC_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}),
        timeout=40,
    )
    if response.status_code >= 300:
        _raise_cloud_error(response, "Failed to create Google Drive folder")
    folder_id = (_json_from_response(response, "Google Drive returned invalid folder creation JSON.") or {}).get("id", "")
    if not folder_id:
        raise CloudIntegrationError("Google Drive did not return created folder id.")
    return folder_id


def _google_find_or_create_folder_id(token):
    folder_id = _google_find_folder_id(token)
    if folder_id:
        return folder_id
    return _google_create_folder(token)


def _google_find_file_in_folder(token, folder_id):
    query = (
        f"'{_google_escape_query(folder_id)}' in parents and "
        f"name='{_google_escape_query(SYNC_FILE_NAME)}' and trashed=false"
    )
    response = _request(
        "GET",
        "https://www.googleapis.com/drive/v3/files",
        "Failed to list Google Drive files",
        headers=_google_headers(token),
        params={"q": query, "fields": "files(id,name,modifiedTime)", "orderBy": "modifiedTime desc", "pageSize": 1},
        timeout=40,
    )
    if response.status_code >= 300:
        _raise_cloud_error(response, "Failed to list Google Drive files")
    files = (_json_from_response(response, "Google Drive returned invalid file list JSON.") or {}).get("files") or []
    if files:
        return files[0]
    return None


def _google_find_latest_json_in_folder(token, folder_id):
    query = (
        f"'{_google_escape_query(folder_id)}' in parents and trashed=false "
        "and mimeType!='application/vnd.google-apps.folder'"
    )
    response = _request(
        "GET",
        "https://www.googleapis.com/drive/v3/files",
        "Failed to list Google Drive files",
        headers=_google_headers(token),
        params={"q": query, "fields": "files(id,name,modifiedTime)", "orderBy": "modifiedTime desc", "pageSize": 20},
        timeout=40,
    )
    if response.status_code >= 300:
        _raise_cloud_error(response, "Failed to list Google Drive files")
    files = (_json_from_response(response, "Google Drive returned invalid file list JSON.") or {}).get("files") or []
    for item in files:
        if str(item.get("name") or "").lower().endswith(".json"):
            return item
    return None


def _google_upload_json(token, folder_id, payload):
    file_data = _google_find_file_in_folder(token, folder_id)
    file_id = str(file_data.get("id") or "") if file_data else ""
    metadata = {"name": SYNC_FILE_NAME}
    if not file_id:
        metadata["parents"] = [folder_id]

    files = {
        "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
        "file": (SYNC_FILE_NAME, _payload_to_json_bytes(payload), "application/json"),
    }

    if file_id:
        response = _request(
            "PATCH",
            f"https://www.googleapis.com/upload/drive/v3/files/{file_id}",
            "Failed to update JSON file in Google Drive",
            headers=_google_headers(token),
            params={"uploadType": "multipart", "fields": "id,name,webViewLink,modifiedTime"},
            files=files,
            timeout=60,
        )
    else:
        response = _request(
            "POST",
            "https://www.googleapis.com/upload/drive/v3/files",
            "Failed to upload JSON file to Google Drive",
            headers=_google_headers(token),
            params={"uploadType": "multipart", "fields": "id,name,webViewLink,modifiedTime"},
            files=files,
            timeout=60,
        )

    if response.status_code >= 300:
        _raise_cloud_error(response, "Failed to sync JSON file with Google Drive")

    data = _json_from_response(response, "Google Drive returned invalid file sync JSON.")
    return {
        "provider": "google_drive",
        "folder_name": SYNC_FOLDER_NAME,
        "file_name": data.get("name") or SYNC_FILE_NAME,
        "file_id": data.get("id") or file_id,
        "location": data.get("webViewLink", ""),
    }


def _google_download_json(token, folder_id):
    file_data = _google_find_file_in_folder(token, folder_id)
    if not file_data:
        file_data = _google_find_latest_json_in_folder(token, folder_id)
    if not file_data:
        raise CloudIntegrationError("No JSON file found in Google Drive sync folder.")

    file_id = str(file_data.get("id") or "").strip()
    if not file_id:
        raise CloudIntegrationError("Google Drive returned file without id.")

    response = _request(
        "GET",
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        "Failed to download JSON file from Google Drive",
        headers=_google_headers(token),
        params={"alt": "media"},
        timeout=60,
    )
    if response.status_code >= 300:
        _raise_cloud_error(response, "Failed to download JSON file from Google Drive")
    return _json_from_response(response, "Google Drive JSON file is invalid.")


def _yandex_headers(token):
    return {"Authorization": f"OAuth {token}"}


def _yandex_folder_path():
    return f"app:/{SYNC_FOLDER_NAME}"


def _yandex_file_path():
    return f"{_yandex_folder_path()}/{SYNC_FILE_NAME}"


def _yandex_ensure_folder(token):
    response = _request(
        "PUT",
        "https://cloud-api.yandex.net/v1/disk/resources",
        "Failed to create Yandex Disk folder",
        headers=_yandex_headers(token),
        params={"path": _yandex_folder_path()},
        timeout=40,
    )
    if response.status_code in {201, 409}:
        return
    if response.status_code >= 300:
        _raise_cloud_error(response, "Failed to create Yandex Disk folder")


def _yandex_upload_json(token, payload):
    _yandex_ensure_folder(token)
    file_path = _yandex_file_path()
    upload_meta = _request(
        "GET",
        "https://cloud-api.yandex.net/v1/disk/resources/upload",
        "Failed to get Yandex Disk upload URL",
        headers=_yandex_headers(token),
        params={"path": file_path, "overwrite": "true"},
        timeout=40,
    )
    if upload_meta.status_code >= 300:
        _raise_cloud_error(upload_meta, "Failed to get Yandex Disk upload URL")

    href = (_json_from_response(upload_meta, "Yandex Disk returned invalid upload metadata JSON.") or {}).get("href")
    if not href:
        raise CloudIntegrationError("Yandex Disk did not return upload URL.")

    upload_result = _request(
        "PUT",
        href,
        "Failed to upload JSON file to Yandex Disk",
        data=_payload_to_json_bytes(payload),
        timeout=60,
    )
    if upload_result.status_code >= 300:
        _raise_cloud_error(upload_result, "Failed to upload JSON file to Yandex Disk")

    return {
        "provider": "yandex_disk",
        "folder_name": SYNC_FOLDER_NAME,
        "path": file_path,
        "file_name": SYNC_FILE_NAME,
    }


def _yandex_download_json(token):
    _yandex_ensure_folder(token)
    file_path = _yandex_file_path()
    download_meta = _request(
        "GET",
        "https://cloud-api.yandex.net/v1/disk/resources/download",
        "Failed to get Yandex Disk download URL",
        headers=_yandex_headers(token),
        params={"path": file_path},
        timeout=40,
    )
    if download_meta.status_code >= 300:
        _raise_cloud_error(download_meta, "Failed to get Yandex Disk download URL")

    href = (_json_from_response(download_meta, "Yandex Disk returned invalid download metadata JSON.") or {}).get("href")
    if not href:
        raise CloudIntegrationError("Yandex Disk did not return download URL.")

    download_result = _request(
        "GET",
        href,
        "Failed to download JSON file from Yandex Disk",
        timeout=60,
    )
    if download_result.status_code >= 300:
        _raise_cloud_error(download_result, "Failed to download JSON file from Yandex Disk")
    return _json_from_response(download_result, "Yandex Disk JSON file is invalid.")


def _import_from_direct_url(remote_ref):
    if not remote_ref:
        raise CloudIntegrationError("Provide direct JSON URL.")
    _validate_direct_import_url(remote_ref)

    response = _request(
        "GET",
        remote_ref,
        "Failed to download file by URL",
        timeout=60,
        stream=True,
        allow_redirects=True,
        headers={
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.1",
        },
    )
    if len(response.history or []) > DIRECT_IMPORT_MAX_REDIRECTS:
        raise CloudIntegrationError("Too many redirects while downloading direct JSON URL.")
    for hop in [*(response.history or []), response]:
        _validate_direct_import_url(getattr(hop, "url", ""))
    if response.status_code >= 300:
        _raise_cloud_error(response, "Failed to download file by URL")

    content_type = str((response.headers or {}).get("Content-Type") or "").lower()
    if content_type and ("json" not in content_type and "text/plain" not in content_type):
        raise CloudIntegrationError("URL response content type is not JSON.")

    raw_content = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        raw_content.extend(chunk)
        if len(raw_content) > DIRECT_IMPORT_MAX_BYTES:
            raise CloudIntegrationError("Direct JSON payload is too large.")

    try:
        return json.loads(bytes(raw_content).decode("utf-8"))
    except Exception:
        try:
            return json.loads(bytes(raw_content).decode("utf-8-sig"))
        except Exception as exc:
            raise CloudIntegrationError("URL response is not valid JSON.") from exc


def export_payload_to_cloud(provider, token, payload):
    """Export normalized history payload to provider sync storage."""
    normalized = (provider or "").strip().lower()
    access_token = str(token or "").strip()
    if not access_token:
        raise CloudIntegrationError("No active cloud OAuth session. Connect provider first.")

    if normalized == "google_drive":
        folder_id = _google_find_or_create_folder_id(access_token)
        return _google_upload_json(access_token, folder_id, payload)
    if normalized == "yandex_disk":
        return _yandex_upload_json(access_token, payload)
    raise CloudIntegrationError("Cloud export is not supported for this provider.")


def import_payload_from_cloud(provider, token, remote_ref=""):
    """Import history payload from provider sync storage or direct URL."""
    normalized = (provider or "").strip().lower()
    if normalized == "url":
        return _import_from_direct_url(remote_ref)

    access_token = str(token or "").strip()
    if not access_token:
        raise CloudIntegrationError("No active cloud OAuth session. Connect provider first.")

    if normalized == "google_drive":
        folder_id = _google_find_or_create_folder_id(access_token)
        return _google_download_json(access_token, folder_id)
    if normalized == "yandex_disk":
        return _yandex_download_json(access_token)
    raise CloudIntegrationError("Unknown cloud provider.")
