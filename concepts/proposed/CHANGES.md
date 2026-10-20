# Proposed changes to seeded rows (schema v1.3), awaiting approval

The CSVs in this folder hold new rows. These are edits to rows already in `concepts/`, so they can't go in a proposed CSV (a proposed id must be new). Nothing here is loaded or used for linking until approved.

1. **`ai:dicofol`**: `use_class` empty → `acaricide` (schema v1.3 adds the value; TNAU 2020 PDF p. 67 lists it for mites).
2. **Optional:** `use_class` → `biopesticide` for `ai:bacillus_thuringiensis_kurstaki` and `ai:beauveria_bassiana` (now `insecticide`, marked "my inference"), and for `ai:pseudomonas_fluorescens` (now `fungicide`). Only if you want the new class used.
3. **`MEMBER_OF ai_group:synthetic_pyrethroids`** for `ai:deltamethrin`, `ai:cypermethrin`, `ai:fenvalerate`, `ai:permethrin` and `ai:etofenprox`.
   - The book names the class but not its members.
   - These five are in the IRAC Mode of Action group 3A (pyrethroids). Verify them against the current IRAC classification before approval.
   - Until approved, the group has no members, so a Caution about it doesn't reach any one ingredient.

Not drafted (open):
- **"KKM 10% D"** (PDF p. 67): the book doesn't say what KKM is. It needs a source before any row is written.
- **ZnSO4 and FeSO4** stay TODO until their nutrient percentages come from an official source.
- **"80 �M" sodium nitroprusside** (PDF p. 73): the converted text lost the µ. Check the rendered page and add a registry `review_note`; until then, mapping it to `micromolar` is a guess.
