# Stress Toolkit

A collection of structural-analysis modules for metallic airframe design,
built with Python and Streamlit.

## Available modules

- **Beam Section Stress** — combined-loading stress and margin-of-safety
  analysis of cross-sections: 11 standard catalog shapes plus custom imported
  polygons (paste vertices or upload DXF). Dual solver — classical closed-form
  / Bruhn midline for catalog shapes and a `sectionproperties` FEM solver for
  imported/arbitrary sections — MMPDS-01 allowables, interactive FEM stress
  contour, and an in-app validation page.

More modules will be added as siblings under `apps/`.

## Local installation

```bash
pip install -r requirements.txt
streamlit run Home.py
```

The app opens at `http://localhost:8501`.

## Deployment (Streamlit Cloud)

1. Push this repo to GitHub.
2. On [share.streamlit.io](https://share.streamlit.io), create a new app.
3. Point it at your repo and set **Main file path** to `Home.py`.

Streamlit Cloud reads `requirements.txt` automatically. Pages in the
`pages/` folder appear in the sidebar navigation.

## Project structure

```
stress_toolkit/
├── Home.py                          ← landing page (Streamlit entry)
├── pages/                           ← auto-discovered sidebar pages
│   └── 1_Beam_Section_Stress.py
├── apps/                            ← one analysis module per subfolder
│   └── beam_section/
│       ├── app.py                   ← Streamlit render() for this module
│       ├── calculations.py          ← stress and MS engines
│       └── plotting.py              ← matplotlib figures
├── library/                         ← shared engineering data
│   ├── materials/
│   │   ├── materials.py             ← Material dataclass + MATERIALS dict
│   │   └── README.md                ← schema and how-to-add docs
│   ├── shapes/
│   │   ├── shapes.py                ← Section base class + 11 shapes
│   │   └── README.md                ← how-to-add-a-shape docs
│   └── analysis/                    ← solvers (classical midline + FEM wrapper)
├── ui/                              ← shared styling
│   ├── theme.py                     ← color tokens (THEME, PLOT_PALETTE)
│   ├── styles.py                    ← CSS injection
│   └── components.py                ← reusable widgets
├── requirements.txt
└── README.md
```

## Adding new functionality

- **A new material** — edit `library/materials/materials.py` and append a
  new `Material(...)` entry. See `library/materials/README.md` for the
  property schema and the convention for flagging conservative estimates.

- **A new cross-section shape** — see `library/shapes/README.md` for the
  step-by-step procedure (subclass `Section`, implement the required
  methods, register in `SHAPE_REGISTRY`).

- **A new analysis module** — create `apps/<module_name>/` mirroring the
  beam_section layout, then add a wrapper `pages/N_<Title>.py` that calls
  the module's `render()` function. Reuse `ui/components.py` so all
  modules look consistent.

## Conventions

- **Units:** inch / pound / second (IPS). Stresses in ksi.
- **Coordinate:** X = beam axis, Y = horizontal right, Z = vertical up.
- **Theme:** dark mode only currently (light mode defined in `ui/theme.py`
  but not yet exposed in the UI; input field text rendering needs
  browser-specific testing).
- **Estimated values:** material properties without MMPDS data are flagged
  with `⚠️ ESTIMATED` comments and listed in `Material.estimated_fields`.
  The UI displays an `EST` badge next to any estimated value.
