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
    md_path = Path("data/processed/BCCH_Capitulo_III_D_3.md")
    if not md_path.exists():
        print(f"❌ Error: No existe {md_path}. Ejecuta primero el parser.")
        return

    print("=" * 70)
    print("🚀 1. INICIANDO CHUNKING JERÁRQUICO NORMATIVO")
    print("=" * 70)

    chunker = NormaHierarchicalChunker(max_tokens_por_chunk=600)
    chunks = chunker.chunk_document(md_path)

    print(f"✅ Chunks totales generados: {len(chunks)}")
    tablas = [c for c in chunks if c.tipo.value == "tabla"]
    print(f"📊 Tablas regulatorias preservadas como chunks únicos: {len(tablas)}")
    total_tokens = sum(c.tokens_estimados for c in chunks)
    print(f"📝 Tokens totales estimados: {total_tokens:,}")

    print("\nEjemplo de los primeros 3 chunks generados:")
    for c in chunks[:3]:
        print(f"   [{c.chunk_id}] ({c.tipo.value.upper()}) {c.jerarquia} | Tokens: {c.tokens_estimados}")

    print("\n" + "=" * 70)
    print("🔍 2. INDEXANDO EN MOTOR HÍBRIDO (BM25 + COSENO + RRF)")
    print("=" * 70)

    retriever = HybridNormaRetriever(chunks)
    qa_engine = NormaQAEngine(retriever)
    print(f"✅ Índice construido para {retriever.corpus_size} documentos.")

    consultas_prueba = [
        "¿Qué es un Repositorio de Transacciones TR y qué objetivos persigue según el BCCh?",
        "¿Cuáles son las entidades obligadas y la matriz de contrapartes para derivados?",
        "¿Qué leyes rigen a las empresas bancarias y qué acceso tiene la CMF?"
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
