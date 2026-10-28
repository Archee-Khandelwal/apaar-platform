# Sample uploads (all synthetic)

Deliberately messy files for the live demo. Column headers do not match our
canonical field names on purpose — the mapping screen has to work them out.

- `sample_1_excess_intake.xlsx` — 63 clean-ish rows, two blank rows and a
  stray `TOTAL = 63` line. Upload it as **Kolhanpur College of Engineering** (`kolhanpur32_admin`): B.Tech Electrical Engineering has 82 of 120 approved seats filled, so 63 more rows push it 25 seats past intake and raise EXCESS_INTAKE.
- `sample_2_dirty_errors.xlsx` — short / non-numeric / missing APAAR IDs, an
  impossible date (31/02/2006), a post-cutoff admission, a missing name, a row
  claiming no APAAR while being Indian, and a duplicate row inside the file.
- `sample_3_garbage.csv` — no usable columns at all. The pipeline must reject it
  cleanly instead of crashing.
- `sample_4_documents.zip` — the documents of the first five students in
  `sample_1_excess_intake.xlsx`, named `<APAAR ID>_<document type>.pdf`. Upload it on
  **Documents** after importing sample 1. Most are verified with the issuer
  automatically; the second student's Class 12 marksheet was edited after issue
  (rejected) and the third student's ID proof belongs to someone else (sent to an
  AICTE officer).
