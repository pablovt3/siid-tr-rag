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
        """construye el prompt aumentado con instrucciones de no alucinacion y estricto espanol"""
        contexto_partes = []
        for i, chunk in enumerate(chunks, 1):
            contexto_partes.append(f"[FUENTE {i}]\n{chunk.to_context_string()}")

        contexto_completo = "\n".join(contexto_partes)

        prompt = f"""Eres un analista cuantitativo y regulatorio experto en la normativa del Banco Central de Chile y el mercado de derivados financieros (SIID).
Tu tarea es responder la consulta del usuario basándote ÚNICA Y EXCLUSIVAMENTE en los fragmentos oficiales proporcionados.

Reglas estrictas de respuesta:
1. IDIOMA OBLIGATORIO: Responde SIEMPRE en ESPAÑOL. No generes ningún texto, nota, lista de verificación ni razonamiento en inglés.
2. RIGOR Y CERO ALUCINACIÓN: No inventes información ni agregues supuestos fuera del texto oficial.
3. CITAS OBLIGATORIAS: Cita siempre el capítulo, anexo, título o sección correspondiente de cada fragmento utilizado.
4. AUSENCIA DE INFORMACIÓN: Si la respuesta a la pregunta no está explícitamente en los fragmentos provistos, responde textualmente: "La normativa provista no contiene información suficiente para responder esta consulta."

=== FRAGMENTOS NORMATIVOS OFICIALES ===
{contexto_completo}
======================================

CONSULTA DEL USUARIO:
{query}

RESPUESTA PROFESIONAL EN ESPAÑOL:"""
        return prompt

    def query(self, user_query: str, top_k: int = 3) -> Dict[str, Any]:
        """ejecuta la busqueda y prepara el paquete completo de respuesta y contexto"""
        resultados = self.retriever.search(user_query, top_k=top_k)

        chunks_recuperados = [chunk for chunk, score in resultados]
        scores = [score for chunk, score in resultados]

        prompt_generado = self.build_prompt(user_query, chunks_recuperados)

        # extrae citas normativas o tecnicas unicas
        citas = []
        for ch in chunks_recuperados:
            origen = ch.capitulo if ch.capitulo not in ("No especificado", "Capitulo_General", "") else ch.titulo_norma
            cita = f"{ch.sigla_institucion} | {origen} | {ch.jerarquia}"
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
