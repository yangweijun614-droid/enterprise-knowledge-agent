# 可选模型与 Milvus

默认演示使用本地检索和抽取式回答。下面的配置用于接入真实模型或 Milvus 实例，需按本机或服务器实际配置填写。三项能力可分别启用，其中 Milvus 向量路径需要同时设置地址和 embedding 模型。

## Milvus 与 BGE Embedding

1. 准备可访问的 Milvus 2.6 服务。使用实际访问地址和认证信息。
2. 在项目虚拟环境安装可选依赖 `python -m pip install -e ".[milvus,models]"`。
3. 配置变量并创建索引。下面是 POSIX shell 示例，PowerShell 可用 `$env:变量名 = "值"` 设置同名变量。

```bash
export AGENT_MILVUS_URI='http://127.0.0.1:19530'
export AGENT_EMBEDDING_MODEL='BAAI/bge-small-zh-v1.5'
python -m enterprise_agent.index
```

实例需要认证时设置 `AGENT_MILVUS_TOKEN`。索引命令只写项目的指纹集合，并检查全部条款 ID 已可读取。查询和入库使用同一个 embedding 模型。通过编译进查询的允许 ID 预先过滤向量候选。 [Milvus 过滤检索文档](https://milvus.io/docs/filtered-search.md)

## BGE Reranker

安装 `models` 扩展依赖后设定变量：

```bash
export AGENT_RERANKER_MODEL='BAAI/bge-reranker-base'
```

重排器只接收已通过版本和角色过滤、且从 RRF 保留下来的候选。首次启用需要具备模型访问与下载条件，也可传本地模型目录。CPU 可以运行小演示，长文本和并行请求需要测量延迟。

## Qwen3-8B 与 vLLM

这是一个 vLLM OpenAI 兼容接口接法。模型服务可在具备相应 GPU 和模型资源的独立机器上运行。实际模型 ID 以服务的 `/v1/models` 为准。

```bash
vllm serve Qwen/Qwen3-8B --host 127.0.0.1 --port 8001
```

给 Agent 进程配置：

```bash
export AGENT_VLLM_URL='http://127.0.0.1:8001/v1'
export AGENT_VLLM_MODEL='Qwen/Qwen3-8B'
```

启用 API 密钥时使用 `AGENT_VLLM_KEY`。模型只接收已授权的候选条款和问题，输出 JSON 引用候选。vLLM 地址的末尾应带兼容 API 的 `/v1`。 [vLLM OpenAI 兼容接口](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/)

## 联调顺序

1. 运行默认评测保留本地基线。
2. 单独启用 Milvus 后执行索引，确认评测的向量后端和模型名。
3. 加 BGE Reranker，记录同一题集的 Recall@5。
4. 加 Qwen，单独核对引文准确率、拒答比例和接口延迟。

```text
python -m enterprise_agent.evaluate --configured-models --json
```

这条命令对同一套虚构样例使用环境变量中配置的模型和实例。本仓库提交前验证了 SDK 接口及权限过滤测试，完整的外部服务联调应按实际部署运行。
