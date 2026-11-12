"""
Motor de recuperacion hibrida para normativa
Combina busqueda lexica BM25 para terminos exactos (codigos, leyes, siglas)
con similitud vectorial para comprension conceptual, fusionados con RRF
"""

from collections import Counter
import math
from pathlib import Path
import re
from typing import List, Set, Tuple
import unicodedata

from src.rag.models import NormaChunk


class HybridNormaRetriever:
    """
    Indice y buscador hibrido (BM25 + similitud vectorial de cosenos con fusion RRF)
    """

    STOPWORDS: Set[str] = {
        "de", "la", "el", "en", "y", "a", "los", "las", "del", "por", "un", "una",
        "unos", "unas", "que", "qué", "sobre", "con", "su", "sus", "para", "se",
        "al", "lo", "como", "es", "son", "o", "u", "e", "este", "esta", "estos",
        "estas", "segun", "cual", "cuales"
    }

    def __init__(self, chunks: List[NormaChunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.corpus_size = len(chunks)

        # estructuras para indice BM25
        self.doc_lengths: List[int] = []
        self.avg_doc_len: float = 0.0
        self.doc_freqs: Counter = Counter()
        self.term_freqs: List[Counter] = []
        self.idf: dict[str, float] = {}

        self._build_index()

    def _tokenize(self, text: str) -> List[str]:
        """
        tokeniza, normaliza diacriticos (tildes) para busqueda tolerante
        y descarta stopwords comunes en espanol
        """
        # remueve diacriticos para unificar terminos (ej: tecnicos == técnicos, modificacion == modificación)
        text_norm = "".join(
            c for c in unicodedata.normalize("NFKD", text.lower())
            if not unicodedata.combining(c)
        )
        palabras = re.findall(r"\b[a-z0-9_\.\-]+\b", text_norm)
        return [
            p for p in palabras
            if (len(p) > 1 or p.isdigit()) and p not in self.STOPWORDS
        ]

    def _build_index(self) -> None:
        """construye las tablas de frecuencias e idf para BM25 indexando metadatos y contenido"""
        if not self.chunks:
            return

        total_len = 0
        for chunk in self.chunks:
            # indexa institucion, capitulo, titulo descriptivo, jerarquia y contenido sustantivo
            meta_header = f"{chunk.sigla_institucion} {chunk.capitulo} {chunk.titulo_norma} {chunk.jerarquia}"
            texto_completo = f"{meta_header} {chunk.contenido}"
            tokens = self._tokenize(texto_completo)
            longitud = len(tokens)
            self.doc_lengths.append(longitud)
            total_len += longitud

            tf = Counter(tokens)
            self.term_freqs.append(tf)

            for term in tf.keys():
                self.doc_freqs[term] += 1

        self.avg_doc_len = total_len / self.corpus_size if self.corpus_size > 0 else 1.0

        # calcula IDF con suavizado estandar
        for term, freq in self.doc_freqs.items():
            self.idf[term] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def _score_bm25(self, query_tokens: List[str], doc_idx: int) -> float:
        """calcula puntaje BM25 de un documento para una consulta"""
        score = 0.0
        doc_len = self.doc_lengths[doc_idx]
        tf = self.term_freqs[doc_idx]
        chunk = self.chunks[doc_idx]

        for token in query_tokens:
            if token not in tf:
                continue
            f = tf[token]
            idf = self.idf.get(token, 0.0)
            numerador = f * (self.k1 + 1.0)
            denominador = f + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
            score += idf * (numerador / denominador)

        # atenuacion para indices de contenido y paginacion cuando la consulta busca sustancia tecnica
        if chunk.metadatos_adicionales and chunk.metadatos_adicionales.get("es_indice_navegacional"):
            if not any(w in query_tokens for w in ("indice", "contenido", "agenda", "estructura")):
                score *= 0.35

        return score

    def _score_cosine(self, query_tokens: List[str], doc_idx: int) -> float:
        """calcula similitud de cosenos sobre frecuencias ponderadas"""
        q_counter = Counter(query_tokens)
        d_counter = self.term_freqs[doc_idx]
        chunk = self.chunks[doc_idx]

        dot_product = sum(q_counter[t] * d_counter.get(t, 0) * self.idf.get(t, 1.0) for t in q_counter)
        norm_q = math.sqrt(sum((count * self.idf.get(t, 1.0)) ** 2 for t, count in q_counter.items()))
        norm_d = math.sqrt(sum((count * self.idf.get(t, 1.0)) ** 2 for t, count in d_counter.items()))

        if norm_q == 0.0 or norm_d == 0.0:
            return 0.0

        sim = dot_product / (norm_q * norm_d)
        if chunk.metadatos_adicionales and chunk.metadatos_adicionales.get("es_indice_navegacional"):
            if not any(w in query_tokens for w in ("indice", "contenido", "agenda", "estructura")):
                sim *= 0.35

        return sim

    def search(self, query: str, top_k: int = 3) -> List[Tuple[NormaChunk, float]]:
        """
        Busca usando fusion de rangos reciprocos (RRF) combinando BM25 y coseno
        """
        if not self.chunks:
            return []

        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []

        # calcula puntajes de ambos metodos
        bm25_scores = [(idx, self._score_bm25(q_tokens, idx)) for idx in range(self.corpus_size)]
        cosine_scores = [(idx, self._score_cosine(q_tokens, idx)) for idx in range(self.corpus_size)]

        # ordena por ranking
        bm25_ranked = sorted(bm25_scores, key=lambda x: x[1], reverse=True)
        cosine_ranked = sorted(cosine_scores, key=lambda x: x[1], reverse=True)

        # aplica Reciprocal Rank Fusion (RRF, k=60)
        k_rrf = 60
        rrf_scores: dict[int, float] = {}

        for rank, (doc_idx, score) in enumerate(bm25_ranked):
            if score > 0:
                rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + (1.0 / (k_rrf + rank + 1))

        for rank, (doc_idx, score) in enumerate(cosine_ranked):
            if score > 0:
                rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + (1.0 / (k_rrf + rank + 1))

        # selecciona los mejores top_k
        mejores = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [(self.chunks[doc_idx], round(score, 4)) for doc_idx, score in mejores]
