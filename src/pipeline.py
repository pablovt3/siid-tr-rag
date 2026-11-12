"""
Pipeline maestro de ingesta y parseo por lotes
Ejecuta el scraper multinivel sobre siid.cl (normativa + metodologias y estudios),
descarga todos los documentos oficiales y los transforma a Markdown con Frontmatter y enlaces
organizados en Obsidian por categorias
"""

from pathlib import Path
from rich.console import Console
from rich.table import Table

from src.connectors.scraper import SIIDScraper
from src.parsers.pdf_to_md import NormaPDFParser

console = Console()


def ejecutar_pipeline():
    console.print("\n[bold cyan]=== INICIANDO PIPELINE MAESTRO MULTI-CATEGORÍA SIID ===[/bold cyan]\n")

    raw_dir = Path("data/raw")
    processed_dir = Path("data/processed")
    vault_dir = Path("data/vault")

    # 1. rastreo multinivel y descarga masiva
    console.print("[yellow]1. Rastreando portal oficial (Normativa + Metodologías y Estudios)...[/yellow]")
    scraper = SIIDScraper()
    documentos_encontrados = scraper.discover_all()
    console.print(f"   [green]✓[/green] Se detectaron {len(documentos_encontrados)} documentos institucionales.")

    descargados = scraper.download_all(output_dir=raw_dir)
    console.print(f"   [green]✓[/green] Descarga completada: {len(descargados)} archivos PDF en {raw_dir}.\n")

    # 2. conversion masiva a markdown estructurado
    console.print("[yellow]2. Procesando PDFs a Markdown estructurado con PyMuPDF4LLM...[/yellow]")
    parser = NormaPDFParser(output_dir=processed_dir, vault_dir=vault_dir)

    procesados = []
    todos_los_pdfs = sorted(raw_dir.glob("*.pdf"))

    for pdf in todos_los_pdfs:
        try:
            md_path = parser.parse(pdf)
            procesados.append(md_path)
            console.print(f"   [green]✓[/green] Parseado: [cyan]{pdf.name}[/cyan] -> [bold white]{md_path.name}[/bold white]")
        except Exception as e:
            console.print(f"   [red]✗[/red] Error al parsear {pdf.name}: {e}")

    # 3. resumen consolidado
    console.print("\n[bold cyan]=== RESUMEN DE LA BÓVEDA DOCUMENTAL ===[/bold cyan]")
    tabla = Table(border_style="green")
    tabla.add_column("Archivo Markdown (Processed / Vault)", style="cyan")
    tabla.add_column("Categoría Vault", style="yellow")
    tabla.add_column("Tamaño", justify="right", style="magenta")

    for p in procesados:
        tam = f"{p.stat().st_size:,} bytes"
        es_estudio = (vault_dir / "metodologias_estudios" / p.name).exists()
        cat = "Estudios / Metodología" if es_estudio else "Normativa Oficial"
        tabla.add_row(p.name, cat, tam)

    console.print(tabla)
    console.print(f"\n[bold green]✓ Pipeline multi-categoría ejecutado exitosamente.[/bold green]")
    console.print(f"[dim]Revisa Obsidian ('open -a Obsidian data/vault') o ejecuta el CLI ('python src/cli.py').[/dim]\n")


if __name__ == "__main__":
    ejecutar_pipeline()
