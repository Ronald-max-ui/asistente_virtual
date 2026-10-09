"""Bounded API DTOs. Passwords remain SecretStr, never response models."""
import re,unicodedata
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,SecretStr,field_validator
Role = Literal['superadmin','administrador','admisiones','revisor_pagos','solo_lectura']
def normalize_username(value):
    value=unicodedata.normalize('NFKC',value).strip().casefold()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.@+\-]{2,119}',value): raise ValueError('Invalid username')
    return value
class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Login(Strict):
    username:str=Field(min_length=3,max_length=120)
    password:SecretStr=Field(min_length=1,max_length=256)
    _username=field_validator('username')(normalize_username)
class CreateUser(Login):
    display_name:str=Field(min_length=1,max_length=120)
    role:Role='solo_lectura'
    @field_validator('display_name')
    @classmethod
    def plain(cls,value):
        if '<' in value or '>' in value or any(ord(c)<32 for c in value): raise ValueError('Plain text required')
        return value.strip()
class UpdateUser(Strict):
    display_name:str=Field(min_length=1,max_length=120)
    role:Role
    enabled:bool
    _plain=field_validator('display_name')(CreateUser.plain.__func__)
class ChangePassword(Strict):
    password:SecretStr=Field(min_length=12,max_length=256)
class ReviewVoucher(Strict):
    status:Literal['approved','rejected']
    review_note:str=Field(default='',max_length=1000)
    @field_validator('review_note')
    @classmethod
    def plain(cls,value):
        if '<' in value or '>' in value or any(ord(c)<32 and c not in '\n\t' for c in value): raise ValueError('Plain text required')
        return value
