"""
Modelos de datos para el pipeline RAG
Define la estructura tipada de cada fragmento normativo (chunk) con Pydantic
"""

from enum import Enum
import math
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class TipoFragmento(str, Enum):
    """Clasificacion de la estructura legal del fragmento"""
    NUMERAL = "numeral"
    ARTICULO = "articulo"
    TABLA = "tabla"
    TITULO_SECCION = "titulo_seccion"
    PROSA_GENERAL = "prosa_general"


class NormaChunk(BaseModel):
    """
    Unidad semantica de una norma con linaje jerarquico para busqueda y RAG
    """
    chunk_id: str = Field(..., description="identificador unico determinista")
    institucion: str = Field(..., description="nombre de la institucion emisora")
    sigla_institucion: str = Field(..., description="sigla formal de la institucion")
    capitulo: str = Field(..., description="capitulo de la norma")
    titulo_norma: str = Field(..., description="titulo principal de la norma")
    jerarquia: str = Field(..., description="ruta de titulos y secciones ancestros")
    tipo: TipoFragmento = Field(default=TipoFragmento.NUMERAL, description="tipo de contenido")
    contenido: str = Field(..., description="texto o tabla markdown del fragmento")
    tokens_estimados: int = Field(default=0, description="tokens estimados del texto")
    sha256_origen: Optional[str] = Field(default=None, description="hash sha256 del pdf origen")
    url_origen: Optional[str] = Field(default=None, description="url de descarga original")
    metadatos_adicionales: Dict[str, Any] = Field(default_factory=dict, description="metadatos extra")

    @classmethod
    def estimar_tokens(cls, texto: str) -> int:
        """calcula aproximacion de tokens (~4 caracteres por token)"""
        if not texto:
            return 0
        return math.ceil(len(texto) / 4)

    def to_context_string(self) -> str:
        """formatea el fragmento para inyectar en el prompt del LLM con cita exacta"""
        encabezado = (
            f"=== [FUENTE: {self.institucion} ({self.sigla_institucion})] ===\n"
            f"Norma: {self.capitulo} - {self.titulo_norma}\n"
            f"Jerarquía: {self.jerarquia}\n"
            f"Tipo: {self.tipo.value.upper()}\n"
        )
        return f"{encabezado}\n{self.contenido.strip()}\n"
