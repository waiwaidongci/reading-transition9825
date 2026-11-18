# 杉页阅读路径接续册

会话内一阶转移计数、条件概率与相对全局基率提升。为杉页研究协作组的12位分析与业务人员提供从样本核对、独立worker计算到批准快照交付的完整工作流。

## 真实业务场景

匿名章节阅读会话→路径接续关联→编辑衔接建议；仅会话内相邻，禁止跨会话拼接，非因果。团队原先将 `reading-transition-202611-01.csv` 复制到多份人工表格，复核时再逐项对照。三个痛点是口径不可追溯、重复计算易错、业务说明与结果脱节。上游提供合成业务观察，系统承担研究和复核，下游业务人员读取批准快照。全部演示数据是固定随机种子生成的模拟数据。

## 业务模块

1. 业务总览：批次、样本、任务与批准交付账册。
2. 阅读文集：创建/修改来源说明、查看样本、用真实业务字段追加记录；列表分页。
3. 分析配置：冻结来源、参数和全部样本，进入Redis队列。
4. 完整结果：真实算法摘要、专属诊断、全部CSV导出和可恢复失败态（原一步接续研究）。
5. 终章到达：指定目标章，求解各章“先到目标再退出”的概率，呈现等待/求解/收敛与概率依据。
6. 终章衔接建议：仅采用误差上界 < 1e-6 的收敛结果，草案→负责人批准→批准快照导出。
7. 编辑衔接建议：原一步研究的分析师草案→负责人批准→阅读者下载批准快照。
8. 审计：登录、来源修改、任务worker完成、业务说明批准等事件。

## 快速启动

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
# 可重复执行，不覆盖人工修改
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [前端](http://localhost:18247)；[API文档](http://localhost:19247/docs)。数据库仅演示用途映射 `17747`。首次准备依赖和初始化数据库需要等待健康状态：`docker compose ps`，五个服务均需healthy。

| 组件 | 技术与职责 |
|---|---|
| frontend | 原生 HTML / CSS / JS ES Modules，Nginx代理 `/api/` |
| backend | Python3.11 / FastAPI / SQLAlchemy / JWT |
| worker | 独立Python进程，Redis BLPOP队列，持久化结果/CSV/心跳 |
| db | MySQL8，命名卷持久化 |
| redis | Redis7，AOF命名卷 |

恰好五服务，均配置healthcheck；后端/worker依赖数据库与Redis健康，前端依赖后端健康；worker与后端共享 `artifacts` 命名卷。重置演示环境：`docker compose down -v --remove-orphans`，会删除本项目卷。

## 账号与权限

所有演示账号密码：`Research2026!`。

| 邮箱 | 角色 | 权限 |
|---|---|---|
| admin@reading-transition.demo | admin | 全部录入/执行、批准业务说明 |
| analyst@reading-transition.demo | analyst | 录入来源/样本、执行、提交说明，无批准权 |
| viewer@reading-transition.demo | viewer | 只读、导出结果及已批准快照 |

时间在数据库/API中以UTC存储，总览与审计页面明确转换为Asia/Shanghai北京时间。

JWT有效期8小时；PBKDF2盐化哈希保存密码；角色每请求从数据库读取。访客写操作403，匿名访问业务数据401，重复样本409，非法业务字段422，重复批准409。每客户端/路径写请求90次/分钟，超限429。生产使用需修改JWT及演示数据库凭据。

## 实体与字段

ReadingCollection / ReadingSession / TransitionRun / EditorialPlan 是核心实体；终章研究另有 ArrivalRun / ArrivalNote（表 `arrival_runs` / `arrival_editorial_plans`）；还有User和Audit。数据库实际表：`reading_collections` → `reading_sessions` → `transition_runs` → `editorial_plans`，以及 `arrival_runs` → `arrival_editorial_plans`。样本以固定字段JSON保存，后端按以下字段严格验证，不接受未知字段替代必填值：匿名会话编号（`session`）、章节路径（用 > 分隔）（`path`）。

实体贯穿 `backend/src/models`、`schemas`、`services`、`controllers`、`routes`，以及 `frontend/src/api/research.js`、`stores/research.js` 和 `pages`。`Source.key` 与 `(Record.source_id, reference)` 为自然键；来源改名不会修改已冻结任务输入。业务说明在创建时保存结果快照，批准后从该快照导出。

## 算法与口径

会话内一阶转移计数、条件概率与相对全局基率提升，全部计算位于 `backend/src/services/algorithm.py`，前端不拟合模型、不生成模拟结果。输入是冻结业务观察及参数，输出summary、专属诊断、逐行计算明细、seed与输入SHA256。CSV包含全部结果行；页面仅预览前30行。参数：

- `min_count`：最少接续次数，默认 `3`。
- `top_n`：保留接续规则数，默认 `20`。

只统计同一会话内的相邻章节；提升度相对于所有接续边的目标章节基率，关联不代表编辑调整造成的因果效果。

失败态：业务字段缺失/非有限数值、参数越界、样本不足、退化特征或结构错误均明确拒绝或将任务标failed，错误消息保存在任务中。可回到来源或配置修正后重新执行，历史失败记录保留。

已知边界：仅统计每行完整匿名会话内的相邻章节，拒绝会话编号重复；不是长序列规则挖掘。无跨会话拼接；提升度只是接续关联，不解释为因果。单章会话有效但不产生边。

### 终章到达研究（吸收型马尔可夫链）

“一步接得高不代表最终能读到终章”。终章研究与一步研究同源但独立冻结、独立求解，代码位于 `backend/src/services/arrival_solver.py`，前端不拟合模型。

口径（每条仅用会话内相邻转移，禁止跨会话拼接）：

- 一阶转移：`P(a→b)=边a→b次数 / 从a出发总次数 out[a]`。
- 会话末尾退出估计：`e(a)=a作为末章次数 end[a] / (out[a]+end[a])`；每个状态满足 `Σ_b P(a→b)+e(a)=1`，可逐状态核验。
- 目标章 `t` 为吸收成功态（`h(t)=1`，目标即到达）。求 `h(a)=从a出发先到达t、再退出会话的概率`，满足 Bellman 方程 `h(a)=Σ_b P(a→b)h(b)`，`h(t)=1`。

循环与无路可达的区分（图结构精确判定，非数值近似）：

- 反向 BFS 求“可沿转移边到达目标”的集合 R(t)；不在 R(t) 的状态概率精确为 0。
- 对不可达状态再用迭代式 Tarjan 强连通分量（SCC，避免万章递归深度问题）区分：
  - `unreachable_cycle`：处于循环强连通分量，沿转移边可无限循环、到不了目标；
  - `unreachable_exit`：不在循环分量，没有到目标的路径，只能在某条会话末章退出。
- 每条会话都是有限路径，因此不存在“永不退出”的状态；这里的“循环”指转移结构中可反复返回的 SCC。

可核验误差上界（不依赖统一收缩率，允许零退出长链/循环结构）：

- 对参与迭代的瞬时态集合 T，维护生存质量 `s_k=(Q^k·1_T)`，Q 为 T 上的次随机转移子矩阵（落到目标/循环/退出的质量被吸收截断）。
- `s_k(a)` 是“k 轮后仍未被任何方式吸收”的概率上界，且 `0 ≤ h*(a)−h_k(a) ≤ s_k(a)`（h* 为精确解）。因此 `max_a s_k(a)` 是对所有章节同时成立的绝对误差上界。
- 当报告上界严格小于 `1e-6`（停机阈值 `5e-7`，给浮点舍入留余量）才判收敛；另报告 Bellman 相邻轮残差供独立数值核对，但不单独作为收敛依据。绝对误差百万分之一内才算收敛，未达标的任务标 failed 或不提供导出，编辑建议一律拒绝采用。

内存与分批（一万章节、十万接续边，预算 < 256MB）：

- 不保存稠密概率矩阵；章节名去重、整数计数 dict、正向/反向 CSR 紧凑数组、h/s 各 8 字节。实测 10000 章 / 102200 边峰值约 98MB。
- Jacobi 半轮按 `BATCH=1024` 状态分块顺序求解；优先使用 NumPy/SciPy 稀疏引擎，缺依赖时回退纯标准库引擎，两引擎数学语义与检查点格式完全一致。

中断恢复与“改目标不复用”：

- 仅在完整一轮结束后写检查点（原子 `os.replace`），半轮更新绝不计数、绝不落盘；检查点含输入 SHA256、目标章、求解器令牌、引擎与完整迭代轮数。
- worker/服务重启时，queued/running 任务按同批冻结输入与同一检查点重新入队续算；输入、目标或章节数不一致则拒绝复用并报错。
- 改目标必须新建研究：每个任务有独立工作目录 `artifacts/arrival/run-<id>/`，目录隔离使旧进度物理上不会被复用。

失败态与建议门控：零转移边、重复会话、未知目标、达到迭代安全上限仍未收敛均明确失败；编辑衔接建议（`arrival_editorial_plans`）只接受 `completed 且 result.converged 且 error_bound<1e-6` 的任务，未收敛结果在前后端均不可选、不可提交、不可导出。

## 演示数据与一天剧本

固定seed=42，3个来源 ` SY-202611-01/02/03`，每来源240条，共720条业务记录；三个账号和首轮种子任务。自然键检查后仅插入缺失数据，连跑seed不重复、不覆盖用户修改。`SEED_DEMO=true` 时启动自动执行；失败记录日志但不阻塞服务。首轮任务同样由独立worker真实计算。

1. 09:00 负责人查看三份来源和720条样本。
2. 09:10 分析师选择 `SY-202611-01 秋季常规组`，核对 `reading-transition-202611-01.csv`。
3. 09:15 在“阅读文集”核对匿名会话编号（`session`）、章节路径（用 > 分隔）（`path`），追加编号 `SY-NEW-001` 的样本。
4. 09:20 新建“十一月复核研究”，按默认参数冻结241条输入。
5. 09:21 独立worker消费Redis队列，返回实算结果与输入校验和。
6. 09:25 分析师查看专属诊断及逐行结果，并下载CSV复算。
7. 09:30 提交“十一月业务复核意见”，负责人核对并批准。
8. 09:40 viewer下载批准快照，查看审计中的worker完成与批准事件。

## 目录与本地开发

```text
frontend/src/api, stores, types, components/common, hooks, pages, router, utils, constants
backend/src/routes, controllers, services, models, schemas, middlewares, utils, constants, config
backend/scripts/seed_demo.py
backend/migrations/001_initial.sql
```

本地后端：Python3.11虚拟环境安装 `backend/requirements.txt`，设置 `DATABASE_URL`、`REDIS_URL`、`ARTIFACT_DIR`，在backend目录运行 `uvicorn src.main:app --reload`；另开终端运行 `python -m src.worker`。原生前端无需编译，推荐以Compose Nginx访问，保证 `/api/` 代理。前端为Google Fonts双字体、oklch色板，离线字体回退serif；1280/768/390响应布局。

| 环境变量 | 默认与说明 |
|---|---|
| COMPOSE_PROJECT_NAME | `reading-transition`，隔离容器/网络/命名卷 |
| FRONTEND_PORT / BACKEND_PORT / DB_PORT | `18247 / 19247 / 17747` |
| SEED_DEMO | `true` |
| JWT_SECRET | `.env.example`演示值，部署前修改 |
| DATABASE_URL / REDIS_URL | Compose内部连接，定义在compose的env锚点 |
| ARTIFACT_DIR | `/artifacts`，后端worker共享 |

共享枚举：`backend/src/constants/enums.py` 与 `frontend/src/constants/enums.js` 都定义 admin/analyst/viewer、queued/running/completed/failed、draft/approved。后端service检查对应字符串；README为全量值说明。共享前端组件table/status/chart/business跨总览、结果、配置与复核复用；actions hook和format utils负责交互/格式。后端errors与rate_limit是两个中间件。

测试及截图在批根 `test-artifacts/gb-0043/`，不混入源码。独立算法oracle、HTTP完整流程和真实Playwright浏览器流程见该目录 `TESTING.md`。License：MIT。
