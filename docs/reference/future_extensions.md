# Future extensions

The transcript-first CFIR pipeline, structured post-parse validation, disagreement comparison, adjudication actions, and loopback dashboard are now implemented foundations. They are not future extensions.

## 1. Additional analysis methods

After the directed/framework-based product is validated, consider hybrid deductive-inductive workflows and clearly separated exploratory analysis. Do not present these as current capabilities.

## 2. JSON-native response schemas
The current prompts are Excel-oriented. A strong next step is to preserve their logic while moving the internal interface to structured JSON.

## 3. Automated comparison execution

The engine can compare explicit artifacts today. A later extension may automatically run selected providers or prompt variants, preserve each lineage, and route disagreements to human review. Detection must not be described as adjudication.

## 4. Multi-user collaboration

After the local individual-researcher workflow is validated, add authentication, roles, shared review queues, conflict handling, and institutional deployment controls.

## 5. Skill / guided mode
A repo-scoped Codex skill and installable plugin now provide the first guided mode for QualFrame CFIR workflows. Keep this layer focused on orchestration, validation, resume/export guidance, and QA review while the Python runner remains responsible for deterministic execution and audit artifacts.

## 6. Software package path

The current progression is:

- working Python engine and CLI
- local governance and review dashboard
- local-first individual-researcher application
- validated multi-framework directed-analysis platform
- later hosted multi-user service
