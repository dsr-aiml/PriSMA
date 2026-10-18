"""Stable two-dimensional placement. Layout never creates relationships."""


def place_application(nodes, edges, start_column):
    members = [node for node in nodes if node.get("context") == "documented application"]
    if not members:
        return 0
    ids = {node["id"] for node in members}
    incoming = {identifier: [] for identifier in ids}
    outgoing = {identifier: [] for identifier in ids}
    for edge in edges:
        if edge["source"] in ids and edge["target"] in ids:
            incoming[edge["target"]].append(edge["source"])
            outgoing[edge["source"]].append(edge["target"])
    ranks = {identifier: 0 for identifier in ids if not incoming[identifier]}
    for _ in range(len(members)):
        pending = [node["id"] for node in members if node["id"] not in ranks and all(parent in ranks for parent in incoming[node["id"]])]
        if not pending:
            break
        for identifier in pending:
            ranks[identifier] = min(3, 1 + max((ranks[p] for p in incoming[identifier]), default=-1))
    for identifier in ids:
        ranks.setdefault(identifier, 0)  # Cycles remain visible without claiming an order.
    positions = {}
    column = start_column
    for rank in sorted(set(ranks.values())):
        layer = [node for node in members if ranks[node["id"]] == rank]
        if rank:
            layer.sort(key=lambda node: (min((positions[p][1] for p in incoming[node["id"]] if p in positions), default=99), node["kind"] != "infrastructure"))
        else:
            layer.sort(key=lambda node: (not outgoing[node["id"]], node["kind"] not in {"frontend", "application"}))
        occupied = set()
        for node in layer:
            preferred = min((positions[p][1] for p in incoming[node["id"]] if p in positions), default=0)
            row = preferred
            while row in occupied:
                row += 1
            occupied.add(row)
            positions[node["id"]] = (column, row)
            node["position"] = {"x": column * 340, "y": row * 210 + 50}
            node["lane"] = "Application" if rank == 0 else "Hosting and integrations" if rank == 1 else "Connected components"
        column += 1
    return column - start_column
