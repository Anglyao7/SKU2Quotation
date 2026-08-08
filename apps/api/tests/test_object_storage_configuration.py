from unittest.mock import patch

from app.adapters.object_storage import S3ObjectStorageAdapter, get_object_storage


def test_s3_object_storage_reads_cloudflare_credentials_from_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "support-media")
    monkeypatch.setenv(
        "OBJECT_STORAGE_ENDPOINT_URL",
        "https://account-id.r2.cloudflarestorage.com",
    )
    monkeypatch.setenv("OBJECT_STORAGE_REGION", "auto")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY_ID", "r2-access-key")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "r2-secret-key")

    with patch("boto3.client") as client_factory:
        storage = get_object_storage()

    assert isinstance(storage, S3ObjectStorageAdapter)
    client_factory.assert_called_once_with(
        "s3",
        endpoint_url="https://account-id.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id="r2-access-key",
        aws_secret_access_key="r2-secret-key",
    )
