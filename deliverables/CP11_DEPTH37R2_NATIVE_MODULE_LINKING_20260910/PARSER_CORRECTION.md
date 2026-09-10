# Installed-module checker correction

The prior check invoked SDK 53 search without --json and attempted to parse human-readable output. Run 34472468617 stopped before native compilation. This revision explicitly requests JSON and verifies discovery for both apple and android. The autolinking configuration and dependency lock are unchanged. Original failed candidate 0c3712b086b5eddab453b2664a21cbe2567537b8 is retained.
