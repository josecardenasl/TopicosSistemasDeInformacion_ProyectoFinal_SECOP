import { Source, QueryResult } from "@/app/page";

interface Props {
  result: QueryResult;
  query: string;
}

function cleanFilename(filename: string): string {
  return filename
    .replace(/\.pdf$/i, "")
    .replace(/[_-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export default function ResultDisplay({ result, query }: Props) {
  /* Deduplicate sources keeping order */
  const seen = new Set<string>();
  const uniqueSources: Source[] = [];
  for (const s of result.sources) {
    const key = `${s.filename}:${s.page}`;
    if (!seen.has(key)) {
      seen.add(key);
      uniqueSources.push(s);
    }
  }

  const uniqueDocs = Array.from(
    new Map(result.sources.map((s) => [s.filename, s])).values()
  );

  return (
    <div className="space-y-4">
      {/* ── Answer card ── */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        {/* Card header */}
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <span className="text-[#1e3a5f] font-semibold text-sm">Respuesta del asistente</span>
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
              Gemini 2.5 Flash · RAG híbrido
            </span>
          </div>
          <p className="text-xs text-gray-400 italic truncate max-w-xs">
            «{query}»
          </p>
        </div>

        {/* Answer body */}
        <div className="px-6 py-5">
          <p className="text-gray-800 text-sm leading-relaxed answer-text">
            {result.answer}
          </p>
        </div>
      </div>

      {/* ── Sources card ── */}
      {uniqueSources.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h3 className="text-sm font-semibold text-[#1e3a5f] mb-4 flex items-center gap-2">
            <span>📄</span>
            <span>
              Fragmentos consultados ({uniqueSources.length})
              <span className="font-normal text-gray-400 ml-1">
                · {uniqueDocs.length} {uniqueDocs.length === 1 ? "documento" : "documentos"}
              </span>
            </span>
          </h3>

          <ul className="space-y-2.5">
            {uniqueSources.map((s, i) => (
              <li
                key={i}
                className="flex items-start gap-3 text-xs"
              >
                <span className="text-gray-300 font-mono text-xs w-5 shrink-0 mt-0.5">
                  {i + 1}.
                </span>
                <span>
                  <span className="font-medium text-gray-800">
                    {cleanFilename(s.filename)}
                  </span>
                  <span className="text-gray-400 ml-1.5">— pág. {s.page}</span>
                </span>
              </li>
            ))}
          </ul>

          <p className="text-xs text-gray-400 mt-4 pt-4 border-t border-gray-100">
            Documentos recuperados del vector store Qdrant Cloud (colección{" "}
            <code className="font-mono text-xs">secop_licitaciones</code>).
            Los PDFs son públicos y provienen de SECOP II — Colombia Compra Eficiente.
          </p>
        </div>
      )}
    </div>
  );
}
