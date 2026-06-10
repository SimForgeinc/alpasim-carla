# Vendored AlpaSim protos (pinned)

The `.proto` files under `alpasim_grpc/v0/` are verbatim copies from NVIDIA
**AlpaSim**, commit `a1f05bb628f3d1d19d79d44188e836e9108f98c6`
(`src/grpc/alpasim_grpc/v0/`), redistributed under the Apache-2.0 license of
that project. Copyright (c) 2025 NVIDIA Corporation.

The corresponding `alpasim_grpc` Python distribution at that commit has
version **0.54.0** — that value is what `get_version` must echo in
`grpc_api_version` (see `alpasim_carla/__init__.py:GRPC_API_VERSION`).

Do not edit these files. To change the contract, re-pin to a new AlpaSim
commit, re-copy, update `GRPC_API_VERSION`, and run `tools/gen_protos.sh`.
