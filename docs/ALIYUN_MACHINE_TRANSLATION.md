# 阿里云机器翻译接入

系统支持在平台后台的“翻译 API”页面切换以下两种全局翻译服务：

- 阿里云机器翻译（通用版）
- OpenAI 兼容的大模型接口

切换后会立即影响商品语言包、前台即时翻译和客服消息翻译；已经生成的语言包与翻译缓存不会被删除。

## 开通前准备

1. 在阿里云开通机器翻译通用版。
2. 创建仅用于本系统的 RAM 用户，不要使用主账号 AccessKey。
3. 为 RAM 用户创建 AccessKey ID 和 AccessKey Secret。
4. 为 RAM 用户授予以下最小权限：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "alimt:TranslateGeneral",
        "alimt:GetBatchTranslate"
      ],
      "Resource": "*"
    }
  ]
}
```

## 后台配置

平台管理员进入“平台设置 → 翻译 API”，选择“阿里云机器翻译（通用版）”，填写：

- 地域：默认 `cn-hangzhou`
- Endpoint：默认 `mt.cn-hangzhou.aliyuncs.com`
- AccessKey ID
- AccessKey Secret
- 请求超时：默认 20 秒

先点击“测试连接”，成功后再点击“保存并生效”。AccessKey ID 与 Secret 都以密文写入数据库，读取配置的接口只返回末四位提示。

## 批量策略与限制

系统会把商品名称、描述、分类和标签拆成独立字段，并优先调用 `GetBatchTranslate`：

- 每次最多 50 段；
- 单段最多 1,000 字符；
- 单批最多 8,000 字符；
- 较长字段自动改用 `TranslateGeneral`；
- 超过 5,000 字符的单字段会按句子边界切分后翻译。

环境变量仍可作为数据库尚未配置时的回退方式，示例见 `apps/api/.env.example`。
