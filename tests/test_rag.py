"""
Script de prueba integral para el pipeline RAG
Verifica chunking jerarquico, indexacion hibrida (BM25 + Coseno + RRF)
y generacion de prompts fundamentados para el Capitulo III.D.3 del BCCh
"""

from pathlib import Path
from src.rag.chunker import NormaHierarchicalChunker
from src.rag.retriever import HybridNormaRetriever
from src.rag.qa import NormaQAEngine


def main():
    archivos_md = sorted(Path("data/processed").glob("*.md"))
    if not archivos_md:
        print(f"❌ Error: No se encontraron archivos en data/processed. Ejecuta primero el pipeline.")
        return

    print("=" * 70)
    print("🚀 1. INICIANDO CHUNKING JERÁRQUICO MULTI-DOCUMENTO")
    print("=" * 70)

    chunker = NormaHierarchicalChunker(max_tokens_por_chunk=600)
    chunks = chunker.chunk_directory(Path("data/processed"))

    print(f"✅ Documentos Markdown procesados: {len(archivos_md)}")
    print(f"✅ Chunks totales generados en el corpus: {len(chunks)}")
    tablas = [c for c in chunks if c.tipo.value == "tabla"]
    print(f"📊 Tablas y gráficos estructurados preservados: {len(tablas)}")
    total_tokens = sum(c.tokens_estimados for c in chunks)
    print(f"📝 Tokens totales estimados en el corpus: {total_tokens:,}")

    print("\nEjemplo de 3 chunks generados:")
    for c in chunks[:3]:
        print(f"   [{c.chunk_id}] ({c.tipo.value.upper()}) {c.jerarquia} | Tokens: {c.tokens_estimados}")

    print("\n" + "=" * 70)
    print("🔍 2. INDEXANDO EN MOTOR HÍBRIDO (BM25 + COSENO + RRF)")
    print("=" * 70)

    retriever = HybridNormaRetriever(chunks)
    qa_engine = NormaQAEngine(retriever)
    print(f"✅ Índice construido para {retriever.corpus_size} fragmentos.")

    consultas_prueba = [
        "¿Qué es un Repositorio de Transacciones TR y qué objetivos persigue según el BCCh?",
        "¿Cuáles son las tres estadísticas de derivados sobre tipos de cambio descritas en la nota técnica 7?",
        "¿Cuáles son las diferencias entre single-sided y double-sided reporting según Alexander Hynes?",
        "¿Cuáles son los campos requeridos en el Anexo 2.A para derivados sobre monedas?"
    ]

    for num, q in enumerate(consultas_prueba, 1):
        print("\n" + "-" * 70)
        print(f"🔎 CONSULTA {num}: {q}")
        print("-" * 70)

        resultado = qa_engine.query(q, top_k=2)

        print(f"🎯 Documentos recuperados: {resultado['total_recuperados']}")
        print(f"⚖️  Puntajes RRF: {resultado['scores_rrf']}")
        print("📜 Citas normativas identificadas:")
        for cita in resultado["citas_normativas"]:
            print(f"   -> {cita}")

        top_chunk = resultado["chunks"][0]
        print(f"\n📄 Top-1 Fragmento [{top_chunk.chunk_id}] (Tipo: {top_chunk.tipo.value}):")
        lineas_vista = top_chunk.contenido.strip().split("\n")[:5]
        for l in lineas_vista:
            print(f"   | {l}")
        if len(top_chunk.contenido.split("\n")) > 5:
            print("   | [...]")

    print("\n" + "=" * 70)
    print("✅ TEST COMPLETADO CON ÉXITO")
    print("=" * 70)


if __name__ == "__main__":
    main()
