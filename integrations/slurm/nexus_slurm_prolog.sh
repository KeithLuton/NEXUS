#!/usr/bin/env bash
# NEXUS v4.0 — SLURM prolog hook
#
# Installed as /etc/slurm/prolog.d/nexus_slurm_prolog.sh
# Called by slurmd before a job starts on a node.
#
# This prolog asks the local NEXUS agent whether the node has thermal
# headroom for the incoming job. If NEXUS says no, the prolog exits
# non-zero and SLURM will defer the job.

set -u

NEXUS_SOCKET="${NEXUS_SOCKET:-/var/run/nexus/agent.sock}"
NEXUS_TIMEOUT_S="${NEXUS_TIMEOUT_S:-5}"

# Fail open if the NEXUS agent isn't running — don't block jobs on a
# missing optional component. Operators who want strict behavior can
# set NEXUS_REQUIRED=1.
if [ ! -S "${NEXUS_SOCKET}" ]; then
    if [ "${NEXUS_REQUIRED:-0}" = "1" ]; then
        echo "nexus-prolog: agent socket ${NEXUS_SOCKET} not present" >&2
        exit 1
    fi
    exit 0
fi

# Ask the agent. Expect "ok" on stdout for a green light.
RESULT=$(timeout "${NEXUS_TIMEOUT_S}" \
    curl --silent --unix-socket "${NEXUS_SOCKET}" \
    "http://localhost/thermal/admit?job_id=${SLURM_JOB_ID:-unknown}" \
    2>/dev/null || echo "timeout")

case "${RESULT}" in
    ok)
        exit 0
        ;;
    defer)
        echo "nexus-prolog: deferred by thermal policy" >&2
        exit 1
        ;;
    *)
        # Unknown / timeout / agent error — fail open.
        exit 0
        ;;
esac
