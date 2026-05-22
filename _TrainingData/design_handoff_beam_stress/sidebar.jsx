// Sidebar — faithful to the original layout, refined typography
const { useState } = React;

function SbIcon({ name }) {
  const props = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };
  switch (name) {
    case "load":
      return <svg {...props}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 4v16M3 9h4M3 14h4" /></svg>;
    case "material":
      return <svg {...props}><path d="M12 2l8 4.5v9L12 20l-8-4.5v-9L12 2z" /><path d="M12 11l8-4.5M12 11v9M12 11L4 6.5" /></svg>;
    case "section":
      return <svg {...props}><path d="M3 12h18M12 3v18" strokeDasharray="2 3" /><rect x="6" y="8" width="12" height="8" /></svg>;
    case "load-app":
      return <svg {...props}><path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z" /></svg>;
    case "caret":
      return <svg {...props}><path d="M9 18l6-6-6-6" /></svg>;
    default: return null;
  }
}

function Stepper({ value, step = 0.5, decimals = 4 }) {
  const [v, setV] = useState(value);
  const update = (delta) => setV((x) => Math.max(0, +(x + delta).toFixed(decimals)));
  return (
    <div className="sb__stepper">
      <input className="mono" value={v.toFixed(decimals)} onChange={(e) => {
        const n = parseFloat(e.target.value);
        if (!isNaN(n)) setV(n);
      }} />
      <button onClick={() => update(-step)} aria-label="decrement">−</button>
      <button onClick={() => update(step)} aria-label="increment">+</button>
    </div>
  );
}

function SbSection({ icon, title, children }) {
  return (
    <div className="sb__section">
      <div className="sb__section-header">
        <SbIcon name={icon} />
        <span>{title}</span>
      </div>
      {children}
    </div>
  );
}

function Sidebar() {
  return (
    <aside className="sb">
      <div className="sb__topbar">
        <button className="sb__collapse" title="Collapse">«</button>
      </div>

      <a className="sb__nav-item" href="#">Home</a>
      <a className="sb__nav-item is-active" href="#">Beam Section Stress</a>
      <a className="sb__nav-item" href="#">Joint Analysis</a>
      <a className="sb__nav-item" href="#">Fastener Group</a>

      <SbSection icon="load" title="Load Case">
        <label className="sb__label">Load Case ID</label>
        <input className="sb__input mono" defaultValue="LC-01" />
        <label className="sb__label">Analyst</label>
        <input className="sb__input" placeholder="J. Doe" />
        <label className="sb__label">Project / Component</label>
        <input className="sb__input" placeholder="Wing rib W-14" />
      </SbSection>

      <SbSection icon="material" title="Material">
        <label className="sb__label">Material</label>
        <div className="sb__stepper" style={{ gridTemplateColumns: "1fr 28px" }}>
          <input className="mono" defaultValue="2024-T3 Sheet" readOnly />
          <button>▾</button>
        </div>

        <div className="sb__row" style={{ marginTop: 10 }}>
          <div>
            <label className="sb__label">SF Yield</label>
            <Stepper value={1.00} step={0.05} decimals={2} />
          </div>
          <div>
            <label className="sb__label">SF Ult</label>
            <Stepper value={1.50} step={0.05} decimals={2} />
          </div>
        </div>

        <div className="sb__disclosure">
          <SbIcon name="caret" />
          <span>Material allowables</span>
        </div>
      </SbSection>

      <SbSection icon="section" title="Cross-Section">
        <label className="sb__label">Section Shape</label>
        <div className="sb__stepper" style={{ gridTemplateColumns: "1fr 28px" }}>
          <input className="mono" defaultValue="Rectangle" readOnly />
          <button>▾</button>
        </div>

        <label className="sb__label">b — Width (in)</label>
        <Stepper value={4.0} step={0.5} decimals={4} />
        <label className="sb__label">h — Height (in)</label>
        <Stepper value={2.0} step={0.5} decimals={4} />
      </SbSection>

      <SbSection icon="load-app" title="Applied Loads">
        <label className="sb__label">P — Axial (lb)</label>
        <Stepper value={1500} step={100} decimals={1} />
        <div className="sb__row" style={{ marginTop: 10 }}>
          <div>
            <label className="sb__label">Vy (lb)</label>
            <Stepper value={500} step={100} decimals={1} />
          </div>
          <div>
            <label className="sb__label">Vz (lb)</label>
            <Stepper value={500} step={100} decimals={1} />
          </div>
        </div>
        <div className="sb__row" style={{ marginTop: 10 }}>
          <div>
            <label className="sb__label">My (in·lb)</label>
            <Stepper value={1000} step={100} decimals={1} />
          </div>
          <div>
            <label className="sb__label">Mz (in·lb)</label>
            <Stepper value={500} step={100} decimals={1} />
          </div>
        </div>
      </SbSection>
    </aside>
  );
}

window.Sidebar = Sidebar;
