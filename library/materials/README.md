# Materials Library

Material property data used across all Stress Toolkit modules.

## Files

- **`materials.py`** — the `Material` dataclass and the registered `MATERIALS` dictionary.
- **`__init__.py`** — re-exports the public API.

## Adding a custom material

Open `materials.py` and append a new `Material(...)` entry to the `_materials` list. The unique key is the `name` attribute. All properties except `name` and `category` are optional — leave them as `None` (the default) if data is unavailable.

```python
Material(
    name="My Custom Alloy",  category="Aluminum",
    Fty=50, Ftu=65, Fcy=48, Fsu=35,
    E=10.5, G=4.0,
    rho=0.100,
    source="Internal test data 2024-08-12",
    notes="Heat lot ABC123",
),
```

## Estimated values

When a property cannot be sourced from MMPDS and a conservative estimate is used, follow this convention:

**1.** Mark the line with the comment prefix `# ⚠️ ESTIMATED — <reason>`:

```python
Fbru = 1.5 * Ftu,  # ⚠️ ESTIMATED — MMPDS lacks bearing for this temper
```

**2.** Add the field name to `estimated_fields` on the same `Material`:

```python
estimated_fields=("Fbru", "Fbry"),
```

The UI will then render an `EST` badge next to any displayed estimated value, so an analyst is never silently relying on a non-MMPDS number.

## Schema reference

| Field   | Unit      | Description                                            |
|---------|-----------|--------------------------------------------------------|
| `Fty`   | ksi       | Tensile yield strength                                 |
| `Ftu`   | ksi       | Tensile ultimate strength                              |
| `Fcy`   | ksi       | Compressive yield strength                             |
| `Fsu`   | ksi       | Shear ultimate strength                                |
| `Fbru`  | ksi       | Bearing ultimate strength (e/D = 1.5)                  |
| `Fbry`  | ksi       | Bearing yield strength (e/D = 1.5)                     |
| `E`     | Msi       | Young's modulus (tension)                              |
| `Ec`    | Msi       | Compression modulus                                    |
| `G`     | Msi       | Shear modulus                                          |
| `nu`    | —         | Poisson's ratio                                        |
| `alpha` | µin/in/°F | Coefficient of thermal expansion (×10⁻⁶)               |
| `k`     | Btu·in/hr·ft²·°F | Thermal conductivity                            |
| `T_max` | °F        | Maximum recommended service temperature                |
| `rho`   | lb/in³    | Density                                                |
