# KamiBlue Deploy

`main` is the deployment branch for KamiBlue.

## What lives here

- `compose.yaml` pulls prebuilt images from GHCR.
- `.env.example` documents the runtime variables required by the Telegram container.
- No service source code is committed to `main`.

## Images

- `ghcr.io/alberto-kali/kamiblue-backend:latest`
- `ghcr.io/alberto-kali/kamiblue-telegram:latest`

## Quick start

```bash
cp .env.example .env
docker compose pull
docker compose up -d
```

Rotate any previously exposed Telegram credentials before using this deployment.

## Worktrees

```bash
git worktree add ../KamiBlue-main main
git worktree add ../KamiBlue-backend backend
git worktree add ../KamiBlue-telegram telegram
```

Use short-lived topic branches and merge through pull requests only.
