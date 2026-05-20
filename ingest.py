import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import requests
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

load_dotenv()

DATA_DIR        = "data/"
EMBED_MODEL     = "gemini-embedding-001"
COLLECTION_NAME = "secop_licitaciones_v2"
EMBED_DIM       = 3072
CHUNK_SIZE      = 1500
CHUNK_OVERLAP   = 200

QDRANT_URL     = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


class GoogleEmbeddings(Embeddings):
    """Llama directamente a la REST API de Google para evitar problemas de versión de SDK."""
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str = EMBED_MODEL):
        self.api_key = api_key
        self.model = model

    def _embed(self, text: str) -> list[float]:
        url = f"{self.BASE_URL}/{self.model}:embedContent"
        r = requests.post(
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


def load_data(directory: str):
    docs = []
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.lower().endswith(".pdf"):
                path = os.path.join(root, filename)
                try:
                    loader = PyMuPDFLoader(path)
                    loaded = loader.load()
                    docs.extend(loaded)
                    print(f"   Cargado: {filename} ({len(loaded)} páginas)")
                except Exception as e:
                    print(f"   ⚠ Error cargando {filename}: {e}")
    print(f"\n  → Total: {len(docs)} páginas cargadas")
    return docs


def enrich_metadata(docs):
    for doc in docs:
        source = doc.metadata.get("source", "")
        filename = os.path.basename(source)
        name_clean = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ")
        doc.metadata["filename"] = filename
        doc.metadata["title"]    = name_clean
        doc.metadata["source"]   = source
    return docs


def split_documents(docs):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " "]
    )
    chunks = splitter.split_documents(docs)
    for chunk in chunks:
        title = chunk.metadata.get("title", "Licitación SECOP")
        page  = chunk.metadata.get("page", "?")
        chunk.page_content = f"[{title} | Página {page}]\n{chunk.page_content}"
    print(f"  → {len(docs)} páginas divididas en {len(chunks)} chunks")
    return chunks


def build_vectorstore(chunks):
    print("\n  Generando embeddings con Google text-embedding-004...")

    embeddings = GoogleEmbeddings(api_key=GOOGLE_API_KEY)

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )

    vectorstore = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
    )

    vectorstore.add_documents(chunks)
    print(f"   Vector store guardado en Qdrant Cloud (colección: {COLLECTION_NAME})")
    return vectorstore


if __name__ == "__main__":
    print("═" * 50)
    print("  Ingesta de PDFs — RAG SECOP EAFIT (Cloud)")
    print("═" * 50)

    if not QDRANT_URL or not QDRANT_API_KEY or not GOOGLE_API_KEY:
        raise ValueError("Faltan variables de entorno. Verifica tu .env")

    print("\n[1/3] Cargando PDFs...")
    docs = load_data(DATA_DIR)

    if not docs:
        print("\n  ⚠ No se encontraron PDFs en data/. Abortando.")
        exit(1)

    print("\n[2/3] Enriqueciendo metadata y dividiendo en chunks...")
    docs   = enrich_metadata(docs)
    chunks = split_documents(docs)

    print("\n[3/3] Construyendo vector store en Qdrant Cloud...")
    build_vectorstore(chunks)

    print("\n  Ingesta completada. Ya puedes correr el retriever.")
