# 接口与数据格式

## HTTP

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 进程启动成功后返回 `{"status":"ok"}` |
| POST | `/v1/chat` | 认证后执行一轮制度问答或审批查询 |
| GET | `/docs` | FastAPI 交互接口文档 |

### 请求字段

| 字段 | 说明 |
| --- | --- |
| `message` | 必填，去掉首尾空白后长度为 1–1000 |
| `session_id` | 首轮省略。后续传回服务返回的 32 位小写十六进制 ID |
| `as_of` | 可选 ISO 日期。显式字段优先于问题中的 ISO 日期，用于制度查询 |
| `Authorization` | 请求头，格式为 `Bearer <token>` |

### 业务返回

| `kind` | 字段特征 | 客户端行为 |
| --- | --- | --- |
| `policy_answer` | `citations` 有条款原文 | 展示答案和来源，可显示生效日期及版本 |
| `no_evidence` | 无引用 | 提示补充制度范围或改写问题 |
| `need_approval_id` | `tool=null` | 保留会话 ID，提示填写一个有效单号 |
| `approval` | 有 `approval`，`tool.outcome=found` | 展示单号、状态、处理提示和更新时间 |
| `approval_unavailable` | `approval=null` | 请用户核对本人单号 |
| `approval_service_error` | `tool.outcome=error` | 保留会话 ID，稍后可重试 |

返回还包含 `session_id`、`as_of` 和 `answer`。引用字段有 `clause_id`、`title`、`heading`、`version`、`effective_from` 和 `quote`。

| HTTP 状态 | 触发条件 |
| --- | --- |
| 401 | Bearer 缺失或不匹配 |
| 404 | 当前用户无权使用该会话 |
| 409 | 同一会话有另一请求先提交 |
| 422 | 字段或 ISO 日期不符合约束 |
| 503 | 配置的 Qwen 证据服务不可用或返回格式错误 |

查不到本人单据时仍返回 200，并使用业务状态 `approval_unavailable`。

## 扩展示例数据

### 制度

在 `enterprise_agent/data/policies.json` 新增版本或制度。版本的 `policy_id` 保持稳定，`effective_from` 在同一制度内唯一，条款 ID 在同一版本内唯一。人工切分时应把例外条款与其限定的规则保留在同一条。

```json
{
  "policy_id": "TRAINING",
  "title": "培训费报销办法",
  "version": "2026",
  "effective_from": "2026-01-01",
  "roles": ["staff", "finance"],
  "clauses": [
    {
      "id": "D1",
      "heading": "培训报名费",
      "text": "经负责人提前批准的工作培训，报名费凭电子发票报销。",
      "topics": ["培训报名费", "培训费用"]
    }
  ]
}
```

部署了 Milvus 的演示在更改制度后重新运行索引命令。使用本地检索时重启 API 即可加载新条款。

### 单据

`approvals.json` 的单据包含 `id`、`owner`、`status`、`step`、`updated_at`。启动时只补建缺失的示例单据，保留 SQLite 中已有同 ID 的记录。要重复验证一套新演示数据，可以把 `AGENT_RUNTIME_DIR` 指向新的目录。
