# KamiBlue Telegram

This branch owns the Telegram userbot image for KamiBlue.

## Layout

- `telegram/` contains the Telegram service sources and Docker build context.
- `.github/workflows/telegram-image.yml` builds and publishes the image for this branch.

## Secrets

Runtime secrets are injected from environment variables only. Do not commit `.env` files or `*.session` files.

## Local build

```bash
docker build -f telegram/Dockerfile .
```

## Worktree

```bash
git worktree add ../KamiBlue-telegram telegram
```
