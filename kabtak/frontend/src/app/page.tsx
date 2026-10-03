import { CheckExperience } from "@/components/check-experience";

export default function Home() {
  return (
    <main className="site-shell">
      <header className="masthead">
        <a className="wordmark" href="#top" aria-label="Kabtak home">
          KABTAK<span>.</span>
        </a>
        <p className="masthead-note">Deadline checks with receipts</p>
        <span className="phase-badge">PHASE 02</span>
      </header>

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
          from institution deadlines, and links every answer back to evidence.
        </p>
      </section>

      <CheckExperience />

      <footer className="footer">
        <span>KABTAK / LOCAL-FIRST</span>
        <span>VERIFY IMPORTANT DATES WITH THE SOURCE</span>
      </footer>
    </main>
  );
}
