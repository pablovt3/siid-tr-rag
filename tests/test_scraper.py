"""
Prueba del scraper multinivel para normativa y metodologias del SIID
"""

from src.connectors.scraper import SIIDScraper


def main():
    print("=" * 70)
    print("🕷️  INICIANDO RASTREO MULTINIVEL EN SIID.CL")
    print("   1. Normativa Oficial: https://www.siid.cl/normativa-n")
    print("   2. Metodologías y Estudios: https://www.siid.cl/estadisticas/metodologias-y-estudios")
    print("=" * 70)

    scraper = SIIDScraper()

    print("\n🔍 1. Rastreando Normativa...")
    normativas = scraper.discover_normativa()
    print(f"   ✓ Encontrados: {len(normativas)} documentos normativos.")

    print("\n🔍 2. Rastreando Metodologías y Estudios (deep crawl)...")
    estudios = scraper.discover_estudios()
    print(f"   ✓ Encontrados: {len(estudios)} estudios/metodologías.")

    todos = normativas + estudios
    print(f"\n🎯 Total consolidado para ingesta: {len(todos)} documentos.")

    print("\nDetalle de documentos descubiertos:")
    for i, doc in enumerate(todos, 1):
        cat = doc.get('categoria', 'norma').upper()
        print(f"[{i:02d}] [{cat}] 📄 {doc['titulo']}")
        print(f"     🔗 {doc['url']}")
        print()

    print("=" * 70)


if __name__ == "__main__":
    main()
