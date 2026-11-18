from sqlalchemy import Column,Integer,String,Text,JSON,ForeignKey
from ..config.database import Base
from ..config.settings import CONFIG
class ArrivalNote(Base):
    """终章研究的编辑衔接建议：仅允许引用已收敛（completed 且 result.converged）的终章任务。"""
    __tablename__=CONFIG['arrival_plan_table']
    id=Column(Integer,primary_key=True)
    arrival_run_id=Column(Integer,ForeignKey(CONFIG['arrival_table']+'.id'),nullable=False)
    title=Column(String(160),nullable=False)
    body=Column(Text,nullable=False)
    state=Column(String(20),default='draft')
    frozen_result=Column(JSON,nullable=False)
    author=Column(String(120),nullable=False)
    approved_by=Column(String(120),default='')
    created_at=Column(String(40),nullable=False)
