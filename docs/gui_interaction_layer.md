# GUI交互层技术文档

## 目标

GUI交互层对应 overview 中的第 3 点：基于屏幕状态规划并执行 GUI 操作。它接收推理层输出的 TaskTree，在安卓设备或模拟器上按依赖顺序执行每个子任务，并输出执行报告。

## 模块边界

- `AppAgent`：执行层主控制器，负责 DAG 调度、屏幕采集、动作执行、重试、日志和报告。
- `StepParser`：把 Task description 拆成 Step，并尽量用规则提取候选 Action。
- `ActionPlanner`：连接规则动作和屏幕状态。规则动作可直接执行时不调用 LLM；目标控件缺失时调用控件理解补全。
- `WidgetUnderstander`：用 LLM 根据操作意图和控件树 XML 选择目标控件，输出结构化 Action。
- `ActionExecutor`：把 Action 翻译成 uiautomator2/ADB 操作，并做操作级重试和坐标/ADB 降级。
- `ScreenCaptor`：承担 Perception，采集控件树、截图、前台包名和 Activity。
- `Evaluator`：承担 Evaluation，比较执行前后屏幕状态，判断操作是否生效，并给出失败后的重试建议。

## 执行流程

1. `AppAgent.execute_task_tree()` 从 TaskTree 中取依赖已满足的任务。
2. `StepParser.parse()` 将任务描述拆为一个或多个 Step。
3. 对每个 Step，`AppAgent` 逐个处理规则候选 Action。
4. `ActionPlanner.resolve()` 判断候选 Action 是否可直接执行：
   - 返回、Home、等待、滑动、键盘事件等无需目标控件，直接执行。
   - 点击、输入、滚动、长按需要目标控件；如果规则里已有 selector 或 bounds，则直接执行。
   - 如果目标不完整，则调用 `WidgetUnderstander` 基于当前屏幕控件树补全。
5. `ActionExecutor.execute_with_retry()` 执行动作，失败时按错误类型决定是否重试。
6. `ScreenCaptor.capture()` 再次采集执行后的屏幕状态。
7. `Evaluator.evaluate()` 比较执行前后包名、Activity、控件树和输入文本是否出现；未通过则重新截图、重新规划并重试。
8. 每次操作写入 `execution_log`，最终返回 summary、tasks 和 execution_log。

## 模型 API 设计

`agent_reasoner.llm_client.LLMClient` 是统一模型入口，对外只暴露：

- `chat(messages, temperature, max_tokens, max_retries) -> str`
- `chat_json(messages, temperature, max_tokens, max_retries) -> dict`

内部通过 provider 适配不同模型：

- `OpenAICompatibleProvider`：直接请求 `/chat/completions`，兼容 DeepSeek、OpenAI-compatible 本地服务等。
- `LiteLLMProvider`：在安装 `litellm` 后，通过 LiteLLM 统一调用多供应商模型。

配置优先级：

1. 构造 `LLMClient(...)` 显式参数。
2. `LLM_PROVIDER`、`LLM_MODEL`、`LLM_BASE_URL`、`LLM_API_KEY`。
3. 兼容旧变量：`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL`。

`chat_json()` 做了更稳健的 JSON 提取，兼容直接 JSON、Markdown 代码块、前后带解释文本、以及 prompt 模板导致的双花括号。

## 关键可靠性处理

- 规则动作不再丢失：原来 `StepParser` 解析出的 `actions` 没有被 AppAgent 使用，现在由 `ActionPlanner` 接入执行链路。
- 控件目标补全：输入框等规则难以确定的目标，会用当前 XML 交给 LLM 精确定位。
- 坐标降级：选择器点击/输入遇到 uiautomator2 RPC 兼容问题时，优先用 bounds 中心点或 ADB 输入降级。
- 键盘事件：软键盘按钮通常不在控件树里，搜索/回车/完成转为 ADB keyevent。
- bounds 兼容：LLM 返回 list、`[x1,y1,x2,y2]` 或 XML 风格 `[x1,y1][x2,y2]` 都会归一化。
- 中文方向归一化：`上/下/左/右` 会映射到 uiautomator2 的 `up/down/left/right`。
- 独立 Evaluation：点击/输入后由 `Evaluator` 比较操作前后的包名、Activity 和控件树，避免只因 API 没报错就认为成功。
