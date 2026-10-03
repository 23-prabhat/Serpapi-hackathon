import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Kabtak — Deadline checks with proof",
  description: "Check scholarship deadlines against reviewed sources and see the evidence.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body>
        <div className="site-shell">
          <header className="masthead">
            <Link className="wordmark" href="/" aria-label="Kabtak home">
              KABTAK<span>.</span>
            </Link>
            <nav className="primary-nav" aria-label="Primary navigation">
              <Link href="/discover">Discover</Link>
              <Link href="/examples">Examples</Link>
              <Link href="/saved">Saved</Link>
            </nav>
            <span className="phase-badge">PHASE 04</span>
          </header>
          {children}
          <footer className="footer">
            <span>KABTAK / LOCAL-FIRST</span>
            <span>VERIFY IMPORTANT DATES WITH THE ORIGINAL SOURCE</span>
          </footer>
        </div>
      </body>
    </html>
  );
}
