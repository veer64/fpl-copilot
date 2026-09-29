# The production Postgres image (2026-09-29): the EXACT base the server ran, pinned by digest,
# plus pgvector built from source at a pinned release tag. Nothing else.
#
# Why this shape:
#   * digest, not tag. postgres:16-alpine moved between the server's pull (2026-07-07 build,
#     PostgreSQL 16.14 on Alpine 3.24.1, musl libc) and a laptop pull of 2026-09-25. The data
#     volume's collation (en_US.utf8, provider libc) must stay byte-identical, so the base is the
#     server's image itself. The digest is the OCI index; its linux/amd64 manifest is
#     sha256:7a396fd264a2067788b6551122b50f162bf6136312c7fc9d74381cb92c648382.
#   * no Debian base. musl -> glibc changes the collation and can silently corrupt text indexes.
#   * pgvector from source at tag v0.8.6 (2026-07-29, the newest tag of
#     github.com/pgvector/pgvector; pgvector publishes tags, not GitHub releases; CHANGELOG.md at
#     the tag). Build deps live in a virtual apk package deleted afterwards. with_llvm=no: the
#     runtime image has no clang/llvm, and PGXS would otherwise try to emit LLVM bitcode.
#
# Built by `docker compose build fpl-postgres` (docker-compose.yml). The deploy workflow never
# builds or restarts this service; the image is swapped by hand in a planned window.
FROM postgres@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777

ARG PGVECTOR_VERSION=v0.8.6

RUN set -eux; \
    apk add --no-cache --virtual .build-deps build-base git; \
    git clone --depth 1 --branch "$PGVECTOR_VERSION" https://github.com/pgvector/pgvector.git /tmp/pgvector; \
    cd /tmp/pgvector; \
    echo "pgvector commit $(git rev-parse HEAD)"; \
    make with_llvm=no; \
    make install with_llvm=no; \
    cd /; \
    rm -rf /tmp/pgvector; \
    apk del .build-deps
