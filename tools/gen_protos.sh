#!/usr/bin/env bash
# Regenerate the vendored gRPC stubs under src/alpasim_carla/_proto/.
#
# The pristine pinned protos live in proto/alpasim_grpc/v0/ (copied verbatim
# from NVIDIA AlpaSim commit a1f05bb628f3d1d19d79d44188e836e9108f98c6,
# Apache-2.0 — see proto/README.md). We relocate them under the
# alpasim_carla/_proto/ namespace before generation so that:
#   1. the generated Python modules import from alpasim_carla._proto.* and
#      never collide with a real `alpasim_grpc` installation, and
#   2. the descriptor-pool file names are namespaced too.
# The proto `package` statements (e.g. nre.grpc.protos.sensorsim) are
# untouched, which is what keeps the gRPC method paths wire-compatible.
set -euo pipefail
cd "$(dirname "$0")/.."

PKGDIR=alpasim_carla/_proto
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/$PKGDIR/alpasim_grpc/v0"
cp proto/alpasim_grpc/v0/*.proto "$STAGE/$PKGDIR/alpasim_grpc/v0/"
sed -i 's#import "alpasim_grpc/v0/#import "alpasim_carla/_proto/alpasim_grpc/v0/#' \
    "$STAGE/$PKGDIR/alpasim_grpc/v0/"*.proto

rm -rf "src/$PKGDIR/alpasim_grpc"
mkdir -p "src/$PKGDIR"

python -m grpc_tools.protoc -I "$STAGE" \
    --python_out=src --grpc_python_out=src --pyi_out=src \
    "$STAGE/$PKGDIR/alpasim_grpc/v0/"*.proto

touch "src/$PKGDIR/__init__.py" \
      "src/$PKGDIR/alpasim_grpc/__init__.py" \
      "src/$PKGDIR/alpasim_grpc/v0/__init__.py"

echo "Generated stubs:"
ls "src/$PKGDIR/alpasim_grpc/v0/"
