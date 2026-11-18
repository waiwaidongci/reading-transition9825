from sqlalchemy import Column,Integer,String,JSON,Text,ForeignKey
from ..config.database import Base
from ..config.settings import CONFIG
class ArrivalRun(Base):
    """终章到达研究任务：指定目标章，对冻结会话求解“先到目标再退出”概率。"""
    __tablename__=CONFIG['arrival_table']
    id=Column(Integer,primary_key=True)
    source_id=Column(Integer,ForeignKey(CONFIG['source_table']+'.id'),nullable=False)
    name=Column(String(160),nullable=False)
    target_chapter=Column(String(500),nullable=False)
    state=Column(String(20),default='queued')   # queued/running/completed/failed
    parameters=Column(JSON,nullable=False)      # 冻结求解参数（容差、分批、上限）
    snapshot=Column(JSON,nullable=False)
    result=Column(JSON,nullable=True)
    error=Column(Text,default='')
    iterations=Column(Integer,default=0)        # 已完成的完整迭代轮数（半轮不计数）
    error_bound=Column(Text,default='')         # 最近一次完整迭代的可核验误差上界
    created_at=Column(String(40),nullable=False)
