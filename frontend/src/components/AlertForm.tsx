"use client";

import { useState, FormEvent } from "react";

interface Props {
  criteria: string;
  apiUrl: string;
}

type Status = "idle" | "loading" | "success" | "error";

export default function AlertForm({ criteria, apiUrl }: Props) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setStatus("loading");
    setErrorMsg("");

    try {
      const res = await fetch(`${apiUrl}/alert`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, criteria }),
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail?.detail ?? `Error ${res.status}`);
      }

      setStatus("success");
    } catch (err: unknown) {
      setStatus("error");
      setErrorMsg(
        err instanceof Error ? err.message : "No se pudo registrar la alerta."
      );
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full py-3.5 border-2 border-dashed border-amber-400 rounded-xl text-amber-600 text-sm font-medium hover:bg-amber-50 transition-colors flex items-center justify-center gap-2"
      >
        <span>🔔</span>
        <span>Recibir alerta por correo cuando haya nuevas licitaciones que coincidan</span>
      </button>
    );
  }

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 space-y-4">
      <div>
        <h3 className="font-semibold text-gray-800 text-sm flex items-center gap-2">
          <span>🔔</span> Registrar alerta por correo
        </h3>
        <p className="text-xs text-gray-500 mt-1.5 leading-relaxed">
          Recibirás un email con los resultados actuales y serás notificado cuando
          aparezcan nuevas licitaciones para:
        </p>
        <div className="mt-2 bg-white border border-amber-200 rounded-lg px-4 py-2.5">
          <p className="text-xs text-amber-800 italic">«{criteria}»</p>
        </div>
      </div>

      {status === "success" ? (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex gap-3 items-start">
          <span className="text-green-600 text-lg leading-none">✅</span>
          <div>
            <p className="text-green-800 text-sm font-medium">¡Alerta registrada!</p>
            <p className="text-green-600 text-xs mt-0.5">
              Revisa tu correo. Te enviamos los resultados actuales y te notificaremos
              cuando haya nuevas coincidencias.
            </p>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="flex gap-3">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="tu@correo.com"
              required
              disabled={status === "loading"}
              className="flex-1 border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-transparent disabled:bg-gray-50"
            />
            <button
              type="submit"
              disabled={status === "loading" || !email.trim()}
              className="bg-amber-500 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-amber-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
            >
              {status === "loading" ? "Registrando…" : "Registrar alerta"}
            </button>
          </div>

          {status === "error" && (
            <p className="text-red-600 text-xs flex gap-1 items-center">
              <span>⚠️</span>
              <span>{errorMsg || "Error al registrar. Intenta de nuevo."}</span>
            </p>
          )}

          <p className="text-xs text-gray-400">
            Solo usamos tu correo para enviarte resultados de esta búsqueda. Sin spam.
          </p>
        </form>
      )}
    </div>
  );
}
