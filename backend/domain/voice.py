"""Public speech parameters, never provider credentials or free-form SSML."""
import re
from typing import Literal
from pydantic import Field,field_validator
from domain.admin import Strict
VOICES=[{'id':'es-PE-CamilaNeural','name':'Camila','language':'Español · Perú'}, {'id':'es-PE-AlexNeural','name':'Alex','language':'Español · Perú'}, {'id':'es-MX-DaliaNeural','name':'Dalia','language':'Español · México'}]
class VoiceConfig(Strict):
    provider:Literal['edge']='edge'
    voice_id:Literal['es-PE-CamilaNeural','es-PE-AlexNeural','es-MX-DaliaNeural']='es-PE-CamilaNeural'
    rate:str=Field(default='+10%',max_length=6)
    pitch:str=Field(default='+0Hz',max_length=7)
    volume:str=Field(default='+0%',max_length=6)
    enabled:bool=True
    @field_validator('rate','pitch','volume')
    @classmethod
    def bounded(cls,value,info):
        suffix='Hz' if info.field_name=='pitch' else '%'
        if not re.fullmatch(r'[+-]\d{1,3}'+suffix,value):raise ValueError('Invalid speech parameter')
        number=int(value[:-len(suffix)]);limit=100 if info.field_name=='pitch' else 50
        if abs(number)>limit:raise ValueError('Speech parameter outside bounds')
        return value
