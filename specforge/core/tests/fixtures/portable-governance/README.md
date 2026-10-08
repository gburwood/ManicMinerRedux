# Portable governance fixtures

CHG-1012 moves distributed Core regression tests away from host-project governance history.

The executable fixture builder is `specforge/core/tests/portable_fixture.py`. It creates a fresh project-format-1 SpecForge project, copies only the installed Core into that project and generates the exact governed records required by each regression scenario.

Rules:

- distributed Core tests must not require host-project CHG/PROP/APR/IMP records;
- governed fixture records must validate against the normal Core schemas;
- fixture IDs are synthetic and isolated from product history;
- tests may reproduce historical failure semantics, but must not copy authority from the host repository;
- the portability suite installs Core into a minimal independent host and reruns the distributed regressions unchanged.
