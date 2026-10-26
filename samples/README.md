# Sample uploads (all synthetic)

Deliberately messy files for the live demo. Column headers do not match our
canonical field names on purpose — the mapping screen has to work them out.

- `sample_1_excess_intake.xlsx` — 70 clean-ish rows, two blank rows and a stray
  `TOTAL = 70` line. Uploading this as **Amaravati Nandan College of Engineering** pushes B.Tech Mechanical Engineering past its approved intake (120 seats) and raises EXCESS_INTAKE.
- `sample_2_dirty_errors.xlsx` — short / non-numeric / missing APAAR IDs, an
  impossible date (31/02/2006), a post-cutoff admission, a missing name, a row
  claiming no APAAR while being Indian, and a duplicate row inside the file.
- `sample_3_garbage.csv` — no usable columns at all. The pipeline must reject it
  cleanly instead of crashing.
