# Shape Library

Cross-section shape definitions used across all Stress Toolkit modules.

## Files

- **`shapes.py`** — `Section` base class, all shape subclasses, `SHAPE_REGISTRY`.
- **`__init__.py`** — re-exports the public API.

## How it works

Each shape is a Python class inheriting from `Section`. The class owns all of its geometry, formulas, and key-point definitions in one place. Apps interact only with the abstract `Section` interface — they call `section.Iy()`, `section.tau_T(T)`, `section.key_points(My, Mz)` and never know which concrete shape they're working with.

## Adding a new shape

1. **Subclass `Section`** in `shapes.py`. Place the new class with the other shapes in the file, ordered by complexity.

2. **Set the class attributes:**
   ```python
   name = "My New Shape"
   category = "Solid"          # or "Hollow" / "Open thin-walled"
   is_open_section = True      # affects torsion formula choice
   dim_labels = [
       ("d1_symbol", "Description of D1"),
       ("d2_symbol", "Description of D2"),
       None, None,             # unused slots
   ]
   dim_defaults = [1.0, 0.5, None, None]
   f_cozzone = 1.50            # Cozzone shape factor (Fbu = f·Ftu)
   ```

3. **Implement the required methods:**
   - `area()`
   - `centroid()` → returns `(y_bar, z_bar)` in shape-local coords
   - `Iy()`, `Iz()` → second moments about centroidal axes
   - `J_torsion()` → torsion constant
   - `tau_T(T_load)` → max torsional shear stress in ksi
   - `Qy()`, `Qz()` → first moments at neutral axis (for VQ/It shear)
   - `tw_y()`, `tw_z()` → web thickness at neutral axis
   - `polygon_vertices()` → list of NumPy arrays, one per closed loop (outer first, inner holes after). Coords **centered on centroid**.
   - `key_points(My, Mz)` → list of `KeyPoint` instances

4. **Register the shape** in `SHAPE_REGISTRY` at the bottom of `shapes.py`:
   ```python
   SHAPE_REGISTRY = {
       ...
       MyNewShape.name: MyNewShape,
   }
   ```

## Coordinate system

```
        +Z (up)
         |
         |
   ──────┼──────  +Y (right)
         |
         |
```

`X` is the beam axis (out of the page). `My` is bending about `Y` (deforms the beam in the Y-Z plane), producing stress proportional to `z`. `Mz` is bending about `Z`, producing stress proportional to `y`.

## Comment style for unusual cases

When a formula has caveats or is an approximation, mark it with a callout in the code:

```python
def Iz(self):
    # ⚠️ ASSUMPTION: bending about geometric Y-Z axes, not principal axes.
    # Valid only when section is constrained by surrounding structure.
    return ...
```

The marker `⚠️ ASSUMPTION` is searchable so anyone auditing the library can find them.

## Cozzone shape factors — note

The `f_cozzone` values are **simplified handbook constants**, not material-dependent. A rigorous Cozzone analysis derives `f` from both shape AND the material's stress-strain curve shape. The values used here are conservative for typical ductile aerospace metals. See `shapes.py` docstring for the full table.
