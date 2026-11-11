"""
Conector generalizado e institucional para la ingesta de normativa financiera chilena.
Diseñado para operar de forma agnóstica con múltiples entidades reguladoras
(Banco Central de Chile, Superintendencia de Pensiones, Comisión para el Mercado Financiero, etc.),
asegurando streaming en bloques de memoria, integridad SHA-256 y resolución dinámica sin sesgos.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, Optional

import httpx
import pymupdf

from src.connectors.base import BaseConnector


class NormaConnector(BaseConnector):
    """
    Conector genérico para la descarga, verificación e inspección
    de normativa institucional y financiera.
    """

    # Registro de dominios institucionales chilenos para resolución automática
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
        base_url: Optional[str] = None,
    ) -> None:
        dominio_raiz = "/".join(document_url.split("/")[:3])

        # Auto-resolución institucional basada en el dominio de la URL si no se especificó
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

        super().__init__(
            name=self.sigla_institucion.lower(),
            base_url=base_url or dominio_raiz,
        )

    def download(self, output_dir: Path) -> Path:
        """
        Descarga el documento por streaming en bloques de 8 KB, calcula su hash SHA-256,
        auto-detecta metadatos del PDF si no fueron dados y genera el manifest.json.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Sanitización de la URL: aísla el nombre terminado en .pdf ignorando query params (?version=...)
        url_limpia = self.document_url.split("?")[0]
        segmentos_pdf = [s for s in url_limpia.split("/") if s.lower().endswith(".pdf")]
        filename = segmentos_pdf[0] if segmentos_pdf else "norma.pdf"
        target_path = output_dir / filename

        # 1. Descarga por streaming HTTP (8 KB por bloque)
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            with client.stream("GET", self.document_url) as response:
                response.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)

        # 2. Cálculo criptográfico SHA-256
        file_hash = self.calculate_sha256(target_path)

        # 3. Auto-inspección de metadatos desde el PDF para campos no especificados
        self._auto_detect_metadata(target_path)

        # 4. Generación del Manifiesto de Trazabilidad
        manifest_data = {
            "institucion": self.institucion,
            "documento": filename,
            "url_origen": self.document_url,
            "descargado_en_utc": datetime.now(timezone.utc).isoformat(),
            "tamaño_bytes": target_path.stat().st_size,
            "sha256": file_hash,
            "metadatos": self.get_metadata(),
        }

        manifest_path = output_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        return target_path

    def _auto_detect_metadata(self, pdf_path: Path) -> None:
        """
        Lee la primera página del PDF mediante PyMuPDF para extraer compendio,
        capítulo y título formalmente si no fueron provistos en la instanciación.
        """
        try:
            doc = pymupdf.open(pdf_path)
            texto_p1 = doc[0].get_text()

            # 1. Inferencia del Compendio a partir de encabezados oficiales
            if not self.compendio:
                if "normas financieras" in texto_p1.lower():
                    self.compendio = "Compendio de Normas Financieras (CNF)"
                elif "normas de pensiones" in texto_p1.lower():
                    self.compendio = "Compendio de Normas del Sistema de Pensiones (SP)"

            # 2. Búsqueda del Capítulo (ej: CAPÍTULO III.D.3)
            match_cap = re.search(r"(CAPÍTULO\s+[A-Z0-9\.]+)", texto_p1, re.IGNORECASE)
            if match_cap and not self.capitulo:
                self.capitulo = match_cap.group(1).strip()

            lineas = [l.strip() for l in texto_p1.split("\n") if l.strip()]

            # 3. Búsqueda del Título formal descartando folios repetitivos de página
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
            "url_origen": self.document_url,
        }