"use client";

import { useState, FormEvent, KeyboardEvent } from "react";

interface Props {
  onSearch: (question: string) => void;
  loading: boolean;
}

const EXAMPLES = [
  "Licitaciones de equipos de cómputo en Medellín",
  "Contratos de mantenimiento de software en Antioquia",
  "Estudios previos de consultoría tecnológica con presupuesto mayor a 100 millones",
  "Invitaciones públicas de servicios de telecomunicaciones",
];

export default function SearchBox({ onSearch, loading }: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = value.trim();
    if (q) onSearch(q);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const q = value.trim();
      if (q && !loading) onSearch(q);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
      <form onSubmit={handleSubmit} className="space-y-3">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          placeholder="Ej: licitaciones de software o servicios de TI en Antioquia con presupuesto mayor a 50 millones…"
          className="w-full border border-gray-300 rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f] focus:border-transparent resize-none leading-relaxed"
          disabled={loading}
        />
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-gray-400">
            Enter para buscar · Shift+Enter para nueva línea
          </p>
          <button
            type="submit"
            disabled={loading || !value.trim()}
            className="bg-[#1e3a5f] text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-[#16304f] transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {loading ? "Buscando…" : "Buscar licitaciones"}
          </button>
        </div>
      </form>

      {/* Quick examples */}
      <div className="mt-4 pt-4 border-t border-gray-100">
        <p className="text-xs text-gray-400 mb-2">Prueba con:</p>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => {
                setValue(ex);
                if (!loading) onSearch(ex);
              }}
              disabled={loading}
              className="text-xs bg-blue-50 text-[#1e3a5f] px-3 py-1.5 rounded-full hover:bg-blue-100 transition-colors disabled:opacity-40 text-left"
            >
              {ex}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
