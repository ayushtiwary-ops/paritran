import { Legend } from "./labels";
import { LiveSeedPanel } from "./LiveSeedPanel";

// Shell for the hosted interactive solution (SPEC_HOSTED_APP.md Section 1).
// S0 header + legend + above-the-fold LIVE entry, S1 recorded-tour zone
// (the recorded REPLAY panels mount here once the seed-42 capture is committed;
// the numbers listed are the frozen seed-42 values a judge can reproduce live
// below), S2 the LIVE Judge's-seed panel, S3 footer.
export function ReplayApp() {
  return (
    <div className="app">
      <header className="site-header">
        <div className="container">
          <div className="brand serif">Paritran</div>
          <div className="tagline">From complaint to conviction. Interactive demonstration.</div>
          <Legend />
          <p className="legend-subline">
            Every number on this page traces to the frozen <code>results.json</code>, to the recorded run, or is
            computed live in front of you.
          </p>
          <a className="jump-live" href="#live">
            Run the real engine in your browser
          </a>
        </div>
      </header>

      <main className="container">
        <section className="zone" aria-labelledby="replay-heading">
          <h2 id="replay-heading">Recorded tour of the full on-premise stack</h2>
          <p className="zone-lead">
            The five-beat tour is captured from a real seed-42 run of the complete docker stack on the demo machine and
            mounts here as a REPLAY once its capture is committed. The unique proof of this page is the live in-browser
            rerun, which already works now: skip straight to it.
          </p>
          <ol className="beat-list">
            <li>
              <b>Intake.</b> 297 synthetic complaints stream in. Zero real PII.
            </li>
            <li>
              <b>Collapse.</b> 297 complaints resolve into 6 mule networks. Linkage F1 0.962.
            </li>
            <li>
              <b>Money trail.</b> 90.8% of complaint value traced to cash-out by directed-graph reachability.
            </li>
            <li>
              <b>Packet and F9.</b> 50 claims checked, 40 passed, 10 stub fabrications withheld, 0 leaked.
            </li>
            <li>
              <b>Custody and tamper.</b> A 12-record SHA-256 chain; tampering with one record breaks the chain there.
            </li>
          </ol>
        </section>

        <section className="zone" id="live" aria-labelledby="live-heading">
          <h2 id="live-heading">Run the real engine in your browser</h2>
          <LiveSeedPanel />
        </section>
      </main>

      <footer className="site-footer">
        <div className="container">
          <p className="footer-scope">
            No accounts, no server, no stored data: Paritran runs on-premise inside the Crime Branch by design, so this
            page demonstrates the same engine and a recording of the same stack without any server at all. The engine
            runs where the data lives, here, that is your device.
          </p>
          <nav className="footer-links">
            <a href="https://github.com/ayushtiwary-ops/paritran">Repository</a>
            <a href="../demo.html">Demo video</a>
            <a href="https://github.com/ayushtiwary-ops/paritran/blob/main/docs/Paritran_White_Paper.pdf">
              White paper
            </a>
            <a href="https://github.com/ayushtiwary-ops/paritran/blob/main/Paritran_Solution_Document.pdf">
              Solution document
            </a>
          </nav>
          <p className="footer-meta mono">PS-69EEFE4F8CD1C. Team: Ayush Tiwary, Aditya Arora.</p>
        </div>
      </footer>
    </div>
  );
}
