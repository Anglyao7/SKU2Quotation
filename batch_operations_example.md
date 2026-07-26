# SKU 批量操作 API 文档

## 概述

为 SKU 商品管理添加了两个批量操作端点：
1. 批量删除 SKU
2. 批量更新 SKU 状态

---

## 1. 批量删除 SKU

### 端点
```
POST /api/product-center/skus/batch-delete
```

### 请求体
```json
{
  "sku_ids": [
    "uuid-1",
    "uuid-2",
    "uuid-3"
  ]
}
```

### 参数说明
- `sku_ids`: UUID 数组，最少 1 个，最多 500 个

### 响应
```json
{
  "success_count": 2,
  "failed_count": 1,
  "total_count": 3,
  "failed_items": [
    {
      "sku_id": "uuid-2",
      "reason": "SKU not found"
    }
  ]
}
```

### 权限要求
- `product_center.write`

### 示例（curl）
```bash
curl -X POST "http://localhost:8000/api/product-center/skus/batch-delete" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sku_ids": [
      "123e4567-e89b-12d3-a456-426614174000",
      "223e4567-e89b-12d3-a456-426614174001"
    ]
  }'
```

---

## 2. 批量更新 SKU 状态

### 端点
```
POST /api/product-center/skus/batch-update-status
```

### 请求体
```json
{
  "sku_ids": [
    "uuid-1",
    "uuid-2"
  ],
  "status": "ACTIVE"
}
```

### 参数说明
- `sku_ids`: UUID 数组，最少 1 个，最多 500 个
- `status`: 状态值，可选：
  - `DRAFT` - 草稿
  - `ACTIVE` - 激活
  - `INACTIVE` - 停用
  - `ARCHIVED` - 归档

### 响应
```json
{
  "success_count": 2,
  "failed_count": 0,
  "total_count": 2,
  "failed_items": []
}
```

### 权限要求
- `product_center.write`

### 示例（curl）
```bash
curl -X POST "http://localhost:8000/api/product-center/skus/batch-update-status" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sku_ids": [
      "123e4567-e89b-12d3-a456-426614174000",
      "223e4567-e89b-12d3-a456-426614174001"
    ],
    "status": "ACTIVE"
  }'
```

---

## 错误处理

### 常见错误

#### 1. 权限不足
```json
{
  "detail": {
    "code": "PERMISSION_REQUIRED",
    "message": "Permission required: product_center.write"
  }
}
```
状态码: `403 Forbidden`

#### 2. 无效状态
```json
{
  "detail": {
    "code": "INVALID_STATUS",
    "message": "Invalid status: INVALID_VALUE"
  }
}
```
状态码: `422 Unprocessable Entity`

#### 3. 关联数据冲突（删除时）
```json
{
  "detail": {
    "code": "BATCH_DELETE_FAILED",
    "message": "批量删除失败，可能存在关联数据"
  }
}
```
状态码: `409 Conflict`

#### 4. 参数验证失败
```json
{
  "detail": [
    {
      "loc": ["body", "sku_ids"],
      "msg": "ensure this value has at least 1 items",
      "type": "value_error"
    }
  ]
}
```
状态码: `422 Unprocessable Entity`

---

## 使用建议

1. **批量大小**：每次请求最多 500 个 SKU ID，如需处理更多，请分批调用
2. **错误处理**：检查响应中的 `failed_items` 数组，了解失败的具体原因
3. **事务性**：批量更新在单个事务中执行，如果整体失败会回滚
4. **部分成功**：删除操作会逐个处理，即使部分失败也会返回成功的数量
5. **审计日志**：状态更新会记录 `updated_by_user_id` 和版本号

---

## 前端集成示例

### React + TypeScript

```typescript
// 批量删除 SKU
async function batchDeleteSkus(skuIds: string[]) {
  const response = await fetch('/api/product-center/skus/batch-delete', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ sku_ids: skuIds }),
  });

  if (!response.ok) {
    throw new Error('批量删除失败');
  }

  return await response.json();
}

// 批量更新状态
async function batchUpdateStatus(skuIds: string[], status: string) {
  const response = await fetch('/api/product-center/skus/batch-update-status', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ 
      sku_ids: skuIds,
      status: status 
    }),
  });

  if (!response.ok) {
    throw new Error('批量更新失败');
  }

  return await response.json();
}

// 使用示例
const result = await batchDeleteSkus([
  '123e4567-e89b-12d3-a456-426614174000',
  '223e4567-e89b-12d3-a456-426614174001',
]);

console.log(`成功删除 ${result.success_count} 个 SKU`);
if (result.failed_count > 0) {
  console.error('失败的项目：', result.failed_items);
}
```

---

## 数据库影响

### 批量删除
- 直接删除 `sku` 表中的记录
- 如果存在外键约束（如关联报价、订单等），会返回冲突错误
- 相关的图片、价格等关联数据的处理取决于外键设置

### 批量更新状态
- 更新 `sku.status` 字段
- 自动更新 `updated_at` 时间戳
- 自动递增 `version` 版本号
- 记录 `updated_by_user_id` 操作人

---

## 性能考虑

- 每个操作在循环中逐个处理，适合中小规模批量操作（< 500）
- 对于超大规模操作，建议考虑异步任务队列
- 使用事务保证数据一致性
- 建议在前端添加进度提示，提升用户体验
