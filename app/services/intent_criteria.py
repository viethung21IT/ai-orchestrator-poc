from app.core.config import IntentCriteriaVersion

V1_INSTRUCTIONS = "Select the route that best matches the user's question."
V1_CRITERIA = {
    "kpi": "Compute, compare, or summarize numerical business metrics from structured data.",
    "rag": "Find or explain information from documents, policies, or procedural text.",
    "graph": "Trace relationships, dependencies, or paths between entities in a knowledge graph.",
    "hybrid_graph_rag": "Use entity relationships and supporting document evidence together.",
    "hybrid_kpi_rag": "Combine a numerical KPI or calculation with supporting document evidence.",
    "other": "General conversation or requests outside the categories above.",
}

V2_INSTRUCTIONS = (
    "Classify the request for a company that develops and deploys software. "
    "Choose the route by the information needed to answer the question, regardless of keywords "
    "or whether the requested records actually exist. Missing data does not make an "
    "enterprise question out of scope. A project name alone does not require a graph lookup. "
    "Choose a hybrid route only if the answer requires both of its specified sources."
)
V2_CRITERIA = {
    "kpi": (
        "Calculate, compare, or summarize quantitative business measures from structured records "
        "such as recognized revenue, direct costs, gross profit, and gross margin. "
        "Filters or grouping by customer, contract, project, or department still count as KPI."
    ),
    "rag": (
        "Retrieve or explain enterprise document contents, such as contract clauses, meeting notes, "
        "project reports, acceptance records, test plans, internal policies, or procedures. "
        "Use this for business definitions or documented explanations. General knowledge is other."
    ),
    "graph": (
        "Look up or traverse structured enterprise relationships or linked document metadata. "
        "A Customer signs a Contract; a Contract covers Projects; a Department is responsible for "
        "Projects; a Project links to Documents. Identifying which documents are linked, or their "
        "titles or types, requires links or metadata without reading their contents."
    ),
    "hybrid_graph_rag": (
        "Use only when the answer requires both a structured entity or document link lookup "
        "and substantive content from enterprise documents. Merely naming a known entity "
        "or asking for linked document titles does not require both."
    ),
    "hybrid_kpi_rag": (
        "Use only when the answer requires both a numerical business measure from structured records "
        "and substantive content from enterprise documents, such as a policy, clause, or recorded reason."
    ),
    "other": (
        "General knowledge, creative or casual requests, and topics outside the enterprise software "
        "services business. Assign in-scope requests to the appropriate route even if evidence is missing."
    ),
}

INTENT_PROMPTS: dict[IntentCriteriaVersion, tuple[str, dict[str, str]]] = {
    "v1": (V1_INSTRUCTIONS, V1_CRITERIA),
    "v2": (V2_INSTRUCTIONS, V2_CRITERIA),
}
