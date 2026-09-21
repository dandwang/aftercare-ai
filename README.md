# AfterCare AI（售后智服台）

AfterCare AI 是一个面向中小电商商家的多租户 AI 客服与工单系统。商家可以上传售后政策、商品说明和常见问题；顾客可以通过对话查询知识、订单、物流和退款状态，并在需要时转人工或创建工单。

本项目有两个同等重要的目标：

1. 完成一个可以部署给少量测试用户使用的受控 Beta 产品。
2. 通过真实交付过程学习 Python AI 应用工程和可验证的 Vibe Coding 工作方法。

## 当前状态

当前处于 **M0：项目定义**。

- 已定义用户、业务目标、范围和非范围。
- 已定义第一版需求与验收案例。
- 已记录初始架构和关键技术决策。
- 尚未创建业务代码或安装依赖。

## 核心业务链路

1. 商家上传知识文档，顾客提问后获得带原文引用的回答。
2. 顾客询问订单、物流或退款状态，系统调用受控的只读工具。
3. 系统无法可靠回答或顾客要求人工服务时，创建工单并转人工。

## 文档阅读顺序

1. [项目简报](docs/PROJECT_BRIEF.md)
2. [第一版需求](docs/REQUIREMENTS.md)
3. [验收案例](docs/ACCEPTANCE_CASES.md)
4. [初始架构](docs/ARCHITECTURE.md)
5. [架构决策](docs/DECISIONS.md)
6. [学习日志](docs/LEARNING_LOG.md)

## 交付原则

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

具体依赖版本将在创建可运行骨架时确定并锁定。

