import os
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select
from redis import Redis
from ..config.settings import REDIS_URL, ARTIFACT_DIR
from ..models.arrival_run import ArrivalRun
from ..models.arrival_note import ArrivalNote
from ..utils.serialization import row, now
from .sources import source_or_404, list_records
from .audit import log
from . import arrival_solver

queue = Redis.from_url(REDIS_URL)
QUEUE_KEY = 'arrival:queue'
WORK_ROOT = Path(os.getenv('ARRIVAL_WORK_DIR', str(ARTIFACT_DIR / 'arrival')))


def work_dir_for(run_id):
    """每个终章任务独立工作目录；改目标须新建任务，目录天然隔离，旧进度不会被复用。"""
    d = WORK_ROOT / ('run-%d' % run_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_run(db, run_id):
    r = db.get(ArrivalRun, run_id)
    if not r:
        raise HTTPException(404, '未找到终章到达研究')
    return r


def _target_candidates(records):
    """从冻结会话提取全部出现过的章节，供前端选择目标章。"""
    seen = set()
    for r in records:
        for s in r['values']['path'].split('>'):
            s = s.strip()
            if s:
                seen.add(s)
    return sorted(seen)


def list_targets(db, source_id):
    source_or_404(db, source_id)
    records = list_records(db, source_id)
    if not records:
        raise HTTPException(422, '至少录入1个完整阅读会话后才能指定目标章')
    return {'targets': _target_candidates(records)}


def create_run(db, user, data):
    s = source_or_404(db, data.source_id)
    records = list_records(db, s.id)
    if not records:
        raise HTTPException(422, '至少录入1个完整阅读会话后才能执行')
    target = (data.target_chapter or '').strip()
    if not target or len(target) > 500:
        raise HTTPException(422, '目标章不能为空且最多500字符')
    candidates = set(_target_candidates(records))
    if target not in candidates:
        raise HTTPException(422, '目标章不在冻结会话出现过的章节中，请先在来源中录入')
    params = {
        'tolerance': arrival_solver.TOLERANCE,
        'stop_eps': arrival_solver.STOP_EPS,
        'max_iterations': arrival_solver.MAX_ITERATIONS,
        'batch': arrival_solver.BATCH,
    }
    r = ArrivalRun(
        source_id=s.id, name=data.name.strip(), target_chapter=target,
        state='queued', parameters=params, iterations=0, error_bound='',
        snapshot={'source': row(s), 'records': records}, created_at=now(),
    )
    db.add(r); db.flush()
    log(db, user, 'arrival.queued', r.id, '%s | 目标章=%s' % (r.name, target))
    db.commit()
    try:
        queue.rpush(QUEUE_KEY, r.id)
    except Exception:
        r.state = 'failed'; r.error = '队列暂不可用，请重新创建任务'; db.commit()
        raise HTTPException(503, r.error)
    return row(r)


def list_runs(db):
    out = []
    for r in db.scalars(select(ArrivalRun).order_by(ArrivalRun.id.desc())):
        d = {k: v for k, v in row(r).items() if k not in ('snapshot', 'result')}
        d['record_count'] = len(r.snapshot['records'])
        out.append(d)
    return out


def execute(run_id):
    """worker 执行入口：同批冻结输入、同检查点续算；半轮不计数、不落盘。"""
    from ..config.database import Session
    with Session() as db:
        r = db.get(ArrivalRun, run_id)
        if not r or r.state not in ('queued', 'running'):
            return
        r.state = 'running'
        db.commit()
        try:
            def progress(iteration, bound, residual):
                r.iterations = iteration
                r.error_bound = repr(bound)
                # 仅在检查点节拍上提交进度，保持事务短且不破坏恢复语义
                if iteration % arrival_solver.CHECKPOINT_EVERY == 0:
                    db.commit()
            result = arrival_solver.solve(
                r.snapshot['records'], r.target_chapter, str(work_dir_for(r.id)),
                max_iterations=r.parameters.get('max_iterations', arrival_solver.MAX_ITERATIONS),
                progress_cb=progress,
            )
            import json as _json
            _json.dumps(result, allow_nan=False)
            r.result = result
            r.state = 'completed'
            r.iterations = result['iterations']
            r.error_bound = repr(result['error_bound'])
            log(db, 'worker', 'arrival.completed', r.id,
                '迭代%d轮 误差上界%.3g' % (result['iterations'], result['error_bound']))
            db.commit()
        except Exception as e:
            import logging
            logging.exception('arrival analysis failed')
            r.state = 'failed'
            r.error = str(e)[:2000]
            log(db, 'worker', 'arrival.failed', r.id, r.error)
            db.commit()


def requeue_interrupted(db):
    """启动恢复：上次 worker 中断留下的 running/queued 任务重新入队，检查点续算。"""
    ids = [r.id for r in db.scalars(
        select(ArrivalRun).where(ArrivalRun.state.in_(('queued', 'running'))))]
    for rid in ids:
        try:
            queue.rpush(QUEUE_KEY, rid)
        except Exception:
            pass
    return ids


# ---------- 编辑衔接建议：仅采用收敛结果 ----------

def list_notes(db):
    return [row(n) for n in db.scalars(select(ArrivalNote).order_by(ArrivalNote.id.desc()))]


def create_note(db, user, data):
    r = get_run(db, data.arrival_run_id)
    if r.state != 'completed':
        raise HTTPException(409, '终章研究尚未完成，不能据此提交编辑衔接建议')
    if not r.result or not r.result.get('converged') or r.result.get('error_bound', 1) >= arrival_solver.TOLERANCE:
        raise HTTPException(409, '仅当误差上界 < 1e-6 的收敛结果才可用于编辑衔接建议')
    n = ArrivalNote(
        arrival_run_id=r.id, title=data.title, body=data.body, state='draft',
        frozen_result=r.result, author=user.email, created_at=now(),
    )
    db.add(n); db.flush()
    log(db, user, 'arrival_note.created', n.id, n.title)
    db.commit()
    return row(n)


def approve_note(db, user, note_id):
    n = db.get(ArrivalNote, note_id)
    if not n:
        raise HTTPException(404, '未找到编辑衔接建议')
    if n.state != 'draft':
        raise HTTPException(409, '该建议已经批准')
    n.state = 'approved'; n.approved_by = user.email
    log(db, user, 'arrival_note.approved', n.id, n.title)
    db.commit()
    return row(n)
