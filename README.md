# AfterCare AI（售后智服台）

AfterCare AI 是一个面向中小电商商家的多租户 AI 客服与工单系统。商家可以上传售后政策、商品说明和常见问题；顾客可以通过对话查询知识、订单、物流和退款状态，并在需要时转人工或创建工单。

本项目有两个同等重要的目标：

1. 完成一个可以部署给少量测试用户使用的受控 Beta 产品。
2. 通过真实交付过程学习 Python AI 应用工程和可验证的 Vibe Coding 工作方法。

## 当前状态

当前处于 **M2：身份与对话** 阶段，M2-A 至 M2-E 的学习演示范围已完成，下一项是 **M2-F：角色、审计与里程碑回归**（先只读分析）。

- 已定义用户、业务目标、范围和非范围。
- 已定义第一版需求与验收案例。
- 已记录初始架构和关键技术决策。
- M0 项目定义已完成并提交。
- M1 可运行骨架已完成、本地验证通过，并提交和推送到远程 `main`。
- M2-A 已交付租户管理员注册、登录与当前用户接口；M2-B 已交付前端登录、会话状态与受保护路由。
- M2-C 已交付持久化会话和消息；M2-D 已交付 SSE 流式回复、停止生成和可追溯的重新生成版本。
- M2-D 加固已保存为本地提交 `4fffa74 — M2-D边界修复`；M2-E 的上下文预算、事实摘录及具体回复反馈已实现，尚未提交或推送。

## 核心业务链路

1. 商家上传知识文档，顾客提问后获得带原文引用的回答。
2. 顾客询问订单、物流或退款状态，系统调用受控的只读工具。
3. 系统无法可靠回答或顾客要求人工服务时，创建工单并转人工。

## 文档阅读顺序

1. [当前状态与交接](docs/STATUS.md)
2. [项目简报](docs/PROJECT_BRIEF.md)
3. [第一版需求](docs/REQUIREMENTS.md)
4. [验收案例](docs/ACCEPTANCE_CASES.md)
5. [初始架构](docs/ARCHITECTURE.md)
6. [架构决策](docs/DECISIONS.md)
7. [M2 身份与对话里程碑](docs/milestones/M2.md)
8. [学习日志](docs/LEARNING_LOG.md)

## 交付原则

- 当前是学习 AI 应用开发的演示项目：默认优先正常端到端流程和易理解的实现，不要求全面边界判断、异常路径测试或生产可靠性机制。需要这些能力时另行明确范围；已批准并加入的改动和测试仍完成收尾。
- 按端到端业务切片交付，不按框架或技术模块堆功能。
- 每次改动先明确范围、验收方法和风险，再开始实现。
- 测试结果是完成依据，页面“看起来能用”不是完成依据。
- 第一版使用模拟业务数据，不保存真实客户隐私或执行真实退款。
- 本地修改、Git 提交、远程推送、创建 PR 和部署分别确认。

## 计划技术栈

- 前端：Vue 3、TypeScript
- API：Python、FastAPI、Pydantic
- 数据访问：SQLAlchemy、Alembic、PostgreSQL
- 缓存和后台任务：Redis、Celery
- 检索：Qdrant Dense + Sparse 混合检索和 Reranker
- Agent：LangGraph 单 Agent 受控工作流
- 对象存储：本地 MinIO，生产环境使用 S3 兼容存储
- 交付：Docker Compose、GitHub Actions、Linux、HTTPS

运行时依赖的精确版本由 `uv.lock` 和 `pnpm-lock.yaml` 锁定；基础镜像版本记录在对应 Dockerfile 与 Compose 配置中。

## M1 本地验证

### 使用 Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

启动后访问：

- Web 状态页：<http://localhost:5173>
- API 存活检查：<http://localhost:8000/health/live>
- API 就绪检查：<http://localhost:8000/health/ready>
- API 文档：<http://localhost:8000/docs>

停止服务但保留本地数据：

```powershell
docker compose down
```

不要在普通停止操作中添加 `--volumes`，否则会删除本地数据库、Redis 和 Qdrant 数据卷。

### 分别验证 API 与 Web

```powershell
Set-Location apps/api
uv sync
uv run ruff check .
uv run pytest

Set-Location ../web
pnpm install
pnpm typecheck
pnpm build
```

API 的 `/health/live` 只表示进程存活；`/health/ready` 会实际检查 PostgreSQL、Redis 和 Qdrant，因此在基础服务没有启动时返回 `503` 是正确行为。

PostgreSQL、Redis 和 Qdrant 默认只暴露在 Compose 内部网络，不占用宿主机端口。需要排障时应优先通过 API 就绪检查或 `docker compose exec` 访问，而不是公开数据服务端口。

## 已加入的 M2-D 隔离验证

这套环境也可用于 M2-E 正常演示，完整 M2-D 失败路径测试不是后续学习任务的默认规模。`compose.verify.yaml` 使用独立项目 `aftercare-m2d-verify`、独立数据卷，以及只绑定回环地址的端口：Web `15173`、API `18000`、PostgreSQL `55432`，不会升级原 `aftercare-ai` 项目。

```powershell
docker compose -f compose.verify.yaml config --quiet
docker compose -f compose.verify.yaml up --build -d --wait
docker compose -f compose.verify.yaml exec -T postgres createdb -U aftercare aftercare_m2d_test
Invoke-RestMethod http://127.0.0.1:18000/health/ready

Set-Location apps/api
$env:AFTERCARE_TEST_DATABASE_URL = 'postgresql+asyncpg://aftercare:aftercare@127.0.0.1:55432/aftercare_m2d_test'
$env:AFTERCARE_TEST_API_URL = 'http://127.0.0.1:18000'
uv run pytest
Remove-Item Env:AFTERCARE_TEST_DATABASE_URL
Remove-Item Env:AFTERCARE_TEST_API_URL
```

`createdb` 只需在新的验证卷执行一次。PostgreSQL 测试会回退并升级指定测试库，因此只允许使用一次性 `_test` 数据库；HTTP 测试只允许上述独立 API 地址。没有设置这两个变量时，普通 Pytest 会跳过相应的 22 个集成测试。Docker Desktop 若未加入 PATH，可使用 `C:\Users\10164\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe` 执行相同命令。

验证完成后，在项目根目录删除这一套临时容器和数据卷：

```powershell
docker compose -f compose.verify.yaml down --volumes
```

### 强制退出后的人工恢复边界

普通断连和协程取消会自动收尾；进程强制终止或数据库不可用时，无法保证执行清理。本轮没有增加自动任务恢复功能。若数据库中遗留 `generating`，先停止**全部生成进程**，确认没有正在工作的生成器，再在对应数据库将遗留记录改为取消。以下示例仅针对独立验证项目：

```powershell
docker compose -f compose.verify.yaml stop api
docker compose -f compose.verify.yaml exec -T postgres psql -U aftercare -d aftercare_m2d -c "UPDATE messages SET generation_status = 'cancelled', is_current = false WHERE generation_status = 'generating';"
docker compose -f compose.verify.yaml up -d api
```

此操作不更改完成回复或旧当前版本；不能在其他 API/生成进程仍运行时批量执行。结构回退使用 Alembic，`20261012_04 → 20260923_03` 会移除新约束，但保留已经修正的来源关联和消息原文。存在歧义历史时升级会停止，先人工核对原始数据，不应绕过检查。

## M2-E 正常学习演示

启动独立环境：

```powershell
docker compose -f compose.verify.yaml up --build -d --wait
```

首次使用空库时，在 `http://localhost:18000/docs` 的 `register-tenant-admin` 接口创建一个模拟商家管理员，再到 `http://localhost:15173` 登录。

1. 创建会话，发送 `Order 42，商品：红色鞋，数量：2。`。
2. 依次发送 `Packaging guidelines`、`Shipping options`、`Return policy overview`。独立演示配置只直接保留最近 2 轮，较早内容进入摘要。
3. 发送 `我刚才问的是哪一笔订单？`，确定性回复会从实际上下文找回订单 42。展开“本次上下文”，查看 Token 预算及保留的订单、商品、数量事实。
4. 对这条回复点踩，选择“表达不清楚”，填写说明并保存。刷新页面，点踩仍存在；再次点踩可看到原原因和说明。
5. 对该回复重新生成。新回复成为版本 2，原回复及反馈留在历史版本 1。

默认配置是总预算 4096、输出上限 512、摘要上限 1024 Token、最多 6 轮。可通过 `.env.example` 中的 `AFTERCARE_CONTEXT_*`、`AFTERCARE_OUTPUT_TOKEN_LIMIT`、`AFTERCARE_SUMMARY_TOKEN_LIMIT` 和 `AFTERCARE_TOKENIZER_NAME` 调整；独立验证配置将窗口改为 2 轮，方便短演示。

计量使用 `tiktoken 0.14.0 / cl100k_base`，计算完整 JSON 提示词（包含系统说明、摘要和包装），并保存每条回复的上下文快照。输出达到上限会被截取。摘要是明确规则的带来源事实摘录，不是通用自然语言理解；回复仍是确定性演示，没有模型账号、费用或真实订单查询。以后接入真实模型时再匹配供应商的提示词格式和用量统计。

迁移 `20261012_05` 只新增上下文、摘要和反馈表，不替旧消息编造快照。回退到 `20261012_04` 会删除这些新增表及其中的元数据/反馈，保留原会话和消息；有需要保留的演示记录时先备份。
