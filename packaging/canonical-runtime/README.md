# Fixed canonical runtime package

Change classes: BUILD, TEST_ONLY, DOCUMENTATION.

This isolated workflow builds the already accepted application tree
995d0d83faf883bec980c896fe8a17b0f12360fa from main commit
c6ea4dd670db36e71f3839fb31e656a5c8806858. It inherits PR66 source tests
and PR67 Evidence; it does not repeat them or alter application/.

The package contains the exact source and deployment definitions, runnable
Docker image, image inspection, installed dependencies and SHA256 inventory.
All 1332 source files remain in the source archive. The unchanged canonical
.dockerignore excludes four historical tracked pytest cache files; the image
check explicitly verifies their absence and all other 1328 source files.
A separate runner downloads the same package, verifies checksums, reloads the
image without rebuilding, checks source bytes, seven worker imports, migration
head, health and OpenAPI with image networking disabled.

The canonical Python Dockerfile and upstream dependency policy are inherited.
Actual base identity and installed packages are recorded. This is a sealed
image-byte transport, not a claim of reproducible dependency resolution or
completed Sealed Node. Worker imports are not process-liveness acceptance.
Neither source PASS nor package PASS authorizes a runtime pointer update.

Sealed Node, complete business release gates, candidate registry digest,
fresh signed plan/CANARY/VERIFY, actual HK cutover and Production remain
separate gates. No signing key, host runtime environment, Docker socket or
HK credential is provided to the workflow. The workflow never deploys.
