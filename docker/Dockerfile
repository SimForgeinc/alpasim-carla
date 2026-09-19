# alpasim-carla bridge image (the renderer process only - bring your own
# CARLA server; see docker/README.md for a compose example).
#
# The CARLA client wheel is copied out of the CARLA image rather than fetched
# from PyPI. There is no `carla==0.10.0` on PyPI at all: the 0.10 client ships
# only as a .whl inside the release package, and the copy inside the server
# image is the one guaranteed to match that server. For stock 0.9.16 twins
# PyPI does work - install the [carla] extra instead of using this image.
#
#   docker build -f docker/Dockerfile \
#       --build-arg CARLA_IMAGE=<registry>/<image>@sha256:<digest> \
#       -t alpasim-carla:0.10 .
#
# On a stock 0.9.16 twin the PythonAPI root differs, so add:
#       --build-arg CARLA_PYTHONAPI=/workspace/PythonAPI
#
# CARLA_IMAGE is pinned BY DIGEST, not by tag. A tag on a private registry can
# be re-pushed, and then two builds of the same Dockerfile silently contain
# different CARLA clients. Resolve the digest once, record it in the
# provenance ledger, and pass it here:
#
#   docker buildx imagetools inspect <registry>/<image>:<tag> | grep Digest
#
# PYTHON_VERSION must match a cp<ver> wheel present in the CARLA image, and
# what an image ships is a property OF THAT IMAGE, not of the CARLA release.
# The default below is a pin, not a preference:
#
#   ghcr.io/simforgeinc/carla-rfs-munich-belmont@sha256:d1b16b061ef1c2947caf
#   2d87109d2809617d5ebfd8c3cb999637e8751da83d22   (CARLA server 0.10.0)
#
# ships exactly one client wheel,
#
#   /home/carla/PythonAPI/carla/dist/carla-0.10.0-cp310-cp310-linux_x86_64.whl
#
# **cp310 only** - whatever the CARLA 0.10 release notes say about 3.8-3.12.
# With the previous 3.12 default the build could not install the wheel it had
# just copied; `--build-arg PYTHON_VERSION=3.10` produced alpasim-carla:
# 0.10.0-belmont (sha256:1b7cec383985e9c14d73fe38b25cf5d7fa2beea322e1beec41b
# 82803011fb4e2, 403 MB, python 3.10.21) with carla.Client and alpasim_carla
# both importing. The bridge's own venv is 3.10 for the same reason; the
# AlpaSim runtime stays on 3.12 in its separate process, which the gRPC
# boundary guarantees (ADR-017).
#
# A different image may ship different wheels - stock 0.9.16 ships cp310
# through cp312. Override the default when you measure otherwise; the
# wheel-selection step below fails with the available filenames listed
# rather than a bare "no matching distribution".

ARG PYTHON_VERSION=3.10

# No default: a build must name the exact image it copied its client from.
ARG CARLA_IMAGE

# Stage 1: the CARLA server image, used only as a source of the client wheel.
FROM ${CARLA_IMAGE} AS carla-dist

# Stage 2: the bridge.
FROM python:${PYTHON_VERSION}-slim
ARG PYTHON_VERSION
ARG CARLA_IMAGE

# The wheel lives at PythonAPI/dist/ on 0.10 and PythonAPI/carla/dist/ on
# 0.9.x. Copy the whole tree; at least one layout exists in any CARLA image.
#
# The ROOT differs too, which this assumed away until the first build was
# attempted: carlasim/carla:0.9.16 keeps it at /workspace/PythonAPI, not
# /home/carla/PythonAPI, and the build failed with
#   COPY failed: stat home/carla/PythonAPI/: file does not exist
# COPY takes no fallbacks, so the root is an argument with the 0.10 layout
# as its default. Find it in a new image with:
#   docker run --rm --entrypoint bash <image> -c 'find / -maxdepth 4 -name PythonAPI -type d'
ARG CARLA_PYTHONAPI=/home/carla/PythonAPI
COPY --from=carla-dist ${CARLA_PYTHONAPI}/ /tmp/carla-pythonapi/

# The tag comes from the INTERPRETER, not from the string the caller typed.
# Deriving it from ${PYTHON_VERSION} looked equivalent and is not: the
# official python:*-slim images set ENV PYTHON_VERSION to the full patch
# version, ENV beats ARG of the same name, and `--build-arg
# PYTHON_VERSION=3.10` therefore produced
#   No CARLA wheel for cp31021 (Python 3.10.21)
# with cp310 sitting in the very list it printed. Asking the interpreter
# also makes the wheel match the python that will import it, which is the
# property actually wanted - a caller who types 3.11 against a 3.10 base
# can no longer install a wheel the runtime cannot load.
RUN set -eu; \
    tag="$(python -c 'import sys; print("cp%d%d" % sys.version_info[:2])')"; \
    wheel="$(find /tmp/carla-pythonapi -name "carla-*-${tag}-*.whl" | head -n1)"; \
    if [ -z "${wheel}" ]; then \
        echo "No CARLA wheel for ${tag} (the interpreter in this image) in ${CARLA_IMAGE}." >&2; \
        echo "Wheels present in that image:" >&2; \
        find /tmp/carla-pythonapi -name 'carla-*.whl' -exec basename {} \; >&2 || true; \
        echo "Rebuild with --build-arg PYTHON_VERSION=<one of the above>." >&2; \
        exit 1; \
    fi; \
    echo "Selected wheel: $(basename "${wheel}")"; \
    pip install --no-cache-dir "${wheel}"; \
    rm -rf /tmp/carla-pythonapi

# Fail the build rather than the first render if the wheel does not import,
# and print which wheel won so the build log is the provenance record.
RUN python -c "import sys, carla; from importlib import metadata; \
print('carla version  :', metadata.version('carla')); \
print('carla.__file__ :', carla.__file__); \
print('interpreter tag: cp%d%d (Python %s)' % (sys.version_info.major, sys.version_info.minor, sys.version.split()[0])); \
print('copied from    : ' + '${CARLA_IMAGE}')"

LABEL org.opencontainers.image.base.name="${CARLA_IMAGE}"

WORKDIR /opt/alpasim-carla
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scenes ./scenes
COPY tools ./tools
# simforge-frames is a dependency of this package and is NOT on PyPI - it
# lives in this repository, split out so simforge-closed-loop can depend on
# the frame conversions without importing the 0.54.0 proto stubs (ADR-017).
# Copying it and installing it first is what the CI workflow already does;
# the image did not, and the build ended at
#   ERROR: No matching distribution found for simforge-frames
COPY packages ./packages

# Plain "." and NOT ".[carla]" - the client is already installed above from
# the server image, and the extra would pull the 0.9.16 PyPI wheel over it.
RUN pip install --no-cache-dir ./packages/simforge-frames && \
    pip install --no-cache-dir .

# SensorsimService port
EXPOSE 50051

ENTRYPOINT ["alpasim-carla"]
CMD ["serve", "--port", "50051", "--scenes-dir", "scenes/examples", \
     "--carla-host", "host.docker.internal", "--carla-port", "2000"]
