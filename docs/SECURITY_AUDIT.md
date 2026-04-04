# Security Audit Report

**Date**: 2026-04-04
**Purpose**: Pre-public-release security review of all source files and git history.

---

## Summary

**17 files** contained personal information (IP addresses, usernames, SSH key paths, or 1Password vault references). All have been remediated in the working tree. No real API keys or passwords were ever committed to the repository.

---

## Findings and Remediations

### 1. Hardcoded Private Network IPs (FIXED)

Personal LAN IPs `192.168.1.221` (NAS) and `192.168.1.116` (Lexicon host) were used as hardcoded defaults throughout the codebase.

**Files fixed:**
- `src/nas.py` -- defaults now read from env vars, fallback to `localhost`
- `src/lexicon.py` -- defaults now read from env vars, fallback to `127.0.0.1`
- `server/config.py` -- defaults changed to `localhost` / `127.0.0.1`
- `docker-compose.yml` -- default env fallbacks changed
- `scripts/generate_all_songs.py` -- now reads env vars
- `scripts/generate_mind_control.py` -- now reads env vars
- `scripts/generate_song_parallel.py` -- now reads env vars
- `server/services/job_queue.py` -- now reads env vars
- `docs/INSTALLATION.md` -- replaced with placeholder IPs
- `web/src/pages/Settings.tsx` -- default changed to `localhost`
- `web/src/pages/SetupWizard.tsx` -- placeholder text updated
- `.env.example` -- replaced with placeholder values

### 2. Hardcoded Personal Username (FIXED)

Username `willcurran` was used as the default NAS SSH user.

**Files fixed:**
- `src/nas.py` -- default changed to `admin` (from env var)
- `src/lexicon.py` -- default from env var
- `server/config.py` -- default changed to `admin`
- `scripts/generate_all_songs.py` -- from env var
- `scripts/generate_mind_control.py` -- from env var
- `scripts/generate_song_parallel.py` -- from env var
- `docs/INSTALLATION.md` -- reference table updated
- `.env.example` -- changed to `your_nas_username`
- `tests/test_nas.py` -- now uses fixture value instead of hardcoded string

### 3. Personal SSH Key Name (FIXED)

SSH key path `~/.ssh/openclaw_rpi_ed25519` was hardcoded as default.

**Files fixed:**
- `src/nas.py` -- default changed to `~/.ssh/id_ed25519`
- `src/lexicon.py` -- default changed to `~/.ssh/id_ed25519`
- `server/config.py` -- default changed to `~/.ssh/id_ed25519`
- `docker-compose.yml` -- now uses `${NAS_SSH_KEY}` env var
- `docs/INSTALLATION.md` -- reference table updated

### 4. 1Password Vault References (FIXED)

Hardcoded `op://OpenClaw/...` references exposed the vault name and item structure.

**Files fixed:**
- `src/cli.py` -- now uses `OP_FAL_REF` / `OP_OPENAI_REF` env vars with generic defaults
- `.env.example` -- replaced with generic placeholder values
- `README.md` -- removed vault name reference

### 5. Personal File Paths (FIXED)

Paths containing `/Users/willcurran/` and `/Users/openclaw/` were hardcoded.

**Files fixed:**
- `src/lexicon.py` -- `LEXICON_PATH_PREFIX` now configurable via env var
- `scripts/generate_song_parallel.py` -- removed `/Users/openclaw/` hardcoded chdir; personal paths genericized
- `scripts/generate_all_songs.py` -- personal paths genericized
- `tests/test_pipeline.py` -- test fixture path genericized

### 6. GitHub Username in Clone URL (FIXED)

`README.md` contained `github.com/willcurran/resolume-sync-visuals`.

**File fixed:** `README.md` -- changed to `your-username`

### 7. Personal Name Reference (FIXED)

`docs/VISUAL_QUALITY_ANALYSIS.md` contained "Will Curran (feedback), Barry (analysis)".

**File fixed:** Changed to "Internal review"

### 8. Brand Name Defaults (NOT PII -- NO ACTION)

Default brand/show names ("Example Brand", "My Show") are generic placeholders used throughout the codebase. They are not personally identifiable information.

---

## Items NOT Found (Clean)

- No real API keys (OpenAI, fal.ai, Replicate) in any committed file
- No passwords or tokens in source code
- No email addresses or phone numbers
- No `.env` file in git history (properly gitignored from the start)
- Git author name is "OpenClaw" (not personal name)

---

## Git History Contamination

The following PII exists in git history across multiple commits and **must be cleaned before making the repo public**:

| Pattern | Occurrences | Risk |
|---------|-------------|------|
| `192.168.1.221` / `192.168.1.116` | ~30+ | Low (private IPs, not routable) |
| `willcurran` (username) | ~20+ | Medium (identifies owner) |
| `openclaw_rpi_ed25519` (SSH key name) | ~10+ | Low (name only, not key material) |
| `op://OpenClaw/...` (1Password refs) | ~8 | Low (vault name, no secrets) |
| `/Users/openclaw/` (home dir) | 1 | Low (local path) |
| `/Users/willcurran/` (Lexicon paths) | ~15 | Medium (identifies owner) |

### Recommended Action

Run [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/) before making the repo public:

```bash
# Create a replacements file
cat > replacements.txt << 'EOF'
192.168.1.221==>localhost
192.168.1.116==>127.0.0.1
willcurran==>admin
openclaw_rpi_ed25519==>id_ed25519
op://OpenClaw==>op://Private
/Users/openclaw==>__PROJECT_DIR__
/Users/willcurran==>__USER_DIR__
EOF

# Run BFG
bfg --replace-text replacements.txt resolume-sync-visuals.git

# Then force push (destructive -- coordinate with any collaborators)
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push --force
```

**DO NOT make the repo public until git history is cleaned.**

---

## `.env` File (Local Only)

The local `.env` file contains personal configuration but is properly gitignored and was never committed. No action needed.
