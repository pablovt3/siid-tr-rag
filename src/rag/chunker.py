"""
Chunker semantico y jerarquico para normativa
Parsea el Markdown estructurado, descarta cabeceras repetitivas de pagina,
preserva tablas intactas y divide por titulos, secciones y numerales
"""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from src.rag.models import NormaChunk, TipoFragmento


class NormaHierarchicalChunker:
    """
    Divide documentos normativos en fragmentos semanticos
    manteniendo el contexto de titulos y secciones superiores
    """

    def __init__(self, max_tokens_por_chunk: int = 800) -> None:
        self.max_tokens_por_chunk = max_tokens_por_chunk

    def _extract_frontmatter(self, text: str) -> tuple[Dict[str, Any], str]:
        """separa el bloque frontmatter del cuerpo del markdown"""
        if text.startswith("---"):
            partes = text.split("---", 2)
            if len(partes) >= 3:
                meta = {}
                for linea in partes[1].split("\n"):
                    if ":" in linea:
                        k, v = linea.split(":", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k:
                            meta[k] = v
                return meta, partes[2].strip()
        return {}, text.strip()

    def _clean_running_headers(self, text: str) -> str:
        """elimina folios de pagina repetitivos y saltos de pagina del pdf"""
        lineas = text.split("\n")
        lineas_limpias = []
        for l in lineas:
            linea_strip = l.strip()
            # descarta saltos de pagina de pymupdf
            if linea_strip == "-----":
                continue
            # descarta folios tipo 'Normas Financieras' o 'Capitulo... Hoja X'
            if linea_strip == "Normas Financieras":
                continue
            if re.search(r"Hoja\s+\d+", linea_strip, re.IGNORECASE):
                continue
            # descarta pie de firma repetitivo de circulares
            if re.search(r"Circular\s+N°\s+\d+.*Acuerdo", linea_strip, re.IGNORECASE):
                continue
            lineas_limpias.append(l)

        return "\n".join(lineas_limpias)

    def chunk_document(self, markdown_path: Path) -> List[NormaChunk]:
        """lee el archivo markdown y produce la lista de chunks validados"""
        if not markdown_path.exists():
            raise FileNotFoundError(f"no existe el archivo: {markdown_path}")

        raw_text = markdown_path.read_text(encoding="utf-8")
        metadata, body = self._extract_frontmatter(raw_text)
        clean_body = self._clean_running_headers(body)

        sigla = metadata.get("sigla", "NORMA").upper()
        capitulo = metadata.get("capitulo", "Capitulo_General")
        institucion = metadata.get("institucion", "Institución No Especificada")
        titulo_norma = metadata.get("titulo", "Normativa")
        sha256 = metadata.get("sha256")
        url_origen = metadata.get("url_origen")

        # variables de estado para rastrear jerarquia
        titulo_actual = "INTRODUCCIÓN"
        seccion_actual = "General"
        chunks: List[NormaChunk] = []

        # divide por bloques de parrafos y tablas
        bloques = re.split(r"\n\s*\n", clean_body)
        buffer_texto: List[str] = []
        buffer_numeral = "General"
        chunk_idx = 1

        def flush_buffer():
            nonlocal buffer_texto, chunk_idx
            if not buffer_texto:
                return
            texto_unido = "\n\n".join(buffer_texto).strip()
            if not texto_unido:
                return

            jerarquia_str = f"{titulo_actual} > {seccion_actual}"
            cid = f"{sigla}_{re.sub(r'[^A-Za-z0-9]', '', capitulo)}_{chunk_idx:03d}"

            # identifica si es tabla o numeral
            tipo = TipoFragmento.NUMERAL
            if "|" in texto_unido and "---" in texto_unido:
                tipo = TipoFragmento.TABLA
            elif texto_unido.startswith("Artículo") or "Artículo" in buffer_numeral:
                tipo = TipoFragmento.ARTICULO

            chunk = NormaChunk(
                chunk_id=cid,
                institucion=institucion,
                sigla_institucion=sigla,
                capitulo=capitulo,
                titulo_norma=titulo_norma,
                jerarquia=jerarquia_str,
                tipo=tipo,
                contenido=texto_unido,
                tokens_estimados=NormaChunk.estimar_tokens(texto_unido),
                sha256_origen=sha256,
                url_origen=url_origen,
                metadatos_adicionales={"numeral_detectado": buffer_numeral}
            )
            chunks.append(chunk)
            chunk_idx += 1
            buffer_texto = []

        for b in bloques:
            b_strip = b.strip()
            if not b_strip:
                continue

            # detecta cambios de titulo principal (ej: TÍTULO I)
            match_tit = re.match(r"^\*?\*?(TÍTULO\s+[IVXLCDM0-9]+)\*?\*?", b_strip, re.IGNORECASE)
            if match_tit:
                flush_buffer()
                titulo_actual = match_tit.group(1).upper()
                buffer_numeral = "Inicio Título"
                buffer_texto.append(b_strip)
                flush_buffer()
                continue

            # detecta secciones tematicas (ej: A. Antecedentes Generales, B. Definiciones)
            match_sec = re.match(r"^\*?\*?([A-Z]\.\s+[^.\n]+)\*?\*?", b_strip)
            if match_sec and len(b_strip.split("\n")[0]) < 80:
                flush_buffer()
                seccion_actual = match_sec.group(1).strip("* ")
                buffer_numeral = "Encabezado Sección"
                buffer_texto.append(b_strip)
                flush_buffer()
                continue

            # detecta tablas completas (preserva la tabla entera en un chunk unico)
            if "|" in b_strip and "---" in b_strip:
                flush_buffer()
                buffer_texto.append(b_strip)
                buffer_numeral = "Tabla"
                flush_buffer()
                continue

            # detecta inicio de un nuevo numeral o articulo (ej: 1. ..., 2. ..., i. ..., Artículo 1°...)
            match_num = re.match(r"^(\d+\.|\b[ivxlcdm]+\.|\bArtículo\s+\d+[°º]?)\s+", b_strip)
            if match_num:
                flush_buffer()
                buffer_numeral = match_num.group(1)
                buffer_texto.append(b_strip)
            else:
                # acumula parrafos relacionados
                buffer_texto.append(b_strip)

                # controla tamano maximo del chunk
                texto_acumulado = " ".join(buffer_texto)
                if NormaChunk.estimar_tokens(texto_acumulado) >= self.max_tokens_por_chunk:
                    flush_buffer()

        flush_buffer()
        return chunks
