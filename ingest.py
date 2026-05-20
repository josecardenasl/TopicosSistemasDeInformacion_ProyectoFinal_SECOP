import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

load_dotenv()

DATA_DIR        = "data/"
EMBED_MODEL     = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
COLLECTION_NAME = "secop_licitaciones"
EMBED_DIM       = 384
CHUNK_SIZE      = 1500
CHUNK_OVERLAP   = 200

QDRANT_URL      = os.getenv("QDRANT_URL")
QDRANT_API_KEY  = os.getenv("QDRANT_API_KEY")
GOOGLE_API_KEY  = os.getenv("GOOGLE_API_KEY")


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

    embeddings = HuggingFaceEmbeddings(
    model_name=EMBED_MODEL,
    model_kwargs={"device": "cpu"}
    )

    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY
    )

    # Reemplaza recreate_collection (deprecado)
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=EMBED_DIM,
            distance=Distance.COSINE
        )
    )

    vectorstore = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings
    )

    vectorstore.add_documents(chunks)
    print(f"   Vector store guardado en Qdrant Cloud")
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
