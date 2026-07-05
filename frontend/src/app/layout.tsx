import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Noor AI — Your Light to Islamic Knowledge",
  description:
    "Ask questions about Islamic rulings, Quran, Hadith, and scholarly opinions.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 min-h-screen">{children}</body>
    </html>
  );
}
