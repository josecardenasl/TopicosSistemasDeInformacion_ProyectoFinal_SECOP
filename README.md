# SECOP Inteligente — Buscador Semántico de Licitaciones para PYMES

**URL de la app:** https://secop-frontend-miguel-c-projects.vercel.app/ 
**Video demo (Loom):** _[completar]_  
**Equipo:** Miguel Angel Correa Piedrahita, Jose David Cardenas Lucas, Julian Osorio Alturo
**Curso:** Tópicos de Sistemas de Información · EAFIT · Mayo 2026

---

## Problema y usuario

Las pequeñas y medianas empresas (PYMES) colombianas pierden oportunidades de contratación pública porque no tienen tiempo ni herramientas para revisar manualmente las decenas de pliegos nuevos que publica SECOP II cada día. El portal oficial requiere conocer siglas, códigos UNSPSC y filtros específicos; una empresa de desarrollo de software no sabe si debe buscar por "servicios de consultoría" o "licenciamiento" o "infraestructura tecnológica".

**Usuario imaginable:** Gerente de una empresa de TI mediana en Medellín, con 15 empleados, que quiere licitar con entidades públicas pero no tiene un equipo dedicado a vigilar oportunidades.

**Momento de uso:** El usuario abre la app, escribe en lenguaje natural lo que su empresa hace ("desarrollo de software a la medida para entidades del sector salud") y en segundos recibe un resumen de los procesos abiertos más relevantes, con las entidades, presupuestos y fechas clave extraídos automáticamente. Puede además registrar su correo para recibir alertas cuando aparezcan nuevos pliegos.

**Por qué no está resuelto hoy:** El buscador oficial de SECOP no entiende lenguaje natural. Servicios comerciales de vigilancia de licitaciones existen pero cuestan entre $200.000 y $500.000 COP/mes, fuera del alcance de muchas PYMES.

---

## Dataset

**Fuente:** Sistema Electrónico de Contratación Pública II (SECOP II)  
- Portal: https://www.colombiacompra.gov.co/secop-ii  
- API Socrata: https://www.datos.gov.co (datasets de procesos 2022–2025)

**Cómo se obtuvo:** El script `scraper_pdfs_secop_2.py` consume tres datasets de datos.gov.co vía API Socrata, filtra registros que tengan URL de documento PDF, aplica criterios de relevancia (tipo de documento, entidad, tamaño del archivo) y descarga los PDFs en paralelo con reintentos. Se priorizan entidades de Antioquia, Medellín, Bogotá y Valle del Cauca.

**Tipos de documentos descargados:**
- Pliegos de condiciones definitivos
- Estudios previos
- Invitaciones públicas
- Resoluciones de apertura

**Decisiones de muestreo y limpieza:**
- Se trabajó con un corpus de ~40 PDFs representativos de diferentes sectores y regiones
- No se aplicó limpieza adicional: PyMuPDFLoader extrae texto directamente del PDF página a página
- Cada documento se trata como un proceso de contratación independiente
- Los documentos son de acceso público por ley (Ley 80 de 1993, Ley 1882 de 2018). No contienen PII — SECOP es un sistema de transparencia del Estado colombiano.

**Tamaño del corpus:** ~53 MB comprimido (`licitaciones_secop.zip`), ~40 PDFs, varios miles de fragmentos (chunks) indexados en Qdrant Cloud.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                        PIPELINE DE DATOS                        │
│                                                                 │
│  SECOP II / datos.gov.co API                                    │
│          ↓                                                      │
│  scraper_pdfs_secop_2.py  →  data/*.pdf                        │
│          ↓                                                      │
│  ingest.py:                                                     │
│    PyMuPDFLoader (extracción por página)                        │
│    RecursiveCharacterTextSplitter (chunks 1500 chars, overlap 200)│
│    HuggingFace Embeddings (paraphrase-multilingual-MiniLM-L12-v2)│
│          ↓                                                      │
│    Qdrant Cloud (colección: secop_licitaciones)                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                       ARQUITECTURA EN PRODUCCIÓN                │
│                                                                 │
│  [Usuario]                                                      │
│      ↓  HTTP                                                    │
│  [Next.js · Vercel]                                             │
│   /  → page.tsx (búsqueda + resultados)                         │
│      ↓  POST /query   POST /alert                               │
│  [FastAPI · Render]   backend/api.py                            │
│      ↓                                                          │
│   Retriever híbrido:                                            │
│   ├── BM25Retriever (40%) — coincidencia exacta de keywords     │
│   └── QdrantVectorStore (60%) — búsqueda semántica              │
│      ↓  Top-12 chunks                                           │
│   Gemini 2.5 Flash — generación de respuesta                    │
│      ↓                                                          │
│   [Respuesta + fuentes]  →  Next.js frontend                    │
│                                                                 │
│   (Alertas)  →  SQLite en Render  →  Resend Email API           │
└─────────────────────────────────────────────────────────────────┘
```

**Flujo de datos en tiempo de consulta:**
1. El usuario escribe su consulta en el frontend (Next.js en Vercel)
2. El frontend hace `POST /query` al backend (FastAPI en Render)
3. El backend ejecuta el EnsembleRetriever (BM25 40% + vectorial 60%)
4. Recupera los 12 fragmentos más relevantes de Qdrant Cloud
5. Construye el contexto y llama a Gemini 2.5 Flash vía LangChain
6. Devuelve la respuesta estructurada + lista de fuentes al frontend
7. (Opcional) El usuario registra su correo; el backend guarda la alerta en SQLite y envía un email inmediato con los resultados vía Resend

---

## Decisiones de stack

| Componente | Elegido | Alternativa descartada | Razón |
|---|---|---|---|
| **Frontend** | Next.js 15 + Tailwind CSS | Gradio / Streamlit | Gradio no es desplegable en Vercel; Next.js es el estándar del catálogo del curso para full-stack |
| **Backend API** | FastAPI + Uvicorn | Flask | FastAPI tiene soporte nativo de async, validación Pydantic y OpenAPI automática. Render tiene buildpack de Python |
| **Vector store** | Qdrant Cloud | ChromaDB local | Qdrant cloud tiene tier gratuito permanente; ChromaDB requiere volumen persistente (no disponible en Render free) |
| **LLM** | Gemini 2.5 Flash | Ollama (llama3 local) | Ollama es muy lento en CPU sin GPU; Gemini tiene tier gratuito generoso y latencia <5 s por consulta |
| **Embeddings** | `paraphrase-multilingual-MiniLM-L12-v2` | `all-MiniLM-L6-v2` | El modelo multilingüe entiende mejor el español colombiano, siglas de contratación y nombres de entidades |
| **Búsqueda** | Híbrida BM25 + vectorial | Solo vectorial | BM25 recupera mejor términos exactos (NITs, números de contrato, siglas como MINTIC, INVIAS) que el encoder semántico pierde |
| **PDF loader** | PyMuPDFLoader | PyPDFLoader | PyMuPDF es más rápido y extrae mejor tablas y texto de documentos gubernamentales con layouts complejos |
| **Email** | Resend | SendGrid | API más simple; tier gratuito de 3.000 emails/mes; SDK Python de una línea |
| **Alertas DB** | SQLite | PostgreSQL | SQLite no requiere servicio externo para una demo; suficiente para el volumen del proyecto |

---

## IA — modelo, costo y estrategia RAG

**Modelo LLM:** `gemini-2.5-flash` (Google AI Studio)  
- Corre vía API de Google (no local)
- Costo aproximado en producción: ~$0.00015 USD por consulta (estimado con ~3.000 tokens de prompt + ~500 tokens de respuesta al precio de la capa de pago)
- El tier gratuito de Google AI Studio cubre completamente el desarrollo y la demo sin costo

**Embeddings:** `paraphrase-multilingual-MiniLM-L12-v2` (HuggingFace)
- Corre 100% local en CPU en el servidor backend
- Dimensión: 384
- Costo: $0 (modelo open source)

**Estrategia RAG — búsqueda híbrida:**
- `EnsembleRetriever` combina BM25 (40%) + búsqueda vectorial en Qdrant (60%)
- Top-K: 12 fragmentos por consulta
- Chunk size: 1.500 caracteres con overlap de 200 caracteres
- Separadores: `["\n\n", "\n", ".", " "]` para respetar párrafos y oraciones
- Cada chunk incluye un prefijo `[Nombre del documento | Página X]` para que el LLM sepa la procedencia exacta de cada fragmento
- El preprocesamiento BM25 normaliza acentos (á→a, é→e, etc.) para que búsquedas como "tecnologia" encuentren documentos con "tecnología"

**Prompt:**
```
Eres un asistente experto en licitaciones públicas colombianas del sistema SECOP.
Tu función es ayudar a PYMES a encontrar oportunidades de contratación relevantes.
Responde ÚNICAMENTE con la información del contexto proporcionado.
Cuando respondas, intenta incluir: entidad contratante, objeto del contrato,
presupuesto estimado, ciudad/departamento y fechas relevantes.
```

**Evaluación informal:** Se probaron 10 consultas representativas (equipos de cómputo, consultoría, software a la medida, obras civiles, etc.) y se verificó manualmente que las respuestas correspondieran a fragmentos reales de los PDFs fuente. El sistema no alucina: cuando no encuentra información relevante, lo indica explícitamente.

---

## Lo que no funcionó y qué se descartó

**Qdrant local (persistencia en disco):** El README original menciona "Qdrant local". En la práctica, Qdrant local con persistencia en disco es inestable en Windows y se descartó a favor de Qdrant Cloud, que ofrece tier gratuito de 1 GB permanente.

**Ollama como LLM local:** Se intentó con `llama3.2:3b` en CPU. El tiempo de respuesta era de 3–8 minutos por consulta, inaceptable para una demo interactiva. Gemini 2.5 Flash responde en 3–6 segundos.

**Gradio como UI:** El catálogo del curso lo menciona y era la primera opción. Sin embargo, Gradio no es desplegable en Vercel (requiere un servidor Python) y su look es genérico. Se reemplazó por Next.js + FastAPI, que da control total sobre la UI y es el stack estándar del catálogo.

**PyPDFLoader:** Produjo texto mal formateado en varios documentos gubernamentales (columnas mezcladas, caracteres basura). Se cambió a PyMuPDFLoader, que es más robusto con layouts complejos.

**Alertas periódicas reales:** El diseño original contemplaba un cron que revisara SECOP diariamente y comparara con alertas guardadas. Render free no tiene cron jobs confiables. La solución implementada envía los resultados actuales de forma inmediata al registrarse la alerta, lo que cumple el requisito de "alertas por correo" para la demo.

**Qué faltaría para una versión de producción real:**
- Scraper programado (ej. GitHub Actions cron) que re-descargue PDFs nuevos semanalmente
- Re-ingestión incremental al vector store (solo documentos nuevos)
- Sistema de alertas diferencial (comparar resultados actuales vs. anteriores para el mismo criterio)
- Autenticación de usuarios para gestionar sus alertas
- Rate limiting en la API

---

## Métricas

| Métrica | Valor |
|---|---|
| Latencia de consulta extremo a extremo (p50) | ~4–6 s (Render cold start excluido) |
| Latencia cold start Render | ~25–40 s (primera consulta tras inactividad) |
| Costo por consulta (API Gemini en capa de pago) | ~$0.00015 USD |
| Costo en tier gratuito | $0 |
| Documentos en corpus | ~40 PDFs |
| Fragmentos indexados en Qdrant | ~2.000–3.000 chunks |
| Dimensión de embeddings | 384 |
| Top-K recuperado | 12 fragmentos |
| Peso BM25 / vectorial | 40% / 60% |

**Evaluación manual (10 consultas de prueba):**  
Se construyó un set de 10 preguntas con respuesta esperada conocida (entidad, objeto y presupuesto extraídos manualmente de los PDFs). El sistema respondió correctamente en 8/10 casos (80%). Los 2 errores fueron por documentos muy cortos donde el chunk no contenía la información clave.

---

## Cómo correrlo en local (menos de 5 pasos)

```bash
# 1. Clonar el repo
git clone https://github.com/tu-usuario/tu-repo.git
cd tu-repo

# 2. Crear y activar entorno virtual, instalar dependencias Python
python -m venv venv && venv\Scripts\activate   # Windows
pip install -r requirements.txt

# 3. Copiar variables de entorno y completar con tus claves
copy backend\.env.example .env
# Editar .env: agregar GOOGLE_API_KEY, QDRANT_URL, QDRANT_API_KEY, RESEND_API_KEY

# 4. Levantar el backend
cd backend
uvicorn api:app --reload --port 8000

# 5. En otra terminal, levantar el frontend
cd frontend
copy .env.local.example .env.local
# .env.local ya trae NEXT_PUBLIC_API_URL=http://localhost:8000
npm install --legacy-peer-deps
npm run dev
# → Abrir http://localhost:3000
```

> **Nota:** Si quieres ingestar PDFs propios, coloca los archivos en `data/`, activa el entorno Python y ejecuta `python ingest.py`. Los PDFs del corpus original están en `licitaciones_secop.zip`.

---

## Estructura del repositorio

```
├── backend/
│   ├── api.py              # FastAPI — endpoints /query y /alert
│   ├── requirements.txt    # Dependencias Python del backend
│   ├── render.yaml         # Configuración de despliegue en Render
│   └── .env.example        # Template de variables de entorno
├── frontend/
│   ├── src/
│   │   ├── app/            # Next.js App Router
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx    # Página principal
│   │   │   └── globals.css
│   │   └── components/
│   │       ├── SearchBox.tsx    # Input de búsqueda con ejemplos
│   │       ├── ResultDisplay.tsx # Respuesta + fuentes
│   │       └── AlertForm.tsx    # Registro de alerta por email
│   ├── package.json
│   ├── vercel.json         # Configuración de despliegue en Vercel
│   └── .env.local.example
├── data/                   # PDFs descargados (no en git, ver .gitignore)
├── ingest.py               # Pipeline de ingestión a Qdrant
├── retriever_gemini.py     # Módulo RAG (consulta directa por terminal)
├── scraper_pdfs_secop_2.py # Descargador de PDFs de SECOP II
├── requirements.txt        # Dependencias Python (ejecución local)
└── licitaciones_secop.zip  # Corpus de PDFs empaquetado
```
