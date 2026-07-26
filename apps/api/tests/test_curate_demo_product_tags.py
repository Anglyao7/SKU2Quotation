from scripts.curate_demo_product_tags import derive_tags


def test_curates_multifunction_book_palette_tags() -> None:
    assert derive_tags(
        product_name="六层中小号书本眼影套装＋唇彩",
        sku_name=None,
        category_name="书本套装",
    ) == ["眼唇彩妆套装", "多合一"]


def test_curates_lip_finish_tags() -> None:
    assert derive_tags(
        product_name="VQ085L亮片变色唇油",
        sku_name=None,
        category_name="唇彩",
    ) == ["唇油", "亮片变色"]
    assert derive_tags(
        product_name="VQ122镜面唇彩",
        sku_name=None,
        category_name="唇彩",
    ) == ["唇彩", "镜面唇妆"]


def test_curates_pet_product_tags_from_grounded_names() -> None:
    assert derive_tags(
        product_name="宠物无线饮水机（不锈钢款）",
        sku_name=None,
        category_name="饮水与喂食",
    ) == ["宠物饮水机", "不锈钢"]
    assert derive_tags(
        product_name="八片带门宠物围栏",
        sku_name=None,
        category_name="围栏与玩具",
    ) == ["宠物围栏", "带门围栏"]


def test_curates_category_fallback_tags_for_code_only_products() -> None:
    assert derive_tags(
        product_name="货号F661",
        sku_name="货号F661",
        category_name="粉底液",
    ) == ["粉底液", "底妆"]
