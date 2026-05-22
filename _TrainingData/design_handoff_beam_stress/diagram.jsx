// Section diagram — clean engineering drawing of the rectangle with KP markers
function SectionDiagram({ b = 4, h = 2, governing = "A", accent = "#1d4ed8" }) {
  // SVG canvas
  const W = 720, H = 380;
  const padL = 60, padR = 30, padT = 40, padB = 50;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  // Data range (square viewport in section coords)
  const range = 3.2;
  const sx = innerW / (2 * range);
  const sy = innerH / (2 * range);
  const scale = Math.min(sx, sy);
  const cx = padL + innerW / 2;
  const cy = padT + innerH / 2;
  const X = (y) => cx + y * scale;       // section y -> screen x
  const Y = (z) => cy - z * scale;       // section z -> screen y (inverted)

  // KPs around the rectangle (b along y, h along z)
  const hy = b / 2, hz = h / 2;
  const kps = [
    { id: "A", y: 0,    z:  hz,  desc: "Top fiber — mid" },
    { id: "B", y: 0,    z: -hz,  desc: "Bot fiber — mid" },
    { id: "C", y:  hy,  z: 0,    desc: "Right fiber — mid" },
    { id: "D", y: -hy,  z: 0,    desc: "Left fiber — mid" },
    { id: "E", y:  hy,  z:  hz,  desc: "Top-right corner" },
    { id: "F", y: -hy,  z:  hz,  desc: "Top-left corner" },
    { id: "G", y:  hy,  z: -hz,  desc: "Bot-right corner" },
    { id: "H", y: -hy,  z: -hz,  desc: "Bot-left corner" },
    { id: "I", y: 0,    z: 0,    desc: "Centroid" },
  ];

  const gridLines = [-3, -2, -1, 0, 1, 2, 3];

  return (
    <svg className="diagram-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
      <defs>
        <pattern id="dotgrid" x="0" y="0" width="10" height="10" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="0.6" fill="var(--rule)" opacity="0.4" />
        </pattern>
      </defs>

      {/* plot area background */}
      <rect x={padL} y={padT} width={innerW} height={innerH} fill="var(--bg-2)" />
      <rect x={padL} y={padT} width={innerW} height={innerH} fill="url(#dotgrid)" />

      {/* major grid */}
      {gridLines.map((g) => (
        <g key={"v" + g}>
          <line x1={X(g)} y1={padT} x2={X(g)} y2={padT + innerH}
            stroke="var(--rule)" strokeWidth="0.5" strokeDasharray={g === 0 ? "0" : "2 3"}
            opacity={g === 0 ? 0.7 : 0.4} />
          <text x={X(g)} y={padT + innerH + 18} fontFamily="IBM Plex Mono" fontSize="10"
            fill="var(--ink-3)" textAnchor="middle">{g}</text>
        </g>
      ))}
      {gridLines.map((g) => (
        <g key={"h" + g}>
          <line x1={padL} y1={Y(g)} x2={padL + innerW} y2={Y(g)}
            stroke="var(--rule)" strokeWidth="0.5" strokeDasharray={g === 0 ? "0" : "2 3"}
            opacity={g === 0 ? 0.7 : 0.4} />
          <text x={padL - 10} y={Y(g) + 3} fontFamily="IBM Plex Mono" fontSize="10"
            fill="var(--ink-3)" textAnchor="end">{g}</text>
        </g>
      ))}

      {/* axis labels */}
      <text x={padL + innerW / 2} y={H - 8} fontFamily="IBM Plex Mono" fontSize="11"
        fill="var(--ink-2)" textAnchor="middle">y (in)</text>
      <text x={18} y={padT + innerH / 2} fontFamily="IBM Plex Mono" fontSize="11"
        fill="var(--ink-2)" textAnchor="middle"
        transform={`rotate(-90 18 ${padT + innerH / 2})`}>z (in)</text>

      {/* section shape */}
      <rect x={X(-hy)} y={Y(hz)} width={X(hy) - X(-hy)} height={Y(-hz) - Y(hz)}
        fill={accent} fillOpacity="0.08" stroke={accent} strokeWidth="1.5" />

      {/* centroid crosshair */}
      <g>
        <line x1={X(0) - 8} y1={Y(0)} x2={X(0) + 8} y2={Y(0)} stroke="var(--ink-2)" strokeWidth="1" />
        <line x1={X(0)} y1={Y(0) - 8} x2={X(0)} y2={Y(0) + 8} stroke="var(--ink-2)" strokeWidth="1" />
      </g>

      {/* KP markers */}
      {kps.map((kp) => {
        const isGov = kp.id === governing;
        return (
          <g className="kp-marker" key={kp.id} transform={`translate(${X(kp.y)} ${Y(kp.z)})`}>
            <circle r={isGov ? 9 : 7} fill="var(--paper)"
              stroke={isGov ? "var(--critical)" : accent}
              strokeWidth={isGov ? 2 : 1.5} />
            <text y="3" textAnchor="middle"
              fill={isGov ? "var(--critical)" : accent}>{kp.id}</text>
          </g>
        );
      })}

      {/* dimension callouts */}
      <g>
        <line x1={X(-hy)} y1={padT + innerH - 12} x2={X(hy)} y2={padT + innerH - 12}
          stroke="var(--ink-3)" strokeWidth="0.6" markerStart="url(#dimArrow)" markerEnd="url(#dimArrow)" />
        <text x={X(0)} y={padT + innerH - 18} fontFamily="IBM Plex Mono" fontSize="10"
          fill="var(--ink-2)" textAnchor="middle">b = {b.toFixed(2)}</text>
      </g>
    </svg>
  );
}

window.SectionDiagram = SectionDiagram;
