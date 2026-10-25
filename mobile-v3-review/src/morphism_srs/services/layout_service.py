from __future__ import annotations

from collections import defaultdict, deque


class LayoutService:
    """Computes Sugiyama-style topological layered coordinates (pos_x, pos_y) for DAG nodes."""

    @staticmethod
    def compute_layered_layout(
        note_ids: list[int],
        edges: list[tuple[int, int]],
        x_spacing: float = 280.0,
        y_spacing: float = 175.0,
    ) -> dict[int, tuple[float, float]]:
        if not note_ids:
            return {}

        node_set = set(note_ids)
        in_degree: dict[int, int] = {nid: 0 for nid in note_ids}
        adj: dict[int, list[int]] = {nid: [] for nid in note_ids}
        parents: dict[int, list[int]] = {nid: [] for nid in note_ids}

        for u, v in edges:
            if u in node_set and v in node_set and u != v:
                adj[u].append(v)
                parents[v].append(u)
                in_degree[v] += 1

        layer_of: dict[int, int] = {nid: 0 for nid in note_ids}
        queue: deque[int] = deque(nid for nid in note_ids if in_degree[nid] == 0)
        visited: set[int] = set()

        while queue:
            u = queue.popleft()
            visited.add(u)
            for v in adj[u]:
                layer_of[v] = max(layer_of[v], layer_of[u] + 1)
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        for nid in note_ids:
            if nid not in visited:
                layer_of[nid] = 0

        layers: dict[int, list[int]] = defaultdict(list)
        for nid in note_ids:
            layers[layer_of[nid]].append(nid)

        positions: dict[int, tuple[float, float]] = {}
        order_in_layer: dict[int, float] = {}

        for l_idx in sorted(layers.keys()):
            nodes = layers[l_idx]
            if l_idx > 0:
                def _barycenter(nid: int) -> float:
                    ps = parents.get(nid, [])
                    if not ps:
                        return float(nid)
                    return sum(order_in_layer.get(p, 0.0) for p in ps) / len(ps)

                nodes.sort(key=_barycenter)

            count = len(nodes)
            start_x = -((count - 1) * x_spacing) / 2.0
            y = float(l_idx) * y_spacing
            for idx, nid in enumerate(nodes):
                x = start_x + idx * x_spacing
                positions[nid] = (x, y)
                order_in_layer[nid] = float(idx)

        return positions
