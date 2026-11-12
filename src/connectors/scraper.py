"""
Scraper multinivel para el portal SIID
Descubre y descarga tanto normativa regulatoria como notas tecnicas,
metodologias y estudios estadisticos del mercado de derivados
"""

from pathlib import Path
import re
from typing import Any, Dict, List
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup
import httpx

from src.connectors.norma import NormaConnector


class SIIDScraper:
    """
    Rastreador web categorizado para el ecosistema documental del SIID
    """

    URL_NORMATIVA = "https://www.siid.cl/normativa-n"
    URL_ESTUDIOS = "https://www.siid.cl/estadisticas/metodologias-y-estudios"

    def __init__(self) -> None:
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

    def discover_normativa(self) -> List[Dict[str, str]]:
        """extrae los enlaces de la seccion oficial de normativa"""
        return self._extract_direct_pdfs(self.URL_NORMATIVA, categoria="norma")

    def discover_estudios(self) -> List[Dict[str, str]]:
        """
        rastreo multinivel:
        1. lee indice https://www.siid.cl/estadisticas/metodologias-y-estudios
        2. extrae enlaces a articulos de detalle (/contenido/-/detalle/...)
        3. entra a cada articulo y extrae el enlace directo al pdf (/documents/...)
        """
        documentos: List[Dict[str, str]] = []
        urls_vistas = set()

        try:
            with httpx.Client(follow_redirects=True, timeout=30.0, headers=self.headers) as client:
                resp = client.get(self.URL_ESTUDIOS)
                if resp.status_code != 200:
                    return []
                soup = BeautifulSoup(resp.text, "lxml")

                # busca enlaces a paginas de detalle de estudios en liferay
                subenlaces = set()
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"].strip()
                    # patron oficial de detalle en liferay siid: /contenido/-/detalle/...
                    if "/contenido/-/detalle/" in href or "/detalle/" in href:
                        full_sub = urljoin("https://www.siid.cl", href)
                        subenlaces.add(full_sub)

                # visita cada pagina de detalle para extraer el pdf
                for sub_url in sorted(subenlaces):
                    try:
                        sub_resp = client.get(sub_url, timeout=25.0)
                        if sub_resp.status_code != 200:
                            continue
                        sub_soup = BeautifulSoup(sub_resp.text, "lxml")

                        # extrae titulo del estudio del encabezado h1/h2 o del titulo de pagina
                        titulo_estudio = "Estudio Metodológico SIID"
                        h_tag = sub_soup.find(["h1", "h2"])
                        if h_tag and h_tag.get_text(strip=True):
                            titulo_estudio = h_tag.get_text(strip=True)

                        # busca el enlace de descarga del pdf en la subpagina
                        sub_docs = self._extract_from_soup(sub_soup, sub_url, categoria="metodologia")
                        for d in sub_docs:
                            if d["url"] not in urls_vistas:
                                # si el titulo capturado es generico o un selector web, deduce del nombre del pdf
                                if "selector" in d["titulo"].lower() or len(d["titulo"]) < 5:
                                    segmentos = [s for s in unquote(d["url"].split("?")[0]).split("/") if s.lower().endswith(".pdf")]
                                    if segmentos:
                                        d["titulo"] = segmentos[0].replace(".pdf", "").replace("+", " ").strip()
                                elif len(titulo_estudio) > len(d["titulo"]) and "selector" not in titulo_estudio.lower():
                                    d["titulo"] = titulo_estudio[:120]
                                documentos.append(d)
                                urls_vistas.add(d["url"])
                    except Exception as e:
                        print(f"Error visitando subpagina {sub_url}: {e}")
        except Exception as e:
            print(f"Error rastreando metodologias y estudios: {e}")

        return documentos

    def _extract_from_soup(self, soup: BeautifulSoup, base_url: str, categoria: str) -> List[Dict[str, str]]:
        """extrae enlaces a pdfs de un arbol bs4"""
        encontrados = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            href_lower = href.lower()

            if ".pdf" in href_lower or "/documents/" in href_lower:
                full_url = urljoin(base_url, href)
                texto = a_tag.get_text(strip=True)
                if not texto or len(texto) < 3:
                    parent = a_tag.parent
                    texto = parent.get_text(strip=True) if parent else "Documento SIID"
                texto_limpio = re.sub(r"\s+", " ", texto).strip()

                encontrados.append({
                    "titulo": texto_limpio[:120],
                    "url": full_url,
                    "categoria": categoria
                })
        return encontrados

    def _extract_direct_pdfs(self, url: str, categoria: str) -> List[Dict[str, str]]:
        """descarga el html de una url y extrae enlaces a pdf"""
        try:
            with httpx.Client(follow_redirects=True, timeout=30.0, headers=self.headers) as client:
                resp = client.get(url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                return self._extract_from_soup(soup, url, categoria=categoria)
        except Exception as e:
            print(f"Error extrayendo pdfs de {url}: {e}")
            return []

    def discover_all(self) -> List[Dict[str, str]]:
        """descubre tanto la normativa como las metodologias y estudios"""
        normativas = self.discover_normativa()
        estudios = self.discover_estudios()

        # deduplica por url
        vistas = set()
        todos = []
        for doc in normativas + estudios:
            if doc["url"] not in vistas:
                vistas.add(doc["url"])
                todos.append(doc)
        return todos

    def download_all(self, output_dir: Path = Path("data/raw")) -> List[tuple[Path, str]]:
        """
        descarga todos los documentos catalogados y retorna tuplas (path, categoria)
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        docs = self.discover_all()
        descargados: List[tuple[Path, str]] = []

        for doc in docs:
            try:
                conector = NormaConnector(document_url=doc["url"], categoria=doc.get("categoria", "norma"))
                pdf_path = conector.download(output_dir)
                descargados.append((pdf_path, doc.get("categoria", "norma")))
            except Exception as e:
                print(f"Error descargando {doc['url']}: {e}")

        return descargados
