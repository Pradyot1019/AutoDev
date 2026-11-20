from pydantic import BaseModel, HttpUrl, validator
from typing import List, Optional
import json

class BookmarkBase(BaseModel):
    url: HttpUrl
    title: str
    tags: Optional[List[str]] = []

    @validator('url')
    def validate_scheme(cls, v):
        if v.scheme not in ('http', 'https'):
            raise ValueError('URL must start with http or https')
        return v

class BookmarkCreate(BookmarkBase):
    pass

class BookmarkResponse(BaseModel):
    id: int
    url: str
    title: str
    tags: List[str]

    class Config:
        from_attributes = True

    @validator('tags', pre=True)
    def parse_tags(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v