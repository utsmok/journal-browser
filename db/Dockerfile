# Official postgres:17-alpine + pgvector compiled from source. The apk
# `postgresql-pgvector` package targets Alpine's system Postgres, not the
# official image's /usr/local install, so it cannot be used here.
# Minor-pinned (PG 17.10, alpine 3.22): a floating postgres minor under an
# existing pgdata volume is the risky kind of drift.
FROM postgres:18.4-alpine3.22

RUN apk add --no-cache git build-base \
    && git clone --depth 1 --branch v0.8.7 https://github.com/pgvector/pgvector /tmp/pgvector \
    # with_llvm= skips the optional JIT bitcode (clang-only, no runtime
    # impact); the alpine Postgres build has LLVM enabled but ships no clang.
    && make -C /tmp/pgvector OPTFLAGS="" with_llvm= \
    && make -C /tmp/pgvector install with_llvm= \
    && rm -rf /tmp/pgvector \
    && apk del git build-base
