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
            Know the date.
            <br />
            <span>See the proof.</span>
          </h1>
        </div>
        <p className="hero-copy">
          Kabtak searches reviewed public sources, separates student deadlines
          from institution deadlines, and links every conclusion back to evidence.
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
