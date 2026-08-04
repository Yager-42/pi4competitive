"""Strict reviewer policy — decision parsing, hard deny, bounded evidence.

Source: pi-auto-review@0.3.2 ``src/policy.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)

Host delta (ADAPT): transcript evidence is built from Python Pi message shapes
(``AssistantMessage`` / ``ToolResultMessage`` content parts) instead of
TypeScript message parts; decision validation, hard-deny rules, redaction,
escape, relevance selection, and budget semantics are preserved exactly.
"""
from __future__ import annotations

import json
import re
from typing import Any, NotRequired, TypeAlias, TypedDict
from urllib.parse import unquote

RiskLevel: TypeAlias = str


class ModelDecision(TypedDict):
    outcome: str
    risk_level: RiskLevel
    user_authorization: str
    rationale: str


class PermissionDetailsLike(TypedDict, total=False):
    surface: str | None
    toolName: str
    command: str
    path: str
    target: str
    toolInputPreview: str


class TranscriptConfig(TypedDict):
    maxUserTranscriptTokens: int
    maxToolTranscriptTokens: int
    maxRelevantResultTokens: NotRequired[int]


class TranscriptResult(TypedDict):
    text: str
    userCharacters: int
    toolCharacters: int
    relevantResultCharacters: int
    truncated: bool


class Evidence(TypedDict):
    index: int
    kind: str
    text: str


class RelevantBoundaryRequest(TypedDict, total=False):
    id: str
    source: str
    surface: str
    operation: str
    command: str
    path: str
    resolvedPath: str
    destination: str
    toolCallId: str
    toolName: str


class HardDeny(TypedDict):
    rule: str
    reason: str


MAX_EVIDENCE_ITEM_CHARACTERS = 4_000

_VALID_OUTCOMES = ("allow", "deny", "defer")
_VALID_RISK_LEVELS = ("low", "medium", "high", "critical")
_VALID_AUTHORIZATIONS = ("unknown", "low", "medium", "high")


def _exact_keys(record: dict[str, Any], expected: tuple[str, ...]) -> bool:
    return sorted(record) == sorted(expected)


def parse_decision(text: str) -> ModelDecision:
    try:
        value = json.loads(text.strip())
    except json.JSONDecodeError:
        raise ValueError("reviewer returned non-JSON output") from None
    if not isinstance(value, dict):
        raise ValueError("reviewer returned a non-object")
    if not _exact_keys(value, ("outcome", "risk_level", "user_authorization", "rationale")):
        raise ValueError("reviewer returned unexpected fields")
    if value["outcome"] not in _VALID_OUTCOMES:
        raise ValueError("reviewer returned an invalid outcome")
    if value["risk_level"] not in _VALID_RISK_LEVELS:
        raise ValueError("reviewer returned an invalid risk level")
    if value["user_authorization"] not in _VALID_AUTHORIZATIONS:
        raise ValueError("reviewer returned invalid user authorization")
    rationale = value["rationale"]
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 600:
        raise ValueError("reviewer returned an invalid rationale")

    decision: ModelDecision = {
        "outcome": value["outcome"],
        "risk_level": value["risk_level"],
        "user_authorization": value["user_authorization"],
        "rationale": rationale.strip(),
    }
    if decision["outcome"] == "allow" and decision["risk_level"] == "critical":
        raise ValueError("reviewer attempted a critical-risk allow")
    if (
        decision["outcome"] == "allow"
        and decision["risk_level"] == "high"
        and decision["user_authorization"] not in ("medium", "high")
    ):
        raise ValueError("reviewer attempted an unauthorized high-risk allow")
    if decision["outcome"] == "defer" and decision["risk_level"] not in ("medium", "high"):
        raise ValueError("reviewer returned an inconsistent defer")
    return decision


def surface_of(details: PermissionDetailsLike) -> str:
    surface = details.get("surface")
    if isinstance(surface, str) and surface:
        return surface
    if details.get("path"):
        return "path"
    if details.get("command"):
        return "bash"
    return details.get("toolName") or "unknown"


def effective_command(details: PermissionDetailsLike) -> str | None:
    command = details.get("command")
    if command and command.strip():
        return command
    if surface_of(details) != "bash_escalated":
        return None
    preview = (details.get("toolInputPreview") or "").strip()
    if not preview:
        return None
    preview = re.sub(r"^input\s+", "", preview)
    try:
        value = json.loads(preview)
    except json.JSONDecodeError:
        # A bounded/truncated preview is deliberately not guessed.
        return None
    if isinstance(value, dict) and isinstance(value.get("command"), str):
        return value["command"]
    return None


def deterministic_hard_deny(details: PermissionDetailsLike) -> HardDeny | None:
    """Keep this list narrow: these checks are terminal and cannot be overridden
    by the model or the user prompt. Ambiguous or merely high-risk actions belong
    in the detailed reviewer, which can defer to the human."""
    command = effective_command(details)
    command = command.strip() if command else ""
    if not command:
        return None

    for segment in re.split(r"&&|\|\||;|\n", command):
        is_rm = re.search(r"(?:^|\s)(?:\/[^\s/]+)*\/?rm(?:\s|$)", segment, re.IGNORECASE)
        recursive = re.search(r"(?:^|\s)--recursive(?:\s|$)", segment, re.IGNORECASE) or re.search(
            r"(?:^|\s)-[A-Za-z]*r[A-Za-z]*(?:\s|$)", segment, re.IGNORECASE
        )
        forced = re.search(r"(?:^|\s)--force(?:\s|$)", segment, re.IGNORECASE) or re.search(
            r"(?:^|\s)-[A-Za-z]*f[A-Za-z]*(?:\s|$)", segment, re.IGNORECASE
        )
        root_or_home_target = re.search(
            r"""(?:^|\s)["']?(?:\/(?:\*)?|~(?:\/(?:\*)?)?|\$HOME(?:\/(?:\*)?)?|\$\{HOME\}(?:\/(?:\*)?)?)["']?(?=\s|$)""",
            segment,
            re.IGNORECASE,
        )
        if is_rm and recursive and forced and root_or_home_target:
            return {
                "rule": "destructive-root-or-home-delete",
                "reason": "recursive forced deletion of root or the home directory is forbidden",
            }

    if (
        re.search(r"\bcurl\b[^;\n]*(?:--insecure\b|-[A-Za-z]*k[A-Za-z]*(?:\s|$))", command, re.IGNORECASE)
        or re.search(r"\bwget\b[^;\n]*--no-check-certificate\b", command, re.IGNORECASE)
        or re.search(r"\bgit\s+config\b[^;\n]*http\.sslverify\s+false\b", command, re.IGNORECASE)
        or re.search(r"\bnpm\s+config\s+set\s+strict-ssl\s+false\b", command, re.IGNORECASE)
        or re.search(r"\bNODE_TLS_REJECT_UNAUTHORIZED\s*=\s*0\b", command, re.IGNORECASE)
    ):
        return {
            "rule": "transport-security-weakening",
            "reason": "disabling TLS or certificate verification is forbidden",
        }

    credential_source = re.compile(
        r"""(?:\/|~\/|\$HOME\/|\$\{HOME\}\/)(?:\.ssh\/(?:id_[A-Za-z0-9_-]+|authorized_keys)|\.aws\/credentials|\.kube\/config|\.docker\/config\.json|\.npmrc|\.netrc|\.pi\/agent\/auth\.json)|(?:^|[\/@\s])\.env(?:\s|$)""",
        re.IGNORECASE,
    )
    network_upload = re.compile(
        r"""\b(?:curl\b[^;\n]*(?:--data(?:-binary|-raw|-urlencode)?|-d|--form|-F|--upload-file|-T)|wget\b[^;\n]*(?:--post-file|--post-data)|(?:nc|ncat|socat)\b)""",
        re.IGNORECASE,
    )
    credential_pipe = re.compile(
        r"""(?:cat|sed|awk|base64|openssl)\b[^|;\n]*(?:\.ssh|\.aws|\.kube|\.docker|\.npmrc|\.netrc|\.env|auth\.json)[^|;\n]*\|[^;\n]*\b(?:curl|wget|nc|ncat|socat)\b""",
        re.IGNORECASE,
    )
    if (credential_source.search(command) and network_upload.search(command)) or credential_pipe.search(command):
        return {
            "rule": "credential-exfiltration",
            "reason": "sending credentials or secret configuration to a network sink is forbidden",
        }

    authorization_path = r"(?:authorized_keys|/etc/sudoers|/etc/sudoers\.d/)"
    redirected_authorization_write = re.compile(
        rf"\b(?:printf|echo|cat)\b[^;\n]*(?:>>?|\|\s*tee\b)[^;\n]*{authorization_path}",
        re.IGNORECASE,
    )
    direct_authorization_write = re.compile(
        rf"\b(?:tee|cp|mv|install)\b[^;\n]*{authorization_path}",
        re.IGNORECASE,
    )
    if redirected_authorization_write.search(command) or direct_authorization_write.search(command):
        return {
            "rule": "access-persistence",
            "reason": "adding SSH or sudo authorization persistence is forbidden",
        }

    return None


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return "[unserializable]"


def bounded_string(value: Any) -> str:
    rendered = _stringify(value)
    if len(rendered) <= MAX_EVIDENCE_ITEM_CHARACTERS:
        return rendered
    half = (MAX_EVIDENCE_ITEM_CHARACTERS - 32) // 2
    return f"{rendered[:half]}\n…[middle truncated]\n{rendered[-half:]}"


def _user_text(message: dict[str, Any]) -> str:
    if message.get("role") != "user":
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            parts.append(part["text"])
    return "\n".join(parts).strip()


def _tool_texts(message: dict[str, Any]) -> list[str]:
    if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
        return []
    out: list[str] = []
    for part in message["content"]:
        if not isinstance(part, dict):
            continue
        if part.get("type") != "toolCall" or not isinstance(part.get("name"), str):
            continue
        # Tool arguments are model/user-controlled and may contain credentials
        # just like a tool result. Redact before adding them to classifier input.
        serialized = _stringify(part.get("arguments") or {})
        arguments = bounded_string(_redact_sensitive_result(serialized))
        out.append(f"{part['name']} {arguments}")
    return out


def _extract_evidence(entries: list[Any]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        user = _user_text(message)
        if user:
            evidence.append({"index": len(evidence), "kind": "user", "text": bounded_string(user)})
        for tool in _tool_texts(message):
            evidence.append({"index": len(evidence), "kind": "tool", "text": tool})
    return evidence


def _redact_sensitive_result(value: str) -> str:
    value = re.sub(
        r"-----BEGIN [^-]*(?:PRIVATE KEY|OPENSSH PRIVATE KEY)-----[\s\S]*?-----END [^-]*(?:PRIVATE KEY|OPENSSH PRIVATE KEY)-----",
        "[REDACTED PRIVATE KEY]",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(authorization\s*:\s*(?:bearer|basic)|bearer)\s+[A-Za-z0-9._~+/=-]+",
        r"\1 [REDACTED]",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"""(["'])([A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY))\1\s*:\s*(["'])[^"'\r\n]*\3""",
        r"\1\2\1:\3[REDACTED]\3",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b([A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY))\s*[:=]\s*([^\s]+)",
        r"\1=[REDACTED]",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\b(?:ghp|github_pat|sk)-[A-Za-z0-9_-]{12,}\b", "[REDACTED TOKEN]", value)
    return value


def _escape_evidence_markup(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _result_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    text = "\n".join(
        part["text"]
        for part in content
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
    ).strip()
    return bounded_string(_redact_sensitive_result(text))


class ToolCallRecord(TypedDict):
    id: str
    name: str
    arguments: Any
    rendered: str


def _message_record(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    return message


def _command_argument(call: ToolCallRecord) -> str:
    arguments = call.get("arguments")
    if isinstance(arguments, dict) and isinstance(arguments.get("command"), str):
        return arguments["command"]
    return ""


class ProviderBranchQuery(TypedDict):
    provider: str
    branch: str


def _normalized_branch(value: str) -> str | None:
    branch = re.sub(r"^refs\/heads\/", "", value)
    try:
        branch = unquote(branch)
    except Exception:  # noqa: BLE001
        return None
    if branch and not re.search(r"[\s;&|`$<>]", branch):
        return branch
    return None


def _explicit_push_branch(command: str) -> str | None:
    if re.search(r"[\n;&|`<>]|\$\(", command):
        return None
    words = [
        re.sub(r"^([\"'])(.*)\1$", r"\2", word)
        for word in command.strip().split()
    ]
    git = next(
        (index for index, word in enumerate(words) if re.search(r"(?:^|\/)git$", word)),
        -1,
    )
    if git < 0 or git + 1 >= len(words) or words[git + 1] != "push":
        return None
    positional = [word for word in words[git + 2 :] if word and not word.startswith("-")]
    # A single explicit refspec keeps the provider evidence bound to the whole
    # push. Multi-ref pushes deliberately receive only the generic Git context.
    if len(positional) != 2:
        return None
    refspec = positional[-1]
    destination = refspec[refspec.rfind(":") + 1 :] if ":" in refspec else refspec
    return _normalized_branch(destination)


def _provider_branch_query(command: str) -> ProviderBranchQuery | None:
    if re.search(r"[\n;&|`<>]|\$\(", command):
        return None
    github = re.match(
        r"""^gh\s+api\s+["']?\/?repos\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/branches\/([^\/\s"']+)(?:\/protection)?["']?$""",
        command.strip(),
    )
    if github:
        branch = _normalized_branch(github.group(1))
        return {"provider": "github", "branch": branch} if branch else None
    gitlab = re.match(
        r"""^glab\s+api\s+["']?\/?projects\/[A-Za-z0-9_.%/-]+\/protected_branches\/([^\/\s"']+)["']?$""",
        command.strip(),
    )
    if gitlab:
        branch = _normalized_branch(gitlab.group(1))
        return {"provider": "gitlab", "branch": branch} if branch else None
    return None


def _relevance_reason(
    call: ToolCallRecord,
    request: RelevantBoundaryRequest,
) -> str | None:
    if request.get("toolCallId") and call["id"] == request["toolCallId"]:
        return "same-tool"
    call_text = call["rendered"].lower()
    needles = [
        value.lower()
        for value in (
            request.get("path"),
            request.get("resolvedPath"),
            request.get("destination"),
            request.get("command"),
        )
        if value is not None and len(value) >= 3
    ]
    tool_name = request.get("toolName")
    names_match = bool(tool_name) and (
        call["name"] == tool_name
        or call["name"].endswith(f"/{tool_name}")
        or tool_name.endswith(f"/{call['name']}")
    )
    current_command = request.get("command") or ""
    prior_command = _command_argument(call)
    pushed_branch = _explicit_push_branch(current_command)
    provider_query = _provider_branch_query(prior_command)
    destructive = bool(re.search(r"\b(?:rm|rmdir|unlink|trash|delete)\b", current_command, re.IGNORECASE))
    read_only_check = bool(re.search(r"^\s*(?:stat|ls|find|test|readlink|realpath)\b", prior_command))
    targets = [
        value.lower()
        for value in (request.get("path"), request.get("resolvedPath"))
        if value is not None
    ]
    if (
        destructive
        and read_only_check
        and any(target in prior_command.lower() for target in targets)
    ):
        return "delete-precheck"
    if re.search(r"\bgit\b[\s\S]*\bpush\b", current_command, re.IGNORECASE) and re.search(
        r"^\s*git\s+(?:remote|branch|status|rev-parse|config\s+--get\s+remote)", prior_command
    ):
        return "git-push-context"
    if (
        pushed_branch
        and provider_query
        and provider_query["branch"] == pushed_branch
    ):
        return "provider-branch-protection"
    if (names_match or len(needles) > 0) and any(needle in call_text for needle in needles):
        return "same-tool"
    return None


def _relevant_result_evidence(
    entries: list[Any],
    request: RelevantBoundaryRequest,
) -> list[dict[str, Any]]:
    calls: dict[str, ToolCallRecord] = {}
    results: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        message = _message_record(entry)
        if message is None:
            continue
        if message.get("role") == "assistant" and isinstance(message.get("content"), list):
            for part in message["content"]:
                if not isinstance(part, dict):
                    continue
                if part.get("type") != "toolCall" or not isinstance(part.get("name"), str):
                    continue
                call_id = (
                    part.get("id")
                    if isinstance(part.get("id"), str)
                    else part.get("toolCallId")
                    if isinstance(part.get("toolCallId"), str)
                    else None
                )
                if not call_id:
                    continue
                calls[call_id] = {
                    "id": call_id,
                    "name": part["name"],
                    "arguments": part.get("arguments"),
                    "rendered": f"{part['name']} {bounded_string(part.get('arguments') or {})}",
                }
            continue
        if message.get("role") != "toolResult" or not isinstance(message.get("toolCallId"), str):
            continue
        call = calls.get(message["toolCallId"])
        if call is None:
            continue
        reason = _relevance_reason(call, request)
        text = _result_text(message)
        if reason and text:
            results.append({
                "index": index,
                "text": (
                    f"<tool-result reason=\"{reason}\" tool=\"{_escape_evidence_markup(call['name'])}\">\n"
                    f"{_escape_evidence_markup(text)}\n</tool-result>"
                ),
            })
    return results


def _sandbox_trap_evidence(request: RelevantBoundaryRequest) -> str | None:
    if request.get("source") != "sandbox-runtime":
        return None
    rendered = _escape_evidence_markup(
        bounded_string({
            "surface": request.get("surface"),
            "operation": request.get("operation"),
            "path": request.get("path"),
            "resolvedPath": request.get("resolvedPath"),
            "destination": request.get("destination"),
            "process": request.get("toolName"),
        })
    )
    return f"<sandbox-trap>\n{rendered}\n</sandbox-trap>"


def _select_evidence(
    evidence: list[Evidence],
    kind: str,
    budget_characters: int,
) -> dict[str, Any]:
    candidates = [item for item in evidence if item["kind"] == kind]
    if not candidates or budget_characters <= 0:
        return {"selected": [], "truncated": len(candidates) > 0}

    selected: dict[int, Evidence] = {}
    remaining = budget_characters

    def add(item: Evidence, limit: int | None = None) -> None:
        nonlocal remaining
        cap = remaining if limit is None else min(remaining, limit)
        if item["index"] in selected or remaining <= 0:
            return
        text = item["text"][:cap]
        if not text:
            return
        selected[item["index"]] = {**item, "text": text}
        remaining -= len(text)

    # Keep the original user intent as an anchor, then fill from newest to oldest.
    if kind == "user":
        first_budget = (
            max(1, budget_characters // 2) if len(candidates) > 1 else budget_characters
        )
        add(candidates[0], first_budget)
        if len(candidates) > 1:
            add(candidates[-1])
    for index in range(len(candidates) - 1, -1, -1):
        add(candidates[index])

    original = {item["index"]: item["text"] for item in candidates}
    return {
        "selected": [selected[index] for index in sorted(selected)],
        "truncated": len(selected) < len(candidates) or any(
            len(item["text"]) < len(original[item["index"]]) for item in selected.values()
        ),
    }


def build_classifier_transcript(
    entries: list[Any],
    config: TranscriptConfig,
    request: RelevantBoundaryRequest | None = None,
) -> TranscriptResult:
    request = request or {}
    evidence = _extract_evidence(entries)
    users = _select_evidence(evidence, "user", config["maxUserTranscriptTokens"] * 4)
    tools = _select_evidence(evidence, "tool", config["maxToolTranscriptTokens"] * 4)
    selected = sorted(
        [*users["selected"], *tools["selected"]],
        key=lambda item: item["index"],
    )
    base_rendered = "\n\n".join(
        f"<{item['kind']}>\n{_escape_evidence_markup(item['text'])}\n</{item['kind']}>"
        for item in selected
    )
    relevant_budget = (
        config.get("maxRelevantResultTokens", config["maxToolTranscriptTokens"]) * 4
    )
    trap = _sandbox_trap_evidence(request)
    relevant_candidates = [
        *([{"index": 2**63 - 1, "text": trap}] if trap else []),
        *_relevant_result_evidence(entries, request),
    ]
    relevant_remaining = relevant_budget
    relevant_selected: list[str] = []
    for candidate in reversed(relevant_candidates):
        if relevant_remaining <= 0:
            break
        text = candidate["text"][:relevant_remaining]
        if text:
            relevant_selected.insert(0, text)
            relevant_remaining -= len(text)
    rendered = "\n\n".join(
        [part for part in [base_rendered, *relevant_selected] if part]
    )
    relevant_truncated = len(relevant_selected) < len(relevant_candidates) or sum(
        len(value) for value in relevant_selected
    ) < sum(len(candidate["text"]) for candidate in relevant_candidates)
    truncated = users["truncated"] or tools["truncated"] or relevant_truncated
    text = (
        f"[Some transcript evidence was omitted or truncated.]\n\n{rendered}"
        if truncated
        else rendered
    )
    return {
        "text": text or "(no eligible transcript evidence)",
        "userCharacters": sum(len(item["text"]) for item in users["selected"]),
        "toolCharacters": sum(len(item["text"]) for item in tools["selected"]),
        "relevantResultCharacters": sum(len(item) for item in relevant_selected),
        "truncated": truncated,
    }


__all__ = [
    "MAX_EVIDENCE_ITEM_CHARACTERS",
    "ModelDecision",
    "PermissionDetailsLike",
    "RelevantBoundaryRequest",
    "TranscriptConfig",
    "TranscriptResult",
    "bounded_string",
    "build_classifier_transcript",
    "deterministic_hard_deny",
    "effective_command",
    "parse_decision",
    "surface_of",
]
