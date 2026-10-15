"""``s0ma-docs-model@1`` — the typed vocabulary the documentation is built from.

The reusable model and provider machinery for the documentation
application lives here, per ADR-012. This milestone (C1) lands the
substrate only:

``records``
    The frozen record types — concepts, served capabilities, journeys,
    teaching sequences, catalog rows, citations, provenance and the build
    stamp — with every field classified authored or sourced.
``ids``
    Stable identity: the table of addressable forms, their validation,
    their normalization, and the resolution of renamed ids.
``serialize``
    One canonical text form per bundle and one digest form, so that the
    same records always produce the same bytes.

Everything here is stdlib-only on purpose. Providers, gates, renderers and
read surfaces all read these records, and none of them should have to take
on a dependency to do it.
"""

from __future__ import annotations

from s0ma_dsl.docs_model.ids import (
    ID_CLASSES,
    ID_FORMS,
    AliasIndex,
    DocsIdError,
    IdForm,
    cli_id,
    id_form,
    is_valid_id,
    normalize_id,
    same_identity,
    studi0_action_id,
    studi0_public_name,
    validate_id,
)
from s0ma_dsl.docs_model.records import (
    AUTHORITY_ORDER,
    BUILD_CHANNELS,
    BUILD_STAMP_ONLY_FIELDS,
    FIELD_CLASS,
    HISTORICAL_CHANNEL,
    PREVIEW_CHANNEL,
    RECORD_TYPES,
    RELEASE_CHANNEL,
    SCHEMA,
    AliasEntry,
    AuthorityDelegation,
    AuthorityRef,
    BuildStamp,
    ConceptRecord,
    DocsBundle,
    DocsModelError,
    DocsSchemaVersionError,
    DocumentRecord,
    ExampleRef,
    FieldClass,
    JourneyRecord,
    JourneyStep,
    Provenance,
    RecoveryPath,
    SurfaceRecord,
    TeachingSequence,
    TeachingStep,
    authored_prose_fields,
    field_class,
    validate_schema_version,
    validate_single_paragraph,
)
from s0ma_dsl.docs_model.serialize import (
    DIGEST_CHARS,
    DIGEST_PREFIX,
    DocsSerializationError,
    canonical_json,
    content_hash,
    deserialize_bundle,
    facts_hash,
    record_from_plain,
    serialize_bundle,
    snapshot_hash,
    stamped,
    to_plain,
)

__all__ = [
    "AUTHORITY_ORDER",
    "BUILD_CHANNELS",
    "BUILD_STAMP_ONLY_FIELDS",
    "DIGEST_CHARS",
    "DIGEST_PREFIX",
    "FIELD_CLASS",
    "HISTORICAL_CHANNEL",
    "ID_CLASSES",
    "ID_FORMS",
    "PREVIEW_CHANNEL",
    "RECORD_TYPES",
    "RELEASE_CHANNEL",
    "SCHEMA",
    "AliasEntry",
    "AliasIndex",
    "AuthorityDelegation",
    "AuthorityRef",
    "BuildStamp",
    "ConceptRecord",
    "DocsBundle",
    "DocsIdError",
    "DocsModelError",
    "DocsSchemaVersionError",
    "DocsSerializationError",
    "DocumentRecord",
    "ExampleRef",
    "FieldClass",
    "IdForm",
    "JourneyRecord",
    "JourneyStep",
    "Provenance",
    "RecoveryPath",
    "SurfaceRecord",
    "TeachingSequence",
    "TeachingStep",
    "authored_prose_fields",
    "canonical_json",
    "cli_id",
    "content_hash",
    "deserialize_bundle",
    "facts_hash",
    "field_class",
    "id_form",
    "is_valid_id",
    "normalize_id",
    "record_from_plain",
    "same_identity",
    "serialize_bundle",
    "snapshot_hash",
    "stamped",
    "studi0_action_id",
    "studi0_public_name",
    "to_plain",
    "validate_id",
    "validate_schema_version",
    "validate_single_paragraph",
]
