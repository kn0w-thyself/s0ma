"""Natural language query engine for the s0ma self-model.

Answers natural language questions about the system by:
1. Parsing the query to identify intent and relevant components
2. Retrieving relevant data from registry, verifiers, and metrics
3. Synthesizing a natural language response

This is a rule-based engine (no LLM dependency). It uses keyword
matching, component name resolution, and template-based responses.
An LLM-backed version can be layered on top in the future (via
STEMCELL's Claude integration).

Zero external dependencies — uses only the Python standard library
plus the existing s0ma self-model API.

Usage::

    from s0ma import initialize
    from s0ma.self_model import SelfModelInterface
    from s0ma.api.query_engine import QueryEngine

    registry = initialize(persist=False)
    smi = SelfModelInterface(registry)
    qe = QueryEngine(registry, smi)
    answer = qe.query("What is ComponentRegistry?")
"""

from __future__ import annotations

import re
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from s0ma.exceptions import RegistryIntegrityError

if TYPE_CHECKING:
    from s0ma.api.teaching import TeachingProvider
    from s0ma.registry import ComponentRegistry
    from s0ma.self_model.interface import SelfModelInterface
    from s0ma.verifiers.interoception import MetricsCollector

__all__ = ["QueryEngine", "QueryIntent", "classify_query"]


class QueryIntent(Enum):
    """Classification of natural language question intent.

    Each intent maps to a specific data retrieval strategy and
    response template.
    """

    COMPONENT_LOOKUP = auto()    # "What is X?", "Tell me about X"
    DEPENDENCY_QUERY = auto()    # "What depends on X?", "What does X use?"
    IMPACT_ANALYSIS = auto()     # "What breaks if X changes?"
    HEALTH_QUERY = auto()        # "What anomalies?", "Is the system healthy?"
    PERFORMANCE_QUERY = auto()   # "Why is X slow?", "What are the metrics?"
    STATS_QUERY = auto()         # "How many components?", "What layers exist?"
    TEACHING_QUERY = auto()      # "How do I...?", "What are the rules?"
    EXTENSION_QUERY = auto()     # "Where can I add X?", "How do I extend?"
    HANDLER_QUERY = auto()       # "What handles X?", "Who processes Y?"
    UNKNOWN = auto()


# Keyword patterns for intent classification.
# Each entry is (compiled regex, intent).
# Order matters — first match wins.
_INTENT_PATTERNS: list[tuple[re.Pattern[str], QueryIntent]] = [
    # Impact analysis — must come before dependency to catch "break/affect"
    (
        re.compile(
            r"\b(break|affect|impact|change[sd]?\b|modif|remov|delet)",
            re.IGNORECASE,
        ),
        QueryIntent.IMPACT_ANALYSIS,
    ),
    # Dependency query
    (
        re.compile(
            r"\b(depend|uses?\b|imports?\b|requires?\b|needs?\b"
            r"|upstream|downstream)",
            re.IGNORECASE,
        ),
        QueryIntent.DEPENDENCY_QUERY,
    ),
    # Health / anomaly query
    (
        re.compile(
            r"\b(health|anomal|errors?\b|warnings?\b|verif|status\b"
            r"|drift|discrepan|phantom|vestigial|immune|inflamm|atroph)",
            re.IGNORECASE,
        ),
        QueryIntent.HEALTH_QUERY,
    ),
    # Performance query
    (
        re.compile(
            r"\b(slow|fast\b|latenc|performance|metrics?\b|throughput"
            r"|speed|bottleneck|profil)",
            re.IGNORECASE,
        ),
        QueryIntent.PERFORMANCE_QUERY,
    ),
    # Stats query
    (
        re.compile(
            r"\b(how many|count|total|statistic|number of|layers?\b"
            r"|kinds?\b|overview|summary|list all)",
            re.IGNORECASE,
        ),
        QueryIntent.STATS_QUERY,
    ),
    # Teaching query — "How do I create a component?", "What are the rules?"
    (
        re.compile(
            r"\b(how do i|how to|teach me|learn|guide|tutorial"
            r"|quickstart|getting started|compliance|rules\b"
            r"|example of|template|show me how)",
            re.IGNORECASE,
        ),
        QueryIntent.TEACHING_QUERY,
    ),
    # Extension query
    (
        re.compile(
            r"\b(add\b|extend|creat|new component|insert"
            r"|where.*(can|should)|extension point)",
            re.IGNORECASE,
        ),
        QueryIntent.EXTENSION_QUERY,
    ),
    # Handler query — "what handles X", "who processes Y"
    (
        re.compile(
            r"\b(handl|process|responsible|manag|who\b"
            r"|which.*component)",
            re.IGNORECASE,
        ),
        QueryIntent.HANDLER_QUERY,
    ),
    # Component lookup — broad "what is X", "tell me about X", "describe X"
    (
        re.compile(
            r"\b(what is|tell me|describe|explain\b|show\b"
            r"|info\b|about\b|detail)",
            re.IGNORECASE,
        ),
        QueryIntent.COMPONENT_LOOKUP,
    ),
]


def classify_query(
    question: str,
) -> tuple[QueryIntent, list[str]]:
    """Classify a natural language question and extract entity references.

    Uses keyword matching to determine the question category, then
    fuzzy-matches component names referenced in the question.

    Args:
        question: The natural language question to classify.

    Returns:
        Tuple of (intent, entity_names_mentioned). Entity names are
        raw extractions — the caller should resolve them against the
        registry using fuzzy matching.
    """
    if not question or not question.strip():
        return QueryIntent.UNKNOWN, []

    # Classify intent
    intent = QueryIntent.UNKNOWN
    for pattern, candidate_intent in _INTENT_PATTERNS:
        if pattern.search(question):
            intent = candidate_intent
            break

    # Extract potential entity names (capitalized words that could be
    # component names, or quoted strings)
    entities: list[str] = []

    # Quoted strings first (highest confidence)
    quoted = re.findall(r'["\']([^"\']+)["\']', question)
    entities.extend(quoted)

    # PascalCase words (likely class/component names)
    pascal_case = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', question)
    for name in pascal_case:
        if name not in entities:
            entities.append(name)

    # ALL_CAPS words of 2+ characters (likely acronyms/enums)
    all_caps = re.findall(r'\b([A-Z]{2,})\b', question)
    for name in all_caps:
        if name not in entities:
            entities.append(name)

    return intent, entities


def _fuzzy_match_component(
    query_term: str,
    component_names: list[str],
) -> str | None:
    """Find the best matching component name for a query term.

    Matching strategy (in order of preference):
    1. Exact match (case-insensitive)
    2. Contains match (component name contains the query term)
    3. Query term contains the component name
    4. No match

    Args:
        query_term: The term to match (from entity extraction).
        component_names: All registered component names.

    Returns:
        The best matching component name, or None if no match.
    """
    query_lower = query_term.lower()

    # 1. Exact match
    for name in component_names:
        if name.lower() == query_lower:
            return name

    # 2. Component name contains query term
    matches: list[str] = []
    for name in component_names:
        if query_lower in name.lower():
            matches.append(name)
    if len(matches) == 1:
        return matches[0]
    if matches:
        # Prefer suffix match (e.g., "registry" -> "ComponentRegistry")
        suffix_matches = [
            n for n in matches if n.lower().endswith(query_lower)
        ]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        # Among suffix matches or all matches, pick alphabetically
        # first for deterministic behavior
        candidates = suffix_matches if suffix_matches else matches
        return sorted(candidates)[0]

    # 3. Query term contains component name
    matches = []
    for name in component_names:
        if name.lower() in query_lower:
            matches.append(name)
    if len(matches) == 1:
        return matches[0]
    if matches:
        return max(matches, key=len)  # Longest match (most specific)

    return None


def _extract_keywords(question: str) -> list[str]:
    """Extract meaningful keywords from a question for intent matching.

    Strips common question words and returns content words.
    """
    stop_words = frozenset({
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall",
        "what", "which", "who", "whom", "where", "when", "why", "how",
        "that", "this", "these", "those", "it", "its", "i", "me", "my",
        "we", "our", "you", "your", "they", "them", "their", "of", "in",
        "on", "at", "to", "for", "with", "by", "from", "about", "if",
        "or", "and", "but", "not", "no", "so", "as", "than", "too",
        "very", "just", "also", "tell", "please", "show",
    })

    words = re.findall(r'\b\w+\b', question.lower())
    return [w for w in words if w not in stop_words and len(w) > 1]


class QueryEngine:
    """Natural language query engine for the self-model.

    Answers questions about the system by:
    1. Parsing the query to identify intent and relevant components
    2. Retrieving relevant data from registry, verifiers, and metrics
    3. Synthesizing a natural language response

    This is a rule-based engine (no LLM dependency). It uses keyword
    matching, component name resolution, and template-based responses.
    An LLM-backed version can be layered on top in the future.

    Args:
        registry: The ComponentRegistry to query.
        self_model: The SelfModelInterface for pre-formatted output.
        metrics_collector: Optional MetricsCollector for runtime data.
    """

    def __init__(
        self,
        registry: ComponentRegistry,
        self_model: SelfModelInterface,
        *,
        metrics_collector: MetricsCollector | None = None,
    ) -> None:
        self._registry = registry
        self._self_model = self_model
        self._metrics_collector = metrics_collector
        self._teacher: TeachingProvider | None = None  # Lazy init

    def query(self, question: str) -> str:
        """Answer a natural language question about the system.

        Supported question categories:
        - "What is X?" -> component description
        - "What depends on X?" / "What does X use?" -> dependency info
        - "What would break if I removed X?" -> impact analysis
        - "What are the anomalies?" / "Is the system healthy?" -> health
        - "Why is X slow?" -> performance/interoception data
        - "How many components are there?" -> registry stats
        - "How do I create a component?" -> framework usage guide
        - "Where can I add X?" -> extension points
        - "What handles X?" -> component search by intent keywords

        Args:
            question: Natural language question about the system.

        Returns:
            Natural language answer, or a helpful fallback response
            listing what kinds of questions can be answered.
        """
        if not question or not question.strip():
            return self._fallback_response()

        intent, entities = classify_query(question)

        # Resolve entities against registered component names
        component_names = sorted(self._registry.get_all().keys())
        resolved: list[str] = []
        for entity in entities:
            match = _fuzzy_match_component(entity, component_names)
            if match is not None and match not in resolved:
                resolved.append(match)

        # Also try to find component names directly in the question text
        # (for unquoted, non-PascalCase references like "registry")
        if not resolved:
            keywords = _extract_keywords(question)
            for keyword in keywords:
                match = _fuzzy_match_component(keyword, component_names)
                if match is not None and match not in resolved:
                    resolved.append(match)

        # Dispatch to the appropriate handler
        handlers = {
            QueryIntent.COMPONENT_LOOKUP: self._handle_component_lookup,
            QueryIntent.DEPENDENCY_QUERY: self._handle_dependency_query,
            QueryIntent.IMPACT_ANALYSIS: self._handle_impact_analysis,
            QueryIntent.HEALTH_QUERY: self._handle_health_query,
            QueryIntent.PERFORMANCE_QUERY: self._handle_performance_query,
            QueryIntent.STATS_QUERY: self._handle_stats_query,
            QueryIntent.TEACHING_QUERY: self._handle_teaching_query,
            QueryIntent.EXTENSION_QUERY: self._handle_extension_query,
            QueryIntent.HANDLER_QUERY: self._handle_handler_query,
        }

        handler = handlers.get(intent)
        if handler is not None:
            return handler(question, resolved)

        # UNKNOWN intent — try component lookup if we found entities
        if resolved:
            return self._handle_component_lookup(question, resolved)

        return self._fallback_response()

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    def _handle_component_lookup(
        self,
        question: str,
        resolved: list[str],
    ) -> str:
        """Handle "What is X?" questions."""
        if not resolved:
            return (
                "I couldn't identify which component you're asking about. "
                + self._suggest_components()
            )

        parts: list[str] = []
        for name in resolved[:3]:  # Limit to 3 components per query
            try:
                desc = self._self_model.describe_component(name)
                parts.append(desc)
            except RegistryIntegrityError:
                parts.append(f"Component '{name}' is not registered.")

        return "\n\n---\n\n".join(parts)

    def _handle_dependency_query(
        self,
        question: str,
        resolved: list[str],
    ) -> str:
        """Handle "What depends on X?" / "What does X use?" questions."""
        if not resolved:
            return (
                "I couldn't identify which component you're asking about. "
                + self._suggest_components()
            )

        question_lower = question.lower()
        name = resolved[0]

        spec = self._registry.get(name)
        if spec is None:
            return f"Component '{name}' is not registered."

        lines: list[str] = []

        # Determine direction: "what depends on X" vs "what does X use"
        if any(
            w in question_lower
            for w in ("depend on", "depends on", "use", "uses", "need")
        ):
            # Forward direction: what does X depend on?
            if spec.dependencies:
                lines.append(f"'{name}' depends on:")
                for dep in sorted(spec.dependencies):
                    dep_spec = self._registry.get(dep)
                    if dep_spec is not None:
                        lines.append(
                            f"  - {dep} ({dep_spec.kind.name.lower()}, "
                            f"{dep_spec.layer.name.lower()}): "
                            f"{dep_spec.intent}"
                        )
                    else:
                        lines.append(f"  - {dep} (not registered)")
            else:
                lines.append(
                    f"'{name}' has no declared dependencies. "
                    f"It is an independent component."
                )
        else:
            # Reverse direction: what depends on X?
            dependents = self._registry.get_dependents(name)
            if dependents:
                lines.append(f"Components that depend on '{name}':")
                for dep_spec in sorted(dependents, key=lambda s: s.name):
                    lines.append(
                        f"  - {dep_spec.name} ({dep_spec.kind.name.lower()}, "
                        f"{dep_spec.layer.name.lower()})"
                    )
            else:
                lines.append(
                    f"No components currently depend on '{name}'. "
                    f"It is a leaf component."
                )

        return "\n".join(lines)

    def _handle_impact_analysis(
        self,
        question: str,
        resolved: list[str],
    ) -> str:
        """Handle "What would break if X changes?" questions."""
        if not resolved:
            return (
                "I couldn't identify which component you're asking about. "
                + self._suggest_components()
            )

        name = resolved[0]
        try:
            return self._self_model.get_impact_analysis(name)
        except RegistryIntegrityError:
            return f"Component '{name}' is not registered."

    def _handle_health_query(
        self,
        question: str,
        resolved: list[str],
    ) -> str:
        """Handle "What anomalies exist?" / "Is the system healthy?" questions."""
        report = self._self_model._try_verify()
        if report is None:
            return (
                "Health status: No verification data available. "
                "The verification engine could not be run."
            )

        lines: list[str] = []
        if report.passed:
            lines.append(
                "The system is healthy. All verification checks passed."
            )
        else:
            lines.append(
                f"The system has {report.total_anomalies} anomalies "
                f"({report.total_errors} errors, "
                f"{report.total_warnings} warnings)."
            )

        lines.append("")
        lines.append(report.explain_for_llm())

        return "\n".join(lines)

    def _handle_performance_query(
        self,
        question: str,
        resolved: list[str],
    ) -> str:
        """Handle "Why is X slow?" / "What are the metrics?" questions."""
        if self._metrics_collector is None:
            return (
                "Performance data is not available. "
                "No MetricsCollector is configured. "
                "To enable runtime metrics, wire a MetricsCollector "
                "and use the @instrument decorator on component methods."
            )

        if not resolved:
            # Return overall metrics summary
            try:
                all_metrics = self._metrics_collector.get_all_metrics()
            except Exception:  # noqa: BLE001
                return "Could not retrieve performance metrics."

            if not all_metrics:
                return "No performance metrics have been collected yet."

            lines = ["Performance metrics summary:"]
            for comp_name, metrics in sorted(all_metrics.items()):
                lines.append(
                    f"  - {comp_name}: {metrics.call_count} calls, "
                    f"p50={metrics.latency_p50_ms:.1f}ms, "
                    f"p99={metrics.latency_p99_ms:.1f}ms, "
                    f"error_rate={metrics.error_rate:.2%}"
                )
            return "\n".join(lines)

        name = resolved[0]
        try:
            comp_metrics = self._metrics_collector.get_metrics(name)
        except Exception:  # noqa: BLE001
            comp_metrics = None

        if comp_metrics is None:
            return (
                f"No performance metrics available for '{name}'. "
                f"The component may not be instrumented. "
                f"Use @instrument to enable runtime monitoring."
            )

        return (
            f"Performance metrics for '{name}':\n"
            f"  Calls: {comp_metrics.call_count}\n"
            f"  Latency p50: {comp_metrics.latency_p50_ms:.1f}ms\n"
            f"  Latency p99: {comp_metrics.latency_p99_ms:.1f}ms\n"
            f"  Error rate: {comp_metrics.error_rate:.2%}\n"
            f"  Last call at: {comp_metrics.last_call_at}"
        )

    def _handle_stats_query(
        self,
        question: str,
        resolved: list[str],
    ) -> str:
        """Handle "How many components?" / "What layers exist?" questions."""
        return self._self_model.describe_system()

    def _handle_teaching_query(
        self,
        question: str,
        resolved: list[str],
    ) -> str:
        """Handle "How do I create a component?" / "What are the rules?" questions.

        Lazily creates a TeachingProvider and delegates to its topic-based
        learning method. The TeachingProvider reads from the actual
        documentation files on disk — no duplication.
        """
        if self._teacher is None:
            from s0ma.api.teaching import TeachingProvider

            self._teacher = TeachingProvider(self._registry)

        # Extract meaningful words from the question to use as topic
        keywords = _extract_keywords(question)
        topic = " ".join(keywords) if keywords else question
        return self._teacher.learn_topic(topic)

    def _handle_extension_query(
        self,
        question: str,
        resolved: list[str],
    ) -> str:
        """Handle "Where can I add X?" questions."""
        return self._self_model.get_available_extension_points()

    def _handle_handler_query(
        self,
        question: str,
        resolved: list[str],
    ) -> str:
        """Handle "What handles X?" / "Who processes Y?" questions.

        Searches component intents for matching keywords.
        """
        keywords = _extract_keywords(question)
        if not keywords:
            return self._fallback_response()

        all_components = self._registry.get_all()
        matches: list[tuple[str, Any, int]] = []

        for name, spec in all_components.items():
            intent_lower = spec.intent.lower()
            score = sum(1 for kw in keywords if kw in intent_lower)
            if score > 0:
                matches.append((name, spec, score))

        # Sort by relevance score (highest first)
        matches.sort(key=lambda m: m[2], reverse=True)

        if not matches:
            return (
                "No components found matching your query. "
                "Try asking about specific components by name. "
                + self._suggest_components()
            )

        # Show top 5 matches
        top = matches[:5]
        lines = [
            f"Components matching your query (top {len(top)} by relevance):"
        ]
        for name, spec, _score in top:
            lines.append(
                f"  - {name} ({spec.kind.name.lower()}, "
                f"{spec.layer.name.lower()}): {spec.intent}"
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _suggest_components(self) -> str:
        """Produce a helpful suggestion listing some component names."""
        names = sorted(self._registry.get_all().keys())
        if len(names) <= 10:
            listing = ", ".join(names)
        else:
            listing = ", ".join(names[:10]) + f", ... ({len(names)} total)"
        return f"Available components: {listing}"

    def _fallback_response(self) -> str:
        """Produce a helpful fallback when the query can't be classified."""
        return (
            "I'm not sure how to answer that question. "
            "Here are the types of questions I can answer:\n\n"
            "  - \"What is <ComponentName>?\" — describe a component\n"
            "  - \"What depends on <ComponentName>?\" — show dependencies\n"
            "  - \"What would break if I changed <ComponentName>?\" "
            "— impact analysis\n"
            "  - \"Are there any anomalies?\" — system health check\n"
            "  - \"How many components are there?\" — system statistics\n"
            "  - \"How do I create a component?\" — framework usage guide\n"
            "  - \"Where can I add a new service?\" — extension points\n"
            "  - \"What handles registration?\" — search by functionality\n"
            "  - \"Why is <ComponentName> slow?\" — performance metrics\n"
            "\n" + self._suggest_components()
        )
