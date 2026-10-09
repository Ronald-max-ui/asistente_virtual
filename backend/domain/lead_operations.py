"""Administrative state is independent from the conversational funnel."""
from typing import Literal
from datetime import datetime
from pydantic import Field,field_validator
from domain.admin import Strict
Status=Literal['new','contacted','interested','follow_up','enrollment_in_progress','converted','lost']
Reason=Literal['price','no_response','other_institution','schedule','modality','not_interested','other']
STATES=['new','contacted','interested','follow_up','enrollment_in_progress','converted','lost']
TRANSITIONS={s:set(STATES)-{s,'new'} for s in STATES};TRANSITIONS['converted']=set();TRANSITIONS['lost']={'contacted','interested','follow_up','enrollment_in_progress'}
class Plain(Strict):
    @field_validator('*',mode='after')
    @classmethod
    def plain(cls,value):
        if isinstance(value,str) and ('<' in value or '>' in value or any(ord(c)<32 and c not in '\n\t' for c in value)):raise ValueError('Plain text required')
        return value
class Search(Plain):
    limit:int=Field(21,ge=1,le=100)
    offset:int=Field(0,ge=0,le=10000)
    status:Status|None=None
    program:str|None=Field(None,max_length=64)
    modality:str|None=Field(None,max_length=64)
    assigned_to:str|None=Field(None,max_length=128)
    quick:Literal['all','new','mine','today','overdue','tomorrow','converted','lost']='all'
    since:datetime|None=None
    until:datetime|None=None
    search:str=Field('',max_length=120)
    @field_validator('since','until')
    @classmethod
    def aware(cls,v):
        if v and (v.tzinfo is None or v.utcoffset() is None):raise ValueError('Timezone required')
        return v
class UpdateTracking(Plain):
    status:Status
    assigned_to_user_id:str|None=Field(None,max_length=128)
    loss_reason:Reason|None=None
    loss_note:str=Field('',max_length=300)
class Activity(Plain):
    type:Literal['note','call','whatsapp_manual']='note'
    text:str=Field(min_length=1,max_length=1000)
class CreateTask(Plain):
    due_at:datetime
    assigned_to:str|None=Field(None,max_length=128)
    type:Literal['call','follow_up','whatsapp_manual']='follow_up'
    note:str=Field('',max_length=500)
    @field_validator('due_at')
    @classmethod
    def aware(cls,v):
        if v.tzinfo is None or v.utcoffset() is None:raise ValueError('Timezone required')
        return v
class CompleteTask(Strict):
    status:Literal['completed','cancelled']
