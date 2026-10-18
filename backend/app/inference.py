from .models import Evidence, now


def infer(evidence: list[Evidence]) -> dict:
    """Build a traceable fictional model without provider requests or LLM usage."""
    timestamp = now().isoformat()
    claims, nodes, edges, technologies, endpoints, entities, fields, relationships = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    proposed_links = []
    by_signal = {key: item for item in evidence for key in item.signals}

    def claim(key, kind, description, classification, score, supports, explanation, contradicts=None):
        result = dict(
            id=key,
            created_at=timestamp,
            type=kind,
            description=description,
            classification=classification,
            confidence=score,
            confidence_explanation=explanation,
            supporting_evidence_ids=list(dict.fromkeys(supports)),
            contradicting_evidence_ids=contradicts or [],
            graph_node_ids=[],
            graph_edge_ids=[],
        )
        claims.append(result)
        return result

    def node(component, basis):
        nodes.append(
            dict(
                id=component["id"],
                created_at=timestamp,
                label=component["label"],
                kind=component["kind"],
                lane=component["lane"],
                description=component["description"],
                position=component["position"],
                claim_id=basis["id"],
                confidence=basis["confidence"],
                classification=basis["classification"],
            )
        )
        basis["graph_node_ids"].append(component["id"])

    for item in evidence:
        signals = item.signals
        if component := signals.get("component"):
            classification = component["classification"]
            observed = classification == "observed"
            basis = claim(
                "c-component-" + component["id"],
                component["kind"],
                component["label"] + ": " + component["description"].lower() + ".",
                classification,
                93 if observed else 72,
                [item.id],
                "Explicitly described in a versioned fictional reference. This score reflects the sample rubric, not a finding about the entered domain."
                if observed
                else "Supported by the fictional reference, with implementation details left unspecified. The score represents evidence strength, not a statistical probability.",
            )
            node(component, basis)
            if technology := component.get("technology"):
                technologies.append(
                    dict(
                        id="t-" + component["id"],
                        name=technology,
                        category=component["kind"],
                        claim_id=basis["id"],
                    )
                )
            for index, endpoint in enumerate(signals.get("endpoints", [])):
                endpoints.append(
                    dict(id=f"endpoint-{index}", **endpoint, classification="observed", claim_id=basis["id"])
                )
        proposed_links.extend((link, item.id) for link in signals.get("connections", []))

        if resources := signals.get("resources"):
            basis = claim(
                "c-data-model",
                "data_model",
                "Resource identifiers suggest a workspace-scoped logical data model.",
                "inferred",
                72,
                [item.id],
                "Resource names and reference fields suggest logical entities. They do not establish physical tables, field types, or a database engine.",
            )
            for name, attributes in resources.items():
                entity_id = name.lower()
                entities.append(dict(id=entity_id, name=name, claim_id=basis["id"], confidence=72))
                fields.extend(
                    dict(
                        id=f"{entity_id}-{attribute}",
                        entity_id=entity_id,
                        name=attribute,
                        type="unknown",
                        claim_id=basis["id"],
                    )
                    for attribute in attributes
                )
            for relation in signals.get("entity_relationships", []):
                relationships.append(
                    dict(
                        id=relation["source"] + "-" + relation["target"],
                        **relation,
                        cardinality="probable one-to-many",
                        claim_id=basis["id"],
                    )
                )

    if entities and not any(item["id"] == "data" for item in nodes):
        basis = next(item for item in claims if item["id"] == "c-data-model")
        node(
            dict(
                id="data",
                label="Logical data model",
                kind="database",
                lane="Platform",
                description="Storage technology unspecified",
                position=dict(x=680, y=270),
            ),
            basis,
        )

    lookup = {item["id"]: item for item in nodes}
    if "gateway" not in lookup and {"frontend", "api"} <= lookup.keys():
        frontend_source = next(
            item for item in evidence if item.signals.get("component", {}).get("id") == "frontend"
        )
        proposed_links.append(
            (
                dict(source="frontend", target="api", label="API requests", classification="observed"),
                frontend_source.id,
            )
        )
    claim_lookup = {item["id"]: item for item in claims}
    seen = set()
    for link, evidence_id in proposed_links:
        source, target = link["source"], link["target"]
        key = f"edge-{source}-{target}"
        if source not in lookup or target not in lookup or key in seen:
            continue
        seen.add(key)
        classification = link["classification"]
        supports = [evidence_id]
        if classification != "observed":
            supports += claim_lookup[lookup[source]["claim_id"]]["supporting_evidence_ids"]
            supports += claim_lookup[lookup[target]["claim_id"]]["supporting_evidence_ids"]
        explanation = {
            "observed": "This connection is explicitly described in fictional technical documentation. It has not been verified against a running system.",
            "inferred": "The referenced responsibilities support this connection, but the sample does not directly describe the transport or implementation.",
            "hypothesis": "This is a plausible architectural connection. Co-occurring components alone do not prove that this path exists.",
        }[classification]
        basis = claim(
            "c-" + key,
            "relationship",
            f"{lookup[source]['label']} connects to {lookup[target]['label']}: {link['label'].lower()}.",
            classification,
            {"observed": 88, "inferred": 68, "hypothesis": 42}[classification],
            supports,
            explanation,
        )
        edges.append(
            dict(
                id=key,
                created_at=timestamp,
                source=source,
                target=target,
                label=link["label"],
                claim_id=basis["id"],
                confidence=basis["confidence"],
                classification=classification,
            )
        )
        basis["graph_edge_ids"].append(key)

    if "delivery_contract" in by_signal and "delivery_claim" in by_signal:
        claim(
            "c-delivery-semantics",
            "messaging",
            "Queue delivery is at least once; exactly-once wording is disputed.",
            "inferred",
            58,
            [by_signal["delivery_contract"].id],
            "The technical queue contract requires consumer deduplication and is more specific than the product copy. Conflicting wording lowers confidence and remains visible for review.",
            [by_signal["delivery_claim"].id],
        )

    return dict(
        schema_version=1,
        fixture="Atlas 2.0 (fictional)",
        confidence_kind="heuristic",
        summary=(
            "The sample describes a workspace platform with identity, an application API, background processing, "
            "search, attachments, integrations, and operational services. Documented connections are separated "
            "from inferred and proposed paths; conflicting queue-delivery claims are retained."
        )
        if len(nodes) > 4
        else "The compact sample covers the web application, API, identity service, and probable logical data model. Additional platform and operational services are omitted.",
        unknowns=[
            "Backend language and framework",
            "Database engine and physical schema",
            "Origin hosting and orchestration",
            "Session persistence",
            "Broker and search engine products",
            "Private endpoints and source code",
        ],
        claims=claims,
        nodes=nodes,
        edges=edges,
        technologies=technologies,
        api_endpoints=endpoints,
        entities=entities,
        fields=fields,
        relationships=relationships,
    )
