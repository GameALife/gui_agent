1.Agent推理层：人在环路的任务目标完善与子任务分解

2.GUI感知层：屏幕状态感知

3.GUI交互层：基于屏幕状态规划并执行GUI操作

4.异常恢复层：GUI交互出现超时/错误后，判断问题级别进行反思与回溯

5.状态管理层：维护任务状态、GUI状态及历史操作记录，为各层提供状态共享与同步支持

**6.分工：**

* [ ]  殷龙飞：1
* [ ]  张耀之：2

* [ ]  陈昊：3
* [ ]  姬凯宁：4

* [ ]  胡沛亮：5

·注：状态管理层贯穿整个系统，由各模块共同维护和使用。

## 模型 API 配置

模型调用已抽象为 `agent_reasoner.llm_client.LLMClient`，推理层和执行层只依赖统一的 `chat/chat_json` 接口，不再绑定 DeepSeek。

默认兼容旧配置：

```bash
export DEEPSEEK_API_KEY="sk-..."
```

推荐使用统一配置：

```bash
export LLM_PROVIDER="openai_compatible"
export LLM_MODEL="deepseek-chat"
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_API_KEY="sk-..."
```

使用 LiteLLM 时：

```bash
pip install litellm
export LLM_PROVIDER="litellm"
export LLM_MODEL="deepseek/deepseek-chat"
export LLM_API_KEY="sk-..."
```

使用 OpenAI 官方接口时：

```bash
export LLM_PROVIDER="openai"
export LLM_MODEL="gpt-4.1-mini"
export OPENAI_API_KEY="sk-..."
```

使用本地 OpenAI-compatible 服务时：

```bash
export LLM_PROVIDER="openai_compatible"
export LLM_BASE_URL="http://127.0.0.1:8000/v1"
export LLM_MODEL="your-local-model"
```

不要把 API Key 写入仓库文件；只使用环境变量或本地未提交配置。
