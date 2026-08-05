from sqlmodel import SQLModel

class GeoOption(SQLModel):
    gid: str
    name: str

class IucnOption(SQLModel):
    id: int
    name: str
