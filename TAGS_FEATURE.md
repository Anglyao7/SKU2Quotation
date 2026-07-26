# 商品标签功能实现总结

## 📋 概述

已完成商品标签统一管理功能的实现，包括后端 API、数据库模型、前端管理界面，并更新了 Excel 导入分隔符。

---

## ✅ 已完成的工作

### 1. 标签分隔符更新

**文件：** `apps/api/app/services/import_service.py`

- ✅ 在现有分隔符基础上添加了 `/` 作为标签分隔符
- 支持的分隔符：`,`、`，`、`;`、`/`、换行符等

```python
TAG_SPLITTERS = [
    ",",      # 英文逗号
    "，",     # 中文逗号
    ";",      # 分号
    "/",      # 斜杠 (新增)
    "\n",     # 换行
    "\r\n",   # Windows 换行
]
```

### 2. 数据库模型与服务

#### 数据库表结构

**文件：** `apps/api/app/models.py`

新增 `ProductTag` 模型：

```python
class ProductTag(Base):
    __tablename__ = "product_tags"
    
    id: UUID                           # 主键
    tenant_id: UUID                    # 租户 ID
    name: str                          # 标签显示名称
    normalized_name: str               # 规范化名称（小写，用于去重）
    description: str | None            # 标签说明
    category: str | None               # 标签分类
    usage_count: int                   # 使用次数
    created_at: datetime
    updated_at: datetime
```

**唯一约束：** `(tenant_id, normalized_name)` - 每个租户内标签名称唯一（不区分大小写）

#### 标签服务

**文件：** `apps/api/app/services/tag_service.py`

核心功能：

- `get_or_create_tags()` - 批量获取或创建标签，自动去重和规范化
- `list_tags()` - 列出标签，支持分类筛选和分页
- `update_tag()` - 更新标签信息
- `delete_tag()` - 删除标签
- `increment_usage()` - 增加使用计数
- `decrement_usage()` - 减少使用计数

**特性：**
- 自动规范化（小写、去空格）
- 自动去重（同一租户内标签名不区分大小写）
- 使用计数自动维护

### 3. API 路由

**文件：** `apps/api/app/routers/tags.py`

提供完整的 RESTful API：

| 方法 | 路径 | 功能 | 权限要求 |
|------|------|------|----------|
| GET | `/api/tags` | 列出所有标签 | 需要登录 |
| POST | `/api/tags` | 创建新标签 | 需要登录 |
| PATCH | `/api/tags/{tag_id}` | 更新标签 | 需要登录 |
| DELETE | `/api/tags/{tag_id}` | 删除标签 | 需要登录 |

**查询参数：**
- `category` - 按分类筛选
- `limit` - 每页数量（默认 200，最大 500）
- `offset` - 偏移量

**已注册到：** `apps/api/app/main.py`

### 4. 数据库迁移

**文件：** `apps/api/migrations/versions/20260726_0033_product_tags_management.py`

- ✅ 创建 `product_tags` 表
- ✅ 添加唯一约束和索引
- ✅ 支持回滚

**运行迁移：**
```bash
cd apps/api
alembic upgrade head
```

### 5. 前端管理界面

#### 标签管理页面

**文件：** `apps/web/src/pages/console/TagManagementPage.tsx`

**功能特性：**
- ✅ 标签列表展示（表格形式）
- ✅ 按分类筛选
- ✅ 创建新标签
- ✅ 编辑标签信息
- ✅ 删除标签（带使用次数警告）
- ✅ 显示使用次数统计
- ✅ 响应式设计
- ✅ 错误处理和加载状态

**标签分类：**
- 不分类
- 状态标签（Hot、New、Sale）
- 特性标签（防水、耐用、便携）
- 场景标签（办公用、家用、工业用）
- 优势标签（高性价比、畅销）

#### 路由配置

**文件：** `apps/web/src/App.tsx`

- ✅ 添加路由：`/console/products/tags`
- ✅ 权限保护：`product.edit`
- ✅ 懒加载支持

#### 导航菜单

**文件：** `apps/web/src/pages/console/ConsoleLayout.tsx`

- ✅ 在"商品"分组下添加"标签管理"菜单项
- ✅ 使用 `Tag` 图标
- ✅ 权限控制：`product.edit`

### 6. 前端构建验证

- ✅ TypeScript 编译通过
- ✅ Vite 构建成功
- ✅ 无运行时错误

---

## 🎯 标签在 RAG 搜索中的作用

### 权重分配

从 `apps/api/app/services/hybrid_search.py` 可以看到标签占 **12%** 的权重：

```python
WEIGHTS = {
    "keyword": 0.32,      # 关键词匹配
    "semantic": 0.45,     # 语义相似度
    "attribute": 0.06,    # 产品属性
    "tag": 0.12,          # 标签匹配 👈
    "supplier": 0.05,     # 供应商评分
}
```

### 标签匹配算法

`_score_tag_relevance` 函数实现了智能匹配：

1. **完全匹配** - 得分 1.0
2. **包含匹配** - 得分 0.55-0.95
3. **反向包含** - 得分 0.90
4. **分词匹配** - 基于 token 覆盖率
5. **字符覆盖** - 中文字符匹配

### 使用场景示例

| 用户搜索 | 匹配标签 | 效果 |
|---------|---------|------|
| "你们卖得最好的产品" | Hot、畅销、爆款 | 提高排名 |
| "最新上架的" | New、新品推荐 | 精确匹配 |
| "性价比高的办公用品" | 高性价比、办公用 | 组合匹配 |
| "防水的设备" | 防水、IP68 | 特性匹配 |

---

## 📝 使用指南

### Excel 导入标签格式

在 Excel 模板的"标签"列（第 7 列）中填入标签，支持多种分隔符：

```csv
商品名称,商品分类,商品型号,商品价格,商品描述,备注,标签
工业级防水接线盒,电气配件/接线盒,JXH-A001,45.80,IP68防护等级,,Hot,防水,IP68,耐用,工业用
便携式蓝牙音箱,电子产品/音响,BT-S200,128.00,支持NFC快速配对,,New/便携/高性价比/畅销
办公椅,家具/椅子,OC-3000,580.00,人体工学设计,,办公用;舒适;可调节
```

支持的分隔符：`,`、`，`、`;`、`/`、换行

### 前端管理

1. 登录控制台
2. 导航至：**商品 → 标签管理**
3. 可以：
   - 创建新标签
   - 编辑标签（名称、分类、说明）
   - 删除标签（会提示使用次数）
   - 按分类筛选
   - 查看使用统计

### 推荐的标签策略

**状态标签：**
- Hot（热销）
- New（新品）
- Sale（促销）
- Limited（限量）

**特性标签：**
- 防水、耐用、便携、轻量
- 静音、节能、快充
- 易安装、免维护、可定制

**场景标签：**
- 办公用、家用、工业用
- 户外、室内
- 批发推荐、企业采购、礼品定制

**优势标签：**
- 高性价比、品质保证、快速发货
- 畅销款、爆款、口碑产品

---

## ⚠️ 注意事项

1. **标签数量限制：** 每个商品最多 20 个标签
2. **标签长度限制：** 每个标签最长 80 字符，建议 2-8 字符
3. **自动去重：** 系统会自动去除重复标签（不区分大小写）
4. **与分类区分：** 
   - 分类是结构化的层级关系
   - 标签是扁平的属性描述
5. **删除警告：** 删除已使用的标签时会显示警告

---

## 🚀 部署步骤

### 后端部署

```bash
# 1. 运行数据库迁移
cd apps/api
source .venv/bin/activate
alembic upgrade head

# 2. 重启 API 服务
# Docker: docker-compose restart api
# 或手动重启 uvicorn
```

### 前端部署

```bash
# 1. 构建前端
cd apps/web
npm run build

# 2. 部署 dist 目录到 Web 服务器
# 或重启容器：docker-compose restart web
```

---

## 🧪 测试建议

1. **创建标签测试：**
   - 创建不同分类的标签
   - 测试中文和英文标签
   - 测试重复标签（应被去重）

2. **Excel 导入测试：**
   - 使用不同分隔符导入
   - 验证标签自动创建
   - 检查使用计数是否正确

3. **RAG 搜索测试：**
   - 搜索带标签关键词的查询
   - 对比有无标签的排名差异
   - 验证语义匹配效果

4. **删除测试：**
   - 删除未使用的标签
   - 删除已使用的标签（应有警告）

---

## 📊 数据库结构

```sql
CREATE TABLE product_tags (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    normalized_name VARCHAR(80) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    usage_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE (tenant_id, normalized_name)
);

CREATE INDEX idx_product_tags_tenant_name ON product_tags(tenant_id, normalized_name);
```

---

## 🎨 UI 截图描述

**标签管理页面包含：**
- 页面标题和说明
- 新建标签按钮
- 分类筛选下拉框
- 标签总数统计
- 标签列表表格：
  - 标签名称（蓝色徽章）
  - 分类（灰色徽章）
  - 说明
  - 使用次数（绿色徽章）
  - 操作按钮（编辑、删除）

**创建/编辑对话框：**
- 标签名称（必填）
- 标签分类（可选下拉）
- 标签说明（可选文本域）
- 提示信息

**删除确认对话框：**
- 显示标签名称
- 使用次数警告（红色）

---

## 📚 相关文件清单

### 后端文件
- `apps/api/app/models.py` - 数据模型
- `apps/api/app/services/tag_service.py` - 标签服务
- `apps/api/app/services/import_service.py` - Excel 导入（更新分隔符）
- `apps/api/app/routers/tags.py` - API 路由
- `apps/api/app/main.py` - 路由注册
- `apps/api/migrations/versions/20260726_0033_product_tags_management.py` - 数据库迁移

### 前端文件
- `apps/web/src/pages/console/TagManagementPage.tsx` - 标签管理页面
- `apps/web/src/pages/console/ConsoleLayout.tsx` - 导航菜单更新
- `apps/web/src/App.tsx` - 路由配置

---

## ✨ 下一步建议

1. **批量操作：** 添加批量删除、批量分类功能
2. **标签合并：** 允许合并相似标签
3. **标签推荐：** 根据商品描述推荐标签
4. **使用分析：** 展示标签使用趋势图表
5. **导出功能：** 导出标签使用报表

---

完成日期：2026-07-26
版本：v1.0
