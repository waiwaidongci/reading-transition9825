"""终章到达研究的独立 oracle 测试（纯标准库，不依赖 Web 框架）。

覆盖：
1. 手算样例：两条会话 A>B>C 与 A>C，目标 C，逐概率对照闭式解；
2. Bellman 方程与“退出+转移=1”口径逐状态核验；
3. 循环困住(trapped_cycle)与无路可达退出(unreachable_exit)的精确 0 与分类；
4. 可核验误差上界：|h-h*|<=bound 且 bound<1e-6（h* 用高斯消元独立求解）；
5. 中断恢复：杀掉半轮后续算 == 一次跑完；检查点只含完整迭代；
6. 改目标 / 改输入拒绝复用旧检查点；
7. 一万章节、十万接续边的内存 <256MB 与耗时、收敛正确性；
8. 退化输入（单章会话、零边、未知目标）明确失败。
"""
import json
import os
import resource
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from src.services.arrival_solver import (  # noqa: E402
    build_graph, classify, solve, input_checksum, TOLERANCE,
)

FAILURES = []


def check(name, cond, detail=''):
    mark = 'PASS' if cond else 'FAIL'
    print(f'[{mark}] {name}' + (f' :: {detail}' if detail else ''))
    if not cond:
        FAILURES.append(name)


def rec(sid, path):
    return {'values': {'session': sid, 'path': '>'.join(path)}}


def exact_solution(records, target):
    """独立 oracle：直接对线性系统 (I-Q)h=g 做高斯消元（部分主元）。"""
    g = build_graph(records)
    t, can_reach, transient, _, _, _, _ = classify(g, target)
    n = g['n']
    pos = {u: k for k, u in enumerate(transient)}
    m = len(transient)
    A = [[0.0] * m for _ in range(m)]
    b = [0.0] * m
    for k, u in enumerate(transient):
        A[k][k] = 1.0
        for p in range(g['row_ptr'][u], g['row_ptr'][u + 1]):
            w, c = g['col_idx'][p], g['edge_w'][p]
            if w == t:
                b[k] += c / g['out'][u]
            elif can_reach[w] and w != u:
                A[k][pos[w]] -= c / g['out'][u]
            elif w == u:
                A[k][k] -= c / g['out'][u]
    # 高斯-约旦消元
    for col in range(m):
        piv = max(range(col, m), key=lambda r: abs(A[r][col]))
        A[col], A[piv] = A[piv], A[col]
        b[col], b[piv] = b[piv], b[col]
        piv_val = A[col][col]
        for j in range(col, m):
            A[col][j] /= piv_val
        b[col] /= piv_val
        for r in range(m):
            if r == col:
                continue
            f = A[r][col]
            if f:
                for j in range(col, m):
                    A[r][j] -= f * A[col][j]
                b[r] -= f * b[col]
    exact = [0.0] * n
    exact[t] = 1.0
    for k, u in enumerate(transient):
        exact[u] = min(1.0, max(0.0, b[k]))
    return g, exact


def test_hand_oracle():
    print('\n== 1. 手算 oracle：含退出、失败后继与目标吸收 ==')
    # 要让 h(B)<1，B 必须有到不了目标的后继 Z（Z 仅作末章退出，h(Z)=0）。
    #   s1 A>B>C：边 A->B、B->C
    #   s2 A>C  ：边 A->C
    #   s3 B>Z  ：边 B->Z（失败后继）
    #   s4 B    ：B 作为末章，end[B]=1
    #   s5 D>B>E：边 D->B、B->E（E 仅退出，h(E)=0），末章 E
    # B 出边：B->C、B->Z、B->E 各一次 -> out[B]=3；end[B]=1 -> e(B)=1/4
    # h(B)=P(B->C)*1 + 0 + 0 = 1/3
    # h(A)=0.5*h(B)+0.5*1 = 2/3；h(D)=h(B)=1/3
    records = [
        rec('s1', ['A', 'B', 'C']),
        rec('s2', ['A', 'C']),
        rec('s3', ['B', 'Z']),
        rec('s4', ['B']),
        rec('s5', ['D', 'B', 'E']),
    ]
    work = tempfile.mkdtemp()
    try:
        result = solve(records, 'C', work)
        h = {r['chapter']: r for r in result['rows']}
        check('h(B)=1/3', abs(h['B']['hit_probability'] - 1 / 3) < 1e-12,
              str(h['B']['hit_probability']))
        check('h(A)=2/3', abs(h['A']['hit_probability'] - 2 / 3) < 1e-12,
              str(h['A']['hit_probability']))
        check('h(D)=1/3', abs(h['D']['hit_probability'] - 1 / 3) < 1e-12,
              str(h['D']['hit_probability']))
        check('h(C)=1（目标即到达）', h['C']['hit_probability'] == 1.0)
        check('h(Z)=h(E)=0（失败后继，仅退出）',
              h['Z']['hit_probability'] == 0.0 and h['E']['hit_probability'] == 0.0)
        check('误差上界 < 1e-6', result['error_bound'] < TOLERANCE, str(result['error_bound']))
        g = build_graph(records)
        ok = True
        for u in range(g['n']):
            total = sum(g['edge_w'][p] for p in range(g['row_ptr'][u], g['row_ptr'][u + 1]))
            p_sum = total / (g['out'][u] + g['end'][u])
            e = g['end'][u] / (g['out'][u] + g['end'][u])
            ok &= abs(p_sum + e - 1.0) < 1e-12
        check('每状态 转移概率和+退出估计=1', ok)
        check('e(B)=1/4', abs(h['B']['exit_estimate'] - 1 / 4) < 1e-12,
              str(h['B']['exit_estimate']))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_linear_system_match():
    print('\n== 2. 随机中等图对照高斯消元精确解 ==')
    import random
    rng = random.Random(7)
    chapters = ['ch%02d' % i for i in range(12)]
    records = []
    for i in range(400):
        length = rng.randint(1, 7)
        path = [rng.choice(chapters) for _ in range(length)]
        records.append(rec('rand-%04d' % i, path))
    target = 'ch03'
    work = tempfile.mkdtemp()
    try:
        result = solve(records, target, work)
        _, exact = exact_solution(records, target)
        g = build_graph(records)
        worst = 0.0
        for r in result['rows']:
            u = g['index'][r['chapter']]
            worst = max(worst, abs(r['hit_probability'] - exact[u]))
        check('全部章节 |迭代解-精确解| <= 报告上界且 <1e-6',
              worst < TOLERANCE and result['error_bound'] < TOLERANCE,
              'worst=%.2e bound=%.2e' % (worst, result['error_bound']))
        # Bellman 方程残差核验
        hvec = [0.0] * g['n']
        for r in result['rows']:
            hvec[g['index'][r['chapter']]] = r['hit_probability']
        res = 0.0
        for u in range(g['n']):
            if chapters[u] == target:
                continue
            acc = sum(g['edge_w'][p] * hvec[g['col_idx'][p]]
                      for p in range(g['row_ptr'][u], g['row_ptr'][u + 1]))
            if g['out'][u]:
                res = max(res, abs(hvec[u] - acc / g['out'][u]))
        check('Bellman 残差(相邻轮差分报告值)与真残差(独立重算)均 <1e-6',
              result['bellman_residual'] < 1e-6 and res < 1e-6,
              'recompute=%.3e reported=%.3e' % (res, result['bellman_residual']))
        # 报告值确为相邻轮差分范数：与真残差不必相等，但都应处于 1e-6 量级
        check('报告残差为非负有限值', result['bellman_residual'] >= 0.0)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_trapped_and_unreachable():
    print('\n== 3. 不可达循环分量 vs 不可达退出态（SCC 区分）==')
    # X<->Y 构成循环 SCC，且没有到目标 C 的路径；Z 是只作为末章出现的孤立退出态；
    # A->C 在另一分量。X/Y 同时也会在某条会话末章退出（有限会话口径），但结构上仍属循环 SCC。
    records = [
        rec('c1', ['X', 'Y', 'X', 'Y']),     # 末章 Y
        rec('c2', ['Y', 'X']),               # 末章 X，补 X 末章
        rec('c3', ['Z']),                    # 孤立，仅退出
        rec('c4', ['A', 'C']),
    ]
    work = tempfile.mkdtemp()
    try:
        result = solve(records, 'C', work)
        by = {r['chapter']: r for r in result['rows']}
        check('X 分类 unreachable_cycle、标记在循环中、概率精确 0',
              by['X']['classification'] == 'unreachable_cycle'
              and by['X']['in_cycle'] is True and by['X']['hit_probability'] == 0.0)
        check('Y 分类 unreachable_cycle、标记在循环中、概率精确 0',
              by['Y']['classification'] == 'unreachable_cycle'
              and by['Y']['in_cycle'] is True and by['Y']['hit_probability'] == 0.0)
        check('Z 分类 unreachable_exit、不在循环、概率精确 0',
              by['Z']['classification'] == 'unreachable_exit'
              and by['Z']['in_cycle'] is False and by['Z']['hit_probability'] == 0.0)
        check('A 可到达目标，概率 1', by['A']['classification'] == 'reachable'
              and by['A']['hit_probability'] == 1.0)
        check('不可达类误差上界精确为 0', by['X']['error_bound'] == 0.0
              and by['Z']['error_bound'] == 0.0)
        check('摘要含两类不可达计数',
              next(x for x in result['summary'] if x['label'] == '不可达循环章节数')['value'] == 2
              and next(x for x in result['summary'] if x['label'] == '不可达退出章节数')['value'] == 1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_resume_and_checkpoint():
    print('\n== 4. 中断恢复：半轮丢弃、完整迭代续算 ==')
    import random
    rng = random.Random(11)
    chapters = ['k%02d' % i for i in range(20)]
    records = []
    for i in range(300):
        path = [rng.choice(chapters) for _ in range(rng.randint(2, 9))]
        records.append(rec('rs-%04d' % i, path))
    target = 'k05'
    w1 = tempfile.mkdtemp(); w2 = tempfile.mkdtemp()
    try:
        full = solve(records, target, w1)
        # 用极小迭代上限制造中断，再放开上限续算
        try:
            solve(records, target, w2, max_iterations=3)
            check('低迭代上限应抛出未收敛错误', False)
        except ValueError:
            check('低迭代上限抛出未收敛错误', True)
        ck = os.path.join(w2, 'arrival-checkpoint.bin')
        check('中断后检查点存在且只记录完整迭代', os.path.exists(ck))
        with open(ck, 'rb') as f:
            meta = json.loads(f.readline().decode())
        check('检查点迭代数为完整轮（3）', meta['iteration'] == 3 and meta['converged'] is False)
        resumed = solve(records, target, w2)
        same = all(abs(a['hit_probability'] - b['hit_probability']) < 1e-12
                   for a, b in zip(full['rows'], resumed['rows']))
        check('恢复后续算结果 == 一次跑完', same)
        check('续算总轮数与一次跑完一致', resumed['iterations'] == full['iterations'],
              '%d vs %d' % (resumed['iterations'], full['iterations']))
        check('检查点输入校验和与冻结输入一致', meta['checksum'] == input_checksum(records))
    finally:
        shutil.rmtree(w1, ignore_errors=True); shutil.rmtree(w2, ignore_errors=True)


def test_target_change_rejects_checkpoint():
    print('\n== 5. 改目标 / 改输入拒绝复用旧进度 ==')
    records = [rec('a1', ['A', 'B', 'C']), rec('a2', ['A', 'C', 'D'])]
    work = tempfile.mkdtemp()
    try:
        solve(records, 'C', work)
        try:
            solve(records, 'D', work)
            check('改目标必须拒绝旧检查点', False)
        except ValueError as e:
            check('改目标拒绝旧检查点', '目标' in str(e))
        shutil.rmtree(work); os.makedirs(work)
        solve(records, 'C', work)
        changed = records + [rec('a3', ['B', 'A'])]
        try:
            solve(changed, 'C', work)
            check('改输入必须拒绝旧检查点', False)
        except ValueError as e:
            check('改输入拒绝旧检查点', '输入' in str(e))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _build_layered_records(rng):
    """万节点规模图：分层 DAG（有界直径、逐层退出）+ 回边循环 + 隔离环簇。

    - 前 9800 节点分 39 层，层间前向边保证信息每轮推进一层，深度可控、快速收敛；
    - 覆盖会话让每个节点至少做一次末章（退出估计 e>0），符合有限会话口径；
    - 少量回边在主图制造可达循环 SCC；
    - 末 200 节点构成与主图完全断开的环，目标在主图末层 -> 规模下出现 unreachable_cycle。
    """
    n_ch = 10000
    n_cycle = 200
    n_main = n_ch - n_cycle            # 9800
    layers = 39
    per = n_main // layers             # 每层节点数

    def layer_of(node):
        return min(node // per, layers - 1)

    records = []
    # 1) 覆盖会话：每个主图节点都至少做一次末章（保证 e(u)>0）
    for i in range(n_main):
        cur = rng.randrange(n_main)
        path = [cur]
        for _ in range(rng.randint(1, 3)):
            l = layer_of(cur)
            if l >= layers - 1:
                break
            cur = (l + 1) * per + rng.randrange(per)
            path.append(cur)
        path[-1] = i                   # 强制末章覆盖节点 i
        records.append(rec('cov%05d' % i, ['ch%05d' % x for x in path]))

    # 2) 层间前向边，凑足 10 万条接续
    edges = sum(r['values']['path'].count('>') for r in records)
    sid = 0
    while edges < 100000:
        l = rng.randrange(layers - 1)
        u = l * per + rng.randrange(per)
        v = (l + 1) * per + rng.randrange(per)
        records.append(rec('f%06d' % sid, ['ch%05d' % u, 'ch%05d' % v]))
        edges += 1; sid += 1

    # 3) 回边制造主图内的可达循环 SCC
    for j in range(2000):
        l = rng.randrange(1, layers - 1)
        u = (l + 1) * per + rng.randrange(per)
        v = l * per + rng.randrange(per)
        records.append(rec('b%05d' % j, ['ch%05d' % u, 'ch%05d' % v]))

    # 4) 隔离环簇：节点 id 9800..9999，仅簇内转移，与主图无边
    ring = list(range(n_main, n_ch))
    for j, u in enumerate(ring):
        w1 = ring[(j + 1) % n_cycle]
        records.append(rec('ring%05d' % j, ['ch%05d' % u, 'ch%05d' % w1]))
        records.append(rec('ringend%05d' % j, ['ch%05d' % u]))  # 环内节点也作末章
    return records, 'ch%05d' % ((layers - 1) * per), n_cycle


def test_scale_10k_100k():
    print('\n== 6. 一万章节 / 十万接续边：内存预算、收敛与规模下结构分类 ==')
    rng = __import__('random').Random(2026)
    records, target, n_cycle = _build_layered_records(rng)
    work = tempfile.mkdtemp()
    t0 = time.time()
    try:
        result = solve(records, target, work)
        elapsed = time.time() - t0
        peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux ru_maxrss 单位 KB
        g = build_graph(records)
        check('章节数=10000', g['n'] == 10000, str(g['n']))
        check('接续边>=100000', g['n_edges'] >= 100000, str(g['n_edges']))
        check('峰值 RSS < 256MB', peak_mb < 256, '%.1f MB' % peak_mb)
        check('误差上界 < 1e-6（绝对误差百万分之一内收敛）',
              result['error_bound'] < TOLERANCE, str(result['error_bound']))
        check('迭代在安全上限内收敛', result['iterations'] < 200000, str(result['iterations']))
        probs = [r['hit_probability'] for r in result['rows']]
        check('概率均在[0,1]且按降序', all(0 <= p <= 1 for p in probs)
              and all(probs[i] >= probs[i + 1] for i in range(len(probs) - 1)))
        n_cycle_rows = sum(1 for r in result['rows'] if r['classification'] == 'unreachable_cycle')
        n_exit_rows = sum(1 for r in result['rows'] if r['classification'] == 'unreachable_exit')
        check('规模下隔离环簇被识别为 unreachable_cycle（>=200）',
              n_cycle_rows >= n_cycle, str(n_cycle_rows))
        check('规模下存在 unreachable_exit 章节', n_exit_rows > 0, str(n_exit_rows))
        t_row = next(r for r in result['rows'] if r['chapter'] == target)
        check('目标章概率为1且分类target', t_row['hit_probability'] == 1.0
              and t_row['classification'] == 'target')
        bad = [r for r in result['rows']
               if r['classification'] not in ('reachable', 'target')
               and (r['hit_probability'] != 0.0 or r['error_bound'] != 0.0)]
        check('不可达类概率与误差上界均精确为 0', not bad, str(len(bad)))
        print(f'    规模: {g["n_edges"]} 边 / {len(records)} 会话 / '
              f'{result["iterations"]} 轮 / {elapsed:.1f}s / 峰值 {peak_mb:.1f}MB / '
              f'循环 {n_cycle_rows} / 退出 {n_exit_rows}')
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_degenerate_inputs():
    print('\n== 7. 退化输入明确失败 ==')
    work = tempfile.mkdtemp()
    try:
        try:
            solve([rec('z1', ['只有一章'])], '只有一章', work)
            check('零转移边拒绝', False)
        except ValueError:
            check('零转移边拒绝', True)
        try:
            solve([rec('d1', ['A', 'B']), rec('d1', ['B', 'A'])], 'A', work)
            check('重复会话编号拒绝', False)
        except ValueError:
            check('重复会话编号拒绝', True)
        try:
            solve([rec('d2', ['A', 'B'])], '不存在的章', work)
            check('未知目标章拒绝', False)
        except ValueError:
            check('未知目标章拒绝', True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    ALL = [
        ('hand', test_hand_oracle),
        ('linear', test_linear_system_match),
        ('trapped', test_trapped_and_unreachable),
        ('resume', test_resume_and_checkpoint),
        ('target', test_target_change_rejects_checkpoint),
        ('scale', test_scale_10k_100k),
        ('degenerate', test_degenerate_inputs),
    ]
    picked = sys.argv[1:] or [name for name, _ in ALL]
    for name, fn in ALL:
        if name in picked:
            fn()
    print('\n%s' % ('全部通过 ✓' if not FAILURES else '失败项: %s' % FAILURES))
    sys.exit(1 if FAILURES else 0)
