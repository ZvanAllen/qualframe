# Contributing

Thanks for your interest in QualFrame. Bug reports, usability feedback from researchers, codebook and method examples, and small focused pull requests are all welcome.

## Reporting a problem

Open an issue with what you did, what you expected and what happened, plus your operating system and QualFrame version (shown on the Methods record page). Use the demo study or a small made-up example to show the problem. **Never include real transcripts, participant information, private codebooks or API keys** in issues, screenshots or logs.

## Suggesting an improvement

Researchers' accounts of where the workflow gets in their way are especially useful. Describe the task you were doing and the step that was confusing or slow.

## Code changes

See [docs/development.md](docs/development.md) for setup and layout, and [AGENTS.md](AGENTS.md) for the project's guardrails. In short:

- Python 3.11 or later; run `python -m pytest -q` before opening a pull request.
- Tests use fictional data and offline providers only. Nothing in CI calls a model.
- Don't edit released prompt files or change how existing records are read; add a new version.
- For interface changes, check the page in a browser at desktop and narrow widths, and include a screenshot using the demo study.

By contributing you agree that your contribution is released under the MIT license.
