import type { Metadata } from "next";

import { LinkCheckForm } from "@/components/link-check-form";

export const metadata: Metadata = {
  title: "Check any official scholarship link — Kabtak",
  description: "Analyse one public scholarship notice with guarded retrieval and preserved evidence.",
};

export default function LinkCheckPage() {
  return (
    <main className="page-shell link-check-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">P1 feature / released</p>
          <h1>Bring the notice. Keep the proof.</h1>
          <p>
            Paste a public notice from a scholarship publisher or institution. Kabtak will read
            that source, test the requested scope, and cite the exact passage behind its result.
          </p>
        </div>
      </section>
      <LinkCheckForm />
    </main>
  );
}
