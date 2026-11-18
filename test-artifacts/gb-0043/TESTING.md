# 终章到达研究 · 测试与核验

本目录的测试不依赖 Web 框架与数据库，可用系统 Python 直接运行（`-I` 隔离模式，避免本地路径注入）。

## 1. 求解器数学与工程测试

```bash
python3 -I test_arrival_solver.py            # 全部
python3 -I test_arrival_solver.py hand scale # 仅选部分：hand/linear/trapped/resume/target/scale/degenerate
```

覆盖：

1. **手算 oracle（hand）**：精心构造含目标吸收、失败后继、会话退出的数据，逐概率核对闭式值
   `h(B)=1/3、h(A)=2/3、h(D)=1/3`，并逐状态核验 `ΣP(a→b)+e(a)=1` 与退出估计。
2. **独立精确解对照（linear）**：另写高斯-约旦消元直接解线性系统 `(I−Q)h=g`，验证迭代解逐章误差
   不超过报告上界且 < 1e-6；并分别核验“相邻轮差分残差”与“独立重算的真 Bellman 残差”。
3. **循环 vs 无路可达（trapped）**：`X↔Y` 循环 SCC 判 `unreachable_cycle`，孤立末章 `Z` 判
   `unreachable_exit`，两类概率与误差上界都精确为 0。
4. **中断恢复（resume）**：低迭代上限产生只含完整轮的检查点，放开后续算结果与一次跑完逐位一致、总轮数一致。
5. **改目标/改输入拒绝复用（target）**：检查点校验输入 SHA256、目标章、章节数，不一致即拒绝。
6. **一万章节/十万接续边（scale）**：分层 DAG + 回边 + 隔离环簇，实测约 513 轮收敛、峰值 RSS < 256MB、
   上界 4.98e-7，并在规模下同时验证 200 个循环态与 229 个退出态分类正确。
7. **退化输入（degenerate）**：零转移边、重复会话、未知目标均明确失败。

> 本地无 NumPy 时自动走纯标准库引擎（`_iterate_python`）；容器内安装了 numpy/scipy，走稀疏引擎
> `_iterate_numpy`。两引擎返回相同 `array.array('d')` 类型、相同检查点格式，数学语义一致。

## 2. 服务层集成测试（桩隔离）

```bash
python3 -I test_arrival_service.py
```

用 `sys.modules` 桩替换 SQLAlchemy / Redis / FastAPI，验证 `services/arrival.py` 的业务规则：

- 目标章必须在冻结会话出现过；未知/空目标返回 422；
- 创建任务入独立队列 `arrival:queue`、每任务独立工作目录；
- worker `execute` 收敛后写入 result/iterations/error_bound；
- 早期检查点只记录完整轮（半轮不混入），中断后再执行沿检查点恢复到与一次求解一致的概率；
- **编辑建议门控**：未完成任务、`error_bound>=1e-6` 的“完成但未收敛”结果一律 409 拒绝；
  仅收敛结果可建草案，负责人批准后方可导出；
- 改目标产生新任务与新目录，新目录不存在旧检查点（进度不复用）。

## 3. 误差上界为什么可核验

对瞬时态集合 T，令 Q 为 T 上的次随机转移子矩阵（落到目标/循环/退出的质量被吸收截断），
`s_k = Q^k · 1_T`。Bellman 迭代 `h_k = Q^k g`（g 为一步到目标的吸收向量），精确解 `h* = Σ_{j≥0} Q^j g`。

- `0 ≤ h* − h_k = Σ_{j>k} Q^j g ≤ Σ_{j>k} Q^j 1_T = s_k`（逐分量，因 `0≤g≤1_T`）。
- 故 `max_a s_k(a)` 是对所有章节同时成立的绝对误差上界，报告上界 < 1e-6 即保证每章绝对误差都 < 1e-6。
- 不可达状态不参与迭代，概率与上界均为结构上的精确 0，不占用误差预算。

## 4. 手工复算入口（无需测试框架）

```bash
python3 -I - <<'PY'
import sys; sys.path.insert(0,'../../backend')
from src.services.arrival_solver import solve
import tempfile
records=[{'values':{'session':f's{i}','path':p}} for i,p in enumerate(
  ['A>B>C','A>C','B>Z','B','D>B>E'])]
print(solve(records,'C',tempfile.mkdtemp())['rows'])
PY
```
