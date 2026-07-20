# cc-connect Recovery Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe command-line script that restores the local cc-connect Bridge when a stale process holds its configuration lock without listening on Bridge ports.

**Architecture:** A standalone Bash script in the Issue Overseer root checks Bridge and management ports with `lsof`. It only terminates the PID recorded in the cc-connect lock file after validating that it is a cc-connect process and that Bridge is not listening; it then uses the official daemon command and waits for both ports.

**Tech Stack:** Bash, macOS `lsof`, `ps`, cc-connect CLI.

## Global Constraints

- Do not modify cc-connect source or `~/.cc-connect/config.toml`.
- Never print token values.
- Only terminate the PID from `~/.cc-connect/.config.toml.lock` after confirming its command is cc-connect.
- Treat `9810` and `9820` listening as success.

---

### Task 1: Add and verify the recovery script

**Files:**
- Create: `recover-cc-connect.sh`
- Create: `tests/test_recover_cc_connect.sh`

**Interfaces:**
- Consumes: `cc-connect daemon start`, `cc-connect daemon status`, `~/.cc-connect/.config.toml.lock`.
- Produces: executable `./recover-cc-connect.sh` returning zero only when ports 9810 and 9820 listen.

- [x] **Step 1: Write the failing smoke test**

Create `tests/test_recover_cc_connect.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")/.." && pwd)"
script="$script_dir/recover-cc-connect.sh"
test -x "$script"
bash -n "$script"
"$script" --help | grep -Fq '恢复本机 cc-connect Bridge'
```

- [x] **Step 2: Run the smoke test to verify it fails**

Run: `bash tests/test_recover_cc_connect.sh`

Expected: failure because `recover-cc-connect.sh` does not exist.

- [x] **Step 3: Implement the minimal recovery script**

Implement the executable script with a help mode, port checks, validated stale-lock cleanup, `daemon start`/`daemon restart`, and a 15-second port wait.

- [x] **Step 4: Run the smoke test and healthy-service verification**

Run: `bash tests/test_recover_cc_connect.sh && ./recover-cc-connect.sh`

Expected: the smoke test passes; a healthy Bridge prints that no recovery is required and exits zero.

- [x] **Step 5: Commit**

```bash
git add recover-cc-connect.sh tests/test_recover_cc_connect.sh docs/superpowers/plans/2026-07-20-cc-connect-recovery-script.md
git commit -m "feat: add cc-connect recovery script"
```
