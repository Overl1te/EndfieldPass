# Contributing to EndfieldPass

Official website: **https://endfieldpass.site/**

Language versions:

- Russian: [CONTRIBUTING](CONTRIBUTING.md)
- English: [CONTRIBUTING_EN](CONTRIBUTING_EN.md)

## Before you start

- Check if a similar `Issue` or `PR` already exists.
- For larger changes, open an `Issue` first to align scope and expectations.
- Be specific: what changes, why it changes, and how to validate it.

## Issue guidelines

For bug reports, include:

- reproduction steps
- expected behavior
- actual behavior
- screenshots/videos (for UI issues)
- environment: OS, browser, Python version, branch/commit

For feature requests, include:

- user problem
- proposed solution
- tradeoffs or alternatives

## Pull Request guidelines

1. Create a dedicated branch from `main`.
2. Keep commits focused and logically grouped.
3. Add or update tests when behavior changes.
4. Run local validation before opening the PR.
5. In PR description, explain what changed, how it was tested, and what reviewers should focus on.

## Local validation

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python manage.py test
```

## Change recommendations

- Do not mix unrelated refactoring and new features in one PR unless necessary.
- If UI changes, attach `before/after` screenshots.
- If UI copy changes, verify localization keys.
- Never commit secrets (`.env`, tokens, OAuth keys, personal data).

## PR checklist

- [ ] Project runs locally without regressions
- [ ] Tests pass
- [ ] Documentation is updated when needed
- [ ] No secrets or unrelated artifacts in the diff
- [ ] PR description is clear for fast review

