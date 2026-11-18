import csv,io
from fastapi import HTTPException
from fastapi.responses import Response
from ..models.note import Note
from ..models.arrival_note import ArrivalNote
from .runs import get_run
from .arrival import get_run as get_arrival_run
def csv_response(result,filename):
    buf=io.StringIO();fields=result['columns'];w=csv.DictWriter(buf,fieldnames=fields);w.writeheader()
    for r in result['rows']:w.writerow({k:r.get(k,'') for k in fields})
    return Response('﻿'+buf.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="'+filename+'"'})
def run_csv(db,id):
    r=get_run(db,id)
    if r.state!='completed':raise HTTPException(409,'结果尚未完成')
    return csv_response(r.result,'run-'+str(id)+'.csv')
def note_csv(db,id):
    n=db.get(Note,id)
    if not n:raise HTTPException(404,'未找到说明')
    if n.state!='approved':raise HTTPException(403,'仅批准后的业务说明可导出')
    return csv_response(n.frozen_result,'approved-'+str(id)+'.csv')
def arrival_csv(db,id):
    r=get_arrival_run(db,id)
    if r.state!='completed':raise HTTPException(409,'终章研究尚未完成')
    if not r.result or not r.result.get('converged'):
        raise HTTPException(409,'结果未收敛，不提供导出')
    return csv_response(r.result,'arrival-'+str(id)+'.csv')
def arrival_note_csv(db,id):
    n=db.get(ArrivalNote,id)
    if not n:raise HTTPException(404,'未找到编辑衔接建议')
    if n.state!='approved':raise HTTPException(403,'仅批准后的编辑衔接建议可导出')
    return csv_response(n.frozen_result,'arrival-approved-'+str(id)+'.csv')
