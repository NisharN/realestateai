import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/nav";

export const metadata: Metadata = {
  title: "Dubai Real Estate AI - Ali",
  description: "AI-powered property assistant for Dubai real estate",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" dir="ltr">
      <body className="font-sans">
        <Nav />
        {children}
      </body>
    </html>
  );
}
