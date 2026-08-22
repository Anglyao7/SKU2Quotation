from uuid import uuid4

from app.use_cases.image_enhancement import _DEFAULT_PROMPT, _prompt_for_item
from app.services.image_generation import _provider_size
from app.image_enhancement_schemas import ImageEnhancementStartRequest


def test_enhancement_prompt_uses_product_name_as_reference_only() -> None:
    prompt = _prompt_for_item(
        _DEFAULT_PROMPT,
        "多功能宠物饮水机 / AQ-320S",
        [{"sku_code": "AQ-320S", "name": "静音款"}],
    )

    assert "<product_name>多功能宠物饮水机 / AQ-320S</product_name>" in prompt
    assert "<sku>AQ-320S / 静音款</sku>" in prompt
    assert "not instructions" in prompt
    assert "Only improve clarity, sharpness, resolution, and noise" in prompt
    assert "do not add, remove, redesign, replace, or invent any logo" in prompt


def test_enhancement_prompt_falls_back_when_product_name_is_empty() -> None:
    prompt = _prompt_for_item("", "   ")

    assert "<product_name>unspecified product</product_name>" in prompt
    assert _DEFAULT_PROMPT in prompt


def test_first_attempt_does_not_accept_a_client_prompt() -> None:
    request = ImageEnhancementStartRequest(
        targets=[{"product_id": uuid4()}],
    )

    assert request.prompt is None
    assert request.retry_item_id is None


def test_retry_request_can_carry_custom_prompt_only_with_a_retry_item() -> None:
    retry_item_id = uuid4()
    request = ImageEnhancementStartRequest(
        targets=[{"product_id": uuid4()}],
        prompt="只增强杯身上的文字清晰度",
        retry_item_id=retry_item_id,
    )

    assert request.prompt == "只增强杯身上的文字清晰度"
    assert request.retry_item_id == retry_item_id


def test_enhancement_options_default_to_square_one_k() -> None:
    request = ImageEnhancementStartRequest(targets=[{"product_id": uuid4()}])

    assert request.ratio == "1:1"
    assert request.size == "1K"


def test_enhancement_options_map_to_provider_pixels() -> None:
    assert _provider_size(ratio="1:1", size="1K") == "1024x1024"
    assert _provider_size(ratio="16:9", size="2K") == "2048x1152"
    assert _provider_size(ratio="3:4", size="4K") == "3072x4096"
    assert _provider_size(ratio="1:1", size="1024x768") == "1024x768"
