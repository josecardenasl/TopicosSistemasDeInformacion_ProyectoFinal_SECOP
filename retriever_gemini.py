import os
import re
from dotenv import load_dotenv
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_qdrant import QdrantVectorStore
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from qdrant_client import QdrantClient

load_dotenv()

DATA_DIR        = "data/"
EMBED_MODEL     = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
COLLECTION_NAME = "secop_licitaciones"
LLM_MODEL       = "gemini-2.5-flash"
TOP_K           = 12
CHUNK_SIZE      = 1500
CHUNK_OVERLAP   = 200
BM25_WEIGHT     = 0.4

QDRANT_URL      = os.getenv("QDRANT_URL")
QDRANT_API_KEY  = os.getenv("QDRANT_API_KEY")
GOOGLE_API_KEY  = os.getenv("GOOGLE_API_KEY")


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

prompt = PromptTemplate(
    template=PROMPT_TEMPLATE,
    input_variables=["context", "question"]
)


def load_chunks():
    docs = []
    for root, _, files in os.walk(DATA_DIR):
        for filename in files:
            if filename.lower().endswith(".pdf"):
                path = os.path.join(root, filename)
                try:
                    loader = PyMuPDFLoader(path)
                    docs.extend(loader.load())
                except Exception as e:
                    print(f"    Error cargando {filename}: {e}")

    if not docs:
        return []

    for doc in docs:
        source = doc.metadata.get("source", "")
        filename = os.path.basename(source)
        name_clean = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ")
        doc.metadata["filename"] = filename
        doc.metadata["title"]    = name_clean

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " "],
    )
    chunks = splitter.split_documents(docs)
    for chunk in chunks:
        title = chunk.metadata.get("title", "Licitación SECOP")
        page  = chunk.metadata.get("page", "?")
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


def load_vectorstore():
    embeddings = HuggingFaceEmbeddings(
    model_name=EMBED_MODEL,
    model_kwargs={"device": "cpu"}
    )
    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY
    )
    vectorstore = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings
    )
    print("   Vector store cloud cargado")
    return vectorstore


def format_docs(docs):
    parts = []
    for doc in docs:
        filename = doc.metadata.get("filename", "desconocido")
        parts.append(f"[Fuente: {filename}]\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)


def build_rag_chain(vectorstore):
    llm = ChatGoogleGenerativeAI(
        model=LLM_MODEL,
        google_api_key=GOOGLE_API_KEY
    )

    vector_retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": TOP_K}
    )

    print("   Indexando BM25...")
    chunks = load_chunks()

    if chunks:
        bm25_retriever = BM25Retriever.from_documents(
            chunks,
            preprocess_func=bm25_preprocess
        )
        bm25_retriever.k = TOP_K
        print(f"   BM25 listo ({len(chunks)} chunks)")
        retriever = EnsembleRetriever(
            retrievers=[bm25_retriever, vector_retriever],
            weights=[BM25_WEIGHT, 1 - BM25_WEIGHT],
        )
    else:
        print("   ⚠ Sin PDFs locales. Usando solo búsqueda semántica.")
        retriever = vector_retriever

    chain = (
        {"context": retriever | RunnableLambda(format_docs), "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    print("   Cadena RAG híbrida lista")
    return chain, retriever


def query(chain, retriever, question: str):
    print(f"\nPregunta: {question}")
    print("─" * 50)
    response = chain.invoke(question)
    print(f"Respuesta:\n{response}")
    print("\nFuentes:")
    docs = retriever.invoke(question)
    sources = []
    for i, doc in enumerate(docs, 1):
        filename = doc.metadata.get("filename", "desconocido")
        page     = doc.metadata.get("page", "?")
        print(f"   [{i}] {filename} — página {page}")
        sources.append(filename)
    return response, sources


if __name__ == "__main__":
    print("═" * 50)
    print("  Retriever SECOP — RAG híbrido (Cloud)")
    print("═" * 50 + "\n")

    if not QDRANT_URL or not QDRANT_API_KEY or not GOOGLE_API_KEY:
        raise ValueError("Faltan variables de entorno. Verifica tu .env")

    vectorstore      = load_vectorstore()
    chain, retriever = build_rag_chain(vectorstore)

    query(chain, retriever, "Cuántos equipos de cómputo tiene Colombia Compra Eficiente")
    query(chain, retriever, "Qué software tiene licenciado la entidad y con qué proveedores")
