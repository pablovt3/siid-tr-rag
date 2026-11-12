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

        # identificador base del archivo para evitar colisiones
        stem_limpio = re.sub(r"[^A-Za-z0-9]", "_", markdown_path.stem)
        stem_limpio = re.sub(r"_+", "_", stem_limpio).strip("_")

        def flush_buffer():
            nonlocal buffer_texto, chunk_idx
            if not buffer_texto:
                return
            texto_unido = "\n\n".join(buffer_texto).strip()
            if not texto_unido:
                return

            es_tabla = ("|" in texto_unido and "---" in texto_unido)
            es_grafico = ("Valores/Escala de gráfico" in texto_unido or "📊" in texto_unido)

            # descarta fragmentos que consisten unicamente en encabezados sin cuerpo sustantivo
            lineas_validas = [l.strip() for l in texto_unido.split("\n") if l.strip()]
            if all(l.startswith(("#", "TÍTULO")) for l in lineas_validas) and not es_tabla and not es_grafico:
                buffer_texto = []
                return

            palabras = texto_unido.split()
            primer_linea = lineas_validas[0] if lineas_validas else ""
            primeras_palabras = [w.lower().strip(",.:;-_") for w in palabras[:6]]

            # purga estricta de residuos de celdas rotas (lineas que arrancan con 'si', 'no', tipos de datos o minusculas)
            es_desborde_celda = (
                any(p in ("sí", "si", "no", "char", "varchar", "num", "date", "datetime") for p in primeras_palabras)
                or (primer_linea and primer_linea[0].islower() and not primer_linea.startswith(("-", "*", ">")))
            )
            if es_desborde_celda and not es_tabla and not es_grafico:
                buffer_texto = []
                return

            tiene_encabezado_formal = any(primer_linea.startswith(pfx) for pfx in ("#", "TÍTULO", "MAT.:", "Bancos N°", "Artículo", "Circular", "ANT.:", "Santiago,"))
            tiene_numeral_formal = bool(re.match(r"^(\d+\.|\b[ivxlcdm]+\.|\bArtículo\s+\d+[°º]?)\s+", primer_linea))

            if not es_tabla and not es_grafico:
                if len(palabras) < 35 and not tiene_encabezado_formal and not tiene_numeral_formal:
                    buffer_texto = []
                    return

            jerarquia_str = f"{titulo_actual} > {seccion_actual}"
            cid = f"{stem_limpio[:28]}_{chunk_idx:03d}"

            # identifica si es tabla, grafico o numeral
            tipo = TipoFragmento.NUMERAL
            if ("|" in texto_unido and "---" in texto_unido) or "Valores/Escala de gráfico" in texto_unido:
                tipo = TipoFragmento.TABLA
            elif texto_unido.startswith("Artículo") or "Artículo" in buffer_numeral:
                tipo = TipoFragmento.ARTICULO

            # detecta si el bloque es un indice navegacional con numeros de pagina (... 12)
            es_indice_nav = len(re.findall(r"\.{4,}\s*\d+", texto_unido)) >= 3 or "......." in texto_unido

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
                metadatos_adicionales={
                    "numeral_detectado": buffer_numeral,
                    "es_indice_navegacional": es_indice_nav
                }
            )
            chunks.append(chunk)
            chunk_idx += 1
            buffer_texto = []

        for b in bloques:
            b_strip = b.strip()
            if not b_strip:
                continue

            # separador de laminas de diapositivas
            if b_strip == "---":
                flush_buffer()
                continue

            # encabezados markdown principales (# Titulo)
            if b_strip.startswith("# ") and len(b_strip) < 120:
                flush_buffer()
                titulo_actual = b_strip.lstrip("# ").strip()
                seccion_actual = "General"
                buffer_numeral = "Título Markdown"
                buffer_texto.append(b_strip)
                continue

            # subencabezados markdown (## Seccion o ### Subseccion)
            if (b_strip.startswith("## ") or b_strip.startswith("### ")) and len(b_strip) < 120:
                if buffer_texto and all(l.strip().startswith(("#", "TÍTULO")) for l in buffer_texto):
                    seccion_actual = b_strip.lstrip("# ").strip()
                    buffer_texto.append(b_strip)
                else:
                    flush_buffer()
                    seccion_actual = b_strip.lstrip("# ").strip()
                    buffer_numeral = "Sección Markdown"
                    buffer_texto.append(b_strip)
                continue

            # detecta cambios de titulo legal (ej: TÍTULO I)
            match_tit = re.match(r"^\*?\*?(TÍTULO\s+[IVXLCDM0-9]+)\*?\*?", b_strip, re.IGNORECASE)
            if match_tit:
                flush_buffer()
                titulo_actual = match_tit.group(1).upper()
                seccion_actual = "General"
                buffer_numeral = "Inicio Título"
                buffer_texto.append(b_strip)
                continue

            # detecta secciones tematicas (ej: A. Antecedentes Generales, B. Definiciones)
            match_sec = re.match(r"^\*?\*?([A-Z]\.\s+[^.\n]+)\*?\*?", b_strip)
            if match_sec and len(b_strip.split("\n")[0]) < 80:
                if buffer_texto and all(l.strip().startswith(("#", "TÍTULO")) for l in buffer_texto):
                    seccion_actual = match_sec.group(1).strip("* ")
                    buffer_texto.append(b_strip)
                else:
                    flush_buffer()
                    seccion_actual = match_sec.group(1).strip("* ")
                    buffer_numeral = "Encabezado Sección"
                    buffer_texto.append(b_strip)
                continue

            # detecta tablas completas (preserva la tabla unida a su encabezado si lo habia)
            if "|" in b_strip and "---" in b_strip:
                if buffer_texto and not all(l.strip().startswith(("#", "TÍTULO")) for l in buffer_texto):
                    texto_previo = [l for l in buffer_texto if not l.strip().startswith(("#", "TÍTULO"))]
                    encabezados = [l for l in buffer_texto if l.strip().startswith(("#", "TÍTULO"))]
                    buffer_texto = texto_previo
                    flush_buffer()
                    buffer_texto = encabezados

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

    def chunk_directory(self, processed_dir: Path = Path("data/processed")) -> List[NormaChunk]:
        """procesa todos los archivos markdown de una carpeta y une los chunks"""
        todos_los_chunks: List[NormaChunk] = []
        archivos_md = sorted(processed_dir.glob("*.md"))
        for f in archivos_md:
            try:
                chunks_doc = self.chunk_document(f)
                todos_los_chunks.extend(chunks_doc)
            except Exception as e:
                print(f"Error procesando {f.name}: {e}")
        return todos_los_chunks
