# 企业知识库与审批查询 Agent

面向费用报销场景的中文 Agent。员工可以询问制度并查看带版本的条款，也可以查询本人报销单的审批进度。项目使用虚构制度和模拟单据，适合本地演示、学习与面试讲解。

## 可以演示什么

| 场景 | 示例 | 核对点 |
| --- | --- | --- |
| 制度问答 | 去北京出差，酒店住宿标准是多少？ | 返回制度名、版本、条款编号和完整原文 |
| 历史版本 | 截至2024-06-01，去北京出差酒店住宿标准是多少？ | 返回 2024 版每晚 500 元，现行示例为 600 元 |
| 权限过滤 | 财务内审抽样比例是多少？ | 员工证据不足，财务角色可引用内审条款 |
| 补齐单号 | 查一下我的报销审批进度 → BX-1001 | 复用会话 ID，拿到单号后调用 MCP |
| 本人范围 | Alice 查询 BX-2002 | 返回通用提示，同未找到单据的反馈一致 |
| 无答案 | 宠物住院费用可以报销吗？ | 明确表示制度证据不足 |

## 本地启动

需要 Python 3.11 或更新版本。以下示例在项目根目录执行。默认演示使用 CPU 和 SQLite，安装依赖后可离线运行。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
$env:AGENT_DEMO = "1"
.\.venv\Scripts\python.exe -m uvicorn enterprise_agent.api:create_app --factory --host 127.0.0.1 --port 8000
```

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
AGENT_DEMO=1 .venv/bin/python -m uvicorn enterprise_agent.api:create_app --factory --host 127.0.0.1 --port 8000
```

启动后在浏览器打开 `http://127.0.0.1:8000/docs`。点 **Authorize** 输入 `demo-alice`，再展开 `POST /v1/chat`。这两个演示令牌只应在本机使用。

| 演示令牌 | 身份 | 本人单据 |
| --- | --- | --- |
| `demo-alice` | 员工 Alice | `BX-1001`、`BX-1002` |
| `demo-bob` | 财务 Bob | `BX-2002`、`BX-2003` |

## 调用示例

在另一个 PowerShell 窗口执行。演示中第一条消息没给单号，第二条消息传回同一个 `session_id`。

```powershell
$uri = "http://127.0.0.1:8000/v1/chat"
$headers = @{ Authorization = "Bearer demo-alice" }
$first = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers `
  -ContentType "application/json; charset=utf-8" `
  -Body (@{ message = "查一下我的报销审批进度" } | ConvertTo-Json -Compress)
$second = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers `
  -ContentType "application/json; charset=utf-8" `
  -Body (@{ session_id = $first.session_id; message = "BX-1001" } | ConvertTo-Json -Compress)
$first.answer
$second | ConvertTo-Json -Depth 6
```

预期第一轮返回 `kind=need_approval_id`，`tool=null`。第二轮返回 `kind=approval`，单据状态为「财务复核中」，`tool.outcome=found`。

问制度时只需发送下面的 JSON。可以省略 `as_of` 使用服务器当前日期，也可以在问题里写「截至 YYYY-MM-DD」。

```json
{
  "message": "国内出差的一线城市酒店住宿标准是多少？",
  "as_of": "2024-06-01"
}
```

## 实现与文档

- [架构与权限设计](docs/architecture.md) 讲解切块、版本、混合检索、证据校验、MCP 和会话状态。
- [评测说明和实测结果](docs/evaluation.md) 给出同题对比、计算口径和数据局限。
- [启用 Milvus、BGE 和 Qwen](docs/model-backends.md) 给出可选后端的配置和验证步骤。
- [接口与数据格式](docs/api.md) 包含字段、返回类型、状态码和扩充样例。

运行测试和评测时使用虚拟环境里的 Python：

```text
python -m pytest -q
python -m enterprise_agent.evaluate
python -m enterprise_agent.evaluate --json
```

`enterprise_agent/data/` 包含制度、单据和带标签的测试题。`tests/` 覆盖版本隔离、条款权限、会话恢复、未授权单据与证据校验。项目演示使用 FastAPI、LangGraph、SQLite 和真实的 MCP stdio 客户端与服务进程。Milvus、BGE 和 Qwen 均可通过环境变量启用，当前结果来自本地演示路径。
