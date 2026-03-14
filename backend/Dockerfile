FROM haskell:9.14-bookworm AS build

WORKDIR /build
COPY backend/KamiBlue/ /build/
RUN stack setup && stack build --copy-bins --install-ghc --local-bin-path /out

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates make gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /out/KamiBlue-exe /usr/local/bin/KamiBlue-exe
COPY backend/KamiBlue/.dev/template /app/template

EXPOSE 7485

CMD ["KamiBlue-exe"]
