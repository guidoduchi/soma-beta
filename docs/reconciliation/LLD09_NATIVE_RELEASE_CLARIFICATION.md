# LLD-09 native release dependency clarification

Accepted by the implementation owner on 2026-10-01, against design
`9a0e891127a771251afccca1a281b7ef7dde9e5f`.

No approved Windows x64 libpff/pypff build or frozen physical PST/OST corpus
currently exists. Do not invent or silently pin one. The exact libpff source
revision, build artifact and hash are intentionally assigned to the release
dependency manifest by `spec/lld/communications/technology.json`. LLD-12 final
package dependency hashes are release-candidate freeze evidence and do not block
ordinary implementation readiness.

Implement the CommunicationSourceAdapter boundary and `adapters/pff_reader.py`
architecture without exposing parser objects, raw exceptions or parser-specific
semantics across that boundary. Verify parser-independent behavior with
deterministic doubles and synthetic TransientMessageV1 evidence. Do not add an
arbitrary pypff version to the production baseline or substitute Outlook COM/MAPI.

Deferred release gates:

- **LLD09-PFF-RELEASE-PIN**: select and freeze the exact libpff source revision,
  Windows x64 build/toolchain and artifact hashes for the supported Python matrix.
- **LLD09-GOLDEN-CORPUS-FREEZE**: freeze sanitized/synthetic PST/OST/MSG fixture
  bytes and hashes; execute LLD09-C001 through LLD09-C012, privacy canaries and
  applicable LLD-12 packaging gates against the selected native build.

Native release certification remains blocked until both are resolved. Ordinary
LLD-09 implementation is not blocked. Synthetic boundary tests do not certify a
native library or the physical compatibility corpus.

The current static release bridge seam requires bounded, preflighted typed
messages, opaque generation-scoped provider positions, native read-only opens,
lazy bounded attachment reads and typed metadata. It performs no native-library
discovery. With no bridge installed, health is UNSUPPORTED. A release bridge must
prove allocation bounds before reading body/recipient/attachment data, truthful
folder discovery and exhaustion, exact native property normalization and source
immutability in the deferred physical compatibility matrix. It cannot confer
identity, matching, lifecycle, retention or coverage authority on parser objects.
