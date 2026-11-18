import json,time,logging
from redis import Redis
from sqlalchemy import select
from .config.database import Session
from .config.settings import REDIS_URL,ARTIFACT_DIR
from .models.run import Run
from .models import source,record,user,note,audit
from .models import arrival_run,arrival_note
from .services.algorithm import calculate
from .services import arrival
from .services.audit import log
from .services.export import csv_response
queue=Redis.from_url(REDIS_URL)
ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
def execute(id):
    with Session() as db:
        r=db.get(Run,id)
        if not r or r.state!='queued':return
        r.state='running';db.commit()
        try:
            result=calculate(r.snapshot['records'],r.parameters)
            json.dumps(result,allow_nan=False)
            r.result=result;r.state='completed'
            response=csv_response(result,'run.csv')
            (ARTIFACT_DIR/f'run-{r.id}.csv').write_bytes(response.body)
            log(db,'worker','run.completed',r.id)
        except Exception as e:
            logging.exception('analysis failed');r.state='failed';r.error=str(e)[:2000]
            log(db,'worker','run.failed',r.id,r.error)
        db.commit()
def main():
    # 启动恢复：worker 中断时遗留在 queued/running 的终章任务按同批输入与检查点重新入队
    with Session() as db:
        requeued=arrival.requeue_interrupted(db)
    if requeued:
        logging.info('arrival runs requeued after worker restart: %s',requeued)
    while True:
        (ARTIFACT_DIR/'heartbeat').write_text(str(time.time()))
        # 两条队列轮询；一步研究与终章到达研究独立排队、独立求解
        value=queue.blpop('analysis:queue',arrival.QUEUE_KEY,timeout=2)
        if not value:continue
        key,payload=value
        try:rid=int(payload)
        except ValueError:continue
        if key==arrival.QUEUE_KEY.encode():
            arrival.execute(rid)
        else:
            execute(rid)
if __name__=='__main__':main()
