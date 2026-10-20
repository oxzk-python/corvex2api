# corvex2api

Corvex Token Factory（`api.tokenfactory.corvex.cloud`）多账号网关：对外暴露 OpenAI / Anthropic 兼容 API，账号池存 Redis（账号 + key + 状态 + 余额口径 + 累计用量）。上游 402（余额耗尽）自动剔除账号并换号重试（同一请求体重发，对话上下文不丢）；429 标记账号冷却（`Retry-After` 优先，到期自动恢复）；其余错误原样透传。每个新账号按 $6 初始余额计费，按模型单价累计 token 费用，余额耗尽自动剔除。代码结构参考 lobsterai2api。

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 启动 Redis
docker run -d --name corvex2api-redis -p 6379:6379 redis:8

# 3. 配置
cp .env.example .env        # API_KEY 为网关鉴权 key，留空则不鉴权

# 4. 启动
uv run uvicorn main:app --host 0.0.0.0 --port 8300

# 5. 导入账号（autara/out/result.json 原格式直接导入；[{email, api_key}] 或单条对象也支持）
curl -X POST http://127.0.0.1:8300/accounts \
  -H 'Content-Type: application/json' \
  -d @/Users/zouhua/work/python/autara/out/result.json

# 6. 调用（key 填 API_KEY，未设置则省略鉴权头）
curl http://127.0.0.1:8300/v1/chat/completions \
  -H 'Authorization: Bearer <API_KEY>' -H 'Content-Type: application/json' \
  -d '{"model":"zai-org/GLM-5.3","messages":[{"role":"user","content":"hi"}],"stream":true}'
```

- Anthropic 客户端（Claude Code 等）：`ANTHROPIC_BASE_URL=http://127.0.0.1:8300`，鉴权用 `x-api-key`，走 `/v1/messages`。
- 管理接口：`GET /accounts`（账号 + 状态 + 余额 + token 用量，不含 key）、`GET /status`（池概览与余额/用量汇总）、`DELETE /accounts/{email}`。
- 账号导入兼容两种格式：简化 `[{"email": "...", "api_key": "sk-corvex-..."}]`（单条对象也可），以及 autara `result.json` 原格式（`api_keys` 数组取第一个 key）；其余字段忽略。同一 email 重复导入视为更新 key 并保留累计用量，余额已耗尽则保持 `exhausted`。

## 余额与用量

价格来自 [docs.corvex.cloud/pricing](https://docs.corvex.cloud/pricing)（USD / 1M tokens）：

| 模型 | 输入 | 输出 |
|---|---|---|
| `zai-org/GLM-5.3` | $1.40 | $4.40 |
| `deepseek-ai/DeepSeek-V4-Flash-0731` | $0.14 | $0.28 |

- 新账号固定初始余额 `$6`，导入内容里的余额字段会被忽略。
- 费用 = 输入 tokens / 1M × 输入单价 + 输出 tokens / 1M × 输出单价；缓存读按输入单价。
- `GET /accounts` 每个账号返回 `initial_balance`、`used`、`remaining_balance`、`input_tokens`、`output_tokens`、`total_tokens`、`requests`、`last_used_at`。
- 累计余额 ≤ 0 自动标记 `exhausted`。该余额是本地估算，上游 402 仍是最终兜底。
- OpenAI Chat 流式请求会注入 `stream_options.include_usage=true`，客户端会多收到一个仅含 usage 的 chunk；Anthropic 与 Responses 流式直接解析上游已有的 usage 事件。
- 未知模型仍记录 token，费用按 0 计并写告警日志。
