"""Cross-task memory inject — recall prior evidences into the write prompt.

最小切片(P4 memory inject, research-workflow v0.2.5):复用 evidences 表当
跨任务记忆库,write stage 建 prompt 时按 brief 竞品 recall 历史 finding,
渲染成 blob 注入 user prompt(**不改** locked write `system_prompt`)。

- 只 write 注入(plan/search 不动)。
- 每 (entity, attribute) 留最新一条(captured_at desc)。
- 按竞品分组渲染 + 变化检测指令揉 blob 头。
- 25KB 按竞品块整块丢 + ``(memory truncated)``(UTF-8 字节截断,不切多字节)。
- 空召回 → None(连头都不加,首次/新竞品零干扰)。

诚实边界:只保证记忆到达 write prompt;"LLM 据此标 old→new 变化"是
policy-only(对齐 competitive-analysis-agent AC11),不测、不保证。
alias 只做 case-insensitive(suffix 去除需 write-time 归一化,defer)。
"""

from __future__ import annotations

from typing import Any

INJECTION_LIMIT = 25 * 1024  # 25KB(对齐 competitive-analysis-agent INJECTION_LIMIT)

_HEADER = (
    "Prior findings (from previous research; captured_at shown for staleness. "
    "Compare each to your CURRENT search results — if a value changed, flag it "
    'in the report as "old → new"):'
)


def _normalize_brand(b: str) -> str:
    """Case-insensitive + whitespace-trim brand key (query + grouping)."""
    return (b or "").strip().lower()


def _captured_key(r: dict[str, Any]) -> str:
    """Recency sort key: captured_at (ISO8601 string, lexicographic works)."""
    return str(r.get("captured_at") or "")


def _render_finding(r: dict[str, Any]) -> str:
    attr = str(r.get("attribute") or "?")
    value = str(r.get("value") or r.get("finding") or "")
    if len(value) > 120:
        value = value[:120] + "…"
    src = str(r.get("source_url") or r.get("source_type") or "")
    if len(src) > 60:
        src = src[:60] + "…"
    conf = r.get("confidence")
    conf_s = f"{float(conf):.2f}" if isinstance(conf, (int, float)) else "?"
    cap_at = str(r.get("captured_at") or "")[:10]  # date only
    return f"- {attr}: {value}  (src: {src}, conf {conf_s}, {cap_at})"


def _byte_len(s: str) -> int:
    return len(s.encode("utf-8"))


def _truncate_blob(text: str, limit: int = INJECTION_LIMIT) -> str:
    """UTF-8 byte truncation; append marker if cut (no mid-multibyte split)."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore") + "\n(memory truncated)"


async def recall_prior_findings(
    store: Any,
    brands: list[str],
    *,
    min_confidence: float = 0.3,
    limit: int = 200,
    cap: int = INJECTION_LIMIT,
) -> str | None:
    """Recall prior evidences for ``brands`` + render an inject blob for write.

    Returns the blob (header + findings grouped by brand) or ``None`` when no
    prior findings (caller skips inject). Per ``(brand, entity, attribute)``
    keeps the latest (max captured_at). 25KB cap drops whole brand blocks once
    exceeded + appends ``(memory truncated)``. Pure: no env, no pi_ai.
    """
    clean = [_normalize_brand(b) for b in brands if _normalize_brand(b)]
    if not clean:
        return None
    rows = await store.query_evidences(brands=clean, min_confidence=min_confidence, limit=limit)
    if not rows:
        return None
    # dedup: per (normalized brand, entity, attribute) keep latest captured_at.
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in rows:
        key = (
            _normalize_brand(r.get("brand") or ""),
            str(r.get("entity") or ""),
            str(r.get("attribute") or ""),
        )
        prev = latest.get(key)
        if prev is None or _captured_key(r) > _captured_key(prev):
            latest[key] = r
    # group by display brand (row's stored brand, first-seen order).
    by_brand: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for r in latest.values():
        disp = str(r.get("brand") or "") or str(r.get("entity") or "") or "(unknown)"
        if disp not in by_brand:
            by_brand[disp] = []
            order.append(disp)
        by_brand[disp].append(r)
    parts: list[str] = [_HEADER]
    for disp in order:
        block = "\n".join([f"## {disp}"] + [_render_finding(r) for r in by_brand[disp]])
        if _byte_len("\n".join(parts + [block])) > cap:
            # this block doesn't fit; stop + mark truncated (only if findings exist).
            if len(parts) == 1:  # only header → no block fit at all
                return None
            return "\n".join(parts) + "\n(memory truncated)"
        parts.append(block)
    return _truncate_blob("\n".join(parts), cap)


__all__ = ["INJECTION_LIMIT", "recall_prior_findings"]
