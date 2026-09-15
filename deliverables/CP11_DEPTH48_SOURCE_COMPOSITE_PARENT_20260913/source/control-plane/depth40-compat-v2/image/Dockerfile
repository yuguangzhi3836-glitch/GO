# Base must be loaded and config ID verified by ci/build_child.py before build.
FROM go-depth40-staging:ci-34565938702
COPY --chown=0:0 preflight.py /opt/go/staging/preflight.py
LABEL go.compatibility-revision="depth40-compat-v2"
LABEL go.parent-image-id="sha256:9ec6ebaf962b6f5e880ecaa2e878a2ec1e51bfd0f1f4012b90aa709692d5057b"
# Inherit source, launcher, runtime, entrypoint, non-root user and dependencies.
