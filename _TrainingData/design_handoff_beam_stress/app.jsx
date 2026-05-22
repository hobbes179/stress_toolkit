// Main app — header, stress summary, diagram, KP table, material panel, MS callout, tweaks
const { useState: useStateMain, useEffect: useEffectMain, useMemo } = React;

// ---------- Data model ----------
const STRESSES = [
  { key: "s1",   name: "Max σ₁",       sym: "σ₁", desc: "Principal (tensile)", value:  0.3971, allow: 42.0, allowKey: "Fty", kind: "tension" },
  { key: "s3",   name: "Min σ₃",       sym: "σ₃", desc: "Principal (compressive)", value: -0.3971, allow: 40.0, allowKey: "Fcy", kind: "compression" },
  { key: "vm",   name: "Max σ_vm",     sym: "σᵥₘ", desc: "Von Mises",   value:  0.4086, allow: 42.0, allowKey: "Fty", kind: "vm" },
  { key: "tau",  name: "Max τ",        sym: "τ", desc: "Total shear", value:  0.0938, allow: 37.0, allowKey: "Fsu", kind: "shear" },
  { key: "bend", name: "Max σ_bend",   sym: "σ_b", desc: "Bending fiber", value:  0.3750, allow: 42.0, allowKey: "Fty", kind: "bending" },
];

const MATERIAL = {
  name: "2024-T3 Sheet",
  spec: "AMS-QQ-A-250/4",
  temper: "T3 · 0.040–0.249 in",
  rows: [
    { k: "Fty",  v: 42.0, u: "ksi", d: "Tensile yield" },
    { k: "Ftu",  v: 62.0, u: "ksi", d: "Tensile ultimate" },
    { k: "Fcy",  v: 40.0, u: "ksi", d: "Compressive yield" },
    { k: "Fsu",  v: 37.0, u: "ksi", d: "Shear ultimate" },
    { k: "E",    v: 10.5, u: "Msi", d: "Young's modulus" },
    { k: "ν",    v: 0.33, u: "",    d: "Poisson's ratio" },
  ],
};

// Stress at each KP for a rectangle under combined load (illustrative values)
const KP_STRESSES = [
  { id: "A", desc: "Top fiber — mid",      y:  0.0000, z:  1.0000, sigma:  0.3750, vm: 0.3760, shear: 0.0188, gov: false },
  { id: "B", desc: "Bot fiber — mid",      y:  0.0000, z: -1.0000, sigma: -0.3750, vm: 0.3760, shear: 0.0188, gov: false },
  { id: "C", desc: "Right fiber — mid",    y:  2.0000, z:  0.0000, sigma:  0.1875, vm: 0.1900, shear: 0.0938, gov: false },
  { id: "D", desc: "Left fiber — mid",     y: -2.0000, z:  0.0000, sigma: -0.1875, vm: 0.1900, shear: 0.0938, gov: false },
  { id: "E", desc: "Top-right corner",     y:  2.0000, z:  1.0000, sigma:  0.3971, vm: 0.4086, shear: 0.0094, gov: true },
  { id: "F", desc: "Top-left corner",      y: -2.0000, z:  1.0000, sigma:  0.1875, vm: 0.2010, shear: 0.0094, gov: false },
  { id: "G", desc: "Bot-right corner",     y:  2.0000, z: -1.0000, sigma:  0.1875, vm: 0.2010, shear: 0.0094, gov: false },
  { id: "H", desc: "Bot-left corner",      y: -2.0000, z: -1.0000, sigma: -0.3971, vm: 0.4086, shear: 0.0094, gov: false },
  { id: "I", desc: "Centroid",             y:  0.0000, z:  0.0000, sigma:  0.0000, vm: 0.0188, shear: 0.0938, gov: false },
];

const GOVERNING_KP = "E";

// ---------- Helpers ----------
function fmt(n, d = 4) {
  if (n === 0) return (0).toFixed(d);
  return n.toFixed(d);
}
function statusFor(util) {
  if (util > 0.9) return "critical";
  if (util > 0.5) return "caution";
  return "safe";
}
function statusLabel(s) {
  return { safe: "Safe", caution: "Watch", critical: "Critical" }[s] || s;
}

// ---------- Stress card ----------
function StressCard({ s }) {
  const util = Math.abs(s.value) / s.allow; // 0..1
  const status = statusFor(util);
  const pct = (util * 100);
  const ms = s.allow / Math.abs(s.value) - 1;
  return (
    <div className="stress-card">
      <div className="stress-card__label">
        <span className="stress-card__name">{s.name}</span>
        <span className={`badge ${status}`}>{statusLabel(status)}</span>
      </div>
      <div className="stress-card__val">
        <span className="num">
          {s.value < 0 ? <span className="sign">−</span> : null}
          {Math.abs(s.value).toFixed(4)}
        </span>
        <span className="unit">ksi</span>
      </div>
      <div className="stress-card__util">
        <div className="util-row">
          <span>{s.desc}</span>
          <b>{pct.toFixed(2)}% of {s.allowKey}</b>
        </div>
        <div className="util-bar">
          <div className={`util-bar__fill is-${status}`} style={{ width: Math.min(100, pct) + "%" }} />
        </div>
        <div className="util-row">
          <span>Margin of Safety</span>
          <b className="mono">MS = {ms > 99 ? "+∞" : "+" + ms.toFixed(1)}</b>
        </div>
      </div>
    </div>
  );
}

// ---------- Material panel ----------
function MaterialPanel() {
  return (
    <aside className="mat-panel">
      <div className="mat-panel__header">
        <div>
          <div className="mat-panel__title">Material allowables</div>
          <div className="mat-panel__name">{MATERIAL.name}</div>
        </div>
      </div>
      <div className="mat-rule" />
      {MATERIAL.rows.map((r) => (
        <div className="mat-row" key={r.k}>
          <div className="mat-row__key">{r.k}</div>
          <div className="mat-row__desc">{r.d}</div>
          <div className="mat-row__val">{r.v.toFixed(r.u === "" ? 2 : 1)}<small>{r.u}</small></div>
        </div>
      ))}
      <div style={{ padding: "10px 16px", borderTop: "1px solid var(--rule)", fontSize: 10,
        fontFamily: "IBM Plex Mono, monospace", color: "var(--ink-3)", letterSpacing: "0.05em" }}>
        SRC <b style={{ color: "var(--ink-2)" }}>MMPDS-01 · A-Basis</b> · {MATERIAL.temper}
      </div>
    </aside>
  );
}

// ---------- Tabs ----------
function ViewTabs({ tab, setTab }) {
  return (
    <div className="tabs">
      <button className={`tab ${tab === "diagram" ? "is-active" : ""}`} onClick={() => setTab("diagram")}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M3 21h18M3 21V8l9-5 9 5v13" /><path d="M9 21V12h6v9" />
        </svg>
        Section Diagram
      </button>
      <button className={`tab ${tab === "contour" ? "is-active" : ""}`} onClick={() => setTab("contour")}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1.5" />
        </svg>
        Stress Contour
      </button>
      <button className={`tab ${tab === "table" ? "is-active" : ""}`} onClick={() => setTab("table")}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <rect x="3" y="3" width="18" height="18" /><path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
        </svg>
        Full Report
      </button>
    </div>
  );
}

// ---------- Stress Contour (simple heatmap of σ over section) ----------
function StressContour() {
  // Generate a grid of σ_bend = My*z/Iy + Mz*y/Iz for illustration
  const b = 4, h = 2;
  const Iy = b * h * h * h / 12;
  const Iz = h * b * b * b / 12;
  const My = 1000, Mz = 500;
  const cols = 40, rows = 20;
  const cells = [];
  let smin = Infinity, smax = -Infinity;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const y = -b / 2 + (c + 0.5) * b / cols;
      const z =  h / 2 - (r + 0.5) * h / rows;
      const s = (My * z / Iy + Mz * y / Iz) / 1000; // ksi
      cells.push({ r, c, y, z, s });
      if (s < smin) smin = s;
      if (s > smax) smax = s;
    }
  }
  const colorFor = (s) => {
    const t = (s - smin) / (smax - smin); // 0..1
    // cool (compression) -> neutral -> warm (tension)
    if (t < 0.5) {
      const u = t / 0.5;
      const r = Math.round(29 + (245 - 29) * u);
      const g = Math.round(78 + (243 - 78) * u);
      const bl = Math.round(216 + (238 - 216) * u);
      return `rgb(${r},${g},${bl})`;
    } else {
      const u = (t - 0.5) / 0.5;
      const r = Math.round(245 + (179 - 245) * u);
      const g = Math.round(243 + (35 - 243) * u);
      const bl = Math.round(238 + (28 - 238) * u);
      return `rgb(${r},${g},${bl})`;
    }
  };

  const W = 720, H = 380, padL = 60, padR = 30, padT = 30, padB = 50;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const cw = innerW / cols, ch = innerH / rows;

  return (
    <svg className="diagram-svg" viewBox={`0 0 ${W} ${H}`}>
      {/* contour cells */}
      {cells.map((c) => (
        <rect key={`${c.r}-${c.c}`} x={padL + c.c * cw} y={padT + c.r * ch}
          width={cw + 0.5} height={ch + 0.5} fill={colorFor(c.s)} />
      ))}
      {/* outline */}
      <rect x={padL} y={padT} width={innerW} height={innerH}
        fill="none" stroke="var(--ink-2)" strokeWidth="1.5" />

      {/* legend */}
      <g transform={`translate(${padL}, ${H - 26})`}>
        <text x="0" y="0" fontFamily="IBM Plex Mono" fontSize="10" fill="var(--ink-3)">σ (ksi)</text>
        {Array.from({ length: 30 }).map((_, i) => {
          const t = i / 29;
          const s = smin + (smax - smin) * t;
          return <rect key={i} x={50 + i * 6} y="-9" width="6" height="10" fill={colorFor(s)} />;
        })}
        <text x="50" y="16" fontFamily="IBM Plex Mono" fontSize="9" fill="var(--ink-3)">{smin.toFixed(3)}</text>
        <text x="230" y="16" fontFamily="IBM Plex Mono" fontSize="9" fill="var(--ink-3)" textAnchor="end">{smax.toFixed(3)}</text>
      </g>
    </svg>
  );
}

// ---------- KP table ----------
function KPTable() {
  return (
    <table className="kp-table">
      <thead>
        <tr>
          <th>KP</th>
          <th>Description</th>
          <th className="num">y (in)</th>
          <th className="num">z (in)</th>
          <th className="num">σ (ksi)</th>
          <th className="num">σᵥₘ (ksi)</th>
          <th className="num">τ (ksi)</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {KP_STRESSES.map((r) => {
          const util = r.vm / 42.0;
          const status = statusFor(util);
          return (
            <tr key={r.id}>
              <td><span className={`kp-chip ${r.gov ? "governing" : ""}`}>{r.id}</span></td>
              <td className={r.gov ? "gov" : ""}>{r.desc}</td>
              <td className="num">{fmt(r.y, 4)}</td>
              <td className="num">{fmt(r.z, 4)}</td>
              <td className="num" style={{ color: r.sigma < 0 ? "var(--critical)" : "var(--ink-2)" }}>
                {r.sigma < 0 ? "−" : ""}{Math.abs(r.sigma).toFixed(4)}
              </td>
              <td className="num">{r.vm.toFixed(4)}</td>
              <td className="num">{r.shear.toFixed(4)}</td>
              <td><span className={`badge ${status}`}>{statusLabel(status)}</span></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ---------- App ----------
function App() {
  const [tw, setTweak] = useTweaks(window.__TWEAK_DEFAULTS);
  const [tab, setTab] = useStateMain("diagram");

  // apply theme/density attrs
  useEffectMain(() => {
    document.documentElement.setAttribute("data-theme", tw.theme || "hybrid");
    document.documentElement.setAttribute("data-density", tw.density || "comfortable");
    document.documentElement.style.setProperty("--accent", tw.accent || "#1d4ed8");
    document.documentElement.style.setProperty("--section", tw.accent || "#1d4ed8");
  }, [tw.theme, tw.density, tw.accent]);

  // Governing MS (min across all)
  const ms = useMemo(() => {
    let min = Infinity, key = null;
    STRESSES.forEach((s) => {
      const m = s.allow / Math.abs(s.value) - 1;
      if (m < min) { min = m; key = s; }
    });
    return { min, key };
  }, []);

  return (
    <div className="app">
      <Sidebar />

      <main className="canvas">
        {/* Top bar */}
        <div className="topbar">
          <div className="breadcrumb">
            <span>Aerostructures</span> <span style={{ opacity: 0.4 }}>/</span> <span>Stress Tools</span> <span style={{ opacity: 0.4 }}>/</span> <b>Beam Section Stress</b>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="badge safe" style={{ fontSize: 10 }}>● Saved 2 min ago</span>
            <button className="deploy-btn">Run Analysis</button>
          </div>
        </div>

        {/* Page header */}
        <header className="header">
          <div>
            <h1>Beam Section Stress <span className="sub">— rectangular cross-section</span></h1>
            <div className="header__meta">
              <span><b>LC-01</b></span>
              <span>Linear-elastic</span>
              <span>IPS units</span>
              <span>MMPDS-01 allowables</span>
              <span>X = beam axis</span>
              <span>Y = horiz. right</span>
              <span>Z = vert. up</span>
            </div>
          </div>
          <div className="stamp">
            <div className="stamp__row"><span className="k">Analyst</span><span className="v">— —</span></div>
            <div className="stamp__row"><span className="k">Rev</span><span className="v">A · 2026-05-20</span></div>
            <div className="stamp__row"><span className="k">Status</span><span className="v" style={{ color: "var(--safe)" }}>Released</span></div>
          </div>
        </header>

        {/* Stress summary */}
        <div className="section-h">
          <span className="section-h__num">01</span>
          <h2 className="section-h__title">Governing Stress Summary</h2>
          <span className="section-h__desc">extreme-fiber results across the section</span>
        </div>

        <div className="stress-grid">
          {STRESSES.map((s) => <StressCard key={s.key} s={s} />)}
        </div>

        {/* Margin of Safety callout */}
        {tw.showMS ? (
          <div className="ms-callout">
            <div>
              <div className="ms-callout__label">Min. Margin of Safety</div>
              <div className="ms-callout__val">+{ms.min.toFixed(1)}</div>
            </div>
            <div className="ms-callout__desc">
              Governing: <b>{ms.key.name}</b> at KP <b>{GOVERNING_KP}</b> — {Math.abs(ms.key.value).toFixed(4)} ksi vs {ms.key.allow.toFixed(1)} ksi <b>{ms.key.allowKey}</b>.
              <br />
              <span style={{ color: "var(--ink-3)", fontSize: 12 }}>All applied factors of safety satisfied. Structure has substantial reserve.</span>
            </div>
            <div className="ms-callout__status">
              <div className="badge safe" style={{ fontSize: 11, padding: "5px 10px" }}>● Pass · Released</div>
            </div>
          </div>
        ) : null}

        {/* Diagram + Material */}
        <div className="section-h">
          <span className="section-h__num">02</span>
          <h2 className="section-h__title">Section Geometry &amp; Key Points</h2>
          <span className="section-h__desc">KP positions and per-fiber stress</span>
        </div>

        <div className="work-grid">
          <div>
            <ViewTabs tab={tab} setTab={setTab} />
            <div className="diagram-card">
              <div className="diagram-header">
                <div className="diagram-header__title">Rectangle · b=4.00 × h=2.00 in</div>
                <div className="diagram-header__props">
                  <span>A = <b>8.0000</b> in²</span>
                  <span>Iy = <b>2.6667</b> in⁴</span>
                  <span>Iz = <b>10.6667</b> in⁴</span>
                  <span>Sy = <b>2.6667</b> in³</span>
                </div>
              </div>

              {tab === "diagram" ? (
                <SectionDiagram b={4} h={2} governing={GOVERNING_KP} accent={tw.accent || "#1d4ed8"} />
              ) : tab === "contour" ? (
                <StressContour />
              ) : (
                <div style={{ padding: 40, textAlign: "center", color: "var(--ink-3)" }}>
                  Full PDF report — generated on Run.
                </div>
              )}

              <KPTable />
            </div>
          </div>

          <MaterialPanel />
        </div>

        <hr className="rule" />
        <div style={{ display: "flex", justifyContent: "space-between", color: "var(--ink-3)",
          fontFamily: "IBM Plex Mono, monospace", fontSize: 11, letterSpacing: "0.04em" }}>
          <span>BEAM-STRESS · v2.4.1 · MMPDS-01 · IPS</span>
          <span>© 2026 · Linear-elastic only · Not for buckling, fatigue, or non-linear analysis</span>
        </div>

        {/* Tweaks */}
        <TweaksPanel title="Tweaks">
          <TweakSection label="Theme">
            <TweakRadio label="Mode" value={tw.theme}
              options={[
                { value: "hybrid", label: "Hybrid" },
                { value: "dark",   label: "Dark" },
                { value: "light",  label: "Light" },
              ]}
              onChange={(v) => setTweak("theme", v)} />
            <TweakRadio label="Density" value={tw.density}
              options={[
                { value: "comfortable", label: "Comfortable" },
                { value: "compact",     label: "Compact" },
              ]}
              onChange={(v) => setTweak("density", v)} />
            <TweakColor label="Accent" value={tw.accent}
              options={["#1d4ed8", "#0b6e6e", "#7a2f8f", "#b35a00"]}
              onChange={(v) => setTweak("accent", v)} />
          </TweakSection>
          <TweakSection label="Page">
            <TweakToggle label="Show MS callout" value={tw.showMS}
              onChange={(v) => setTweak("showMS", v)} />
          </TweakSection>
        </TweaksPanel>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
