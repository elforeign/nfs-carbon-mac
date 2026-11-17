# World converter tools

Offline tools that read and rewrite the PC game's world archives (road sections, collision, zones, sidecars) and check
the result structurally. No source archive is ever modified; outputs go outside the repository.

- `formats.py` parses and writes the chunk container; unchanged round trips are byte-exact.
- `merge.py`, `region.py`, `convert.py`, `classify.py`, `emitters.py`, `sidecars.py` convert and relocate sections.
- `validate.py`, `audit.py` and the `test_*.py` files check the output; the tests run bare and skip when the game's
  files are absent.

Run from the checkout root with the project's Python:

```
python -I tools_snapshot/worldmerge/merge.py --check-only
python -I tools_snapshot/worldmerge/test_worldmerge.py
python -I tools_snapshot/worldmerge/audit.py
```

`merge.py` without `--check-only` writes the merged archives to a fresh output folder (`--out`); existing outputs,
source folders and escaping symlinks are rejected, and the folder is published only after the pair validates.

`props.py` imports ordinary scenery physics (`0x34027`) in both complete-world
builders. These placements include normal street props; the chunk is not a
scripted pursuit-breaker table. The combined writer converts 13,484 placements
in 366 chunks into 195 owners (maximum 242 rows), emits them after their scenery,
and preserves the native placements. Header count moves from +12 to +10; the six
reference/mode words move from +32 to +28. Physics XYZ shifts with the city.

The import appends all 22,340 scenery overrides and rebuilds their bindings,
rebasing instance selectors after composition. Bounds import uses 263 source
collections; five fence-post placements retain missing source bounds. The three
shared bounds keys with different shapes and the shared hierarchy key with
different child order receive separate identities. All 133 model hierarchies
are retained, including their original mesh references. Bounds lookup keeps the
first occurrence of repeated keys, matching the native loader.

`test_props.py` checks both global-zone modes and rejects the old count offset,
a missing bounds key, a wrong override rebase and untranslated XYZ. The bridge
output retains 12,702 native rows byte-for-byte; their SHA-256 is pinned from a
stored fixture. Live contact, body displacement and scripted effects need
separate runtime proof. Missing physical attribute collections are a separate
import; this data check does not establish their availability.
