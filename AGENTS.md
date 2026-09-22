# AfterCare AI Repository Instructions

## Project purpose

AfterCare AI is a learning project and a controlled-beta product for multi-tenant ecommerce after-sales support. Preserve both goals: ship verifiable product slices and explain the engineering decisions clearly enough for the owner to learn from them.

## Read before working

Read these files in order before proposing or implementing a task:

1. `docs/STATUS.md`
2. The active milestone file under `docs/milestones/`
3. `docs/REQUIREMENTS.md`
4. `docs/ACCEPTANCE_CASES.md`
5. `docs/ARCHITECTURE.md`
6. `docs/DECISIONS.md`

Use `README.md` for setup commands and `docs/LEARNING_LOG.md` for historical decisions and learning evidence. Treat `docs/STATUS.md` as the current delivery truth when historical notes differ from it.

## Required workflow

1. Start with read-only inspection. Check Git status, the current branch and commit, relevant code, tests, and documentation.
2. Before changing code, explain the current gap or root cause, proposed change, files likely to change, validation plan, and risks.
3. Wait for explicit approval of that scope before modifying code.
4. Treat editing, committing, pushing, opening a pull request, requesting review, and deploying as separate permissions. Never infer one permission from another.
5. Keep unrelated user changes intact. Stop and report any overlap or unexpected dirty files.
6. At task completion, run proportionate checks, inspect the final diff, update `docs/STATUS.md`, and add learning evidence to `docs/LEARNING_LOG.md` when a milestone or meaningful task finishes.

## Git and concurrency

- This personal learning repository currently uses serial development directly on `main` when the user explicitly approves it.
- Start each new implementation task from a clean, synchronized `main`.
- Do not run two code-writing tasks in the same working directory.
- Parallel code work requires separate branches and separate Git worktrees. Do not start a downstream milestone while its required contracts are still changing.
- Never commit, push, create a pull request, request review, merge, or deploy without the corresponding explicit permission.

## Architecture boundaries

- Keep the application a modular monolith unless an approved decision changes that direction.
- Keep tenant and authorization checks on the backend. Never trust tenant or role values supplied only by the client or model.
- Use Alembic for every database schema change.
- Keep the AI workflow as a controlled single-agent design for the first release.
- Do not introduce microservices, Kubernetes, autonomous multi-agent behavior, real payment actions, or real customer data unless the project scope is explicitly changed.
- Record material architectural changes in `docs/DECISIONS.md`.

## Language and security

- Write code, code comments, commit messages, and pull-request comments in English.
- Project documentation and explanations to the owner may be written in Chinese.
- Never commit secrets, tokens, real customer data, or `.env` files.
- Do not log passwords, access tokens, full private documents, or unnecessary personal data.

## Standard validation

Run checks relevant to the changed area. The current baseline commands are:

```powershell
Set-Location apps/api
uv sync
uv run ruff check .
uv run pytest

Set-Location ../web
pnpm install
pnpm typecheck
pnpm build

Set-Location ../..
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

For a documentation-only change, verify links, run `git diff --check`, and confirm the final diff contains only approved files. Do not run unrelated dependency installation or rebuilds.

## Definition of done

A task is complete only when its approved acceptance cases pass, important failure paths are tested, the final diff matches the approved scope, documentation reflects the new current state, and remaining risks are reported. A successful page load alone is not completion evidence.
