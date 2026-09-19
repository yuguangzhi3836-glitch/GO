"""The Hong Kong executor's last no-migration line of defence (CCV1-84 WP-2).

> **CCV1 V1 DOES NOT EXECUTE DATABASE MIGRATIONS.**

The Command Center refuses a candidate that declares the prohibited condition, and the
plan derivation refuses one whose declared migration graph is not the graph the
environment is on.  Both of those are refusals *before* a Task exists.  This module is
the third and last one, on the host that would actually run something: even if the
Command Center were wrong, the executor must not act on a candidate that needs a
migration it is not allowed to run.

The vocabulary is the same two stable codes the other two layers use, and no third:

* `E_DATABASE_MIGRATION_REQUIRED`      -- the candidate declares the prohibited condition;
* `E_DATABASE_MIGRATION_GRAPH_MISMATCH` -- the candidate's graph is not the environment's,
  or its graph cannot be established at all.

**STATUS: NOT WIRED, and deliberately so.**  Nothing in this module is called by
`deploy_runtime.py`, and a test in the Hong Kong lineage suite asserts that, so the
absence cannot be mistaken for a check that passed.  The reason is contract, not
oversight: the DEPLOY Task parameters the agent validates are an *exact* set
(`hk_agent/deployment_actions.py`, `validate()`) and carry no candidate migration fact;
supplying one is the Task and Evidence contract extension that **WP-4** owns.  Wiring
this module without that extension would mean inventing a Task field, which is the one
thing WP-2 is not allowed to do.

What WP-2 therefore delivers is the check itself, complete and tested, plus the exact
seam it plugs into: `precheck()` is what a wired `run_deploy()` calls, with the
candidate's migration declaration and the environment's head.  The day WP-4 supplies
those two values, the wiring is one call.

This module is pure: it reads nothing, writes nothing, runs nothing.  It exists to
decide, and to refuse.
"""
# The two stable public codes (CCV1-82 CONTRACT SPEC section 10).  Declared here as
# well as in the two Command Center components because the executor is a different
# component on a different host and cannot import theirs; the lineage suite pins the
# three copies equal, so they cannot drift apart unnoticed.
E_DATABASE_MIGRATION_REQUIRED = 'E_DATABASE_MIGRATION_REQUIRED'
E_DATABASE_MIGRATION_GRAPH_MISMATCH = 'E_DATABASE_MIGRATION_GRAPH_MISMATCH'

# The three outcomes of asking this module a question.  `FACT_NOT_SUPPLIED` exists so
# that "nobody gave me the candidate's migration declaration" is a distinct, observable
# answer rather than something that can be read as a pass.
VERIFIED_NO_MIGRATION = 'VERIFIED_NO_MIGRATION'
REFUSED_MIGRATION_REQUIRED = 'REFUSED_MIGRATION_REQUIRED'
REFUSED_MIGRATION_GRAPH_MISMATCH = 'REFUSED_MIGRATION_GRAPH_MISMATCH'
FACT_NOT_SUPPLIED = 'NOT_SUPPLIED_PENDING_WP4'

# The declaration this check reads out of a candidate migration fact.  Both are named
# explicitly rather than defaulted: a fact missing one of them is not a fact this check
# can conclude anything from.
DECLARATION_FIELDS = ('migration_required', 'migration_head')


class Reject(ValueError):
    """A refusal, carrying one of the two stable codes as its message."""


def verdict(candidate_migration, supported_migration_head):
    """What this candidate implies for a no-migration deployment.

    `candidate_migration` is the candidate's migration declaration -- the part of the
    candidate fact this check needs, and nothing else -- or None when the caller has
    none.  `supported_migration_head` is the graph the environment is on.

    Returns one of `VERIFIED_NO_MIGRATION`, `REFUSED_MIGRATION_REQUIRED`,
    `REFUSED_MIGRATION_GRAPH_MISMATCH` or `FACT_NOT_SUPPLIED`.  It never raises: the
    caller decides what a refusal costs, and `precheck()` is the caller that makes it
    cost the deployment.

    Both refusals are returned rather than one `False`, because they are different
    findings: one is about the candidate and one is about the host, and an operator
    answers them differently.
    """
    if candidate_migration is None:
        return FACT_NOT_SUPPLIED
    if not isinstance(candidate_migration, dict):
        return REFUSED_MIGRATION_GRAPH_MISMATCH
    for field in DECLARATION_FIELDS:
        if field not in candidate_migration:
            # A declaration that does not say which graph it is on cannot be shown to
            # be on ours.  Missing is not "fine by default".
            return REFUSED_MIGRATION_GRAPH_MISMATCH
    if candidate_migration['migration_required'] is not False:
        # `is not False` rather than falsy: 0, '', None and a missing key are all
        # "does not declare the prohibited condition absent", which is not a licence
        # to deploy.  A declaration has to be made, not merely not contradicted.
        return REFUSED_MIGRATION_REQUIRED
    if candidate_migration['migration_head'] != supported_migration_head:
        return REFUSED_MIGRATION_GRAPH_MISMATCH
    return VERIFIED_NO_MIGRATION


def precheck(candidate_migration, supported_migration_head):
    """The check a wired `run_deploy()` must run before it touches anything.

    Returns `VERIFIED_NO_MIGRATION`, or raises `Reject` with one of the two stable
    codes.  It runs no command, opens no file and mutates nothing, so it can be called
    as the first statement of the deploy path.

    An unsupplied fact refuses, in the graph code: "I was not told which graph this
    candidate is on" and "this candidate is on a different graph" both mean the
    deployment cannot be shown to be a no-migration deployment, which is the only kind
    V1 may perform.  Keeping it to two codes is the point -- a third spelling for the
    same outcome is what WP-2 exists to remove.
    """
    outcome = verdict(candidate_migration, supported_migration_head)
    if outcome == VERIFIED_NO_MIGRATION:
        return outcome
    if outcome == REFUSED_MIGRATION_REQUIRED:
        raise Reject(E_DATABASE_MIGRATION_REQUIRED)
    raise Reject(E_DATABASE_MIGRATION_GRAPH_MISMATCH)


# The seam WP-4 completes, named so it can be found rather than remembered.  A wired
# `deploy_runtime.run_deploy()` calls:
#
#     migration_guard.precheck(candidate_migration, supported_migration_head)
#
# as its first statement -- before `_precheck()` and before any Docker argv is built --
# with `candidate_migration` taken from the candidate fact the Task's
# `candidate_contract_sha256` addresses, and `supported_migration_head` from the
# install fact the launcher already trusts.  Neither exists on the host today.
WP4_SEAM = 'deploy_runtime.run_deploy -> migration_guard.precheck'
