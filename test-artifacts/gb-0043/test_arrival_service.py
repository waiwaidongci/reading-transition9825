"""终章服务层集成测试：用 sys.modules 桩替换 SQLAlchemy/Redis/FastAPI，
仅验证 backend/src/services/arrival.py 的业务规则（无需安装 Web 框架）。

覆盖：
- 目标章必须在冻结会话中；非法/空目标 422；
- 创建任务入队、独立工作目录（改目标=新任务=新目录，天然不复用进度）；
- execute 收敛后写 result/iterations/error_bound；
- 中断（低迭代上限失败）后再执行可沿检查点恢复到收敛；
- 编辑建议：未完成/未收敛一律拒绝；仅 error_bound<1e-6 的收敛结果可建建议并批准/导出。
"""
import os
import shutil
import sys
import tempfile
import types

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
sys.path.insert(0, BACKEND)
# 先注册父包占位并设置 __path__，保证后续 src.* 子模块桩不会落到命名空间包的未知位置
_PKG_PATHS = {
    'src': [os.path.join(BACKEND, 'src')],
    'src.config': [os.path.join(BACKEND, 'src', 'config')],
    'src.models': [os.path.join(BACKEND, 'src', 'models')],
    'src.utils': [os.path.join(BACKEND, 'src', 'utils')],
    'src.services': [os.path.join(BACKEND, 'src', 'services')],
}
for _pkg, _paths in _PKG_PATHS.items():
    _m = types.ModuleType(_pkg)
    _m.__path__ = _paths
    sys.modules.setdefault(_pkg, _m)


# ---- 桩：在导入 arrival 服务前注入其重依赖 ----
class _StubModel:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeDB:
    def __init__(self):
        self.runs = {}
        self.notes = {}
        self._rid = 0
        self._nid = 0

    def add(self, obj):
        if type(obj).__name__ == 'ArrivalRun':
            self._rid += 1
            obj.id = self._rid
            self.runs[obj.id] = obj
        elif type(obj).__name__ == 'ArrivalNote':
            self._nid += 1
            obj.id = self._nid
            self.notes[obj.id] = obj

    def flush(self):
        pass

    def commit(self):
        pass

    def get(self, model, pk):
        name = getattr(model, '__name__', '')
        return self.runs.get(pk) if name == 'ArrivalRun' else self.notes.get(pk)


class _FakeRedis:
    def __init__(self):
        self.queued = []

    def rpush(self, key, value):
        self.queued.append((key, value))

    def ping(self):
        return True


FAKE_DB = _FakeDB()
FAKE_REDIS = _FakeRedis()


def _install_stubs():
    # settings
    settings = types.ModuleType('src.config.settings')
    settings.REDIS_URL = 'redis://stub'
    work_root = tempfile.mkdtemp(prefix='arrival-work-')
    settings.ARTIFACT_DIR = types.SimpleNamespace(__truediv__=lambda self, x: __import__('pathlib').Path(work_root) / x)
    # 让 WORK_ROOT 指向临时目录
    import pathlib
    settings.ARTIFACT_DIR = pathlib.Path(work_root)
    sys.modules['src.config.settings'] = settings

    # database
    database = types.ModuleType('src.config.database')
    class Session:
        def __enter__(self):
            return FAKE_DB
        def __exit__(self, *a):
            return False
    database.Session = Session
    sys.modules['src.config.database'] = database

    # redis
    redis_mod = types.ModuleType('redis')
    class Redis:
        @classmethod
        def from_url(cls, url):
            return FAKE_REDIS
    redis_mod.Redis = Redis
    sys.modules['redis'] = redis_mod

    # fastapi
    fastapi = types.ModuleType('fastapi')
    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)
    fastapi.HTTPException = HTTPException
    sys.modules['fastapi'] = fastapi

    # sqlalchemy
    sqlalchemy = types.ModuleType('sqlalchemy')
    def select(*a, **k):
        return ('select', a)
    sqlalchemy.select = select

    # 让 db.scalars(...).all() 返回当前 run 列表；db.scalar 通用返回 None
    def scalars(stmt):
        return types.SimpleNamespace(all=lambda: list(FAKE_DB.runs.values()))
    FAKE_DB.scalars = scalars
    FAKE_DB.scalar = lambda stmt: None
    sqlalchemy.select = select
    sys.modules['sqlalchemy'] = sqlalchemy

    # 父包已在顶部注册并带 __path__，这里确保子模块桩可直接挂载
    for pkg in ('src', 'src.config', 'src.models', 'src.utils', 'src.services'):
        sys.modules.setdefault(pkg, sys.modules[pkg])

    # models
    ar_run_mod = types.ModuleType('src.models.arrival_run')
    class ArrivalRun(_StubModel):
        pass
    ar_run_mod.ArrivalRun = ArrivalRun
    sys.modules['src.models.arrival_run'] = ar_run_mod
    ar_note_mod = types.ModuleType('src.models.arrival_note')
    class ArrivalNote(_StubModel):
        pass
    ar_note_mod.ArrivalNote = ArrivalNote
    sys.modules['src.models.arrival_note'] = ar_note_mod

    # utils
    ser = types.ModuleType('src.utils.serialization')
    import datetime
    ser.now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    def row(obj):
        return {k: getattr(obj, k) for k in vars(obj)}
    ser.row = row
    sys.modules['src.utils.serialization'] = ser

    # services.sources / audit 桩
    sources = types.ModuleType('src.services.sources')
    sources.source_or_404 = lambda db, sid: types.SimpleNamespace(id=sid)
    def list_records(db, sid):
        return _RECORDS
    sources.list_records = list_records
    sys.modules['src.services.sources'] = sources
    audit = types.ModuleType('src.services.audit')
    audit.log = lambda *a, **k: None
    sys.modules['src.services.audit'] = audit
    return work_root


_RECORDS = [
    {'id': 1, 'values': {'session': 'a1', 'path': 'A>B>C'}},
    {'id': 2, 'values': {'session': 'a2', 'path': 'A>C'}},
    {'id': 3, 'values': {'session': 'a3', 'path': 'B>Z'}},
    {'id': 4, 'values': {'session': 'a4', 'path': 'B'}},
    {'id': 5, 'values': {'session': 'a5', 'path': 'D>B>E'}},
]

FAIL = []
def check(name, cond, detail=''):
    print(('[PASS] ' if cond else '[FAIL] ') + name + ((' :: ' + detail) if detail else ''))
    if not cond:
        FAIL.append(name)


class _User:
    def __init__(self, email='analyst@x.demo'):
        self.email = email


def main():
    work_root = _install_stubs()
    from src.services import arrival
    from src.services.arrival_solver import TOLERANCE

    # 目标章候选
    targets = arrival.list_targets(FAKE_DB, 1)
    check('目标候选含全部出现章节', set(targets['targets']) == {'A', 'B', 'C', 'D', 'E', 'Z'})

    # 非法目标
    try:
        arrival.create_run(FAKE_DB, _User(), types.SimpleNamespace(
            source_id=1, name='坏目标研究', target_chapter='不存在'))
        check('未知目标章被拒绝', False)
    except Exception as e:
        check('未知目标章被拒绝(422)', getattr(e, 'status_code', None) == 422)

    # 空目标
    try:
        arrival.create_run(FAKE_DB, _User(), types.SimpleNamespace(
            source_id=1, name='空目标', target_chapter='  '))
        check('空目标被拒绝', False)
    except Exception as e:
        check('空目标被拒绝(422)', getattr(e, 'status_code', None) == 422)

    # 合法创建并入队
    data = types.SimpleNamespace(source_id=1, name='终章C研究', target_chapter='C')
    r = arrival.create_run(FAKE_DB, _User(), data)
    check('创建后状态 queued', r['state'] == 'queued')
    check('已推入终章队列', FAKE_REDIS.queued and FAKE_REDIS.queued[-1][0] == arrival.QUEUE_KEY)
    run_id = r['id']
    wd = arrival.work_dir_for(run_id)
    check('每任务独立工作目录', os.path.isdir(str(wd)))

    # worker 执行到收敛
    arrival.execute(run_id)
    run = FAKE_DB.runs[run_id]
    check('执行后 completed', run.state == 'completed')
    check('结果标记收敛且上界<1e-6',
          run.result['converged'] is True and run.result['error_bound'] < TOLERANCE)
    check('iterations 与结果一致', run.iterations == run.result['iterations'] and run.iterations > 0)

    # 中断恢复：再建一个同目标任务，先用极小上限制造失败，再正常执行恢复
    r2 = arrival.create_run(FAKE_DB, _User(),
                            types.SimpleNamespace(source_id=1, name='中断恢复研究', target_chapter='C'))
    rid2 = r2['id']
    # 直接调底层 solver，用 1 轮上限落盘一个早期检查点（只含完整迭代，不含半轮）
    from src.services import arrival_solver
    ck = os.path.join(str(arrival.work_dir_for(rid2)), 'arrival-checkpoint.bin')
    try:
        arrival_solver.solve(_RECORDS, 'C', str(arrival.work_dir_for(rid2)), max_iterations=1)
    except ValueError:
        pass
    check('早期检查点已落盘且只记录完整迭代（1 轮）', os.path.exists(ck))
    if os.path.exists(ck):
        import json as _json
        with open(ck, 'rb') as f:
            meta = _json.loads(f.readline().decode())
        check('检查点轮数=1，绝无半轮混入', meta['iteration'] == 1)
    # 模拟 worker 用默认上限执行 -> 应沿检查点恢复并收敛
    arrival.execute(rid2)
    run2 = FAKE_DB.runs[rid2]
    check('中断任务恢复后收敛', run2.state == 'completed' and run2.result['error_bound'] < TOLERANCE)
    check('两次求解概率一致',
          all(abs(a['hit_probability'] - b['hit_probability']) < 1e-12
              for a, b in zip(run.result['rows'], run2.result['rows'])))

    # ---- 编辑建议仅采用收敛结果 ----
    # 未完成任务
    r3 = arrival.create_run(FAKE_DB, _User(),
                            types.SimpleNamespace(source_id=1, name='排队中任务', target_chapter='C'))
    try:
        arrival.create_note(FAKE_DB, _User(), types.SimpleNamespace(
            arrival_run_id=r3['id'], title='不能这样做', body='x' * 10))
        check('未完成任务不可建建议', False)
    except Exception as e:
        check('未完成任务拒绝建议(409)', getattr(e, 'status_code', None) == 409)

    # 手动伪造一个 completed 但未收敛的任务，应被拒绝
    ArrivalRunCls = sys.modules['src.models.arrival_run'].ArrivalRun
    fake = ArrivalRunCls(
        source_id=1, name='未收敛完成', target_chapter='C', state='completed',
        result={'converged': True, 'error_bound': 2e-6}, snapshot={'records': _RECORDS})
    FAKE_DB.add(fake)
    try:
        arrival.create_note(FAKE_DB, _User(), types.SimpleNamespace(
            arrival_run_id=fake.id, title='不应通过', body='y' * 10))
        check('未收敛(上界>=1e-6)不可建建议', False)
    except Exception as e:
        check('未收敛结果拒绝建议(409)', getattr(e, 'status_code', None) == 409)

    # 收敛任务可建建议
    n = arrival.create_note(FAKE_DB, _User(), types.SimpleNamespace(
        arrival_run_id=run_id, title='终章衔接意见', body='仅基于收敛快照' * 2))
    check('建议草案创建成功并冻结收敛结果',
          n['state'] == 'draft' and n['frozen_result']['error_bound'] < TOLERANCE)
    # 非 admin 批准拒绝（服务层未强制角色，由路由依赖保证；这里验证 admin 可批准）
    admin = _User('admin@x.demo')
    approved = arrival.approve_note(FAKE_DB, admin, n['id'])
    check('负责人批准后状态 approved', approved['state'] == 'approved'
          and approved['approved_by'] == admin.email)

    # 改目标 = 新任务 = 不同工作目录，绝不共享检查点
    r4 = arrival.create_run(FAKE_DB, _User(),
                            types.SimpleNamespace(source_id=1, name='改目标研究', target_chapter='B'))
    check('改目标产生独立任务与独立目录',
          r4['id'] != run_id and str(arrival.work_dir_for(r4['id'])) != str(wd))
    check('新任务目录无旧检查点',
          not os.path.exists(os.path.join(str(arrival.work_dir_for(r4['id'])), 'arrival-checkpoint.bin')))

    shutil.rmtree(work_root, ignore_errors=True)
    print('\n%s' % ('服务层测试全部通过 ✓' if not FAIL else '失败: %s' % FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
