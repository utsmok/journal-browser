# Official postgres:17-alpine + pgvector compiled from source. The apk
# `postgresql-pgvector` package targets Alpine's system Postgres, not the
# official image's /usr/local install, so it cannot be used here.
FROM postgres:17-alpine

RUN apk add --no-cache git build-base \
    && git clone --depth 1 --branch v0.8.7 https://github.com/pgvector/pgvector /tmp/pgvector \
    # with_llvm= skips the optional JIT bitcode (clang-only, no runtime
    # impact); the alpine Postgres build has LLVM enabled but ships no clang.
    && make -C /tmp/pgvector OPTFLAGS="" with_llvm= \
    && make -C /tmp/pgvector install with_llvm= \
    && rm -rf /tmp/pgvector \
    && apk del git build-base
