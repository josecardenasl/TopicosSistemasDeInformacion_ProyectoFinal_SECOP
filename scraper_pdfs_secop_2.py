"""
scraper_pdfs_secop.py
=====================
Descarga PDFs de licitaciones públicas colombianas desde SECOP II.

Fuente oficial:
  Dataset "SECOP II - Archivos Descarga Desde 2025" (dmgg-8hin)
  Dataset "SECOP II - Archivos Descarga Histórico 2023-2024" (3skv-9na7)
  API Socrata → datos.gov.co (pública, sin login)

Los PDFs se descargan de:
  https://community.secop.gov.co/Public/Archive/RetrieveFile/Index?DocumentId=...

Estructura de salida:
  data/
  ├── licitacion_001_estudios_previos_gobernacion_antioquia.pdf
  ├── licitacion_002_invitacion_alcaldia_medellin.pdf
  └── ...
  data_licitaciones.zip   ← entregable final

Uso:
  pip install requests pandas tqdm
  python scraper_pdfs_secop.py

Proyecto: Buscador Inteligente de Licitaciones SECOP - EAFIT 2026
"""

import requests
import pandas as pd
import os
import re
import time
import zipfile
import json
import unicodedata
from tqdm import tqdm
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN — ajusta aquí según tus necesidades
# ─────────────────────────────────────────────────────────────

# Cuántos PDFs descargar como máximo
TARGET_PDFS = 40

# Cuántos registros del CSV leer para encontrar candidatos relevantes
# (el dataset tiene millones de filas; con 5000 hay más que suficiente para filtrar)
CSV_ROWS_TO_SCAN = 5_000

# Directorio de salida
OUTPUT_DIR = "data"

# Nombre del ZIP final
ZIP_NAME = "licitaciones_secop.zip"

# Pausa entre descargas (segundos) — para no saturar el servidor
DOWNLOAD_DELAY = 0.5

# Timeout por descarga (segundos)
DOWNLOAD_TIMEOUT = 45

# Tamaño mínimo de PDF válido (bytes) — evitar PDFs corruptos o vacíos
MIN_PDF_SIZE = 10_000   # 10 KB
MAX_PDF_SIZE = 15_000_000  # 15 MB (evitar PDFs gigantes)

# ── Palabras clave de NOMBRES DE DOCUMENTOS relevantes para licitaciones ──
# Los documentos que contengan alguna de estas palabras en su nombre
# son los que nos interesan para el RAG
DOCUMENT_KEYWORDS = [
    "pliego", "pliegos", "condicion",
    "estudio", "estudios", "previo", "previos",
    "invitacion", "invitación",
    "terminos", "términos", "referencia",
    "apertura", "convocatoria",
    "resolucion", "resolución",
    "solicitud", "oferta",
    "bases", "licitacion", "licitación",
    "seleccion", "selección",
    "propuesta", "contrato",
    "aviso",
]

# ── Entidades / departamentos de interés (en el campo Entidad del CSV) ──
# Si el nombre de la entidad contiene alguna de estas palabras, priorízalo
# (si la lista está vacía, acepta cualquier entidad)
ENTITY_PRIORITY_KEYWORDS = [
    "antioquia", "medellín", "medellin",
    "bogotá", "bogota", "valle",
    "gobernacion", "gobernación",
    "alcaldia", "alcaldía",
    "universidad", "hospital",
    "ministerio", "secretaria",
]

# ─────────────────────────────────────────────────────────────
# DATASETS — en orden de preferencia (más reciente primero)
# ─────────────────────────────────────────────────────────────
DATASETS = [
    {
        "id": "dmgg-8hin",
        "name": "SECOP II Archivos Descarga 2025",
        "api": "https://www.datos.gov.co/resource/dmgg-8hin.csv",
    },
    {
        "id": "3skv-9na7",
        "name": "SECOP II Archivos Descarga 2023-2024",
        "api": "https://www.datos.gov.co/resource/3skv-9na7.csv",
    },
    {
        "id": "kgcd-kt7i",
        "name": "SECOP II Archivos Descarga 2022",
        "api": "https://www.datos.gov.co/resource/kgcd-kt7i.csv",
    },
]

# ─────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Convierte a minúsculas y elimina tildes/acentos para comparaciones."""
    if not isinstance(text, str):
        return ""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def safe_filename(text: str, max_len: int = 60) -> str:
    """Convierte texto en nombre de archivo seguro."""
    text = normalize(text)
    text = re.sub(r"[^a-z0-9\s_]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:max_len]


def is_relevant_document(doc_name: str) -> bool:
    """Retorna True si el nombre del documento sugiere que es un pliego,
    estudio previo, invitación u otro documento de licitación."""
    norm = normalize(doc_name)
    return any(kw in norm for kw in DOCUMENT_KEYWORDS)


def is_priority_entity(entity_name: str) -> bool:
    """Retorna True si la entidad coincide con nuestros departamentos preferidos."""
    if not ENTITY_PRIORITY_KEYWORDS:
        return True
    norm = normalize(entity_name)
    return any(kw in norm for kw in ENTITY_PRIORITY_KEYWORDS)


def build_pdf_filename(idx: int, doc_name: str, entity: str) -> str:
    """Genera el nombre descriptivo del PDF."""
    num = str(idx).zfill(3)
    doc_clean = safe_filename(doc_name, 40)
    ent_clean = safe_filename(entity, 30)
    name = f"SECOP_{num}_{ent_clean}_{doc_clean}.pdf"
    # Reemplazar dobles guiones bajos
    name = re.sub(r"_+", "_", name)
    return name


# ─────────────────────────────────────────────────────────────
# PASO 1: Obtener el índice CSV de documentos
# ─────────────────────────────────────────────────────────────

def fetch_document_index(limit: int) -> pd.DataFrame:
    """
    Descarga el índice de documentos desde la API Socrata.
    Prueba cada dataset en orden hasta obtener suficientes filas.
    Retorna un DataFrame con columnas normalizadas.
    """
    all_rows = []
    per_dataset = limit // len(DATASETS) + 500  # un poco más por si algunos no son PDF

    for ds in DATASETS:
        print(f"\n  📂 Dataset: {ds['name']} ({ds['id']})")
        url = ds["api"]
        params = {
            "$limit": per_dataset,
            "$offset": 0,
            "$order": ":id DESC",  # más recientes primero
        }
        try:
            r = requests.get(url, params=params, timeout=60,
                             headers={"Accept": "text/csv"})
            r.raise_for_status()

            # Parsear CSV desde la respuesta
            from io import StringIO
            df = pd.read_csv(StringIO(r.text), dtype=str, low_memory=False)
            print(f"     Filas descargadas: {len(df):,}  |  Columnas: {list(df.columns)[:6]}...")
            all_rows.append(df)

        except Exception as e:
            print(f"     ⚠️  Error con {ds['name']}: {e}")
            continue

    if not all_rows:
        raise RuntimeError("No se pudo obtener el índice de ningún dataset.")

    combined = pd.concat(all_rows, ignore_index=True)
    combined = combined.drop_duplicates()

    # Normalizar nombres de columnas (el CSV puede variar entre datasets)
    combined.columns = [c.strip().lower().replace(" ", "_") for c in combined.columns]
    print(f"\n  Total registros combinados: {len(combined):,}")
    print(f"  Columnas disponibles: {list(combined.columns)}")

    return combined


def detect_columns(df: pd.DataFrame) -> dict:
    """
    Detecta dinámicamente qué columna del DataFrame corresponde a cada
    campo que necesitamos. El dataset puede cambiar nombres entre versiones.
    """
    col_map = {}

    # URL de descarga
    for candidate in ["url_descarga_documento", "url_descarga", "url", "link"]:
        if candidate in df.columns:
            col_map["url"] = candidate
            break

    # Nombre del documento
    for candidate in ["nombre_archivo", "nombre_documento", "nombre_del_documento",
                      "descripci_n", "descripcion", "nombre_doc", "nombre"]:
        if candidate in df.columns:
            col_map["doc_name"] = candidate
            break

    # Entidad
    for candidate in ["entidad", "nombre_entidad", "entidad_compradora"]:
        if candidate in df.columns:
            col_map["entity"] = candidate
            break

    # Proceso (ID del proceso)
    for candidate in ["proceso", "id_proceso", "numero_proceso"]:
        if candidate in df.columns:
            col_map["proceso"] = candidate
            break

    # Extensión
    for candidate in ["extensi_n", "extension", "ext"]:
        if candidate in df.columns:
            col_map["ext"] = candidate
            break

    # Tamaño
    for candidate in ["tamanno_archivo", "tama_o_documento", "tamano_documento", "tamano", "size"]:
        if candidate in df.columns:
            col_map["size"] = candidate
            break

    missing = [k for k in ["url", "doc_name", "entity"] if k not in col_map]
    if missing:
        raise RuntimeError(
            f"No se encontraron columnas requeridas: {missing}\n"
            f"Columnas disponibles: {list(df.columns)}"
        )

    print(f"\n  Mapeo de columnas detectado: {col_map}")
    return col_map


# ─────────────────────────────────────────────────────────────
# PASO 2: Filtrar candidatos relevantes
# ─────────────────────────────────────────────────────────────

def filter_candidates(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """
    Filtra el DataFrame para quedarse solo con PDFs relevantes:
    1. Extensión PDF (o nombre termina en .pdf)
    2. Nombre de documento sugiere que es pliego/estudio/invitación/etc.
    3. Tiene URL válida
    4. Tiene tamaño razonable (si el campo existe)
    """
    print("\n🔍 Filtrando candidatos relevantes...")
    original = len(df)

    url_col = col_map["url"]
    doc_col = col_map["doc_name"]

    # 1. Solo PDFs
    if "ext" in col_map:
        ext_col = col_map["ext"]
        df = df[df[ext_col].str.lower().str.strip().isin(["pdf", ".pdf"])]
    else:
        # Si no hay columna de extensión, filtrar por nombre
        df = df[df[doc_col].str.lower().str.strip().str.endswith(".pdf")]

    print(f"   Después de filtro PDF: {len(df):,} (de {original:,})")

    # 2. Solo con URL válida
    df = df[df[url_col].notna() & (df[url_col].str.len() > 20)]
    print(f"   Después de filtro URL: {len(df):,}")

    # 3. Filtro por nombre relevante (pliego, estudio previo, etc.)
    mask_relevant = df[doc_col].apply(is_relevant_document)
    df_relevant = df[mask_relevant].copy()
    df_other = df[~mask_relevant].copy()
    print(f"   Documentos con palabras clave relevantes: {len(df_relevant):,}")

    # 4. Tamaño razonable (si el campo existe)
    if "size" in col_map:
        size_col = col_map["size"]
        for frame in [df_relevant, df_other]:
            frame[size_col] = pd.to_numeric(frame[size_col], errors="coerce")
            mask_size = (
                frame[size_col].isna() |
                ((frame[size_col] >= MIN_PDF_SIZE) & (frame[size_col] <= MAX_PDF_SIZE))
            )
            # Aplicar in-place
            frame.drop(frame[~mask_size].index, inplace=True)
        print(f"   Después de filtro tamaño: {len(df_relevant):,} relevantes")

    # Combinar: primero los relevantes, luego el resto como relleno
    df_combined = pd.concat([df_relevant, df_other], ignore_index=True)

    # 5. Priorizar entidades de Antioquia, Bogotá, Valle (no excluir los demás)
    entity_col = col_map["entity"]
    df_combined["_priority"] = df_combined[entity_col].apply(
        lambda x: 0 if is_priority_entity(x) else 1
    )
    df_combined = df_combined.sort_values("_priority").drop(columns=["_priority"])
    df_combined = df_combined.reset_index(drop=True)

    print(f"   Total candidatos ordenados: {len(df_combined):,}")
    return df_combined


# ─────────────────────────────────────────────────────────────
# PASO 3: Descargar PDFs
# ─────────────────────────────────────────────────────────────

def download_pdfs(candidates: pd.DataFrame, col_map: dict) -> list:
    """
    Descarga hasta TARGET_PDFS PDFs desde las URLs del dataset.
    Retorna lista de rutas de archivos descargados.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    url_col = col_map["url"]
    doc_col = col_map["doc_name"]
    entity_col = col_map["entity"]

    downloaded = []
    errors = 0
    skipped = 0
    idx = 1

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; EAFIT-Research-Bot/1.0)",
        "Accept": "application/pdf,*/*",
    })

    print(f"\n⬇️  Iniciando descarga de hasta {TARGET_PDFS} PDFs...")
    print(f"   Destino: {os.path.abspath(OUTPUT_DIR)}/\n")

    pbar = tqdm(
        total=TARGET_PDFS,
        desc="PDFs descargados",
        unit="pdf",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"
    )

    for _, row in candidates.iterrows():
        if idx > TARGET_PDFS:
            break

        url = str(row[url_col]).strip()
        doc_name = str(row.get(doc_col, "documento")).strip()
        entity = str(row.get(entity_col, "entidad_desconocida")).strip()

        # Limpiar URL (el CSV a veces tiene espacios al final)
        url = url.rstrip()
        if not url.startswith("http"):
            skipped += 1
            continue

        # Nombre de archivo de salida
        filename = build_pdf_filename(idx, doc_name, entity)
        filepath = os.path.join(OUTPUT_DIR, filename)

        # No re-descargar si ya existe
        if os.path.exists(filepath) and os.path.getsize(filepath) > MIN_PDF_SIZE:
            downloaded.append(filepath)
            idx += 1
            pbar.update(1)
            continue

        try:
            response = session.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True)

            # Verificar que es un PDF real
            content_type = response.headers.get("Content-Type", "")
            if response.status_code != 200:
                errors += 1
                continue

            # Leer contenido
            content = b""
            for chunk in response.iter_content(chunk_size=65536):
                content += chunk
                if len(content) > MAX_PDF_SIZE:
                    break  # PDF demasiado grande, saltar

            # Verificar tamaño mínimo
            if len(content) < MIN_PDF_SIZE:
                skipped += 1
                continue

            # Verificar magic bytes de PDF (%PDF-)
            if not content.startswith(b"%PDF"):
                # Algunos archivos son PDFs disfrazados — intentar detectar
                if b"%PDF" not in content[:1024]:
                    skipped += 1
                    continue

            # Guardar
            with open(filepath, "wb") as f:
                f.write(content)

            downloaded.append(filepath)
            idx += 1
            pbar.update(1)

            # Pausa educada
            time.sleep(DOWNLOAD_DELAY)

        except requests.exceptions.Timeout:
            errors += 1
            pbar.set_postfix_str(f"⏱ timeout #{errors}")
        except requests.exceptions.ConnectionError:
            errors += 1
            time.sleep(2)
        except Exception as e:
            errors += 1
            pbar.set_postfix_str(f"err: {str(e)[:30]}")

    pbar.close()

    print(f"\n✅ Descarga completada:")
    print(f"   PDFs exitosos : {len(downloaded)}")
    print(f"   Errores       : {errors}")
    print(f"   Saltados      : {skipped}")

    return downloaded


# ─────────────────────────────────────────────────────────────
# PASO 4: Crear ZIP y manifiesto
# ─────────────────────────────────────────────────────────────

def create_zip_and_manifest(downloaded_files: list, candidates: pd.DataFrame, col_map: dict):
    """
    1. Crea el ZIP con todos los PDFs
    2. Genera un manifest.json con metadatos de cada PDF (útil para el RAG)
    """
    # ── Manifiesto JSON ──
    manifest = []
    url_col = col_map["url"]
    doc_col = col_map["doc_name"]
    entity_col = col_map["entity"]
    proceso_col = col_map.get("proceso", None)

    # Construir lookup de metadata por nombre de archivo
    meta_lookup = {}
    for _, row in candidates.iterrows():
        url = str(row.get(url_col, "")).strip()
        meta_lookup[url] = row

    for filepath in downloaded_files:
        filename = os.path.basename(filepath)
        size_kb = round(os.path.getsize(filepath) / 1024, 1)

        entry = {
            "filename": filename,
            "path": filepath,
            "size_kb": size_kb,
        }
        manifest.append(entry)

    manifest_path = os.path.join(OUTPUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n📋 Manifiesto guardado: {manifest_path}  ({len(manifest)} entradas)")

    # ── ZIP ──
    zip_path = ZIP_NAME
    print(f"📦 Creando ZIP: {zip_path}...")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filepath in downloaded_files:
            arcname = os.path.join("data", os.path.basename(filepath))
            zf.write(filepath, arcname)
        # Incluir el manifiesto
        zf.write(manifest_path, "data/manifest.json")

    zip_size_mb = os.path.getsize(zip_path) / 1024 / 1024
    print(f"✅ ZIP creado: {zip_path}  ({zip_size_mb:.1f} MB)")
    print(f"   Contiene {len(downloaded_files)} PDFs + manifest.json")

    return zip_path


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  SECOP II — Descarga de PDFs para RAG")
    print("  Proyecto Tópicos de SI — EAFIT Mayo 2026")
    print("=" * 65)

    start = datetime.now()

    # 1. Obtener índice CSV de documentos
    print("\n[1/4] Descargando índice de documentos desde datos.gov.co...")
    df = fetch_document_index(limit=CSV_ROWS_TO_SCAN)

    # 2. Detectar columnas
    print("\n[2/4] Detectando estructura del dataset...")
    col_map = detect_columns(df)

    # 3. Filtrar candidatos
    candidates = filter_candidates(df, col_map)

    if len(candidates) == 0:
        print("\n❌ No se encontraron candidatos. Revisa los filtros o la conexión.")
        return

    print(f"\n[3/4] Descargando PDFs ({min(TARGET_PDFS, len(candidates))} objetivo)...")
    downloaded = download_pdfs(candidates, col_map)

    if not downloaded:
        print("\n❌ No se descargó ningún PDF. Verifica la conexión a community.secop.gov.co")
        return

    # 4. ZIP + manifiesto
    print("\n[4/4] Empaquetando resultados...")
    zip_path = create_zip_and_manifest(downloaded, candidates, col_map)

    elapsed = (datetime.now() - start).seconds
    print(f"\n{'='*65}")
    print(f"  ✅ COMPLETADO en {elapsed}s")
    print(f"  PDFs en    : {os.path.abspath(OUTPUT_DIR)}/")
    print(f"  ZIP final  : {os.path.abspath(zip_path)}")
    print(f"{'='*65}")
    print("\n🚀 Próximos pasos para el pipeline RAG:")
    print("  1. Extraer texto de PDFs con:  pip install pymupdf")
    print("     import fitz  # PyMuPDF")
    print("     doc = fitz.open('archivo.pdf')")
    print("     texto = ''.join(p.get_text() for p in doc)")
    print("  2. Dividir en chunks con LangChain RecursiveCharacterTextSplitter")
    print("  3. Generar embeddings con all-MiniLM-L6-v2")
    print("  4. Insertar en ChromaDB con metadatos del manifest.json")


if __name__ == "__main__":
    main()
