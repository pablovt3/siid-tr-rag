"""
Parser para convertir normativas y estudios financieros en PDF a Markdown estructurado
Preserva tablas y jerarquia de encabezados con pymupdf4llm,
agrega frontmatter YAML con autores y titulos reales, compacta graficos y genera wikilinks para Obsidian
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, Optional
import unicodedata
from urllib.parse import unquote

import pymupdf4llm


class NormaPDFParser:
    """
    Convierte normativa y estudios PDF a Markdown limpio con metadatos enriquecidos y enlaces
    """

    def __init__(
        self,
        output_dir: Path = Path("data/processed"),
        vault_dir: Optional[Path] = Path("data/vault"),
    ) -> None:
        self.output_dir = output_dir
        self.vault_dir = vault_dir

        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.vault_dir:
            self.vault_dir.mkdir(parents=True, exist_ok=True)

    def _load_manifest(self, pdf_path: Path) -> Dict[str, Any]:
        """Carga el manifiesto especifico o el consolidado de la carpeta"""
        item_manifest = pdf_path.parent / f"{pdf_path.stem}.manifest.json"
        if item_manifest.exists():
            try:
                with open(item_manifest, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        manifest_path = pdf_path.parent / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if pdf_path.name in data:
                        return data[pdf_path.name]
                    return data
            except Exception:
                pass
        return {}

    def _extract_methodology_metadata(self, markdown_text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """extrae titulo real, autores, tipo de documento y fecha para estudios y notas tecnicas"""
        meta_copia = dict(meta)
        lineas = [l.strip() for l in markdown_text.split("\n") if l.strip()][:50]

        titulo_detectado = None
        subtitulo_detectado = None
        autores_detectados = None
        tipo_pub = "Estudio / Nota Técnica"
        fecha_detectada = None

        for idx, l in enumerate(lineas):
            l_lower = l.lower()

            # clasifica tipo de publicacion con su numero si existe
            if "documento de trabajo" in l_lower or "working paper" in l_lower:
                num_match = re.search(r"N[°º]?\s*(\d+)", markdown_text[:2000], re.IGNORECASE)
                tipo_pub = f"Documento de Trabajo N° {num_match.group(1)}" if num_match else "Documento de Trabajo"
            elif "nota técnica" in l_lower or "nota tecnica" in l_lower:
                num_match = re.search(r"N[°º]?\s*(\d+)", l, re.IGNORECASE) or re.search(r"N[°º]?\s*(\d+)", markdown_text[:1500], re.IGNORECASE)
                tipo_pub = f"Nota Técnica N° {num_match.group(1)}" if num_match else "Nota Técnica"
            elif any(w in l_lower for w in ("presentation", "presentación", "regulators’ forum", "pwc")):
                tipo_pub = "Presentación Técnica"

            # busca autores por etiqueta explicita o patrones conocidos
            match_aut = re.search(r"(?:Autores?|Autoras?):\s*(.+)", l, re.IGNORECASE)
            if match_aut and not autores_detectados:
                autores_detectados = match_aut.group(1).strip("*_ ")
            elif not autores_detectados:
                if "Alexander Hynes" in l:
                    autores_detectados = "Alexander Hynes"
                elif "José Miguel Villena" in l:
                    autores_detectados = "José Miguel Villena Martínez"
                elif "Felipe Bustamante" in l and "José Miguel Villena" in l:
                    autores_detectados = "Felipe Bustamante y José Miguel Villena"
                elif "Vanessa Ramírez" in l:
                    autores_detectados = "Vanessa Ramírez y Felipe Bustamante"
                elif "Nicole Delpiano" in l:
                    autores_detectados = "Nicole Delpiano y Felipe Bustamante"
                elif "|" in l and any(k in l_lower for k in ("economist", "economista", "gerente", "división")):
                    nombre_part = l.split("|")[0].strip("*_# ")
                    if len(nombre_part.split()) >= 2:
                        autores_detectados = nombre_part

            # busca fecha de publicacion (mes + anho o anho)
            match_f = re.search(r"\b(Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre)\s+(20\d\d)\b", l, re.IGNORECASE)
            if match_f and not fecha_detectada:
                fecha_detectada = f"{match_f.group(1).capitalize()} {match_f.group(2)}"

            # busca titulo principal descartando cabeceras genericas de portada
            if (l.startswith("# ") or l.startswith("## ") or l.startswith("### ")) and not titulo_detectado:
                candidato = re.sub(r"^#+\s*", "", l).strip("*_ ")
                if candidato.lower() not in (
                    "documentos de trabajo",
                    "working papers",
                    "banco central de chile",
                    "contenidos",
                    "agenda",
                    "resumen",
                ):
                    titulo_detectado = candidato
            elif titulo_detectado and not subtitulo_detectado and (l.startswith("## ") or l.startswith("### ")):
                cand_sub = re.sub(r"^#+\s*", "", l).strip("*_ ")
                if cand_sub.lower() not in ("contenidos", "agenda") and not match_aut:
                    if "chile" in cand_sub.lower() or "experi" in cand_sub.lower():
                        subtitulo_detectado = cand_sub

        # compone titulo final si habia subtitulo relevante
        if titulo_detectado and subtitulo_detectado:
            titulo_detectado = f"{titulo_detectado}: {subtitulo_detectado}"

        # actualiza metadata
        if titulo_detectado and meta_copia.get("titulo") in (None, "No especificado", ""):
            meta_copia["titulo"] = titulo_detectado

        if autores_detectados:
            meta_copia["autores"] = autores_detectados

        meta_copia["tipo_publicacion"] = tipo_pub
        if fecha_detectada:
            meta_copia["fecha_publicacion"] = fecha_detectada

        return meta_copia

    def _extract_norma_metadata(self, markdown_text: str, meta: Dict[str, Any], fallback_name: str) -> Dict[str, Any]:
        """extrae asunto MAT y titulo descriptivo para documentos de normativa oficial"""
        meta_copia = dict(meta)

        match_mat = re.search(r"MAT\.?:\s*([^\n\r]+)", markdown_text[:2500], re.IGNORECASE)
        if match_mat:
            asunto = match_mat.group(1).strip()
            if "758" in fallback_name:
                meta_copia["titulo"] = f"Carta Circular N° 758: {asunto}"
            else:
                meta_copia["titulo"] = asunto
        elif "651" in fallback_name or "CC_651" in fallback_name:
            meta_copia["titulo"] = "Carta Circular N° 651: Informa calendario de puesta en marcha del SIID-TR"
        elif "3013" in fallback_name or "RO-SIID" in fallback_name:
            meta_copia["titulo"] = "Circular N° 3013-940: Modifica Reglamento Operativo del SIID-TR (RO-SIID)"
        elif "CNF" in fallback_name:
            meta_copia["titulo"] = "Compendio de Normas Financieras - Capítulo III.D.3 Normativa SIID-TR"

        return meta_copia

    def _clean_slides_and_charts(self, text: str) -> str:
        """
        Limpia ruido de diapositivas y presentaciones:
        - consolida secuencias de escalas de graficos y ejes numericos en bloques legibles
        - repara encabezados largos de diapositivas convirtiendolos en parrafos de conclusion
        - unifica divisores de laminas y elimina saltos redundantes
        """
        # normaliza separadores de laminas
        text = re.sub(r"\n+-----\n+", "\n\n---\n\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        lineas = text.split("\n")
        nuevas_lineas = []
        buffer_numeros = []

        def flush_numeros():
            nonlocal buffer_numeros, nuevas_lineas
            if not buffer_numeros:
                return
            if len(buffer_numeros) >= 2:
                valores_str = ", ".join(buffer_numeros)
                nuevas_lineas.append(f"> 📊 *Valores/Escala de gráfico detectados:* [{valores_str}]")
            else:
                nuevas_lineas.extend(buffer_numeros)
            buffer_numeros = []

        for l in lineas:
            strip_l = l.strip()

            # ignora lineas vacias dentro de una secuencia numerica para no cortar la acumulacion
            if not strip_l:
                if buffer_numeros:
                    continue
                nuevas_lineas.append(l)
                continue

            # detecta si la linea es solo un numero, porcentaje, rango o lista corta de numeros
            es_numero_puro = bool(re.match(r"^[-+]?[\d\.,\s%$/€]+$", strip_l) and re.search(r"\d", strip_l))
            if es_numero_puro:
                # separa numeros individuales si vienen separados por espacios
                tokens_num = [tok for tok in strip_l.split() if re.search(r"\d", tok)]
                buffer_numeros.extend(tokens_num if tokens_num else [strip_l])
                continue

            # si veniamos acumulando numeros y encontramos texto regular, vaciamos el buffer
            flush_numeros()

            # detecta si un encabezado de pymupdf (##### ...) es en realidad una conclusion larga de diapositiva
            match_header_largo = re.match(r"^(#{3,6})\s+(.+)$", strip_l)
            if match_header_largo:
                contenido_header = match_header_largo.group(2).strip()
                palabras = contenido_header.split()
                # si tiene mas de 12 palabras o termina con punto, es un parrafo/conclusion, no un titulo
                if len(palabras) > 12 or contenido_header.endswith("."):
                    nuevas_lineas.append(f"> 💡 **Conclusión:** {contenido_header}")
                    continue

            # detecta pie de graficos o fuentes tipicas
            if re.match(r"^Fuente:\s*(.+)", strip_l, re.IGNORECASE):
                nuevas_lineas.append(f"> *{strip_l}*")
                continue

            nuevas_lineas.append(l)

        flush_numeros()

        resultado = "\n".join(nuevas_lineas)
        # compacta multiples divisores consecutivos
        resultado = re.sub(r"(\n*---\n*){2,}", "\n\n---\n\n", resultado)

        # limpia desbordes de celdas partidas por saltos de pagina que anteceden a tablas markdown
        resultado = re.sub(
            r"(\n---\n+)(?:[ \t]*(?:Sí|Si|No|Char|Varchar|Num|Date)[^\n]*\n+)+(?=\|[^\n]+\|\n\|[-:| ]+\|\n)",
            r"\1",
            resultado,
            flags=re.IGNORECASE,
        )
        return resultado

    def _build_frontmatter(
        self,
        metadata: Dict[str, Any],
        sha256: Optional[str] = None,
        tamano_bytes: Optional[int] = None,
        fecha_ingesta: Optional[str] = None,
    ) -> str:
        """Arma bloque YAML de propiedades para Obsidian y RAG"""
        frontmatter_lines = [
            "---",
            f"institucion: \"{metadata.get('institucion', 'No especificado')}\"",
            f"sigla: \"{metadata.get('sigla_institucion', 'DESCONOCIDA')}\"",
            f"categoria: \"{metadata.get('categoria', 'norma')}\"",
            f"titulo: \"{metadata.get('titulo', 'No especificado')}\"",
        ]

        if metadata.get("autores"):
            frontmatter_lines.append(f"autores: \"{metadata.get('autores')}\"")
        if metadata.get("tipo_publicacion"):
            frontmatter_lines.append(f"tipo_publicacion: \"{metadata.get('tipo_publicacion')}\"")
        if metadata.get("fecha_publicacion"):
            frontmatter_lines.append(f"fecha_publicacion: \"{metadata.get('fecha_publicacion')}\"")

        if metadata.get("compendio") and metadata.get("compendio") != "No especificado":
            frontmatter_lines.append(f"compendio: \"{metadata.get('compendio')}\"")
        if metadata.get("capitulo") and metadata.get("capitulo") != "No especificado":
            frontmatter_lines.append(f"capitulo: \"{metadata.get('capitulo')}\"")
        if metadata.get("mercado") and metadata.get("mercado") != "No especificado":
            frontmatter_lines.append(f"mercado: \"{metadata.get('mercado')}\"")

        if sha256:
            frontmatter_lines.append(f"sha256: \"{sha256}\"")
        if tamano_bytes:
            frontmatter_lines.append(f"tamano_bytes: {tamano_bytes}")
        if fecha_ingesta:
            frontmatter_lines.append(f"fecha_ingesta: \"{fecha_ingesta}\"")

        url_origen = metadata.get("url_origen")
        if url_origen:
            frontmatter_lines.append(f"url_origen: \"{url_origen}\"")

        frontmatter_lines.extend(["---", ""])
        return "\n".join(frontmatter_lines)

    def _enrich_wikilinks(self, markdown_text: str) -> str:
        """Convierte citas legales a formato wikilink [[...]]"""
        # enlaza capitulos oficiales con numeracion romana o decimal
        texto = re.sub(
            r"\b(Cap[íi]tulo\s+([IVXLCDM0-9]+(?:\.[A-Za-z0-9]+)*))\b",
            r"[[\2|\1]]",
            markdown_text,
        )

        # enlaza menciones a leyes chilenas
        texto = re.sub(
            r"\b(Ley\s+N[°º]?\s*([0-9\.]+))\b",
            r"[[Ley_\2|\1]]",
            texto,
            flags=re.IGNORECASE,
        )

        return texto

    def _generate_canonical_name(self, metadata: Dict[str, Any], fallback: str) -> str:
        """Genera nombre de archivo unico sin tildes rotas"""
        sigla = metadata.get("sigla_institucion", "NORMA").upper()
        capitulo = metadata.get("capitulo", "")

        # normaliza tildes del nombre de origen antes de limpiar caracteres (ej: Estadísticas -> Estadisticas)
        stem_unquoted = unquote(Path(fallback).stem)
        stem_sin_tildes = "".join(
            c for c in unicodedata.normalize("NFKD", stem_unquoted)
            if not unicodedata.combining(c)
        )
        stem_limpio = re.sub(r"[^A-Za-z0-9]", "_", stem_sin_tildes)
        stem_limpio = re.sub(r"_+", "_", stem_limpio).strip("_")

        if capitulo and capitulo != "No especificado":
            cap_sin_tildes = "".join(
                c for c in unicodedata.normalize("NFKD", capitulo)
                if not unicodedata.combining(c)
            )
            cap_limpio = re.sub(r"[^A-Za-z0-9]", "_", cap_sin_tildes).strip("_")
            if stem_limpio.upper() not in (cap_limpio.upper(), "NORMA"):
                return f"{sigla}_{cap_limpio}_{stem_limpio[:35]}.md"
            return f"{sigla}_{cap_limpio}.md"

        return f"{sigla}_{stem_limpio[:45]}.md"

    def parse(self, pdf_path: Path) -> Path:
        """Procesa el PDF y genera el archivo Markdown final con metadatos y grafos"""
        if not pdf_path.exists():
            raise FileNotFoundError(f"No se encontro el archivo PDF en: {pdf_path}")

        # recupera metadatos del manifiesto
        manifest = self._load_manifest(pdf_path)
        meta_norma = manifest.get("metadatos", {})
        sha256 = manifest.get("sha256")
        tamano = manifest.get("tamaño_bytes")
        fecha = manifest.get("descargado_en_utc")

        # extraccion a markdown respetando tablas y negritas
        markdown_crudo = pymupdf4llm.to_markdown(str(pdf_path))

        # extrae titulo y autores si es documento de estudio o nota tecnica
        if meta_norma.get("categoria") in ("metodologia", "estudio") or not meta_norma.get("titulo") or meta_norma.get("titulo") == "No especificado":
            if meta_norma.get("categoria") in ("metodologia", "estudio"):
                meta_norma = self._extract_methodology_metadata(markdown_crudo, meta_norma)
            else:
                meta_norma = self._extract_norma_metadata(markdown_crudo, meta_norma, pdf_path.name)

        # limpia ruido de diapositivas y graficos
        markdown_limpio = self._clean_slides_and_charts(markdown_crudo)

        # agrega metadatos y enlaces
        frontmatter = self._build_frontmatter(
            metadata=meta_norma,
            sha256=sha256,
            tamano_bytes=tamano,
            fecha_ingesta=fecha,
        )
        markdown_enriquecido = self._enrich_wikilinks(markdown_limpio)
        contenido_final = f"{frontmatter}\n{markdown_enriquecido}"

        # guarda archivo procesado
        filename_md = self._generate_canonical_name(meta_norma, pdf_path.name)
        target_path = self.output_dir / filename_md

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(contenido_final)

        # copia en el vault de obsidian organizado por categoria
        if self.vault_dir:
            subcarpeta = "metodologias_estudios" if meta_norma.get("categoria") in ("metodologia", "estudio") else "normativa"
            carpeta_destino = self.vault_dir / subcarpeta
            carpeta_destino.mkdir(parents=True, exist_ok=True)
            vault_target = carpeta_destino / filename_md
            with open(vault_target, "w", encoding="utf-8") as f:
                f.write(contenido_final)

        return target_path
