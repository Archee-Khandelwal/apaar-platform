# Sample uploads (all synthetic)

Deliberately messy files for the live demo. Column headers do not match our
canonical field names on purpose — the mapping screen has to work them out.

- `sample_1_excess_intake.xlsx` — 58 clean-ish rows, two blank rows and a
  stray `TOTAL = 58` line. Upload it as **Sindhupuri Institute of Engineering and Technology** (`sindhupuri4_admin`): B.Tech Information Technology has 87 of 120 approved seats filled, so 58 more rows push it 25 seats past intake and raise EXCESS_INTAKE.
- `sample_2_dirty_errors.xlsx` — short / non-numeric / missing APAAR IDs, an
  impossible date (31/02/2006), a post-cutoff admission, a missing name, a row
  claiming no APAAR while being Indian, and a duplicate row inside the file.
- `sample_3_garbage.csv` — no usable columns at all. The pipeline must reject it
  cleanly instead of crashing.
