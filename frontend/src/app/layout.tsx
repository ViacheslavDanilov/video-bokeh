import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

// Geist Sans and Geist Mono, per DESIGN.md. The `geist` package is Vercel's own and
// ships the fonts only — there is no public Vercel component library, so the look
// comes from the tokens in globals.css rather than from anything installed.

export const metadata: Metadata = {
  title: "Video Bokeh",
  description:
    "Generate a synthetic scene from the mounted asset library and compare its streams.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="flex min-h-full flex-col" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
