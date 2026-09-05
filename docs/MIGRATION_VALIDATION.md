# Migration validation, 2026-09-05

Application implementation commit: `e8121db` (following extracted merged history).

- Standalone source tests: 162 passed.
- Isolated package environment tests: 162 passed; full package_host.ps1 exit 0.
- Clean single-branch clone tests: 162 passed; imported sensor_host path verified
  under the clone's own src directory.
- compileall on src/tools and git diff --check: passed.
- Packaged executable smoke test: passed as part of packaging.
- EXE size: 64,505,369 bytes.
- EXE SHA-256: c8bf8b4eb2242e62b59aa656f787862c1c0d86f71696037db331dc9c6e0a76cd.
- Original repository after host removal: 19 Python protocol tests passed.
- Embedded implementation paths unchanged; no embedded build/flash was executed.
- Firmware test reference matches original sdf1.py SHA-256:
  63e0781a79a426f0ce1c99460294ec81447265990fe1b40659cbbd57043916c0.
- New Git repository has no origin pointing to firmware and no objects alternates.

The clean-clone check reused installed Python dependencies but loaded application
code and fixtures from the clone. Real CDC/ESP hardware acceptance was not performed
during this directory migration. Existing original worktrees and untracked data
were retained. Historical branches in this repository contain extracted history;
use main for the integrated standalone application.
