"""pi_auto_review capability — fail-closed boundary approval core.

Python behavioral port of ``pi-auto-review@0.3.2`` (MIT):
- broker: hard deny -> breaker -> model reviewer -> exact one-shot grant
- grants: stable canonical request hash, TTL, single-use store
- circuit breaker: consecutive/rolling denial thresholds
- policy: strict JSON decision parser, deterministic hard deny, bounded and
  redacted transcript evidence
- reviewer: trusted/project config, model review via ``earendil_works.pi_ai``

Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)
"""
from __future__ import annotations

from .broker import FAILURE_REVIEW, BoundaryApprovalBroker, BoundaryApprovalBrokerOptions
from .circuit_breaker import CircuitBreakerResult, DenialCircuitBreaker
from .grants import OneShotGrantStore, boundary_request_hash
from .policy import (
    MAX_EVIDENCE_ITEM_CHARACTERS,
    bounded_string,
    build_classifier_transcript,
    deterministic_hard_deny,
    effective_command,
    parse_decision,
    surface_of,
)
from .reviewer import (
    DEFAULT_CONFIG,
    EXTENSION_NAME,
    PACKAGE_ROOT,
    ReviewResult,
    apply_project_config,
    apply_user_config,
    assert_trusted_installation,
    complete,
    create_reviewer_broker,
    current_turn_scope,
    load_config,
    model_decision_to_boundary_review,
    package_config_path,
    protected_write_hard_deny,
    resolve_reviewer,
    session_config,
    validate_config,
)

__all__ = [
    "DEFAULT_CONFIG",
    "EXTENSION_NAME",
    "FAILURE_REVIEW",
    "MAX_EVIDENCE_ITEM_CHARACTERS",
    "PACKAGE_ROOT",
    "BoundaryApprovalBroker",
    "BoundaryApprovalBrokerOptions",
    "CircuitBreakerResult",
    "DenialCircuitBreaker",
    "OneShotGrantStore",
    "ReviewResult",
    "apply_project_config",
    "apply_user_config",
    "assert_trusted_installation",
    "boundary_request_hash",
    "bounded_string",
    "build_classifier_transcript",
    "complete",
    "create_reviewer_broker",
    "current_turn_scope",
    "deterministic_hard_deny",
    "effective_command",
    "load_config",
    "model_decision_to_boundary_review",
    "package_config_path",
    "parse_decision",
    "protected_write_hard_deny",
    "resolve_reviewer",
    "session_config",
    "surface_of",
    "validate_config",
]
