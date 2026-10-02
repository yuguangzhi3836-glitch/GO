# Aoluguya official gallery expansion

Base: PR198 commit f827a3aefd95fd95dedb2bd2ecc93ae01111ea90; application tree eef8adc0d99f679220e51efc9d6c5ca28ba6ab0c.

The approved gallery previously contained 21 room photos without room bindings. This change admits the exact measured 40-photo plan: 1 official homepage HERO and 39 GALLERY assets, including 18 public-area photos. The UI checks each asset role and renders its category during completion. Every image remains RIGHTS_UNKNOWN and nonpublishable; no room identity is inferred.

The new fixture has a separate filename. The existing 21-image fixture remains byte-identical; its original PR198 test source and test evidence are archived here. The current test rejects that old plan for this expanded action.

Category, caption and page provenance remain in the reviewed plan and completion UI only; the existing harvest API does not persist those fields. HERO is persisted and read back as an actual media role. This change does not claim authorization, public release, served-byte verification or cache persistence.

Two measured HK probes support 21 + 19 unique assets. The public-area report local copy has two trailing LF newlines, whereas its EASON original uses CRLF and one trailing newline; exact original serialization reconstructs SHA256 12e5ff5a599b129cc3900aae0e08f4e2fbfc415eddeb95f4fab79cb46245d431.

Application-only incremental files; no control-plane or PR201 source is included. Root must base the new Draft on the exact PR198 commit above.
