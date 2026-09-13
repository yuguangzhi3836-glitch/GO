#!/bin/sh
set -eu
: "${PREVIOUS_IMAGE_TAG:?Set PREVIOUS_IMAGE_TAG}"
echo "Rollback contract: deploy immutable image tag ${PREVIOUS_IMAGE_TAG}; DO NOT downgrade DB migrations automatically."
echo "Run forward-compatible app rollback first. Database rollback requires explicit reviewed migration plan."
