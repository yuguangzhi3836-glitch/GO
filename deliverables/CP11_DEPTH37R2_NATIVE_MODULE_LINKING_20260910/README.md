# DEPTH37R2 native module linking

The prior iOS build compiled, but delayed startup logs proved a runtime failure: Cannot find native module ExpoAsset. SDK 53 autolinking searched the app node_modules but missed four Expo modules installed under node_modules/expo/node_modules. This delta adds that exact installed directory to autolinking searchPaths and adds a real installed-module discovery check. The dependency lock, dependency versions, backend and business UI remain unchanged.

Original failure: run 34471255577, candidate cb81f9ea32c88c4d349ed43d48c5b9d7027615ab. Documentation: https://docs.expo.dev/modules/autolinking/#searchpaths . Both native binaries must be rebuilt and startup must be verified before passing this fix. No deployment or production operation is authorized.
