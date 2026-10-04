import Link from "next/link";

import { CheckForm } from "@/components/check-form";

export default async function Home(props: PageProps<"/">) {
  const searchParams = await props.searchParams;
  const programme = typeof searchParams.programme === "string" ? searchParams.programme : undefined;
  return (
    <main>
      <section className="hero" id="top">
        <div>
          <p className="eyebrow">Scholarship deadline checker</p>
          <h1>
            Which date
            <br />
            is <span>yours?</span>
          </h1>
        </div>
        <p className="hero-copy">
          Scholarship notices often list several dates. Kabtak finds the one meant
          for you, keeps institution deadlines separate, and shows the proof.
          <span className="hero-links">
            <Link href="/discover">Browse the catalogue</Link>
            <Link href="/examples">Try an offline example</Link>
          </span>
        </p>
      </section>
      <CheckForm initialProgrammeId={programme} />
    </main>
  );
}
