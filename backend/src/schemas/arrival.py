from pydantic import BaseModel,Field
class ArrivalRunInput(BaseModel):
    source_id:int
    name:str=Field(min_length=2,max_length=160)
    target_chapter:str=Field(min_length=1,max_length=500)
class ArrivalNoteInput(BaseModel):
    arrival_run_id:int
    title:str=Field(min_length=2,max_length=160)
    body:str=Field(min_length=5,max_length=4000)
