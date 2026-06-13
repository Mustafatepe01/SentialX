from pydantic import BaseModel
from typing import Optional, List


class RAGRequest(BaseModel):
    violation_type: str           # "ppe_ihlali", "yangin", "yasak_bolge", "ramak_kala"
    violation_subtype: Optional[str] = None  # "eldivensiz_calisma", "baretsiz" vb.
    process: Optional[str] = None  # "demir_bukme", "kaynak" vb.
    zone: Optional[str] = None    # "Hat-3 Bükme İstasyonu"
    description: Optional[str] = None  # VLM'den gelen açıklama


class Regulation(BaseModel):
    name: str
    url: Optional[str] = None


class Source(BaseModel):
    name: str
    url: Optional[str] = None
    node: Optional[str] = None


class SolutionCriteria(BaseModel):
    mandatory: List[str]
    recommended: List[str]


class RAGResponse(BaseModel):
    query: str
    technical_context: str
    similar_incidents: List[str]
    regulations: List[Regulation]
    solution_criteria: SolutionCriteria
    sources: List[Source]
    nodes_used: List[str]
    answer: str