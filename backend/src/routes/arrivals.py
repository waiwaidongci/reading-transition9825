from fastapi import APIRouter,Depends
from ..config.database import db_session
from ..schemas.arrival import ArrivalRunInput,ArrivalNoteInput
from ..services.auth import current_user,writer,admin
from ..services.export import arrival_csv,arrival_note_csv
from ..controllers.arrivals import ArrivalsController as C
router=APIRouter()

@router.get('/arrivals')
def list_runs(db=Depends(db_session),u=Depends(current_user)):return C.list(db)

# 注意：静态路径 /arrivals/targets 必须在参数路径 /arrivals/{id} 之前注册，
# 否则 targets 会被当作整数 id 解析并触发 422。
@router.get('/arrivals/targets')
def targets(source_id:int,db=Depends(db_session),u=Depends(current_user)):
    return C.targets(db,source_id)

@router.post('/arrivals')
def create(data:ArrivalRunInput,db=Depends(db_session),u=Depends(writer)):
    return C.create(db,u,data)

@router.get('/arrivals/{id}')
def detail(id:int,db=Depends(db_session),u=Depends(current_user)):return C.get(db,id)

@router.get('/arrivals/{id}/export')
def export(id:int,db=Depends(db_session),u=Depends(current_user)):
    return arrival_csv(db,id)

@router.get('/arrival-notes')
def list_notes(db=Depends(db_session),u=Depends(current_user)):return C.notes(db)

@router.post('/arrival-notes')
def create_note(data:ArrivalNoteInput,db=Depends(db_session),u=Depends(writer)):
    return C.create_note(db,u,data)

@router.post('/arrival-notes/{id}/approve')
def approve(id:int,db=Depends(db_session),u=Depends(admin)):
    return C.approve_note(db,u,id)

@router.get('/arrival-notes/{id}/export')
def note_export(id:int,db=Depends(db_session),u=Depends(current_user)):
    return arrival_note_csv(db,id)
