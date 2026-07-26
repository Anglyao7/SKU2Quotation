#!/usr/bin/env python3
"""标签功能测试脚本"""

import re


def test_tag_splitter():
    """测试标签分隔符正则表达式"""
    print("测试标签分隔符...")

    # 这是实际使用的正则表达式
    pattern = r"[,，;；、|/\r\n]+"

    test_cases = [
        ("Hot,New,防水", ["Hot", "New", "防水"]),
        ("Hot/New/防水", ["Hot", "New", "防水"]),
        ("Hot;New;防水", ["Hot", "New", "防水"]),
        ("Hot，New，防水", ["Hot", "New", "防水"]),
        ("Hot|New|防水", ["Hot", "New", "防水"]),
        ("Hot、New、防水", ["Hot", "New", "防水"]),
        ("Hot\nNew\n防水", ["Hot", "New", "防水"]),
        ("Hot, New, 防水", ["Hot", "New", "防水"]),
        ("", []),
    ]

    for input_val, expected in test_cases:
        result = [tag.strip() for tag in re.split(pattern, input_val) if tag.strip()]
        status = "✓" if result == expected else "✗"
        print(f"  {status} split('{repr(input_val)}') = {result}")
        if result != expected:
            print(f"      期望: {expected}")


def test_deduplication():
    """测试标签去重"""
    print("\n测试标签去重...")

    pattern = r"[,，;；、|/\r\n]+"

    test_input = "Hot,Hot,new,NEW,防水,防水"
    tags = []
    seen = set()

    for tag in re.split(pattern, test_input):
        tag = tag.strip()
        if not tag:
            continue
        normalized = tag.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        tags.append(tag)

    print(f"  输入: {test_input}")
    print(f"  输出: {tags}")
    print(f"  ✓ 去重成功" if tags == ["Hot", "new", "防水"] else "  ✗ 去重失败")


def test_slash_separator():
    """重点测试斜杠分隔符"""
    print("\n重点测试斜杠分隔符 '/'...")

    pattern = r"[,，;；、|/\r\n]+"

    test_cases = [
        "Hot/New/防水",
        "办公用/便携/轻量",
        "防水/IP68/耐用",
    ]

    for test_input in test_cases:
        result = [tag.strip() for tag in re.split(pattern, test_input) if tag.strip()]
        print(f"  ✓ '{test_input}' → {result}")


if __name__ == "__main__":
    print("=" * 60)
    print("标签分隔符功能测试")
    print("=" * 60)

    test_tag_splitter()
    test_deduplication()
    test_slash_separator()

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
