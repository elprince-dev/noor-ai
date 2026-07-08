import type { Metadata, Viewport } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";
import { SettingsProvider } from "@/components/SettingsProvider";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const playfair = Playfair_Display({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Noor AI — Your Light to Islamic Knowledge",
  description:
    "Ask questions about Islamic rulings, Quran, Hadith, and scholarly opinions across the four madhabs.",
  keywords: [
    "Islam",
    "Islamic Q&A",
    "Quran",
    "Hadith",
    "Fiqh",
    "Madhab",
    "Fatwa",
  ],
  openGraph: {
    title: "Noor AI — Your Light to Islamic Knowledge",
    description:
      "Ask questions about Islamic rulings, Quran, Hadith, and scholarly opinions.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#04060D",
  width: "device-width",
  initialScale: 1,
};

// Runs before React hydrates so the correct theme/direction is applied on the
// very first paint — prevents a flash of the wrong theme or LTR/RTL flip.
const noFlashScript = `
(function () {
  try {
    var t = localStorage.getItem('noor.theme');
    if (!t) {
      t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    var l = localStorage.getItem('noor.lang') || 'en';
    var h = document.documentElement;
    h.classList.remove('dark', 'light');
    h.classList.add(t);
    h.setAttribute('lang', l);
    h.setAttribute('dir', l === 'ar' ? 'rtl' : 'ltr');
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" dir="ltr" className={`${inter.variable} ${playfair.variable} dark`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: noFlashScript }} />
      </head>
      <body className="min-h-screen antialiased">
        <SettingsProvider>{children}</SettingsProvider>
      </body>
    </html>
  );
}