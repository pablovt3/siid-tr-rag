# NORMA SIID: Inteligencia Normativa y RAG

Motor de búsqueda híbrida y extracción regulatoria especializado en la normativa del **Sistema Integrado de Información sobre Transacciones de Derivados (SIID)**.

El sistema procesa compendios regulatorios, cartas circulares y estudios metodológicos, ofreciendo dos modalidades de consulta en terminal: auditoría directa de fuentes oficiales con nulo consumo de tokens o síntesis generativa fundamentada con consumo de tokens.

```
                  ARQUITECTURA DE FLUJO DOCUMENTAL Y RAG
                  
  [ Portal SIID / BCCh ]
           │
           ▼
  1. Crawler & Ingesta (src/connectors/)
     • Descarga por streaming (bloques de 8 KB)
     • Verificación de integridad SHA-256
           │
           ▼
  2. Parsing Estructurado (src/parsers/)
     • PyMuPDF4LLM con normalización Unicode NFKD
     • Reparación de tablas rotas y compresión de escalas gráficas
     • Generación de Frontmatter y exportación a Obsidian Vault
           │
           ▼
  3. Chunking Jerárquico (src/rag/chunker.py)
     • Header-Table Binding (vinculación atómica título-tabla)
     • Umbral sustantivo (mínimo 35 palabras por bloque)
     • Detección y penalización de índices de contenido
           │
           ▼
  4. Motor de Búsqueda Híbrido (src/rag/retriever.py)
     • BM25 léxico con plegado de diacríticos y stopwords
     • Similitud Coseno vectorial sobre frecuencias TF-IDF
     • Fusión de Rangos Recíprocos (RRF, k=60)
           │
           ▼
  5. CLI Interactivo (src/cli.py)
     ├── [F] Extractor Certificado (Local, 0 tokens, tablas Rich)
     └── [G] Síntesis con Gemini 3.8-Flash (API, telemetría y citas)
```

---

## Decisiones Técnicas de Diseño

El sistema prioriza la precisión legal sobre la fluidez conversacional. Las decisiones de arquitectura responden a las particularidades de la regulación financiera del Banco Central de Chile:

* **Vinculación Atómica de Tablas (Header-Table Binding):** Los anexos técnicos de derivados (como el Anexo 2.A de monedas o las matrices de contrapartes del Capítulo III.D.3) contienen especificaciones densas que pierden significado si se separan de sus encabezados. El chunker agrupa el título de sección con su tabla en un único fragmento, evitando que la búsqueda recupere filas aisladas sin contexto.
* **Cuadrículas Nativas en Consola:** En lugar de volcar texto Markdown sin formato, el CLI detecta matrices tabulares y las renderiza mediante `rich.table.Table` con bordes visuales, columnas alineadas y cabeceras contrastadas.
* **Gobernanza de Inferencia (0 Tokens por Defecto):** En consultas de cumplimiento y auditoría, el analista suele necesitar el texto exacto del artículo o la tabla oficial. El motor resuelve la búsqueda en memoria RAM local mediante BM25 y similitud coseno. La llamada al LLM es opcional y se activa únicamente al presionar `[G]` o al añadir `--ia` a la consulta.
* **Desactivación de Tokens de Razonamiento:** Para las consultas con Gemini 3.8-Flash, el payload fija `thinkingBudget: 0`. Esto elimina la generación de trazas intermedias en inglés, agiliza la respuesta y reduce el gasto de tokens a la síntesis en español formal.
* **Telemetría Exacta:** La terminal extrae `usageMetadata` de cada llamada para reportar tokens de entrada, tokens generados y el costo estimado en dólares, manteniendo un acumulador durante toda la sesión de trabajo.
* **Atenuación de Índices Navegacionales:** Las tablas de contenido que solo listan títulos y números de página reciben una penalización de puntaje (factor 0.35x), garantizando que las secciones con contenido normativo real clasifiquen en los primeros lugares de consenso.

---

## Documentación Indexada

El repositorio procesa 10 fuentes documentales organizadas en dos categorías (en primera instancia):

### Regulación Vigente (Normativa)
* **Compendio de Normas Financieras (CNF), Capítulo III.D.3:** Marco general del SIID, entidades obligadas, instrumentos derivados cubiertos y reglas de reporte según contraparte.
* **Reglamento Operativo (RO-SIID), Capítulo III.D.3.1:** Instrucciones operativas, validaciones técnicas y canales de transmisión de datos.
* **Carta Circular N° 651:** Régimen de transición para operaciones de derivados sobre monedas y tasas de interés.
* **Carta Circular N° 758:** Actualización del Anexo 2.A, especificaciones de archivos CSV y validaciones de campos obligatorios.

### Metodologías y Series Empíricas
* **Nota Técnica N° 8:** Metodología para operaciones Spot vinculadas a coberturas cambiarias con derivados.
* **Posiciones Netas Bancarias:** Medición estadística de posiciones en moneda extranjera y derivados financieros.
* **Documento de Trabajo N° 1097:** Gestión de riesgo cambiario y funcionamiento del mercado de derivados en Chile.
* **Using TR Data to Measure Onshore and Offshore FX Activity in Latam (2026):** Estimación empírica de volúmenes transados mediante repositorios de transacciones.
* **Optimal Reporting Regimes:** Análisis de incentivos y estándares de reporte en mercados emergentes.
* **SIID: Una mirada al mercado de derivados en Chile:** Estudio descriptivo de contrapartes, plazos y subyacentes operados por el sector bancario y corporativo.

---

## Instalación y Configuración

### 1. Clonar el repositorio y preparar el entorno
```bash
git clone https://github.com/pablovaldes/NORMA_SIID.git
cd NORMA_SIID

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configuración de API Key (Opcional)
Para el modo local (0 tokens) no se requiere configuración externa. Si deseas activar la síntesis con Gemini:

```bash
# Para la sesión actual de terminal
export GEMINI_API_KEY="tu_clave_aqui"

# O de forma permanente en tu perfil local (fuera del repositorio)
echo 'export GEMINI_API_KEY="tu_clave_aqui"' >> ~/.zshrc
source ~/.zshrc
```

El archivo `.gitignore` excluye `.env` y credenciales locales por defecto.

---

## Uso

### 1. Ejecutar el Pipeline de Ingesta y Parsing
Descarga los PDFs oficiales, calcula sus hashes criptográficos y genera la bóveda estructurada en Markdown:
```bash
python src/pipeline.py
```

### 2. Interfaz Interactiva de Consulta (CLI)
Inicia la consola de consulta con motor híbrido:
```bash
python src/cli.py
```

Flujo en terminal:
1. Escribe tu pregunta sobre la norma (ejemplo: `¿Qué operaciones de derivados y qué tipo de entidades están obligadas a reportar al SIID según el Capítulo III.D.3?`).
2. El sistema recupera los fragmentos con mayor consenso RRF y muestra una tabla resumen con sus puntajes.
3. Elige el modo de despliegue:
   * **`Enter` (opción `[F]`):** Despliega las tablas y numerales oficiales con **0 tokens consumidos**.
   * **`G`:** Genera la respuesta sintetizada con **Gemini 3.8-Flash** e imprime el consumo de tokens.
   * **`1` a `3`:** Muestra únicamente el fragmento seleccionado.
   * Modificador rápido: Añade `--k 5` al final de la pregunta para ampliar la profundidad de búsqueda, o usa `/k 5` para fijarla como regla de sesión.

### 3. Ejecución de Pruebas
Verifica el comportamiento del motor híbrido ante consultas de prueba:
```bash
python tests/test_rag.py
```

---

## Estructura del Repositorio

```
NORMA_SIID/
├── data/
│   ├── raw/                   # PDFs originales descargados y manifiestos JSON
│   ├── processed/             # Markdown estructurado con Frontmatter YAML
│   └── vault/                 # Bóveda organizada para Obsidian
│       ├── normativa/         # Compendios, reglamentos operativos y circulares
│       └── metodologias_estudios/ # Notas técnicas y documentos de trabajo
├── src/
│   ├── connectors/
│   │   ├── base.py            # Clase abstracta BaseConnector con hash SHA-256
│   │   ├── norma.py           # Conector universal con auto-resolución institucional
│   │   └── scraper.py         # Crawler multinivel para portal siid.cl
│   ├── parsers/
│   │   └── pdf_to_md.py       # Conversor PyMuPDF4LLM con normalización y filtros
│   ├── rag/
│   │   ├── models.py          # Modelos Pydantic (NormaChunk, TipoFragmento)
│   │   ├── chunker.py         # Chunker jerárquico con Header-Table Binding
│   │   ├── retriever.py       # Motor híbrido BM25 + Coseno + Fusión RRF (k=60)
│   │   └── qa.py              # Generador de prompts con citas obligatorias en español
│   ├── cli.py                 # Terminal interactiva con control de tokens y tablas Rich
│   └── pipeline.py            # Orquestador del flujo completo de descarga y parseo
├── tests/
│   ├── test_rag.py            # Pruebas de integración de recuperación y RRF
│   └── test_scraper.py        # Verificación del crawler documental
├── .env.example               # Plantilla de variables de entorno
├── .gitignore                 # Exclusiones de Git (datos crudos, secretos y bitácora)
└── README.md                  # Documentación técnica del proyecto
```

---

## Alcance y Consideraciones Regulatorias

Proyecto orientado a investigación y prueba de concepto. Los textos normativos corresponden a publicaciones oficiales del Banco Central de Chile.
