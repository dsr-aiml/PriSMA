"""Validate the only anonymous POST operation admitted by the public transport."""

import json
import re

from graphql import parse
from graphql.language import OperationType
from graphql.language.ast import FieldNode, FragmentDefinitionNode, OperationDefinitionNode


def validate_read_operation(body):
    if not isinstance(body, (str, bytes)) or len(body.encode() if isinstance(body, str) else body) > 16_384:
        raise ValueError("Read operation exceeds the request allowance.")
    try:
        data = json.loads(body)
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise ValueError("A complete GraphQL query is required.") from exc
    if (
        not isinstance(data, dict)
        or set(data) - {"query", "variables", "operationName"}
        or not isinstance(data.get("query"), str)
    ):
        raise ValueError("Only complete, unbatched GraphQL queries are admitted.")
    if data.get("operationName") is not None and not isinstance(data["operationName"], str):
        raise ValueError("Invalid operation name.")
    if not isinstance(data.get("variables", {}), dict):
        raise ValueError("Invalid query variables.")
    if re.search(
        r"token|secret|password|authorization|session|api.?key|credential",
        json.dumps(data["variables"] if "variables" in data else {}).casefold(),
    ):
        raise ValueError("Queries containing credential variables are excluded.")
    try:
        document = parse(data["query"], max_tokens=1000)
    except Exception as exc:
        raise ValueError("The GraphQL query could not be validated.") from exc
    operations = [d for d in document.definitions if isinstance(d, OperationDefinitionNode)]
    if (
        len(operations) != 1
        or operations[0].operation != OperationType.QUERY
        or any(
            not isinstance(d, (OperationDefinitionNode, FragmentDefinitionNode)) for d in document.definitions
        )
    ):
        raise ValueError("Mutation and subscription operations are excluded.")
    # Schema-independent executable rules reject duplicate/missing fragments,
    # unused variables and cycles without contacting an introspection endpoint.
    from graphql.language.visitor import ParallelVisitor, visit
    from graphql.validation import ASTValidationContext
    from graphql.validation.rules.known_fragment_names import KnownFragmentNamesRule
    from graphql.validation.rules.no_fragment_cycles import NoFragmentCyclesRule
    from graphql.validation.rules.unique_fragment_names import UniqueFragmentNamesRule

    errors = []
    context = ASTValidationContext(document, errors.append)
    visit(
        document,
        ParallelVisitor(
            [
                rule(context)
                for rule in (NoFragmentCyclesRule, KnownFragmentNamesRule, UniqueFragmentNamesRule)
            ]
        ),
    )
    if errors:
        raise ValueError("GraphQL fragment structure could not be validated.")
    operation = operations[0]
    name = operation.name.value if operation.name else None
    if data.get("operationName") not in {None, name}:
        raise ValueError("Query operation name does not match.")
    fields, nodes = [], list(document.definitions)
    while nodes:
        node = nodes.pop()
        if getattr(node, "kind", "") in {"argument", "variable"} and re.search(
            r"token|secret|password|authorization|session|api.?key|credential", node.name.value, re.I
        ):
            raise ValueError("Credential arguments are excluded.")
        if isinstance(node, FieldNode):
            fields.append(node.name.value)
        for key in node.keys:
            value = getattr(node, key, None)
            if isinstance(value, tuple):
                nodes.extend(v for v in value if hasattr(v, "keys"))
            elif hasattr(value, "keys"):
                nodes.append(value)
    if any(
        re.search(
            r"^(?:__|login|logout|signIn|signOut|create|update|delete|remove|submit|send|purchase|checkout|subscribe|upload|authorize|set[A-Z])",
            field,
        )
        for field in fields
    ):
        raise ValueError("Query contains an excluded action or introspection field.")
    # The server's implementation may violate GraphQL read semantics. Execution
    # stays an explicit opt-in, never an assertion about arbitrary backend code.
    return {
        "kind": "graphql_query",
        "operation": name or "anonymous",
        "fields": list(dict.fromkeys(fields))[:60],
    }
