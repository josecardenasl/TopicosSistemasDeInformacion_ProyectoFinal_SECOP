import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime

import resend
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter
import requests as http_requests
from langchain_core.embeddings import Embeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_qdrant import QdrantVectorStore
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from qdrant_client import QdrantClient

load_dotenv(find_dotenv())

DATA_DIR        = os.path.join(os.path.dirname(__file__), "..", "data")
EMBED_MODEL     = "gemini-embedding-001"
COLLECTION_NAME = "secop_licitaciones_v2"
LLM_MODEL       = "gemini-2.5-flash"
TOP_K           = 12
CHUNK_SIZE      = 1500
CHUNK_OVERLAP   = 200
BM25_WEIGHT     = 0.4
DB_PATH         = os.path.join(os.path.dirname(__file__), "alerts.db")

QDRANT_URL     = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

PROMPT_TEMPLATE = """
Eres un asistente experto en licitaciones públicas colombianas del sistema SECOP.
Tu función es ayudar a pequeñas y medianas empresas (PYMES) a encontrar
oportunidades de contratación relevantes para su negocio.

Responde ÚNICAMENTE con la información del contexto proporcionado.
Si no encuentras la respuesta en el contexto, di claramente que no tienes
esa información en los documentos disponibles.

Cuando respondas, intenta siempre incluir (si están disponibles):
- Entidad contratante
- Objeto del contrato
- Presupuesto estimado
- Ciudad / Departamento
- Fechas relevantes

Contexto:
{context}

Pregunta del usuario: {question}

Respuesta:"""

class GoogleEmbeddings(Embeddings):
    """Llama directamente a la REST API de Google para evitar problemas de versión de SDK."""
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str = EMBED_MODEL):
        self.api_key = api_key
        self.model = model

    def _embed(self, text: str) -> list[float]:
        url = f"{self.BASE_URL}/{self.model}:embedContent"
        r = http_requests.post(
            url,
            params={"key": self.api_key},
            json={"content": {"parts": [{"text": text}]}},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["embedding"]["values"]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


prompt = PromptTemplate(
    template=PROMPT_TEMPLATE,
    input_variables=["context", "question"],
)

_chain = None
_retriever = None


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            criteria TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_alert(email: str, criteria: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO alerts (email, criteria, created_at) VALUES (?, ?, ?)",
        (email, criteria, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def load_chunks():
    if not os.path.isdir(DATA_DIR):
        return []
    docs = []
    for root, _, files in os.walk(DATA_DIR):
        for filename in files:
            if filename.lower().endswith(".pdf"):
                path = os.path.join(root, filename)
                try:
                    loader = PyMuPDFLoader(path)
                    docs.extend(loader.load())
                except Exception as e:
                    print(f"Error cargando {filename}: {e}")
    if not docs:
        return []
    for doc in docs:
        source = doc.metadata.get("source", "")
        filename = os.path.basename(source)
        name_clean = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ")
        doc.metadata["filename"] = filename
        doc.metadata["title"] = name_clean
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " "],
    )
    chunks = splitter.split_documents(docs)
    for chunk in chunks:
        title = chunk.metadata.get("title", "Licitación SECOP")
        page = chunk.metadata.get("page", "?")
        chunk.page_content = f"[{title} | Página {page}]\n{chunk.page_content}"
    return chunks


def bm25_preprocess(text: str):
    text = text.lower()
    text = re.sub(r"[áà]", "a", text)
    text = re.sub(r"[éè]", "e", text)
    text = re.sub(r"[íì]", "i", text)
    text = re.sub(r"[óò]", "o", text)
    text = re.sub(r"[úù]", "u", text)
    return re.findall(r"[a-z0-9ñ]+", text)


def format_docs(docs):
    parts = []
    for doc in docs:
        filename = doc.metadata.get("filename", "desconocido")
        parts.append(f"[Fuente: {filename}]\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)


def load_vectorstore():
    embeddings = GoogleEmbeddings(api_key=GOOGLE_API_KEY)
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
    )


def build_rag_chain(vectorstore):
    llm = ChatGoogleGenerativeAI(model=LLM_MODEL, google_api_key=GOOGLE_API_KEY)
    vector_retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": TOP_K},
    )
    chunks = load_chunks()
    if chunks:
        bm25_retriever = BM25Retriever.from_documents(
            chunks, preprocess_func=bm25_preprocess
        )
        bm25_retriever.k = TOP_K
        retriever = EnsembleRetriever(
            retrievers=[bm25_retriever, vector_retriever],
            weights=[BM25_WEIGHT, 1 - BM25_WEIGHT],
        )
        print(f"Búsqueda híbrida lista ({len(chunks)} chunks BM25 + Qdrant Cloud)")
    else:
        retriever = vector_retriever
        print("Sin PDFs locales. Usando solo búsqueda semántica (Qdrant Cloud).")
    chain = (
        {"context": retriever | RunnableLambda(format_docs), "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain, retriever


async def send_alert_email(email: str, criteria: str, answer: str, sources: list):
    if not RESEND_API_KEY:
        print(f"RESEND_API_KEY no configurada. Email omitido para {email}.")
        return
    try:
        resend.api_key = RESEND_API_KEY
        sources_html = "".join(
            f"<li style='margin-bottom:4px;'><strong>{s['filename'].replace('_',' ').replace('.pdf','')}</strong>"
            f" &mdash; página {s['page']}</li>"
            for s in sources[:6]
        )
        resend.Emails.send({
            "from": "SECOP Alertas <onboarding@resend.dev>",
            "to": [email],
            "subject": f"SECOP: resultados para «{criteria[:60]}»",
            "html": f"""<!DOCTYPE html>
<html lang="es">
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,sans-serif;">
<div style="max-width:600px;margin:32px auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
  <div style="background:#1e3a5f;padding:24px 28px;">
    <h1 style="margin:0;color:white;font-size:20px;">🔍 SECOP Inteligente</h1>
    <p style="margin:4px 0 0;color:#93c5fd;font-size:13px;">Buscador de licitaciones para PYMES</p>
  </div>
  <div style="padding:28px;">
    <p style="color:#6b7280;font-size:13px;margin-top:0;">Resultados para tu búsqueda:</p>
    <div style="background:#eff6ff;border-left:4px solid #1e3a5f;padding:12px 16px;border-radius:4px;margin-bottom:24px;">
      <em style="color:#1e40af;font-size:14px;">«{criteria}»</em>
    </div>
    <h2 style="color:#1f2937;font-size:15px;margin-bottom:8px;">Respuesta</h2>
    <p style="color:#374151;line-height:1.7;font-size:14px;">{answer.replace(chr(10), '<br>')}</p>
    {"<h2 style='color:#1f2937;font-size:15px;margin-top:24px;'>Documentos consultados</h2><ul style='color:#6b7280;font-size:13px;padding-left:20px;'>" + sources_html + "</ul>" if sources_html else ""}
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
    <p style="color:#9ca3af;font-size:12px;margin:0;">
      Recibirás nuevas alertas cuando haya licitaciones que coincidan con tus criterios.<br>
      Proyecto académico &middot; Tópicos de Sistemas de Información &middot; EAFIT 2026
    </p>
  </div>
</div>
</body>
</html>""",
        })
        print(f"Email enviado a {email}")
    except Exception as e:
        print(f"Error enviando email a {email}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _chain, _retriever
    print("Iniciando sistema RAG...")
    vectorstore = load_vectorstore()
    _chain, _retriever = build_rag_chain(vectorstore)
    init_db()
    print("Sistema listo.")
    yield


app = FastAPI(title="SECOP RAG API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str


class AlertRequest(BaseModel):
    email: str
    criteria: str


@app.get("/health")
def health():
    return {"status": "ok", "ready": _chain is not None}


@app.post("/query")
async def query_rag(req: QueryRequest):
    if not _chain:
        raise HTTPException(status_code=503, detail="Sistema RAG no inicializado aún.")
    answer = await _chain.ainvoke(req.question)
    docs = _retriever.invoke(req.question)
    sources = [
        {"filename": d.metadata.get("filename", "?"), "page": d.metadata.get("page", "?")}
        for d in docs
    ]
    return {"answer": answer, "sources": sources}


@app.post("/alert")
async def create_alert(req: AlertRequest, bg: BackgroundTasks):
    if not _chain:
        raise HTTPException(status_code=503, detail="Sistema RAG no inicializado aún.")
    save_alert(req.email, req.criteria)
    answer = await _chain.ainvoke(req.criteria)
    docs = _retriever.invoke(req.criteria)
    sources = [
        {"filename": d.metadata.get("filename", "?"), "page": d.metadata.get("page", "?")}
        for d in docs
    ]
    bg.add_task(send_alert_email, req.email, req.criteria, answer, sources)
    return {"message": "Alerta registrada. Recibirás los resultados actuales por correo."}
