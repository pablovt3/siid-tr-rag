"""
Conector institucional para la ingesta de normativa
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, Optional
from urllib.parse import unquote

import httpx
import pymupdf

from src.connectors.base import BaseConnector


class NormaConnector(BaseConnector):
    """
    Conector para la descarga, verificación e inspección
    de normativa
    """

    #registro de dominios institucionales chilenos tipos
    DOMINIOS_INSTITUCIONALES: Dict[str, tuple[str, str]] = {
        "bcentral.cl": ("Banco Central de Chile", "BCCh"),
        "siid.cl": ("Banco Central de Chile", "BCCh"),
        "spensiones.cl": ("Superintendencia de Pensiones", "SP"),
        "cmfchile.cl": ("Comisión para el Mercado Financiero", "CMF"),
    }

    def __init__(
        self,
        document_url: str,
        institucion: Optional[str] = None,
        sigla_institucion: Optional[str] = None,
        compendio: Optional[str] = None,
        capitulo: Optional[str] = None,
        titulo: Optional[str] = None,
        mercado: Optional[str] = None,
        categoria: str = "norma",
        base_url: Optional[str] = None,
    ) -> None:
        dominio_raiz = "/".join(document_url.split("/")[:3])

        #autoresolucion institucional basada en el dominio de la URL
        inst_auto, sigla_auto = None, None
        url_lower = document_url.lower()
        for dominio, (nombre_inst, sigla) in self.DOMINIOS_INSTITUCIONALES.items():
            if dominio in url_lower:
                inst_auto, sigla_auto = nombre_inst, sigla
                break

        self.document_url = document_url
        self.institucion = institucion or inst_auto or "Institución No Especificada"
        self.sigla_institucion = sigla_institucion or sigla_auto or "DESCONOCIDA"
        self.compendio = compendio
        self.capitulo = capitulo
        self.titulo = titulo
        self.mercado = mercado
        self.categoria = categoria

        super().__init__(
            name=self.sigla_institucion.lower(),
            base_url=base_url or dominio_raiz,
        )

    def download(self, output_dir: Path) -> Path:
        """
        Descarga el documento por streaming en bloques de 8 KB
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # limpia y decodifica el nombre del archivo terminado en .pdf
        url_limpia = self.document_url.split("?")[0]
        segmentos_pdf = [s for s in url_limpia.split("/") if s.lower().endswith(".pdf")]
        nombre_crudo = unquote(segmentos_pdf[0]) if segmentos_pdf else "norma.pdf"
        filename = re.sub(r'[\/\\:\*\?"<>\|]', '_', nombre_crudo)
        target_path = output_dir / filename

        # descarga por streaming HTTP (8 KB chunk)
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            with client.stream("GET", self.document_url) as response:
                response.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)

        # calculo hash
        file_hash = self.calculate_sha256(target_path)

        # inspeccion metadatos pdf
        self._auto_detect_metadata(target_path)

        # manifiesto individual y actualizacion del registro global
        manifest_data = {
            "institucion": self.institucion,
            "documento": filename,
            "url_origen": self.document_url,
            "descargado_en_utc": datetime.now(timezone.utc).isoformat(),
            "tamaño_bytes": target_path.stat().st_size,
            "sha256": file_hash,
            "metadatos": self.get_metadata(),
        }

        # guarda manifiesto especifico para este documento
        manifest_item_path = output_dir / f"{target_path.stem}.manifest.json"
        with open(manifest_item_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        # actualiza o crea el manifiesto consolidado
        manifest_path = output_dir / "manifest.json"
        registro_global = {}
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    registro_global = json.load(f)
            except Exception:
                pass
        registro_global[filename] = manifest_data
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(registro_global, f, indent=2, ensure_ascii=False)

        return target_path

    #autodeteccion de metadatos a partir del contenido del pdf
    def _auto_detect_metadata(self, pdf_path: Path) -> None:
        """
        Lee la primera página del PDF mediante PyMuPDF para extraer compendio,
        capítulo y título formalmente si no fueron provistos en la instanciación.
        """
        try:
            doc = pymupdf.open(pdf_path)
            texto_p1 = doc[0].get_text()

            #inferencia de encabezados
            if not self.compendio:
                if "normas financieras" in texto_p1.lower():
                    self.compendio = "Compendio de Normas Financieras (CNF)"
                elif "normas de pensiones" in texto_p1.lower():
                    self.compendio = "Compendio de Normas del Sistema de Pensiones (SP)"

            #busca capitulo
            match_cap = re.search(r"(CAPÍTULO\s+[A-Z0-9\.]+)", texto_p1, re.IGNORECASE)
            if match_cap and not self.capitulo:
                self.capitulo = match_cap.group(1).strip()

            lineas = [l.strip() for l in texto_p1.split("\n") if l.strip()]

            #busca titulo
            if not self.titulo:
                for idx, linea in enumerate(lineas):
                    if re.match(r"^CAP[ÍI]TULO\s+[A-Z0-9\.]+$", linea, re.IGNORECASE):
                        partes_titulo = []
                        for siguiente in lineas[idx + 1:]:
                            if siguiente.startswith("TÍTULO") or siguiente.startswith("Artículo"):
                                break
                            partes_titulo.append(siguiente)
                            if len(partes_titulo) >= 2:
                                break
                        if partes_titulo:
                            self.titulo = " ".join(partes_titulo)
                        break
        except Exception:
            pass  # En archivos rasterizados o escaneados preserva lo recibido

    def get_metadata(self) -> Dict[str, Any]:
        """
        Retorna la ficha técnica de la normativa, sin suposiciones fijas.
        """
        return {
            "institucion": self.institucion,
            "sigla_institucion": self.sigla_institucion,
            "compendio": self.compendio or "No especificado",
            "capitulo": self.capitulo or "No especificado",
            "titulo": self.titulo or "No especificado",
            "mercado": self.mercado or "No especificado",
            "categoria": self.categoria,
            "url_origen": self.document_url,
        }