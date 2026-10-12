# M3-A 开发契约与环境选型

> 日期：2026-10-12。
> 状态：M3-A 已完成。用户已确认权限、生命周期与固定旧版 MinIO 的本地隔离用途；M3-B 尚未获实施批准。
> 当前代码基线：`main / 07b11114b3cda6f683bda032cdc1fb5610175df9`，本地、跟踪分支和实时 GitHub main 相同，开始时工作区干净。
> 用户已确认：回答走云模型 API；Embedding 和重排先在本机评估。

M3-A 的结果是后续开发可以遵循的权限、生命周期、接口和配置约定。本轮只交付文档，不增加业务代码、迁移、依赖或容器。真实模型候选没有下载、执行或产生费用；其运行验收分别放在 M3-D、M3-E 的进入条件中。

## 1 当前缺口与方案

身份依赖已经能提供可信的 user、tenant、role，会话读写已经要求 tenant + owner。当前迁移文件的 head 为 `20261012_06`，运行数据库 revision 本轮未核验。回复仍通过确定性 `demo_reply` 生成；没有知识模型、存储 SDK、任务 Worker、业务索引、模型适配器和引用。M3 不需要先重做认证和会话，而需要建立这些缺失模块之间的契约。

采用现有 FastAPI 模块化单体。Knowledge 管理文档；Retrieval 提供带权限的证据；Generation 调用云模型；Conversations 管理回复版本、预算与 SSE。解析和索引在 Linux Celery Worker 中执行，API 与 Worker 共享领域代码，不共享请求会话或跨事件循环的数据库连接。

## 2 权限契约

以下权限、生命周期和本地隔离用途已经用户于 2026-10-12 明确确认，作为后续实施契约；代码实施仍按每个子任务取得批准。

| 操作 | 管理员 | 客服 | 顾客 |
|---|---|---|---|
| 上传、文档列表/详情、任务查询、更新、删除、重试 | 本租户允许 | 403 | 403 |
| 在自己的会话检索 `customer_visible` | 本租户允许 | 本租户允许 | 本租户允许 |
| 在自己的会话检索 `staff_only` | 本租户允许 | 本租户允许 | 不返回 |
| 展开具体回复的引用 | 会话所有权 + 当前来源权限 | 同左 | 同左 |
| 读取其他用户会话，包括同租户 | 404 | 404 | 404 |
| 已通过角色检查后定位跨租户资源 | 404 | 404 | 404 |

- 未认证为 401。先做角色判断，再做 tenant/resource 查询，不用差异响应泄露其他租户数据。
- tenant 与 role 来自数据库回查的 CurrentIdentity；请求 Schema 不接受可信 tenant、owner、actor 或任意角色列表。
- 可见性只有 `customer_visible` 和 `staff_only`。默认 staff_only，管理员上传演示政策时主动选 customer_visible；customer_visible 仍需登录，并非互联网公开。
- M3 不提供可见性动态编辑、成员 ACL 或匿名访问。以后增加权限编辑时，需补历史引用和索引权限同步规则。
- 两路召回均先过滤。结果进入重排或模型前再按数据库 active、deleted、visibility 复核；来源展开也必须复核。
- 管理员仍无权查看其他用户的会话。管理文档的权力不能变成读取全部聊天记录的权力。

## 3 数据与生命周期契约

### 表和归属

| 模型 | 最小职责 | 关联规则 |
|---|---|---|
| knowledge_documents | title、visibility、created_by、active_version_id、deleted_at | tenant + document ID；active 必须指向本租户本文件的 ready 版本 |
| document_versions | version_number、file_name、file_type、size_bytes、checksum、object_key、status、脱敏错误和配置版本 | 文档 + version_number 唯一；版本不能引用其他租户文档 |
| document_jobs | ingestion/cleanup 类型、version/document ID、状态、stage、task_id、时间、脱敏错误 | 从持久化关联推导租户，不仅信任队列参数 |
| document_chunks | chunk_index、text、locator、token_count、point_id、text checksum | version + chunk_index 唯一；tenant/version 关联一致 |
| message_citations | 具体 message ID、document/version/chunk ID、label、标题/位置/摘录快照 | 回复版本固定，不随当前版本移动，不级联删除聊天历史 |

M3-B 新增前四张表；引用及生成快照扩展在 M3-E 再加迁移。数据库关系使用必要的联合唯一约束/外键约束或同事务校验，保证冗余 tenant 与父资源一致。active 指针与版本构成的循环关系，应在创建表后建立约束；禁止仅按一个跨租户 UUID 关联资源。

### 状态

| 对象 | 状态 | 解释 |
|---|---|---|
| 文档版本 | queued、parsing、parsed、indexing、ready、failed | ready 仅表示全部预期 Chunk 索引完成；是否生效仍看文档 active 指针 |
| 处理任务 | queued、running、succeeded、failed | 当前步骤单独放 stage，如 parse/index/activate/cleanup |
| 文档 | active_version_id + deleted_at | 首次上传处理中可以没有 active；更新处理中保留旧 active |

正常顺序：`queued → parsing → parsed → indexing → ready → 切换 active`。M3-B 只证明上传、落库、投递和任务可被 Worker 读取；M3-C 实现解析，M3-D 才允许完整索引激活。在解析器/索引器尚未完成的阶段，不以一个占位任务返回 succeeded/ready 冒充摄取成功。

更新先创建新版本。完整索引写入确认后，在数据库事务中检查文档未删除、新版本 ready，再切换 active。失败保留旧版。删除先标记 deleted、清空 active，使新检索排除所有版本，再清理该文档全部 points 与原文件；任务失败记录原因，提供最小人工重试，不自动复活文档。

队列重试沿用原 version，Chunk 和 point ID 根据 version + chunk_index 稳定生成，重复执行不新增一组 Chunk。默认单 Worker、并发 1；使用必要状态检查，不增加 Outbox、自动补偿调度器或完整分布式锁。

删除后历史回答和引用快照仍可作为原会话记录保留；来源展开提示“文档已删除”，不能返回原文件。旧版来源可展示但标记“已被替换”。新提问和重新生成重新检索，不能将旧助手回答当作现行政策。

## 4 M3-B API 契约草案

### 首个切片

| 接口 | 请求 | 响应和约束 |
|---|---|---|
| POST /api/v1/knowledge/documents | multipart：file、title、visibility | 202：document_id、version_id、job_id、status=queued |
| GET /api/v1/knowledge/documents | limit 默认 20、最多 100；offset 默认 0 | items + has_more；仅本租户未删除文档，不默认返回全文 |
| GET /api/v1/knowledge/documents/{document_id} | document UUID | title、visibility、active_version、latest_version、最近处理 job；404 不泄露资源 |
| GET /api/v1/knowledge/jobs/{job_id} | job UUID | type、status、stage、version_id、开始/结束时间、脱敏错误 |

M3-B 首先只接受 UTF-8 `.md`，上传上限建议 10 MiB。大小在服务端实际读取时累计，不只信任 Content-Length；文件名只是展示字段，对象键不能由文件名拼接。PDF/DOCX 在 C 开放，扫描 PDF 和旧 DOC 不包含在本阶段。

新增领域错误暂沿用现有 `HTTPException.detail` 风格：无身份 401、角色不允许 403、资源不在范围 404、不支持格式 415、文件过大 413、字段错误 422、无法完成存储/投递 503。可以给 detail 加固定业务 code，但不在本切片重写全站错误格式。异常信息不得透出连接字符串、Secret 或文件内容。

对象存储先写成功，数据库事务再保存 document/version/job；事务提交后投递 Celery。上传在完成传输、存储和元数据提交后返回，不等待解析或索引。“异步处理”不意味着无需等待整个上传。存储/数据库失败执行最小 best-effort 清理；队列投递失败把已创建任务/版本记为 failed 并返回明确失败，而不是返回虚假的正常 queued。

更新版本、删除、重试和引用 API 路径沿用 [M3 总计划](M3.md#6-api-与配置草案)，在 F 或对应已批准切片实现，不因本次草案自动纳入 B。

## 5 本机环境与隔离方案

2026-10-12 只读核验：

| 项目 | 当前结果 | 方案影响 |
|---|---|---|
| CPU | Intel i5-12400F，6 核 / 12 逻辑 CPU | 检索先按 CPU 推理评估 |
| 主机内存 | 31.8 GiB | 不等于容器可用内存 |
| Docker | 客户端 29.7.2，Linux，12 CPU，约 15.5 GiB 内存 | 与其他运行服务共享，需限制推理线程和 Worker 并发 |
| GPU | NVIDIA GeForce GTX 960 | 本计划不依赖 GPU，不宣称已验证 CUDA 能力 |
| 磁盘 | C 约 156.0 GiB、D 约 126.4 GiB 可用 | 可准备独立模型缓存，实际下载/使用量仍需测量 |
| 现有项目 | 长期 aftercare-ai 与 aftercare-m2d-verify 均运行；还有其他应用 | 不停止、重建、复用或清理它们 |
| M3 计划端口 | 15183、18030、55433、19000、19001 核验时无监听 | 启动前再次检查，当前结果不预留端口 |

新增验证文件 `compose.m3.verify.yaml`，独立项目 `aftercare-m3-verify`，独立库 `aftercare_m3`，独立卷和网络。PostgreSQL、Redis、Qdrant、MinIO 和模型缓存不挂现有项目数据卷。HTTP 测试固定允许 `http://127.0.0.1:18030`；Web 使用 15183。无需公开 Redis 或 Qdrant 端口。

API 先执行 Alembic upgrade 后才启动；Worker 等 API 启动健康且数据库结构存在后才消费。MinIO 初始化单独完成私有 bucket 创建后 API/Worker 才处理上传。当前 API ready 不证明 Worker 已完成摄取，应以一条真实任务和数据库状态验收。

### MinIO 候选修正

官方社区仓库于 2026-04-25 归档，README 明确不再维护。不能在新配置里使用不受控 latest 或假定社区持续发布。[官方仓库](https://github.com/minio/minio)

本机现有镜像已核验：

```text
Version: RELEASE.2025-09-07T16-13-09Z
Digest: minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e
```

用户已确认仅为本地学习演示按该 digest 创建新的隔离 MinIO 服务，使用新私有 bucket `aftercare-m3-knowledge`、新卷和新凭据，不连接当前其他应用的 MinIO。版本锁定证明可重复，不证明当前维护性或生产安全；公开部署前重新选定受维护的 S3 服务。当前确认不包含容器启动、迁移或生产供应商替换。

存储适配器建议使用 boto3 的 S3 client，配置自定义 endpoint 与 path-style，操作限制为所需 bucket 的上传、读取和删除。同步 SDK 操作不要阻塞 FastAPI 事件循环；放入受控线程或 Worker。对象键建议 `tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/source.md`。

## 6 检索与回答模型选型

**已确认的路线**：用户选择云回答、本机 Embedding/重排评估。以下具体模型和参数是候选，不等于已经通过本机质量、耗时或锁定版本兼容验证。

| 能力 | 候选 | 需要验证的条件 |
|---|---|---|
| Dense | FastEmbed CPU / BAAI/bge-small-zh-v1.5，512 维，Cosine | 中文问题集、模型输入长度、查询指令、锁定包的支持列表和模型 revision |
| Sparse | 中文分词后 BM25 类编码，优先评估 jieba + Qdrant/bm25 适配 | query/document 统一分词、无随机词 ID、同义与关键词案例、Qdrant IDF 配置 |
| 重排 | FastEmbed CPU / BAAI/bge-reranker-base | 有限候选排序、中文效果、首轮加载和常驻内存、锁定版本支持 |
| 融合 | Qdrant 两路召回 + RRF | 现有服务 v1.15.4 和 SDK 的实际兼容，不照搬新版参数 |
| 回答 | 用户选择的云 API，供应商及 model ID 待定 | 凭据、预算、模型上下文与计数、超时、响应/usage 格式 |

FastEmbed 当前上游源列出上述 Dense 与重排模型，但它不是本项目 uv.lock 中已安装的能力；B 中不提前安装模型依赖，D 再解析、锁定和验证。源码列出的模型文件大小也不是运行内存或下载完成证明。[Dense 支持列表](https://raw.githubusercontent.com/qdrant/fastembed/main/fastembed/text/onnx_embedding.py)、[重排支持列表](https://raw.githubusercontent.com/qdrant/fastembed/main/fastembed/rerank/cross_encoder/onnx_text_cross_encoder.py)

默认 Qdrant/bm25 源码语言列表未列中文，使用 SimpleTokenizer；不能仅设置 language=chinese 就视为可用。D 先做中文分词的一致性小验证，再确定接入方式；如果锁定版本不支持必要适配，用清晰独立的中文 Sparse 编码器或重新选择方案，记录决策，不假装英文默认实现已满足中文需求。[BM25 源码](https://raw.githubusercontent.com/qdrant/fastembed/main/fastembed/sparse/bm25.py)、[jieba 项目](https://github.com/fxsjy/jieba)

首轮评估可从 ONNX CPU threads=2、Worker concurrency=1、最多 20 条候选重排开始；观察资源后再调整，不把 Docker 12 CPU 全部分配给一个推理请求。不启用 GPU，不装一整套本地生成大模型，不把云回答和检索模型混为一项费用。

中文 Dense/重排模型会截取有限输入。C 的 Chunk 切分必须用所选检索编码器检查长度，不能拿 cl100k_base 的 400 Token 等同于模型的 512 输入长度。给查询指令、特殊 Token 和 question + chunk 对留空间；两阶段各自记录编码与配置版本。[Dense 模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[重排模型卡](https://huggingface.co/BAAI/bge-reranker-base)

模型下载授权、包安装和可运行探针纳入 D 的具体实施范围；本次只查阅公开模型元数据。E 前用户补供应商、endpoint、model ID 和允许费用，通过本地 Secret 注入 API key，不发到聊天、Git 或前端。不读取或推断其他应用已有云凭据。本进程未发现相关 AFTERCARE 模型变量，不等于本机其他位置没有配置。

## 7 配置与依赖交接

下表是计划键名，**尚未加入 Settings 或 .env.example**。

| 组 | 建议键名与非敏感默认值 | 引入阶段 |
|---|---|---|
| S3 | AFTERCARE_S3_ENDPOINT、BUCKET=aftercare-m3-knowledge、REGION=us-east-1、ACCESS_KEY_ID、SECRET_ACCESS_KEY | B |
| 任务 | AFTERCARE_CELERY_BROKER_URL、QUEUE=knowledge、Worker concurrency=1 | B |
| 上传 | AFTERCARE_KB_MAX_UPLOAD_BYTES=10485760、ALLOWED_TYPES=md | B；C 增加 pdf/docx |
| 检索 | AFTERCARE_DENSE_MODEL、DENSE_DIMENSION、SPARSE_CONFIG_VERSION、RERANK_MODEL、QDRANT_COLLECTION | D |
| 生成 | AFTERCARE_LLM_PROVIDER、BASE_URL、MODEL、API_KEY、TIMEOUT_SECONDS | E |
| 预算 | 沿用 AFTERCARE_CONTEXT_*；匹配所选 LLM 编码与实际消息包装 | E |

S3 和 Celery 的内部地址指向新 Compose 服务。Redis broker 可用独立 Redis 的 db 0；任务查询以 PostgreSQL 为准，首版不依赖 Celery result backend。Secret 不设真实值或沿用其他应用凭据，示例键为空/占位；实施时选择本地环境注入方式。

B 只新增 Celery Redis 支持、boto3、multipart 所需依赖；具体版本在 uv 解析后固定进 uv.lock，并验证 Python 3.12。C 再增加解析器，D 再增加 Qdrant/模型/分词依赖。现有 PostgreSQL/Redis/Qdrant 不默认升级；新 MinIO 使用明确 digest。迁移 head 保持 `20261012_06`，直到 B 新增迁移。

## 8 合成资料与小验证方案

| 资料 | 内容约定 | 用途 |
|---|---|---|
| 租户 A 政策 v1 | 签收后七天内可退货；商品未使用；无海外费用规则 | 正常答案、条件保留和拒答 |
| 租户 A 政策 v2 | 期限改为十五天，其余同 v1 | 新版本切换 |
| 租户 B 政策 | 签收后三十天；另有专属产品名 | 租户隔离，避免同答案掩盖泄露 |
| 内部说明 | 虚构客服处理步骤，staff_only | 顾客可见性过滤 |
| 三格式副本 | 合成 Markdown、文本 PDF、DOCX | 原文与 locator 一致性 |

当前只定义资料内容；文件生成由对应实施阶段完成。资料不含真实顾客、密码、订单或支付数据。

A 的验证已覆盖代码/需求一致性、远程 SHA、干净基线、Docker 信息、现有镜像版本/digest、拟用端口和官方候选元数据。模型下载速度、真实推理、中文召回质量、实际内存和云调用仍未测试。D 用明确答案、同义问法、关键词和缺失证据的小集合测量；E 至少有一次用户授权的真实云回答。

## 9 M3-B 实施方案与批准边界

**原因**：目前缺少文档元数据、原文件存储和请求结束后能继续工作的任务基础。直接把上传解析放在聊天请求里，会混淆权限、异步状态和回复生命周期。

**首个开发结果**：管理员通过 API 上传 Markdown，获得 document/version/job ID；原文件在独立私有 bucket，数据库保存状态；Linux Worker 可以读取该任务。顾客直接管理请求被拒绝，跨租户资源不可读。暂不包含 RAG、真实回答或管理页面。

**建议执行顺序**：

1. 按用户分支规则 fetch 最新 origin/main，创建普通开发分支；不从本计划推断允许直接在 main 写代码，不创建 PR。
2. 新增 knowledge 模型、迁移、Schema 和服务；导入 Alembic metadata，先验证空库升级及 M2 head 升级。
3. 加入私有对象存储适配器、实际上传限制、管理员上传/列表/详情/任务接口。
4. 创建 Celery 入口与独立数据库生命周期，落实提交后投递及明确失败状态。
5. 加入独立 Compose、bucket 初始化、新 Secret 注入和管理审计动作。
6. 运行针对性测试、独立真实存储/任务验证与迁移回退重升级；更新文档和最终差异。

**预计代码文件**：`apps/api/src/aftercare_api/knowledge/`、任务入口模块、`config.py`、`main.py`、`audit/middleware.py`、`alembic/env.py` 与新增迁移、`pyproject.toml`、`uv.lock`、`Dockerfile`、`.env.example`、`compose.m3.verify.yaml` 和对应 tests。前端与 M2 会话实现不在首个切片。

**相称验证**：管理员正常上传与状态查询；顾客/客服 403；跨租户 404；文件上限/格式的基本拒绝；存储或投递失败不呈现正常成功。独立 PostgreSQL 迁移可升级、回退、重升级，M2 数据保留；MinIO 对象与 Worker 任务实际可读。普通测试不下载模型、不调用云 API，既有测试保留。

**主要风险**：数据库/存储/队列不是共同事务，首版有明确失败状态和最小清理而非可靠恢复；MinIO 候选仅为固定旧版的本地演示；Worker 的异步数据库连接必须归属其进程/事件循环；本机已有多套服务，独立项目不能共用数据卷或侵占端口。

用户已确认 M3-A 契约；M3-B 实施仍需单独明确批准。M3-A 文档交付不授权 B 的代码、提交、推送、PR、review 或长期环境升级。

## 10 本次文件与下一条件

本轮变更仅为本文件、M3 总计划、DECISIONS、STATUS、LEARNING_LOG 和 README。用户确认后 ADR-011/012 为 Accepted（设计契约，尚未实现）；ADR-013 将已确认的模型运行路线与未确认的具体型号分开记录。

进入 B/C 的权限、生命周期和本地存储契约已确认，剩余是首个切片代码实施批准；不要求现在取得云 API key。进入 D 需批准并通过本地模型/中文 Sparse 小验证；进入 E 需明确云供应商、model ID、Secret 注入、预算和真实调用授权。

相关文档：[M3 总计划](M3.md)、[当前状态](../STATUS.md)、[架构决策](../DECISIONS.md)、[需求](../REQUIREMENTS.md)、[验收](../ACCEPTANCE_CASES.md)。补充依据：[Celery Redis](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)、[boto3 配置](https://docs.aws.amazon.com/boto3/latest/guide/configuration.html)。
