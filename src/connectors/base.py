from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict
import hashlib

class BaseConnector(ABC):
    """
    Clase base abstracta para la descarga y trazabilidad de normativa.
    Todas las instituciones heredan de esta clase e implementan sus metodos.
    """
    def __init__(self, name: str, base_url: str) -> None:
        self.name = name
        self.base_url = base_url

    @abstractmethod
    def download(self, output_dir: Path) -> Path:
        """
        Descarga el documento y lo guarda en output_dir
        Debe retornar Path al archivo descargado en disco
        """
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """
        Retorna un dic con la metadata del documento descargado
        """
        pass

    def calculate_sha256(self, file_path: Path) -> str:
        """
        calcula hash criptografico de un archivo en disco
        lee en bloque de 8 kb con el fin de optimizar RAM
        """
        if not file_path.exists():
            raise FileNotFoundError(f'Archivo no encontrado: {file_path}')
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)  #lee en bloques de 8 KB
                if not chunk:
                    break
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
