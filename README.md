# KamiBlue Backend

This branch owns the backend service image for KamiBlue.

## Layout

- `backend/` contains the Haskell service sources and Docker build context.
- `.github/workflows/backend-image.yml` builds and publishes the image for this branch.

## Local build

```bash
docker build -f backend/Dockerfile .
```

## Worktree

```bash
git worktree add ../KamiBlue-backend backend
```
