from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest

from app.services.qwen_batch_translation import (
    DEFAULT_QWEN_BATCH_MODEL,
    QWEN_BATCH_REQUEST_MAX_ITEMS,
    QwenBatchClient,
    QwenBatchConfiguration,
    qwen_batch_api_base_url,
    qwen_batch_translation_requests,
)
from app.services.translation import TranslationProviderError


JOB_ID = UUID("11111111-2222-3333-4444-555555555555")


def _configuration() -> QwenBatchConfiguration:
    return QwenBatchConfiguration(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        api_key="sk-test-secret",
        timeout_seconds=20,
        max_tokens=16_384,
    )


def test_qwen_batch_base_url_accepts_chat_or_v1_forms() -> None:
    expected = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert qwen_batch_api_base_url(expected, production=True) == expected
    assert (
        qwen_batch_api_base_url(
            f"{expected}/chat/completions",
            production=True,
        )
        == expected
    )


def test_qwen_batch_requests_are_deterministic_and_bounded() -> None:
    first = qwen_batch_translation_requests(
        {"zh-CN": ["甲" * 6, "乙" * 6, "丙", "甲" * 6]},
        job_id=JOB_ID,
        max_items=2,
        max_characters=10,
    )
    second = qwen_batch_translation_requests(
        {"zh-CN": ["甲" * 6, "乙" * 6, "丙", "甲" * 6]},
        job_id=JOB_ID,
        max_items=2,
        max_characters=10,
    )
    assert first == second
    assert [row["values"] for row in first] == [
        ["甲" * 6],
        ["乙" * 6, "丙"],
    ]
    assert len({row["custom_id"] for row in first}) == len(first)


def test_qwen_batch_default_layout_exposes_hundreds_of_file_requests() -> None:
    requests = qwen_batch_translation_requests(
        {"zh-CN": [f"待翻译字段 {index}" for index in range(3_980)]},
        job_id=JOB_ID,
    )

    assert QWEN_BATCH_REQUEST_MAX_ITEMS == 20
    assert len(requests) == 199
    assert max(len(row["values"]) for row in requests) == 20
    assert sum(len(row["values"]) for row in requests) == 3_980


def test_qwen_batch_jsonl_uses_flash_and_disables_thinking() -> None:
    client = QwenBatchClient(
        _configuration(),
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: None)),
    )
    requests = qwen_batch_translation_requests(
        {"zh-CN": ["智能宠物喂食器 SF-6L20", "颜色"]},
        job_id=JOB_ID,
    )
    line = json.loads(client.jsonl_content(requests, target_locale="en-US"))
    assert line["url"] == "/v1/chat/completions"
    assert line["body"]["model"] == DEFAULT_QWEN_BATCH_MODEL
    assert line["body"]["enable_thinking"] is False
    assert line["body"]["temperature"] == 0
    assert "reasoning_effort" not in line["body"]
    assert "[[ATCK_00000]]" in line["body"]["messages"][1]["content"]


def test_qwen_batch_lifecycle_and_result_mapping() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/files"):
            assert request.headers["authorization"] == "Bearer sk-test-secret"
            assert b'name="purpose"' in request.read()
            return httpx.Response(200, json={"id": "file-batch-input"})
        if request.method == "GET" and request.url.path.endswith("/batches"):
            assert request.url.params["input_file_ids"] == "file-batch-input"
            return httpx.Response(200, json={"data": []})
        if request.method == "POST" and request.url.path.endswith("/batches"):
            payload = json.loads(request.read())
            assert payload["input_file_id"] == "file-batch-input"
            assert payload["completion_window"] == "24h"
            return httpx.Response(
                200,
                json={
                    "id": "batch-test",
                    "status": "validating",
                    "input_file_id": "file-batch-input",
                    "output_file_id": None,
                    "error_file_id": None,
                    "request_counts": {"total": 0, "completed": 0, "failed": 0},
                },
            )
        if request.method == "GET" and request.url.path.endswith("/batches/batch-test"):
            return httpx.Response(
                200,
                json={
                    "id": "batch-test",
                    "status": "completed",
                    "input_file_id": "file-batch-input",
                    "output_file_id": "file-batch-output",
                    "error_file_id": None,
                    "request_counts": {"total": 1, "completed": 1, "failed": 0},
                },
            )
        if request.method == "GET" and request.url.path.endswith(
            "/files/file-batch-output/content"
        ):
            result = {
                "custom_id": batch_requests[0]["custom_id"],
                "response": {
                    "status_code": 200,
                    "body": {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {
                                    "content": json.dumps(
                                        [
                                            "Smart pet feeder [[ATCK_00000]]",
                                            "Color",
                                        ]
                                    )
                                },
                            }
                        ]
                    },
                },
                "error": None,
            }
            return httpx.Response(
                200,
                content=(json.dumps(result) + "\n").encode(),
            )
        if request.method == "DELETE" and "/files/" in request.url.path:
            return httpx.Response(200, json={"deleted": True})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    batch_requests = qwen_batch_translation_requests(
        {"zh-CN": ["智能宠物喂食器 SF-6L20", "颜色"]},
        job_id=JOB_ID,
    )
    client = QwenBatchClient(
        _configuration(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    file_id = client.upload_jsonl(
        client.jsonl_content(batch_requests, target_locale="en-US"),
        filename="catalog.jsonl",
    )
    assert client.find_batch(file_id) is None
    created = client.create_batch(
        file_id,
        name="test",
        description="test batch",
    )
    assert created.id == "batch-test"
    completed = client.retrieve_batch(created.id)
    assert completed.status == "completed"
    result = client.parse_output(
        client.download_file(completed.output_file_id or ""),
        batch_requests,
        target_locale="en-US",
    )
    assert result.translations_by_locale == {
        "zh-CN": {
            "智能宠物喂食器 SF-6L20": "Smart pet feeder SF-6L20",
            "颜色": "Color",
        }
    }
    assert result.processed_values == 2
    assert result.failures == ()
    assert client.delete_file(file_id) is True
    assert ("POST", "/compatible-mode/v1/batches") in seen


def test_qwen_batch_can_cancel_provider_work() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/batches/batch-running/cancel")
        return httpx.Response(
            200,
            json={
                "id": "batch-running",
                "status": "cancelling",
                "input_file_id": "file-batch-input",
                "output_file_id": None,
                "error_file_id": None,
                "request_counts": {
                    "total": 199,
                    "completed": 12,
                    "failed": 0,
                },
            },
        )

    client = QwenBatchClient(
        _configuration(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    cancelled = client.cancel_batch("batch-running")

    assert cancelled.status == "cancelling"
    assert cancelled.total_requests == 199
    assert cancelled.completed_requests == 12


def test_qwen_batch_empty_task_list_accepts_null_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/batches")
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": None,
                "first_id": None,
                "last_id": None,
                "has_more": False,
            },
        )

    client = QwenBatchClient(
        _configuration(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.find_batch("file-batch-without-task") is None


def test_qwen_batch_rejects_unknown_result_identity() -> None:
    client = QwenBatchClient(
        _configuration(),
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: None)),
    )
    requests = qwen_batch_translation_requests(
        {"zh-CN": ["颜色"]},
        job_id=JOB_ID,
    )
    content = json.dumps(
        {
            "custom_id": "some-other-request",
            "response": {"status_code": 200, "body": {}},
        }
    ).encode()
    with pytest.raises(TranslationProviderError, match="unknown custom_id"):
        client.parse_output(content, requests, target_locale="en-US")


def test_qwen_batch_salvages_valid_rows_and_reports_only_invalid_subset() -> None:
    client = QwenBatchClient(
        _configuration(),
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: None)),
    )
    requests = qwen_batch_translation_requests(
        {"zh-CN": ["颜色", "尺寸"]},
        job_id=JOB_ID,
        max_items=1,
    )
    valid = {
        "custom_id": requests[0]["custom_id"],
        "response": {
            "status_code": 200,
            "body": {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(["Color"])},
                    }
                ]
            },
        },
    }
    invalid = {
        "custom_id": requests[1]["custom_id"],
        "response": {
            "status_code": 200,
            "body": {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps([])},
                    }
                ]
            },
        },
    }
    content = (json.dumps(valid) + "\n" + json.dumps(invalid) + "\n").encode()

    result = client.parse_output(content, requests, target_locale="en-US")

    assert result.translations_by_locale == {"zh-CN": {"颜色": "Color"}}
    assert result.processed_values == 1
    assert result.failed_values == 1
    assert [failure.custom_id for failure in result.failures] == [
        requests[1]["custom_id"]
    ]
