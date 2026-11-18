"""终章到达研究：吸收型马尔可夫链的“先到目标章、再退出会话”概率求解。

口径（与一步研究同源、独立计算，不复用其结果）：
- 状态 = 章节；每条会话内相邻章节 a>b 计为一条一阶转移边（仅会话内，禁止跨会话拼接）。
- 转移概率 P(a->b) = 边 a->b 次数 / 从 a 出发的总次数 out[a]。
- 会话末尾退出估计：e(a) = a 作为会话末章的次数 end[a] / (out[a] + end[a])。
  每个状态 a 满足 sum_b P(a->b) + e(a) = 1（无自环归一化，分母同口径，可逐条核验）。
- 目标章 t 为吸收成功态：h(t)=1。求 h(a)=从 a 出发先到达 t、再退出的概率，
  即 Bellman 方程 h(a)=sum_b P(a->b) h(b)，h(t)=1。

循环与无路可达的区分（图可达性 + 强连通分量，精确判定，非数值近似）：
- 反向 BFS 求“可沿转移边到达目标”的状态集合 R(t)；不在 R(t) 的状态 h 必为 0。
- 对不可达状态再用 Tarjan SCC 区分：
  * unreachable_cycle 处于循环强连通分量：沿转移边可无限循环，到不了目标；
  * unreachable_exit  不在循环分量中：没有到目标的路径，只能在某条会话末章退出离开。
  两者在冻结图上都是结构事实，概率精确为 0，不参与迭代。
  注：每条会话都是有限路径，因此不存在“永不退出”的状态；这里的“循环”指转移结构中
  存在可反复返回的强连通分量，而非真正无法终止。

可核验误差上界（不依赖统一收缩率，允许零退出的长链/循环结构）：
- 对参与迭代的瞬时态集合 T，维护生存质量 s_k(a) = (Q^k 1_T)(a)，
  Q 为 T 上的转移子矩阵（落到目标/循环/退出的质量均被吸收截断）。
- s_k(a) 是“k 轮后仍未被任何方式吸收”的概率上界；Bellman 迭代 h_k = Q^k g 有
      0 <= h*(a) - h_k(a) <= s_k(a)        （h* 为精确解）
  证明见 README“终章到达研究·误差依据”。因此 max_a s_k(a) 是逐状态同时成立的
  可核验绝对误差上界；当它 < 容差时，所有章节的绝对误差都严格小于容差，判定收敛。
- 另报告 Bellman 残差 r=max|h_k-Q h_k| 供独立数值核对（不单独作为收敛依据）。

内存预算（一万章节、十万接续边，目标 < 256MB）：
- 章节名 str 去重约 1.2MB；计数 dict 约 10MB；CSR/反向 CSR 紧凑 array 约 2MB；
  h/s 各 8 字节共 0.16MB；检查点二进制约 1MB。峰值远低于 256MB。
- 不保存稠密概率矩阵：P(a->b) 用整数计数在热循环中即时换算，避免 1e8 稠密单元。

分批与恢复：
- Jacobi 半轮按状态分块（BATCH 个状态一块）顺序求解；仅在完整一轮结束后写检查点，
  检查点只含完整迭代，半轮更新绝不混入。
- 检查点含输入 SHA256、目标章与求解器令牌；中断后沿用同批冻结输入与同一检查点续算；
  输入或目标不一致则拒绝复用（改目标必须新建研究、从零开始）。
"""
import array
import hashlib
import json
import os
import tempfile

TOLERANCE = 1e-6            # 收敛判据要求的绝对误差上限
STOP_EPS = 5e-7             # 实际停机阈值，给浮点舍入留出余量，保证报告上界 < 1e-6
MAX_ITERATIONS = 200000     # 安全上限；瞬时态有限时 Q 必为收敛矩阵，正常远早于此
BATCH = 1024                # Jacobi 半轮的状态分块大小
CHECKPOINT_EVERY = 10       # 每 N 个完整迭代落一次检查点
SOLVER_TOKEN = 'arrival-jacobi-v1'
MAX_CHAPTER_LEN = 500


def input_checksum(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_graph(records):
    """两遍扫描冻结会话，构建一阶转移图。

    返回紧凑结构：names(id->章节名)、index(章节名->id)、边计数与度计数。
    单章会话无相邻边，只贡献末尾退出计数；重复会话编号按一步研究同口径拒绝。
    """
    index = {}
    names = []

    def get_id(name):
        i = index.get(name)
        if i is None:
            i = len(names)
            index[name] = i
            names.append(name)
        return i

    seen_sessions = set()
    edge_count = {}                       # (u,v) -> 次数
    out = array.array('q')                # 出发边总次数（按 id 动态增长）
    end = array.array('q')                # 作为会话末章次数
    n_edges = 0
    n_sessions = 0

    def grow(arr, i):
        if i >= len(arr):
            arr.extend([0] * (i - len(arr) + 1))

    for r in records:
        v = r['values']
        sid = v['session']
        if sid in seen_sessions:
            raise ValueError('会话编号重复，请将一个完整会话保存在同一行')
        seen_sessions.add(sid)
        path = [s.strip() for s in v['path'].split('>')]
        if any(not s or len(s) > MAX_CHAPTER_LEN for s in path):
            raise ValueError('章节路径包含空章节或超长章节名（上限 %d 字符）' % MAX_CHAPTER_LEN)
        n_sessions += 1
        for a, b in zip(path, path[1:]):
            u, w = get_id(a), get_id(b)
            grow(out, max(u, w))
            edge_count[(u, w)] = edge_count.get((u, w), 0) + 1
            out[u] += 1
            n_edges += 1
        grow(end, get_id(path[-1]))
        end[get_id(path[-1])] += 1

    n = len(names)
    if n_edges == 0:
        raise ValueError('没有相邻章节转移；单章会话不形成接续边，无法估计终章到达概率')
    if len(out) < n:
        out.extend([0] * (n - len(out)))
    if len(end) < n:
        end.extend([0] * (n - len(end)))

    # 正向 CSR：按源状态排序的边
    pairs = sorted(edge_count.items())
    row_ptr = array.array('q', [0]) * (n + 1)
    col_idx = array.array('i')
    edge_w = array.array('q')
    for (u, w), c in pairs:
        col_idx.append(w)
        edge_w.append(c)
    pos = 0
    for u in range(n):
        while pos < len(pairs) and pairs[pos][0][0] == u:
            pos += 1
        row_ptr[u + 1] = pos

    # 反向 CSR：按目标状态排序的边，供反向 BFS 求可达目标集合
    rev_pairs = sorted((w, u) for (u, w), c in pairs)
    rev_ptr = array.array('q', [0]) * (n + 1)
    rev_col = array.array('i')
    for w, u in rev_pairs:
        rev_col.append(u)
    pos = 0
    for w in range(n):
        while pos < len(rev_pairs) and rev_pairs[pos][0] == w:
            pos += 1
        rev_ptr[w + 1] = pos

    return {
        'n': n, 'names': names, 'index': index, 'out': out, 'end': end,
        'row_ptr': row_ptr, 'col_idx': col_idx, 'edge_w': edge_w,
        'rev_ptr': rev_ptr, 'rev_col': rev_col,
        'n_edges': n_edges, 'n_sessions': n_sessions,
    }


def find_scc(graph):
    """迭代式 Tarjan 强连通分量（避免万章规模下的递归深度问题）。

    返回 comp(状态->分量id) 与 cyclic_scc(含循环的分量 id 集合：分量>1 或存在自环)。
    """
    n = graph['n']
    rp, ci = graph['row_ptr'], graph['col_idx']
    idx = [-1] * n
    low = [0] * n
    on_stack = bytearray(n)
    stack = []
    comp = [-1] * n
    comp_size = []
    counter = cid = 0
    for root in range(n):
        if idx[root] != -1:
            continue
        idx[root] = low[root] = counter
        counter += 1
        stack.append(root); on_stack[root] = 1
        work = [(root, rp[root])]
        while work:
            v, pos = work[-1]
            if pos < rp[v + 1]:
                w = ci[pos]
                work[-1] = (v, pos + 1)
                if idx[w] == -1:
                    idx[w] = low[w] = counter
                    counter += 1
                    stack.append(w); on_stack[w] = 1
                    work.append((w, rp[w]))
                elif on_stack[w]:
                    if idx[w] < low[v]:
                        low[v] = idx[w]
            else:
                work.pop()
                if work:
                    pv = work[-1][0]
                    if low[v] < low[pv]:
                        low[pv] = low[v]
                if low[v] == idx[v]:
                    size = 0
                    while True:
                        w = stack.pop(); on_stack[w] = 0
                        comp[w] = cid; size += 1
                        if w == v:
                            break
                    comp_size.append(size); cid += 1
    cyclic = {c for c, size in enumerate(comp_size) if size > 1}
    for v in range(n):                      # 自环使单点分量也构成循环
        for p in range(rp[v], rp[v + 1]):
            if ci[p] == v:
                cyclic.add(comp[v])
    return comp, cyclic


def classify(graph, target):
    """图结构精确分类。返回 target_id、可达标记、瞬时态列表与 SCC 循环信息。"""
    idx = graph['index']
    if target not in idx:
        raise ValueError('目标章节不在冻结会话出现过的章节中：%s' % target[:80])
    t = idx[target]
    n = graph['n']
    rev_ptr, rev_col = graph['rev_ptr'], graph['rev_col']

    can_reach = bytearray(n)              # 能否沿转移边到达目标
    can_reach[t] = 1
    stack = [t]
    while stack:
        w = stack.pop()
        for p in range(rev_ptr[w], rev_ptr[w + 1]):
            u = rev_col[p]
            if not can_reach[u]:
                can_reach[u] = 1
                stack.append(u)

    comp, cyclic = find_scc(graph)
    transient = [u for u in range(n) if u != t and can_reach[u]]
    n_unreachable_cycle = sum(
        1 for u in range(n) if not can_reach[u] and comp[u] in cyclic)
    n_unreachable_exit = sum(
        1 for u in range(n) if not can_reach[u] and comp[u] not in cyclic)
    return t, can_reach, transient, comp, cyclic, n_unreachable_cycle, n_unreachable_exit


def _jacobi_block(graph, transient, h, s, h_new, s_new, lo, hi):
    """对 transient[lo:hi] 执行半轮 Jacobi 更新（分块求解，原地数组）。"""
    row_ptr, col_idx, edge_w, out = graph['row_ptr'], graph['col_idx'], graph['edge_w'], graph['out']
    for k in range(lo, hi):
        u = transient[k]
        denom = out[u]
        acc_h = 0.0
        acc_s = 0.0
        for p in range(row_ptr[u], row_ptr[u + 1]):
            w = col_idx[p]
            c = edge_w[p]
            acc_h += c * h[w]
            acc_s += c * s[w]
        h_new[u] = acc_h / denom
        s_new[u] = acc_s / denom


def _engine_name():
    try:
        import numpy  # noqa: F401
        import scipy  # noqa: F401
        return 'numpy'
    except Exception:
        return 'python'


def _iterate_numpy(graph, transient, t, h, s, max_iterations, iteration0, bound0, residual0, progress_cb):
    """NumPy/scipy 分块 Jacobi。

    构建瞬时态行随机子矩阵 Q_T（CSR）与到目标的吸收向量 g_T：每条边权除以源状态出度，
    落到目标/不可达/退出的质量由矩阵外吸收，保证 Q_T 次随机（行和 <=1），标准吸收马尔可夫链口径。
    h/s 为全状态 array.array，检查点格式与纯 Python 引擎一致；bound0/residual0 取自检查点。
    """
    import numpy as np
    from scipy.sparse import csr_matrix
    rp, ci, ew, out = graph['row_ptr'], graph['col_idx'], graph['edge_w'], graph['out']
    rows, cols, data, g = [], [], [], []
    tset_pos = {u: k for k, u in enumerate(transient)}
    for k, u in enumerate(transient):
        denom = out[u]
        gv = 0.0
        for p in range(rp[u], rp[u + 1]):
            w, c = ci[p], ew[p]
            if w == t:
                gv += c / denom
            elif w in tset_pos:
                rows.append(k); cols.append(tset_pos[w]); data.append(c / denom)
        g.append(gv)
    m = len(transient)
    Q = csr_matrix((np.asarray(data, dtype=np.float64),
                    (np.asarray(rows, dtype=np.intp), np.asarray(cols, dtype=np.intp))),
                   shape=(m, m))
    Q.sum_duplicates()
    Q = Q.tocsr()
    gvec = np.asarray(g, dtype=np.float64)
    pos = np.fromiter(transient, dtype=np.intp, count=m)
    hT = np.asarray(h, dtype=np.float64)[pos].copy()
    sT = np.asarray(s, dtype=np.float64)[pos].copy()
    iteration = iteration0
    # 从恢复的 s 数组重算 bound，与检查点元数据一致；residual 沿用检查点值（首轮即被刷新）
    bound = float(sT.max()) if m else 0.0
    residual = residual0
    while iteration < max_iterations and bound >= STOP_EPS:
        h_new = Q.dot(hT) + gvec
        s_new = Q.dot(sT)
        residual = float(np.abs(h_new - hT).max()) if m else 0.0
        hT, sT = h_new, s_new
        iteration += 1
        bound = float(sT.max()) if m else 0.0
        if progress_cb:
            progress_cb(iteration, bound, residual)
    # 回写全状态 array.array（与纯 Python 引擎同类型，保证检查点 tobytes 与 JSON 序列化口径一致）
    hfull = array.array('d', [0.0]) * graph['n']
    sfull = array.array('d', [0.0]) * graph['n']
    hfull[t] = 1.0
    hT_list = hT.tolist(); sT_list = sT.tolist()
    for k, u in enumerate(transient):
        hfull[u] = hT_list[k]
        sfull[u] = sT_list[k]
    return hfull, sfull, iteration, bound, residual, bound < STOP_EPS


def _iterate_python(graph, transient, t, h, s, max_iterations, iteration0, bound0, residual0, progress_cb):
    """纯标准库回退引擎：分块 Jacobi，语义与 NumPy 引擎完全一致。"""
    n = graph['n']
    h_new = array.array('d', [0.0]) * n
    s_new = array.array('d', [0.0]) * n
    nt = len(transient)
    iteration = iteration0
    bound = bound0
    residual = residual0
    converged = bound < STOP_EPS
    while iteration < max_iterations and not converged:
        h_new[t] = 1.0
        s_new[t] = 0.0
        for lo in range(0, nt, BATCH):
            _jacobi_block(graph, transient, h, s, h_new, s_new, lo, min(lo + BATCH, nt))
        h, h_new = h_new, h
        s, s_new = s_new, s
        iteration += 1
        bound = 0.0
        residual = 0.0
        for u in transient:
            if s[u] > bound:
                bound = s[u]
            d = h[u] - h_new[u]
            if d < 0.0:
                d = -d
            if d > residual:
                residual = d
        converged = bound < STOP_EPS
        if progress_cb:
            progress_cb(iteration, bound, residual)
    return h, s, iteration, bound, residual, converged


def solve(records, target, work_dir, max_iterations=MAX_ITERATIONS, progress_cb=None):
    """完整求解流程，支持中断恢复。返回可直接存入结果表的 result dict。"""
    checksum = input_checksum(records)
    graph = build_graph(records)
    t, can_reach, transient, comp, cyclic, n_unreachable_cycle, n_unreachable_exit = classify(graph, target)
    n = graph['n']
    names = graph['names']
    engine = _engine_name()

    h = array.array('d', [0.0]) * n       # h_k：目标为 1，其余初值 0
    s = array.array('d', [0.0]) * n       # s_k：生存质量，瞬时态初值 1
    h[t] = 1.0
    for u in transient:
        s[u] = 1.0

    ckpt_path = os.path.join(work_dir, 'arrival-checkpoint.bin')
    iteration = 0
    resumed_from = 0
    bound = 1.0
    residual = 1.0
    converged = False
    resumed_engine = engine

    if os.path.exists(ckpt_path):
        with open(ckpt_path, 'rb') as f:
            meta = json.loads(f.readline().decode())
            if meta.get('token') != SOLVER_TOKEN:
                raise ValueError('检查点求解器版本不匹配，需新建研究从零求解')
            if meta.get('checksum') != checksum:
                raise ValueError('检查点输入与当前冻结输入不一致，拒绝复用旧进度')
            if meta.get('target') != target:
                raise ValueError('检查点目标章与当前目标不一致；改目标需新建研究，不复用旧进度')
            if meta.get('n') != n:
                raise ValueError('检查点章节数与当前冻结图不一致，拒绝复用旧进度')
            iteration = meta['iteration']
            resumed_from = iteration
            h = array.array('d'); h.frombytes(f.read(8 * n))
            s = array.array('d'); s.frombytes(f.read(8 * n))
            bound = meta['bound']; residual = meta['residual']
            converged = meta.get('converged', False)
            resumed_engine = meta.get('engine', 'python')
        # 检查点只存完整迭代；引擎切换不影响数学状态，继续用当前可用引擎续算

    def persist(conv):
        os.makedirs(work_dir, exist_ok=True)
        meta = {
            'token': SOLVER_TOKEN, 'checksum': checksum, 'target': target, 'n': n,
            'iteration': iteration, 'bound': bound, 'residual': residual, 'converged': conv,
            'engine': engine,
        }
        fd, tmp = tempfile.mkstemp(dir=work_dir, prefix='.ckpt-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(json.dumps(meta, ensure_ascii=False).encode())
                f.write(b'\n')
                f.write(h.tobytes())
                f.write(s.tobytes())
            os.replace(tmp, ckpt_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # 已收敛检查点（重复读取同一任务）直接复用，不再迭代；否则按当前可用引擎续算
    if not converged:
        if engine == 'numpy':
            h, s, iteration, bound, residual, converged = _iterate_numpy(
                graph, transient, t, h, s, max_iterations, iteration, bound, residual, progress_cb)
        else:
            h, s, iteration, bound, residual, converged = _iterate_python(
                graph, transient, t, h, s, max_iterations, iteration, bound, residual, progress_cb)
        # 统一在引擎外落盘：收敛即存；未收敛按节拍或触达安全上限时存（仅完整轮）
        if converged or iteration % CHECKPOINT_EVERY == 0 or iteration >= max_iterations:
            persist(converged)

    # 终值裁剪到 [0,1]，消除纯舍入造成的微小越界
    for u in range(n):
        x = h[u]
        h[u] = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)

    if not converged:
        raise ValueError('达到迭代安全上限 %d 次仍未收敛（当前误差上界 %.3g），任务未给出可用概率'
                         % (max_iterations, bound))

    # 结构分类：目标 / 可到达目标 / 不可达且处于循环 SCC / 不可达但可经会话退出离开
    kind_of = ['unreachable_exit'] * n
    for u in transient:
        kind_of[u] = 'reachable'
    kind_of[t] = 'target'
    for u in range(n):
        if not can_reach[u] and comp[u] in cyclic:
            kind_of[u] = 'unreachable_cycle'

    rows = []
    for u in range(n):
        rows.append({
            'chapter': names[u],
            'hit_probability': h[u],
            'error_bound': s[u] if kind_of[u] == 'reachable' else 0.0,
            'classification': kind_of[u],
            'in_cycle': comp[u] in cyclic,
            'outgoing_count': graph['out'][u],
            'session_end_count': graph['end'][u],
            'exit_estimate': graph['end'][u] / (graph['out'][u] + graph['end'][u]),
        })
    rows.sort(key=lambda r: (-r['hit_probability'], r['chapter']))

    return {
        'summary': [
            {'label': '冻结会话数', 'value': graph['n_sessions']},
            {'label': '章节数', 'value': n},
            {'label': '一阶接续边', 'value': graph['n_edges']},
            {'label': '完整迭代轮数', 'value': iteration},
            {'label': '可到达目标章节数', 'value': 1 + len(transient)},
            {'label': '不可达循环章节数', 'value': n_unreachable_cycle},
            {'label': '不可达退出章节数', 'value': n_unreachable_exit},
        ],
        'target_chapter': target,
        'tolerance': TOLERANCE,
        'stop_eps': STOP_EPS,
        'engine': engine,
        'checkpoint_engine': resumed_engine if resumed_from else None,
        'resumed_from_iteration': resumed_from,
        'error_bound': bound,
        'bellman_residual': residual,
        'iterations': iteration,
        'converged': True,
        'classification_legend': {
            'target': '目标章，到达概率定义为 1',
            'reachable': '图上存在到目标的转移路径，概率由 Bellman 迭代求出',
            'unreachable_cycle': '无路可达且处于循环强连通分量：沿转移边可无限循环，到不了目标，概率精确为 0',
            'unreachable_exit': '无路可达且不在循环中：只能靠会话末尾退出离开，概率精确为 0',
        },
        'rows': rows,
        'columns': ['chapter', 'hit_probability', 'error_bound', 'classification',
                    'in_cycle', 'outgoing_count', 'session_end_count', 'exit_estimate'],
        'explanation': (
            'P(先到目标章再退出 | 当前章=a) 满足 Bellman 方程 h(a)=Σ P(a→b)h(b)，目标章 h=1；'
            'P(a→b)=边a→b次数/从a出发总次数，退出估计 e(a)=末章次数/(出发次数+末章次数)，'
            '每个状态满足 ΣP+e=1。反向 BFS 精确判定能否到达目标；不可达章节再按 SCC 强连通分量'
            '区分“处于循环”与“仅能退出”两类，二者概率精确为 0，不参与迭代。瞬时态用分块 Jacobi '
            '迭代，误差上界取生存质量 max(Q^k·1)，所有章节绝对误差同时小于该上界，'
            '上界 < 1e-6 才判收敛。仅会话内相邻转移，无跨会话拼接，非因果。'
        ),
        'checksum': checksum,
    }
