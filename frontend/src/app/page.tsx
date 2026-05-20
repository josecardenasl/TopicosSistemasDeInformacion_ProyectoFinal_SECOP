"use client";

import { useState } from "react";
import SearchBox from "@/components/SearchBox";
import ResultDisplay from "@/components/ResultDisplay";
import AlertForm from "@/components/AlertForm";

export interface Source {
  filename: string;
  page: string | number;
}

export interface QueryResult {
  answer: string;
  sources: Source[];
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export default function Home() {
  const [result, setResult] = useState<QueryResult | null>(null);
  const [lastQuery, setLastQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async (question: string) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setLastQuery(question);

    try {
      const res = await fetch(`${API_URL}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail?.detail ?? `Error ${res.status}`);
      }

      const data: QueryResult = await res.json();
      setResult(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error desconocido";
      setError(
        msg.includes("fetch") || msg.includes("Failed")
          ? "No se pudo conectar con el servidor. El backend puede estar iniciando (puede tardar hasta 30 s en Render). Intenta de nuevo en unos segundos."
          : msg
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* ── Header ── */}
      <header className="bg-[#1e3a5f] text-white shadow-md">
        <div className="max-w-3xl mx-auto px-4 py-5 flex items-center gap-4">
          <span className="text-4xl" aria-hidden>🔍</span>
          <div>
            <h1 className="text-xl font-bold tracking-tight leading-tight">
              SECOP Inteligente
            </h1>
            <p className="text-blue-200 text-xs mt-0.5">
              Buscador semántico de licitaciones públicas para PYMES · Colombia
            </p>
          </div>
        </div>
      </header>

      {/* ── Main ── */}
      <main className="flex-1 max-w-3xl mx-auto w-full px-4 py-10 space-y-6">
        {/* Hero copy */}
        <div className="text-center space-y-2">
          <h2 className="text-2xl font-semibold text-gray-800">
            Encuentra oportunidades de contratación
          </h2>
          <p className="text-gray-500 text-sm max-w-lg mx-auto">
            Escribe tu consulta en lenguaje natural. El sistema usa RAG híbrido sobre
            documentos reales de SECOP II para encontrar y resumir los procesos más
            relevantes para tu empresa.
          </p>
        </div>

        {/* Search */}
        <SearchBox onSearch={handleSearch} loading={loading} />

        {/* Error */}
        {error && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm flex gap-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 text-gray-400 space-y-3">
            <div className="w-10 h-10 border-4 border-[#1e3a5f] border-t-transparent rounded-full animate-spin" />
            <p className="text-sm">Buscando en documentos SECOP II…</p>
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <>
            <ResultDisplay result={result} query={lastQuery} />
            <AlertForm criteria={lastQuery} apiUrl={API_URL} />
          </>
        )}
      </main>

      {/* ── Footer ── */}
      <footer className="border-t bg-white text-center text-xs text-gray-400 py-4 px-4">
        Proyecto académico · Tópicos de Sistemas de Información · EAFIT 2026 ·
        Datos: SECOP II – Colombia Compra Eficiente (dominio público)
      </footer>
    </div>
  );
}
