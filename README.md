# Memory Lab · 四层记忆实验台

直接在 React 页面聊天。四层记忆和 Deep Agents 都能从对话自动整理长期偏好，并在新会话中按需使用。回答下可查看实际耗时、token 和来源。

## V2 聊天入口

双击 **打开热量选餐.cmd**，或在本地服务运行后打开 [热量选餐实验室](http://127.0.0.1:8010/?view=meal)。

1. 选择“四层记忆”“Deep Agents”或“并排对话”。
2. 发送“以后晚饭我喜欢吃辣，预算500块，热量不超过1000千卡。” 看到“已更新记忆”后继续。
3. 点击“新会话”，发送“晚上吃什么好？” 展开“查看记忆与来源”核对本轮使用的条件。
4. 点“新会话”旁的下拉箭头，选择“新建无记忆对照”。再问同一句，两组对照均按明确标注的演示默认值运行。

新记忆保存在 `data/memory_v2/` 下。原始记录为 JSONL，笔记、上下文、运行及检查点为 JSON，主题知识和 Deep Agents 的长期记忆为 Markdown。旧记忆库用于一次性只读迁移与归档，菜品业务库继续使用 SQLite。详情见 [V2 使用说明](docs/CHAT_V2.md)。

## 热量选餐新场景

从聊天页“实验工具”打开 [旧选餐演示](http://127.0.0.1:8010/?view=meal-legacy)，可手动生成和执行只读 SQL，检查热量计算和旧会话历史。
独立业务库位于 `data/meal_lab/meal_catalog.sqlite3`，可以在 DBeaver 中打开。详见 [热量选餐使用说明](docs/MEAL_LAB.md)。

## 打开页面

双击工作区根目录的 **打开记忆演示.cmd** 或 **start-demo.cmd**，入口会启动后台服务并打开浏览器。成功显示 `READY`，日志保存在 `data/launcher.log`。

服务运行后直接访问 **http://127.0.0.1:8010/**。后台服务不依赖演示终端保持开启。

## 在页面里演示

在 [交互演示](http://127.0.0.1:8010/?view=studio) 中选择“分步演示”，可按左侧九个步骤操作：

1. 录入日常偏好：预填不吃辣、午饭80元、建议简短，可自行修改。
2. 提取记忆笔记：查看事实与逐字原文依据。
3. 整理主题与索引：生成主题 Wiki 与精简启动记忆。
4. 预览注入上下文：查看 L4 将提供的内容，不调用模型。
5. 换个会话问午饭：真实回答、按需检索与来源引用。
6. 改一下午饭预算：按钮依次执行保存、提取、整理与新会话验证。
7. 从原话找回猫名：故意跳过提取与整理，直接回查原始记录。
8. 问一个无关问题：检查是否过滤饮食和猫名材料。
9. 和 Deep Agents 比较：真实框架执行，三组回答直接在页面展示。

每一步都提供 **输出结果 / 输入与输出 / 引用来源**。点击来源 ID 可检查原文、笔记版本和实际上下文。演示进度与输入保存在当前浏览器，已完成结果保存在本地数据库，刷新后可以继续查看。

“自由操作”允许自行选择保存、提取、整理、预览、提问和对比。会话同名时继续聊天，改名时演示跨会话记忆。

“新建空白演示”创建新的独立空间，不删除已有演示。默认空间为 `demo`，历史验收示例为 `walkthrough`，其他空间可通过生成的页面 URL 访问。

完整讲解见 [前端演示手册](docs/DEMO.md)。

## 四层与数据

- Transcripts：原始消息、回答、工具与模型执行事件。
- Memory notes：带来源、逐字证据和版本的原子笔记。
- Memory representations：主题 Wiki、笔记引用和交叉链接。
- Injected context：少量通用偏好与索引；和本轮按需检索内容分开展示。

原交互演示的记忆、运行与事件已迁至 `data/memory_v2/studio/`。每次旧版 Deep Agents 对比使用独立文件记忆与 JSON 检查点。

## API 配置

后端读取本地 `.env`；密钥不会进入前端构建或文档。更换服务地址、模型和 Key 后重启后端生效。

当前模型为 `deepseek-v4.1-flash`，通过 OpenAI 兼容 Chat Completions 接口调用。Deep Agents 分支需要模型支持工具调用。

## 开发与检查

依赖已经安装。首次在其他环境安装时运行 `scripts/setup.ps1`，需要 Python 3.11+ 和 Node.js 22+。开发者命令仍保留供调试，演示操作均可在页面完成。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm run build --prefix frontend
npm run test:ui --prefix frontend
```

真实浏览器完整九步验收：在服务运行后执行 `node frontend/browser-demo-check.mjs`（或在 frontend 目录执行）。这会真实调用 API 并产生模型用量，数据存放在独立验收空间，结果与截图在 `artifacts/browser-demo/`。

详细数据流见 [架构说明](docs/ARCHITECTURE.md)。

## 范围

这是本地单进程演示。四层方案是工程实现，非 Anthropic 官方源码。来源 ID、逐字摘录和引用关系可检查，但不证明模型内部推理的因果关系，也不代替语义事实审计。

三组对比包含学习与回答，框架提示词、工具和学习过程不同，不作为匹配计算预算的性能基准。没有接入 embedding，原文检索使用中文关键词与双字片段匹配。

## 参考

- [Anthropic: The components of agent memory](https://www.anthropic.com/research/components-of-agent-memory)
- [Deep Agents Memory](https://docs.langchain.com/oss/python/deepagents/memory)
- [Deep Agents Context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering)
