import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Noto_Sans, Noto_Sans_Devanagari } from "next/font/google";
import "./globals.css";

const bricolage = Bricolage_Grotesque({ variable: "--font-bricolage", subsets: ["latin"] });
const noto = Noto_Sans({ variable: "--font-noto", subsets: ["latin"] });
const notoDeva = Noto_Sans_Devanagari({ variable: "--font-noto-deva", subsets: ["devanagari"] });

export const metadata: Metadata = {
  title: "WorthyWaste",
  description: "Your scrap is your credit score.",
};

export const viewport: Viewport = {
  themeColor: "#1E7F4F",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${bricolage.variable} ${noto.variable} ${notoDeva.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
