"""
Motor de consulta y generacion aumentada (RAG)
Recupera fragmentos relevantes, construye el prompt aumentado con citas obligatorias
y genera la respuesta fundamentada
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.rag.models import NormaChunk
from src.rag.retriever import HybridNormaRetriever


class NormaQAEngine:
    """
    Orquesta la recuperacion y generacion de respuestas con citacion estricta
    """

    def __init__(self, retriever: HybridNormaRetriever) -> None:
        self.retriever = retriever

    def build_prompt(self, query: str, chunks: List[NormaChunk]) -> str:
        """construye el prompt aumentado con instrucciones de no alucinacion"""
        contexto_partes = []
        for i, chunk in enumerate(chunks, 1):
            contexto_partes.append(f"[FUENTE {i}]\n{chunk.to_context_string()}")

        contexto_completo = "\n".join(contexto_partes)

        prompt = f"""Eres un analista experto en regulacion financiera y normativa del Banco Central de Chile.
Tu tarea es responder la consulta del usuario basandote UNICA Y EXCLUSIVAMENTE en los fragmentos normativos proporcionados a continuacion.

Reglas estrictas:
- No inventes informacion ni agregues suposiciones que no esten en el texto.
- Cita siempre el capitulo, titulo y seccion de donde extrajiste cada afirmacion.
- Si la respuesta no se encuentra en las fuentes, responde: "La normativa provista no contiene informacion suficiente para responder esta consulta."

=== FRAGMENTOS OFICIALES DISPONIBLES ===
{contexto_completo}
=======================================

CONSULTA DEL USUARIO:
{query}

RESPUESTA FUNDAMENTADA (incluye citas normativas):"""
        return prompt

    def query(self, user_query: str, top_k: int = 3) -> Dict[str, Any]:
        """ejecuta la busqueda y prepara el paquete completo de respuesta y contexto"""
        resultados = self.retriever.search(user_query, top_k=top_k)

        chunks_recuperados = [chunk for chunk, score in resultados]
        scores = [score for chunk, score in resultados]

        prompt_generado = self.build_prompt(user_query, chunks_recuperados)

        # extrae citas normativas unicas
        citas = []
        for ch in chunks_recuperados:
            cita = f"{ch.sigla_institucion} | {ch.capitulo} | {ch.jerarquia}"
            if cita not in citas:
                citas.append(cita)

        return {
            "query": user_query,
            "total_recuperados": len(chunks_recuperados),
            "citas_normativas": citas,
            "scores_rrf": scores,
            "chunks": chunks_recuperados,
            "prompt_aumentado": prompt_generado,
        }
