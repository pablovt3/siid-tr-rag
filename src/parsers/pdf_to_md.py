"""
Parser para convertir normativas PDF a Markdown estructurado
Preserva tablas y jerarquia de encabezados con pymupdf4llm,
agrega frontmatter YAML y genera wikilinks para Obsidian
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, Optional
import unicodedata

import pymupdf4llm


class NormaPDFParser:
    """
    Convierte normativa en PDF a Markdown limpio con metadatos y enlaces
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
        """Carga manifest.json si existe en la carpeta del PDF"""
        manifest_path = pdf_path.parent / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

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
            f"compendio: \"{metadata.get('compendio', 'No especificado')}\"",
            f"capitulo: \"{metadata.get('capitulo', 'No especificado')}\"",
            f"titulo: \"{metadata.get('titulo', 'No especificado')}\"",
            f"mercado: \"{metadata.get('mercado', 'No especificado')}\"",
        ]

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
        """Genera nombre de archivo estandar sin tildes ni caracteres raros"""
        sigla = metadata.get("sigla_institucion", "NORMA").upper()
        capitulo = metadata.get("capitulo", "")

        if capitulo and capitulo != "No especificado":
            # quita tildes para evitar problemas en sistemas de archivos
            cap_sin_tildes = "".join(
                c for c in unicodedata.normalize("NFKD", capitulo)
                if not unicodedata.combining(c)
            )
            cap_limpio = re.sub(r"[^A-Za-z0-9]", "_", cap_sin_tildes).strip("_")
            return f"{sigla}_{cap_limpio}.md"

        return f"{sigla}_{Path(fallback).stem}.md"

    def parse(self, pdf_path: Path) -> Path:
        """Procesa el PDF y genera el archivo Markdown final"""
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

        # agrega metadatos y enlaces
        frontmatter = self._build_frontmatter(
            metadata=meta_norma,
            sha256=sha256,
            tamano_bytes=tamano,
            fecha_ingesta=fecha,
        )
        markdown_enriquecido = self._enrich_wikilinks(markdown_crudo)
        contenido_final = f"{frontmatter}\n{markdown_enriquecido}"

        # guarda archivo procesado
        filename_md = self._generate_canonical_name(meta_norma, pdf_path.name)
        target_path = self.output_dir / filename_md

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(contenido_final)

        # copia en el vault de obsidian si esta activo
        if self.vault_dir:
            vault_target = self.vault_dir / filename_md
            with open(vault_target, "w", encoding="utf-8") as f:
                f.write(contenido_final)

        return target_path
