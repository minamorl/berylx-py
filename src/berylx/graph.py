"""Static structural visualization; execution always uses EffectTree."""

import json

from .nodes import Branch, Parallel, Rescue, Sequence


class Graph:
    def __init__(self, name, root):
        self.name, self.root = name, root

    @classmethod
    def from_node(cls, node, name=None):
        return cls(name, node)

    def nodes(self):
        return [node.name for node in self.root.nodes()]

    def parallel_nodes(self):
        def collect(node):
            if isinstance(node, Parallel):
                return [[leaf.name for leaf in node.nodes()]] + [
                    group for child in node.branches for group in collect(child)
                ]
            children = (
                node.steps
                if isinstance(node, Sequence)
                else [arm.body for arm in node.arms]
                if isinstance(node, Branch)
                else [node.body, node.handler]
                if isinstance(node, Rescue)
                else []
            )
            return [group for child in children for group in collect(child)]

        return collect(self.root)

    def _render(self, mermaid):
        lines = []
        counter = 0

        def declare(name):
            nonlocal counter
            key = f"n{counter}" if mermaid else f"{name}#{counter}"
            counter += 1
            label = str(name).replace('"', "&quot;")
            lines.append(f'{key}["{label}"]' if mermaid else f"{json.dumps(key)};")
            return key

        def connect(left, right, label=None):
            for a in left:
                for b in right:
                    if mermaid:
                        text = str(label).replace('"', "&quot;") if label else ""
                        lines.append(f"{a} -->|{text}| {b}" if label else f"{a} --> {b}")
                    else:
                        attr = f" [label={json.dumps(label)}]" if label else ""
                        lines.append(f"{json.dumps(a)} -> {json.dumps(b)}{attr};")

        def build(node):
            if isinstance(node, Sequence):
                entries = None
                exits: list[str] = []
                for child in node.steps:
                    start, end = build(child)
                    if entries is None:
                        entries = start
                    connect(exits, start)
                    exits = end
                return entries or [], exits
            if isinstance(node, Parallel):
                split, join = declare("split"), declare("join")
                for child in node.branches:
                    start, end = build(child)
                    connect([split], start)
                    connect(end, [join])
                return [split], [join]
            if isinstance(node, Branch):
                decision, exits = declare("branch"), []
                for arm in node.arms:
                    start, end = build(arm.body)
                    connect([decision], start, arm.predicate.name)
                    exits.extend(end)
                return [decision], exits
            if isinstance(node, Rescue):
                start, end = build(node.body)
                heal_start, heal_end = build(node.handler)
                connect(end, heal_start)
                return start, [*end, *heal_end]
            leaf = declare(node.name)
            return [leaf], [leaf]

        build(self.root)
        header = "flowchart TD" if mermaid else f"digraph {json.dumps(self.name or 'berylx')} {{"
        return "\n".join([header, *("  " + line for line in lines), *([] if mermaid else ["}"])])

    def to_dot(self):
        return self._render(False)

    def to_mermaid(self):
        return self._render(True)
