import type { Metadata } from "next";
import { DM_Mono, DM_Sans, Yatra_One } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const dmSans = DM_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
});

const dmMono = DM_Mono({
  variable: "--font-mono",
  weight: ["400", "500"],
  subsets: ["latin"],
});

const yatraOne = Yatra_One({
  variable: "--font-display",
  weight: "400",
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
      className={`${dmSans.variable} ${dmMono.variable} ${yatraOne.variable} h-full antialiased`}
    >
      <body>
        <div className="site-shell">
          <header className="masthead">
            <Link className="wordmark" href="/" aria-label="Kabtak home">
              <span className="wordmark-ticket" aria-hidden="true" />
              <span>Kabtak</span>
            </Link>
            <nav className="primary-nav" aria-label="Primary navigation">
              <Link href="/#check">New check</Link>
              <Link href="/discover">Discover</Link>
              <Link href="/examples">Examples</Link>
              <Link href="/saved">Saved</Link>
            </nav>
            <span className="phase-badge">Evidence first</span>
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
