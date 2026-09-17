#!/bin/sh
set -eu
role=${1:?role required: command-center|hk-staging}
phase=${2:-preinstall}
case "$role" in
  command-center)
    test "$(sha256sum /usr/local/libexec/go-boss-request-bridge | awk '{print $1}')" = "3a23d4fb5ab7946fc6dcca15fb3450d14f6f896f6c2289ad3a0aa0e8bf0fc129"
    test "$(sha256sum /etc/go-command-center/boss-request-bridge-v1.json | awk '{print $1}')" = "88880363d761eb924aac1910caa7696619dbbb0b4fcb112b63cf726de3bf1335"
    test -f /etc/go-command-center/keys/github-go-pr-resolver
    test "$(stat -c %a /etc/go-command-center/keys/github-go-pr-resolver)" = 600
    test ! -e /etc/go-command-center/keys/github-go-source-reader
    ;;
  hk-staging)
    test -f /etc/go-hk-agent/keys/github-go-source-reader
    test "$(stat -c %a /etc/go-hk-agent/keys/github-go-source-reader)" = 600
    test -f /etc/go-hk-agent/keys/task-verify.pub
    test -f /etc/go-hk-agent/keys/evidence-signing.pem
    getent passwd go-hk-agent >/dev/null
    getent group go-hk-agent >/dev/null
    test -r /usr/bin/git && test -x /usr/bin/git
    test -r /usr/bin/ssh && test -x /usr/bin/ssh
    test -r /usr/bin/docker && test -x /usr/bin/docker
    test -S /var/run/docker.sock
    getent group docker >/dev/null
    runuser -u go-hk-agent -- test -r /etc/go-hk-agent/keys/github-go-source-reader
    case "$phase" in
      preinstall)
        test "$(sha256sum /opt/go-hk-agent-rebuilt/hk_agent/transport.py | awk '{print $1}')" = "4301a7e920fc25d98ea8403ac00ebbdb6a864bcb092d33caf343ad28603ff490"
        test "$(sha256sum /etc/go-hk-agent/agent.json | awk '{print $1}')" = "82ab805b921081ec0299ffa20576963476e12f57e711438f46ada2342a7c7b30"
        test "$(sha256sum /opt/go-hk-agent-rebuilt/hk_agent/deployment_actions.py | awk '{print $1}')" = "7400ef03caf9473db73eccca5206233c81707ae742547489f0ed93728e5b323e"
        test ! -e /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py
        test ! -e /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v2
        test ! -e /var/lib/go-hk-test-pr
        test ! -e /etc/systemd/system/go-hk-agent.service.d/30-test-pr-docker-access.conf
        ;;
      postinstall)
        test -d /var/lib/go-hk-test-pr && test ! -L /var/lib/go-hk-test-pr
        test "$(stat -c %u:%g /var/lib/go-hk-test-pr)" = 0:0
        test "$(stat -c %a /var/lib/go-hk-test-pr)" = 711
        test -d /var/lib/go-hk-test-pr/builds && test ! -L /var/lib/go-hk-test-pr/builds
        test "$(stat -c %u:%g /var/lib/go-hk-test-pr/builds)" = "$(id -u go-hk-agent):$(id -g go-hk-agent)"
        test "$(stat -c %a /var/lib/go-hk-test-pr/builds)" = 700
        # The sealed-artifact store is written by the agent and read by the Hong
        # Kong executor as root, so its owner is the writer, never the reader.
        test -d /var/lib/go-hk-artifacts && test ! -L /var/lib/go-hk-artifacts
        test "$(stat -c %u:%g /var/lib/go-hk-artifacts)" = "$(id -u go-hk-agent):$(id -g go-hk-agent)"
        test "$(stat -c %a /var/lib/go-hk-artifacts)" = 700
        test -d /var/lib/go-hk-artifacts/objects && test ! -L /var/lib/go-hk-artifacts/objects
        test "$(stat -c %u:%g /var/lib/go-hk-artifacts/objects)" = "$(id -u go-hk-agent):$(id -g go-hk-agent)"
        test "$(stat -c %a /var/lib/go-hk-artifacts/objects)" = 700\n        test -d /var/lib/go-hk-artifacts/failures && test ! -L /var/lib/go-hk-artifacts/failures\n        test "$(stat -c %u:%g /var/lib/go-hk-artifacts/failures)" = "$(id -u go-hk-agent):$(id -g go-hk-agent)"\n        test "$(stat -c %a /var/lib/go-hk-artifacts/failures)" = 700
        test -f /etc/systemd/system/go-hk-agent.service.d/30-test-pr-docker-access.conf
        test "$(stat -c %u:%g /etc/systemd/system/go-hk-agent.service.d/30-test-pr-docker-access.conf)" = 0:0
        test "$(stat -c %a /etc/systemd/system/go-hk-agent.service.d/30-test-pr-docker-access.conf)" = 644
        grep -Fx 'SupplementaryGroups=docker' /etc/systemd/system/go-hk-agent.service.d/30-test-pr-docker-access.conf >/dev/null
        ! systemctl is-active --quiet go-hk-agent.service
        ;;
      *) exit 64 ;;
    esac
    ;;
  *) exit 64 ;;
esac
