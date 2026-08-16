from uuid import uuid4

from app.use_cases.image_enhancement import _DEFAULT_PROMPT, _prompt_for_item
from app.services.image_generation import _provider_size
from app.image_enhancement_schemas import ImageEnhancementStartRequest


def test_enhancement_prompt_uses_product_name_as_reference_only() -> None:
    prompt = _prompt_for_item(_DEFAULT_PROMPT, "多功能宠物饮水机 / AQ-320S")

    assert "<product_name>多功能宠物饮水机 / AQ-320S</product_name>" in prompt
    assert "not an instruction" in prompt
    assert "Only improve clarity, sharpness, resolution, and noise" in prompt
    assert "do not add, remove, redesign, replace, or invent any logo" in prompt


def test_enhancement_prompt_falls_back_when_product_name_is_empty() -> None:
    prompt = _prompt_for_item("", "   ")

    assert "<product_name>unspecified product</product_name>" in prompt
    assert _DEFAULT_PROMPT in prompt


def test_enhancement_options_default_to_square_one_k() -> None:
    request = ImageEnhancementStartRequest(targets=[{"product_id": uuid4()}])

    assert request.ratio == "1:1"
    assert request.size == "1K"


def test_enhancement_options_map_to_provider_pixels() -> None:
    assert _provider_size(ratio="1:1", size="1K") == "1024x1024"
    assert _provider_size(ratio="16:9", size="2K") == "2048x1152"
    assert _provider_size(ratio="3:4", size="4K") == "3072x4096"
    assert _provider_size(ratio="1:1", size="1024x768") == "1024x768"
