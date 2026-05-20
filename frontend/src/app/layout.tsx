import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "SECOP Inteligente — Buscador de Licitaciones para PYMES",
  description:
    "Encuentra licitaciones públicas colombianas con inteligencia artificial. Búsqueda semántica sobre SECOP II orientada a pequeñas y medianas empresas.",
  keywords: ["SECOP", "licitaciones", "Colombia", "PYMES", "contratación pública", "RAG"],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <body className={inter.className}>{children}</body>
    </html>
  );
}
