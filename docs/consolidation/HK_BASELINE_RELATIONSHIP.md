# HK-STAGING archived runtime relationship

## Conclusion

`HK_BASELINE_RELATIONSHIP=PARTIAL_ANCESTRY`

This is a **source-content** relationship, not a Git commit ancestry claim. The HK runtime snapshot was recovered from a running image on 2026-09-11 and is not itself a historical product Git commit.

## Compared identities

### HK archived runtime

- archive root: `hk-staging/source/runtime/`
- running business image at observation: `go-hotel:aoluguya-direct-r3-1-20260906`
- image ID: `sha256:66c540878ff5dd8d2d089059288c3d9f0c45f880514f7b053bd50defb9e8c324`
- runtime application file count: `577`
- runtime source manifest SHA-256: `2c2606a33c5b124062c5ea99b7f2431d2714fd8e453529549431c84205087022`
- host build-context file count: `577`
- host build-context manifest SHA-256: `3dd3cd35985f24b55b87c8793dff010c2b23269b9b6d12a5367d14eeb8c30c7d`
- runtime-vs-host common paths: `577`
- byte-identical runtime-vs-host paths: `576`
- known runtime-vs-host drift: `src/go_hotel/connectors/aoluguya_test.py`

### Earliest PR product lineage

PR #2 starts DEPTH10 from the DEPTH09 archive lineage. DEPTH09 identifies:

- baseline source tree SHA-256: `c4c00f4476a3c7041ae7ed10a10bef60dc2efcf8c56e86c83d35ca24748310ea`
- resulting DEPTH09 source tree SHA-256: `1c92d5d79c48a58a5194a57fbd61e395156e5b710bfe2e27e171a9b3d50c43bd`
- deployment: false
- release gates: HOLD

### Final selected source

- semantic P0.3 head: `e0742e2168b9a0fc0c1d6391f767c3219efb5e97`
- sealed package: `CP11_DEPTH40_P03_PARENT_20260911`
- canonical source files: `1271`
- canonical source tree SHA-256: `64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667`

## Direct path-level evidence

DEPTH09's delta manifest records `before_sha256` and resulting SHA-256 values. Those can be compared to the HK runtime source manifest.

| Application path | HK archived runtime SHA-256 | DEPTH09 before SHA-256 | DEPTH09 result SHA-256 | Final DEPTH40 SHA-256 | Interpretation |
|---|---|---|---|---|---|
| `src/go_hotel/services/hotel_autopage_factory.py` | `8dacd2d1172f7e2bd82ff8a1350d6cfce9327e07e7017e017415c04984cc838d` | same | `02b7cc98204f5198bbc159b61cf5dbde94597c0ebc7d1e5eb54b9cd766181855` | same as DEPTH09 result | direct content ancestry from HK-like baseline into DEPTH09 and retained through final source |
| `src/go_hotel/services/hotel_discovery_orchestrator.py` | `7adad99dd9cbb39ad95d24b44fdaf72c29237ee6f71fc35a33e544a1bb06402d` | same | `3e50751f45dd5176b9014573b01fb0c6afd890d42e2ecf39c185f0a4dfaa1f71` | same as DEPTH09 result | direct content ancestry and retention |
| `src/go_hotel/services/hotel_infrastructure_p0.py` | `25e040840f3d9814189d99ddd2f5696e7045e9ed070522cd876119e396805c01` | same | `9dac943866ec1e688f6b0c66fd018d5f5e77625ff9da0cf079d1f0d642638701` | same as DEPTH09 result | direct content ancestry and retention |
| `src/go_hotel/services/media_harvester.py` | `114446f88793961c8daf3c4d49af5ca8c765397c0cf247d9fc5e6534476ad264` | `3661ed936e4495e1897bc29855933a30919f425a736ac731149e1828d0da5361` | `0b12ae55d6e4f1edd2217648b9da126ecd3f56e8381f21326dc8a76a9d9b2492` | `62a9181c919fd9deb38f7a52b130cc66eab51e0cc3059fd8c998055f0bfa1423` | HK is not the uniform whole-tree parent of DEPTH09; this path had already diverged |

The first three paths prove that material from the HK-era application baseline participates in the DEPTH09→final lineage. The fourth path proves that the entire HK archived runtime cannot honestly be labeled IDENTICAL or a strict whole-tree ANCESTOR of DEPTH09.

Therefore:

- `IDENTICAL` is false: 577 vs 1271 files and different source digests.
- strict whole-tree `ANCESTOR` is not proven and is contradicted by path-level divergence.
- `UNRELATED` is false because multiple material business files match DEPTH09's recorded pre-change bytes exactly and those changes are retained in the final source.
- `PARTIAL_ANCESTRY` is the strongest evidence-supported label.

## What this means operationally

The current HK archive is **not** the latest product source and must not be used as the canonical builder input. It is a historical/operational runtime baseline useful for deployment-delta analysis.

The canonical builder input established by this consolidation is `application/` on the consolidation branch. Deployment planning must still compare that source/runtime requirement to the current live HK state and use the separately proven signed-task execution path; this document is not deployment authority.