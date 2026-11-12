"""
Interfaz de linea de comandos interactiva con rich
Permite realizar consultas en lenguaje natural sobre las normativas financieras,
mostrando citas oficiales, fragmentos relevantes y respuesta generada
"""

import os
from pathlib import Path
import re
import sys

from dotenv import load_dotenv
import httpx
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src.rag.chunker import NormaHierarchicalChunker
from src.rag.models import NormaChunk
from src.rag.qa import NormaQAEngine
from src.rag.retriever import HybridNormaRetriever

# carga variables de entorno desde .env si existe
load_dotenv()

console = Console()


def llamar_gemini(prompt: str, api_key: str) -> tuple[str, dict]:
    """
    envia el prompt a la api de gemini usando httpx con autodeteccion de modelos disponibles.
    desactiva thinking tokens para ahorrar consumo y retorna (texto_respuesta, usage_metadata)
    """
    api_key_clean = api_key.strip()
    headers = {
        "x-goog-api-key": api_key_clean,
        "Content-Type": "application/json"
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1200,
            # desactiva razonamiento oculto para ahorrar tokens y acelerar respuesta
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }

    # 1. autodescubrimiento dinamico via ListModels de Google
    modelos_a_probar = []
    try:
        url_list = "https://generativelanguage.googleapis.com/v1beta/models"
        resp_list = httpx.get(url_list, headers=headers, timeout=10.0)
        if resp_list.status_code == 200:
            lista_raw = resp_list.json().get("models", [])
            for m in lista_raw:
                metodos = m.get("supportedGenerationMethods", [])
                if "generateContent" in metodos:
                    nombre_modelo = m["name"].replace("models/", "")
                    modelos_a_probar.append(nombre_modelo)
        elif resp_list.status_code != 200:
            resp_list_q = httpx.get(url_list, params={"key": api_key_clean}, timeout=10.0)
            if resp_list_q.status_code == 200:
                lista_raw = resp_list_q.json().get("models", [])
                for m in lista_raw:
                    metodos = m.get("supportedGenerationMethods", [])
                    if "generateContent" in metodos:
                        modelos_a_probar.append(m["name"].replace("models/", ""))
    except Exception:
        pass

    # orden de preferencia optimizado: gemini-3.8-flash (recomendado por Google), luego 2.5-pro
    modelos_priorizados = ["gemini-3.8-flash"]
    for m in modelos_a_probar:
        if "tts" in m.lower() or "gemini-2.5-flash" == m:
            continue
        if m not in modelos_priorizados:
            modelos_priorizados.append(m)

    errores = []
    # 2. invocar generateContent con los modelos en orden de prioridad
    for modelo in modelos_priorizados:
        for version in ("v1beta", "v1"):
            url = f"https://generativelanguage.googleapis.com/{version}/models/{modelo}:generateContent"
            try:
                resp = httpx.post(url, headers=headers, json=payload, timeout=35.0)
                if resp.status_code == 200:
                    data = resp.json()
                    parts = data["candidates"][0]["content"].get("parts", [])
                    # filtrar partes de razonamiento interno
                    partes_texto = [p.get("text", "") for p in parts if not p.get("thought", False)]
                    texto_final = "\n".join(partes_texto).strip()
                    if not texto_final:
                        texto_final = "\n".join([p.get("text", "") for p in parts]).strip()
                    usage = data.get("usageMetadata", {})
                    return texto_final, usage

                resp_q = httpx.post(url, params={"key": api_key_clean}, json=payload, timeout=35.0)
                if resp_q.status_code == 200:
                    data = resp_q.json()
                    parts = data["candidates"][0]["content"].get("parts", [])
                    partes_texto = [p.get("text", "") for p in parts if not p.get("thought", False)]
                    texto_final = "\n".join(partes_texto).strip()
                    if not texto_final:
                        texto_final = "\n".join([p.get("text", "") for p in parts]).strip()
                    usage = data.get("usageMetadata", {})
                    return texto_final, usage

                err_msg = resp.json().get("error", {}).get("message", resp.text)
                errores.append(f"{modelo} ({version}): {err_msg}")
            except Exception as e:
                errores.append(f"{modelo}: {str(e)}")
                continue

    diagnostico = "\n".join(errores[:2]) if errores else "No se encontraron modelos compatibles con esta clave."
    return f"Google API rechazó los modelos:\n{diagnostico}", {}


def mostrar_contador_tokens(usage: dict, acumulado: dict):
    """despliega contador visual de tokens consumidos en la consulta y acumulados en la sesion"""
    prompt_tok = usage.get("promptTokenCount", 0)
    output_tok = usage.get("candidatesTokenCount", 0)
    total_tok = usage.get("totalTokenCount", 0)

    acumulado["total"] += total_tok
    acumulado["prompt"] += prompt_tok
    acumulado["output"] += output_tok
    acumulado["consultas"] += 1

    costo_usd = (acumulado["prompt"] * 0.000000075) + (acumulado["output"] * 0.00000030)

    texto = (
        f"[bold white]Esta consulta:[/bold white] [bold yellow]{total_tok:,}[/bold yellow] tokens "
        f"[dim](Entrada: {prompt_tok:,} | Respuesta: {output_tok:,})[/dim]\n"
        f"[bold white]Total acumulado sesión ({acumulado['consultas']} consulta{'s' if acumulado['consultas'] > 1 else ''} con IA):[/bold white] "
        f"[bold cyan]{acumulado['total']:,}[/bold cyan] tokens "
        f"[dim](Costo est.: ${costo_usd:.5f} USD | $0.00 en Free Tier)[/dim]"
    )
    console.print(Panel(texto, title="[bold blue]📊 Contador de Consumo de Tokens[/bold blue]", border_style="blue"))


def mostrar_banner():
    """muestra cabecera estilizada de la aplicacion"""
    console.print()
    banner_text = (
        "[bold cyan]SIID-TR RAG[/bold cyan] - [bold white]Motor de Consulta sobre la Normativa del SIID[/bold white]\n"
        "[dim]Banco Central de Chile & Regulación de Derivados OTC[/dim]\n"
        "[dim]Motor Híbrido: BM25 + Coseno + Reciprocal Rank Fusion (RRF)[/dim]"
    )
    console.print(Panel(banner_text, border_style="cyan", expand=False))
    console.print()


def inicializar_sistema() -> tuple[NormaQAEngine, int]:
    """carga todos los markdowns procesados, divide en chunks e indexa en memoria"""
    processed_dir = Path("data/processed")
    archivos_md = list(processed_dir.glob("*.md"))
    if not archivos_md:
        console.print(f"[bold red]Error:[/bold red] No hay archivos Markdown en {processed_dir}. Ejecuta el parser primero.")
        sys.exit(1)

    with console.status(f"[bold green]Indexando {len(archivos_md)} documentos normativos en memoria...[/bold green]"):
        chunker = NormaHierarchicalChunker(max_tokens_por_chunk=600)
        chunks = chunker.chunk_directory(processed_dir)
        retriever = HybridNormaRetriever(chunks)
        engine = NormaQAEngine(retriever)

    return engine, len(chunks)


def mostrar_tabla_fuentes(resultado: dict):
    """despliega tabla de fragmentos recuperados con puntajes y jerarquia"""
    tabla = Table(title="Fuentes Normativas Recuperadas (RRF Consensus)", border_style="blue")
    tabla.add_column("Rank", justify="center", style="bold yellow", width=6)
    tabla.add_column("Chunk ID", style="cyan", width=22)
    tabla.add_column("Tipo", style="magenta", width=10)
    tabla.add_column("Jerarquía Normativa Oficial", style="white")
    tabla.add_column("Score", justify="right", style="green", width=8)

    for i, (chunk, score) in enumerate(zip(resultado["chunks"], resultado["scores_rrf"]), 1):
        ref_padre = chunk.capitulo if chunk.capitulo not in ("No especificado", "Capitulo_General", "") else chunk.titulo_norma[:30]
        tabla.add_row(
            f"#{i}",
            chunk.chunk_id,
            chunk.tipo.value.upper(),
            f"{ref_padre} > {chunk.jerarquia}",
            f"{score:.4f}"
        )

    console.print(tabla)


def extraer_tabla_rich(contenido: str):
    """
    detecta si el contenido contiene una tabla markdown y la convierte en una rich.table.Table nativa
    retorna (texto_previo, objeto_tabla, texto_posterior) o None
    """
    lineas = contenido.split("\n")
    idx_inicio = -1
    idx_fin = -1

    for i, l in enumerate(lineas):
        strip_l = l.strip()
        if strip_l.startswith("|") and strip_l.endswith("|"):
            if idx_inicio == -1:
                idx_inicio = i
            idx_fin = i + 1
        elif idx_inicio != -1 and not strip_l:
            continue
        elif idx_inicio != -1 and not (strip_l.startswith("|") and strip_l.endswith("|")):
            break

    if idx_inicio == -1:
        return None

    lineas_tabla = [l.strip() for l in lineas[idx_inicio:idx_fin] if l.strip().startswith("|")]
    if len(lineas_tabla) < 2:
        return None

    cabecera_raw = [c.strip().replace("<br>", "\n").replace("**", "") for c in lineas_tabla[0].split("|")[1:-1]]
    if not cabecera_raw or all(not c for c in cabecera_raw):
        return None

    tabla_rich = Table(border_style="cyan", show_lines=True, expand=True)
    for col_nombre in cabecera_raw:
        tabla_rich.add_column(col_nombre or "-", style="white", header_style="bold yellow")

    for row_line in lineas_tabla[1:]:
        if re.match(r"^\|[\s\-:|]+\|$", row_line):
            continue
        celdas = [c.strip().replace("<br>", "\n").replace("**", "").replace("~~", "") for c in row_line.split("|")[1:-1]]
        if len(celdas) < len(cabecera_raw):
            celdas.extend([""] * (len(cabecera_raw) - len(celdas)))
        elif len(celdas) > len(cabecera_raw):
            celdas = celdas[:len(cabecera_raw)]
        tabla_rich.add_row(*celdas)

    texto_previo = "\n".join(lineas[:idx_inicio]).strip()
    texto_posterior = "\n".join(lineas[idx_fin:]).strip()
    return texto_previo, tabla_rich, texto_posterior


def mostrar_fragmento_oficial(idx: int, chunk: NormaChunk, score_val: float):
    """despliega el fragmento oficial renderizando tablas visuales de Rich si corresponde"""
    origen_cita = chunk.capitulo if chunk.capitulo not in ("No especificado", "Capitulo_General", "") else chunk.titulo_norma
    tipo_str = chunk.tipo.value.upper()

    datos_tabla = extraer_tabla_rich(chunk.contenido)
    if datos_tabla:
        texto_previo, tabla_rich, texto_post = datos_tabla
        cabecera = (
            f"[bold cyan]Cita:[/bold cyan] {origen_cita} | {chunk.jerarquia}\n"
            f"[dim]Tipo: {tipo_str} (TABLA ESTRUCTURADA) | ID: {chunk.chunk_id}[/dim]"
        )
        if texto_previo:
            cabecera += f"\n\n[bold white]{texto_previo}[/bold white]"

        console.print(Panel(cabecera, title=f"[bold green]Fragmento Oficial #{idx} (RRF Score: {score_val:.4f})[/bold green]", border_style="green"))
        console.print(tabla_rich)
        if texto_post:
            console.print(f"[dim]{texto_post}[/dim]")
        console.print()
    else:
        extracto = (
            f"[bold cyan]Cita:[/bold cyan] {origen_cita} | {chunk.jerarquia}\n"
            f"[dim]Tipo: {tipo_str} | ID: {chunk.chunk_id}[/dim]\n\n"
            f"{chunk.contenido.strip()}"
        )
        console.print(Panel(extracto, title=f"[bold green]Fragmento Oficial #{idx} (RRF Score: {score_val:.4f})[/bold green]", border_style="green"))


def main():
    mostrar_banner()
    engine, total_chunks = inicializar_sistema()
    console.print(f"[green]✓[/green] Sistema listo con [bold]{total_chunks}[/bold] fragmentos normativos indexados.\n")

    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        console.print("[dim green]● Conexión a Gemini API detectada (Modo Generativo Disponible).[/dim green]\n")
    else:
        console.print("[dim yellow]○ Sin GEMINI_API_KEY en .env: Operando en modo extractor legal certificado.[/dim yellow]\n")

    top_k_default = 3
    console.print("[dim]Tip: Puedes cambiar la cantidad de resultados escribiendo '/k 5' o añadiendo '--k 5' a tu consulta.[/dim]\n")

    # acumulador de consumo de tokens durante la sesion
    tokens_acumulados = {"total": 0, "prompt": 0, "output": 0, "consultas": 0}

    while True:
        try:
            consulta = Prompt.ask("[bold yellow]Ingresa tu consulta sobre la norma[/bold yellow] (o '[dim]salir[/dim]')")
            if not consulta.strip():
                continue
            if consulta.lower().strip() in ("salir", "exit", "quit", "q"):
                if tokens_acumulados["consultas"] > 0:
                    console.print(f"\n[bold blue]Resumen de sesión:[/bold blue] Consumiste [bold]{tokens_acumulados['total']:,}[/bold] tokens en {tokens_acumulados['consultas']} consultas IA.")
                console.print("\n[cyan]Cerrando sesión de consulta. ¡Hasta luego![/cyan]\n")
                break

            # comando para cambiar top_k al vuelo
            if consulta.strip().startswith("/k"):
                partes = consulta.strip().split()
                if len(partes) > 1 and partes[1].isdigit():
                    top_k_default = max(1, min(20, int(partes[1])))
                    console.print(f"[bold green]✓ Top-K actualizado:[/bold green] Ahora se recuperarán [bold]{top_k_default}[/bold] fragmentos por consulta.\n")
                else:
                    console.print(f"[dim]Top-K actual: {top_k_default}. Uso: /k <numero>, ej. /k 5[/dim]\n")
                continue

            # deteccion de modificador inline --k <num>
            k_a_usar = top_k_default
            match_k = re.search(r"--k\s+(\d+)", consulta, re.IGNORECASE)
            if match_k:
                k_a_usar = max(1, min(20, int(match_k.group(1))))
                consulta = re.sub(r"--k\s+\d+", "", consulta, flags=re.IGNORECASE).strip()

            # deteccion de modificador inline --ia para forzar sintesis directa
            forzar_ia = False
            if "--ia" in consulta.lower():
                forzar_ia = True
                consulta = re.sub(r"--ia", "", consulta, flags=re.IGNORECASE).strip()

            console.print()
            with console.status(f"[bold cyan]Buscando en la normativa ({k_a_usar} fragmentos con BM25 + Coseno + RRF)...[/bold cyan]"):
                resultado = engine.query(consulta, top_k=k_a_usar)

            # muestra tabla resumen con las fuentes oficiales detectadas
            mostrar_tabla_fuentes(resultado)
            console.print()

            chunks = resultado["chunks"]
            scores = resultado["scores_rrf"]
            total = len(chunks)

            # si el usuario uso --ia directamente en la consulta
            if forzar_ia:
                if api_key:
                    with console.status("[bold purple]Sintetizando respuesta fundamentada con Gemini (consumiendo tokens)...[/bold purple]"):
                        respuesta_texto, usage = llamar_gemini(resultado["prompt_aumentado"], api_key)
                    console.print(Panel(Markdown(respuesta_texto), title="[bold green]Respuesta Fundamentada (Gemini API)[/bold green]", border_style="green"))
                    if usage:
                        mostrar_contador_tokens(usage, tokens_acumulados)
                else:
                    console.print("[bold red]Aviso:[/bold red] Solicitaste síntesis con IA (--ia) pero no hay [bold]GEMINI_API_KEY[/bold] en tu archivo .env. Mostrando fuentes directas:\n")
                    for idx, chunk in enumerate(chunks, 1):
                        mostrar_fragmento_oficial(idx, chunk, scores[idx - 1])
            else:
                # menu de control de tokens
                if api_key:
                    menu_txt = (
                        "¿Cómo deseas responder?\n"
                        "  [bold green][F][/bold green] Ver fuentes oficiales directas ([bold green]0 tokens / Local[/bold green])\n"
                        "  [bold purple][G][/bold purple] Sintetizar con Gemini ([bold yellow]Consume tokens API[/bold yellow])\n"
                        f"  [bold cyan][1-{total}][/bold cyan] Ver solo un fragmento específico ([bold green]0 tokens[/bold green])\n"
                        "  [dim][S] Saltar a la siguiente consulta[/dim]"
                    )
                else:
                    menu_txt = (
                        "¿Cómo deseas revisar las fuentes?\n"
                        "  [bold green][F][/bold green] Desplegar todos los fragmentos oficiales ([bold green]0 tokens / Local[/bold green])\n"
                        f"  [bold cyan][1-{total}][/bold cyan] Ver solo un fragmento específico ([bold green]0 tokens[/bold green])\n"
                        "  [dim][S] Saltar a la siguiente consulta[/dim]\n"
                        "  [dim italic](Tip: Agrega GEMINI_API_KEY en .env para activar opción de síntesis con IA)[/dim italic]"
                    )

                console.print(Panel(menu_txt, border_style="blue", expand=False))
                eleccion = Prompt.ask("[bold yellow]Tu opción[/bold yellow]", default="F").strip().upper()

                if eleccion == "G":
                    if api_key:
                        with console.status("[bold purple]Sintetizando respuesta con Gemini (consumiendo tokens)...[/bold purple]"):
                            respuesta_texto, usage = llamar_gemini(resultado["prompt_aumentado"], api_key)
                        console.print()
                        console.print(Panel(Markdown(respuesta_texto), title="[bold green]Respuesta Fundamentada (Gemini API)[/bold green]", border_style="green"))
                        if usage:
                            mostrar_contador_tokens(usage, tokens_acumulados)
                    else:
                        console.print("[yellow]Para usar síntesis con Gemini, configura GEMINI_API_KEY en tu archivo .env.[/yellow]")
                        for idx, chunk in enumerate(chunks, 1):
                            mostrar_fragmento_oficial(idx, chunk, scores[idx - 1])

                elif eleccion in ("F", "TODOS", "ALL"):
                    console.print()
                    for idx, chunk in enumerate(chunks, 1):
                        mostrar_fragmento_oficial(idx, chunk, scores[idx - 1])

                elif eleccion.isdigit():
                    num = int(eleccion)
                    if 1 <= num <= total:
                        console.print()
                        mostrar_fragmento_oficial(num, chunks[num - 1], scores[num - 1])
                    else:
                        console.print(f"[red]Número fuera de rango (1-{total}).[/red]")

                elif eleccion == "S":
                    console.print("[dim]Consulta finalizada sin desplegar texto.[/dim]")

            console.print("\n" + "─" * 60 + "\n")

        except KeyboardInterrupt:
            console.print("\n\n[cyan]Sesión interrumpida por el usuario.[/cyan]\n")
            break


if __name__ == "__main__":
    main()
