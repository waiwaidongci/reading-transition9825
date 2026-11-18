import os,logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from .config.database import Base,engine,Session
from .config.settings import CONFIG
from .models import user,source,record,run,note,audit,arrival_run,arrival_note
from .middlewares.errors import error_boundary
from .middlewares.rate_limit import rate_limit
from .routes import auth,sources,runs,notes,audit as audit_routes,arrivals
from .services.runs import queue
from .services import arrival
@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    # 启动恢复：worker 中断遗留的终章任务重新入队，沿用同批冻结输入与求解检查点
    try:
        with Session() as db:
            arrival.requeue_interrupted(db)
    except Exception:logging.exception('arrival requeue failed')
    if os.getenv('SEED_DEMO','true')=='true':
        try:
            from scripts.seed_demo import seed
            seed()
        except Exception:logging.exception('seed failed; service remains available')
    yield
app=FastAPI(title=CONFIG['title'],lifespan=lifespan)
app.middleware('http')(error_boundary)
app.middleware('http')(rate_limit)
for router in (auth.router,sources.router,runs.router,notes.router,audit_routes.router,arrivals.router):app.include_router(router)
@app.get('/health')
def health():
    with engine.connect() as c:c.execute(text('SELECT 1'))
    queue.ping();return {'status':'ok'}
@app.get('/catalog')
def catalog():return CONFIG
