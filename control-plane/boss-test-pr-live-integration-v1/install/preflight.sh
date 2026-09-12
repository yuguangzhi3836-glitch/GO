#!/bin/sh
set -eu
role=${1:?role required: command-center|hk-staging}
case "$role" in
  command-center)
    test "$(sha256sum /usr/local/libexec/go-boss-request-bridge | awk '{print $1}')" = "3a23d4fb5ab7946fc6dcca15fb3450d14f6f896f6c2289ad3a0aa0e8bf0fc129"
    test "$(sha256sum /etc/go-command-center/boss-request-bridge-v1.json | awk '{print $1}')" = "88880363d761eb924aac1910caa7696619dbbb0b4fcb112b63cf726de3bf1335"
    test -f /etc/go-command-center/keys/github-go-pr-resolver
    test "$(stat -c %a /etc/go-command-center/keys/github-go-pr-resolver)" = 600
    test ! -e /etc/go-command-center/keys/github-go-source-reader
    ;;
  hk-staging)
    test "$(sha256sum /opt/go-hk-agent-rebuilt/hk_agent/transport.py | awk '{print $1}')" = "4301a7e920fc25d98ea8403ac00ebbdb6a864bcb092d33caf343ad28603ff490"
    test "$(sha256sum /etc/go-hk-agent/agent.json | awk '{print $1}')" = "82ab805b921081ec0299ffa20576963476e12f57e711438f46ada2342a7c7b30"
    test "$(sha256sum /opt/go-hk-agent-rebuilt/hk_agent/deployment_actions.py | awk '{print $1}')" = "7400ef03caf9473db73eccca5206233c81707ae742547489f0ed93728e5b323e"
    test ! -e /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py
    test ! -e /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1
    test -f /etc/go-hk-agent/keys/github-go-source-reader
    test "$(stat -c %a /etc/go-hk-agent/keys/github-go-source-reader)" = 600
    test -f /etc/go-hk-agent/keys/task-verify.pub
    test -f /etc/go-hk-agent/keys/evidence-signing.pem
    ;;
  *) exit 64 ;;
esac
