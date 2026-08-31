from typing import Literal

from sqlmodel import SQLModel

class GeoOption(SQLModel):
    gid: str
    name: str

class IucnOption(SQLModel):
    id: int
    name: str


class CoordinateGeoOption(SQLModel):
    gid: str
    name: str


class CoordinateGadmMatch(SQLModel):
    status: Literal["matched", "unmatched", "ambiguous"]
    gadm0: CoordinateGeoOption | None = None
    gadm1: CoordinateGeoOption | None = None
    gadm2: CoordinateGeoOption | None = None


class CoordinateIhoMatch(SQLModel):
    status: Literal["matched", "unmatched", "ambiguous"]
    option: CoordinateGeoOption | None = None


class CoordinateMatchesResponse(SQLModel):
    gadm: CoordinateGadmMatch
    iho: CoordinateIhoMatch
