from sqlalchemy import Column, Integer, String, Text
from app.database import Base
import json

class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    tags = Column(Text, default="[]")

    @property
    def tags_list(self):
        return json.loads(self.tags) if self.tags else []