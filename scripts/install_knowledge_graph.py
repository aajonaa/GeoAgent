"""Apply small, idempotent UI hooks to a verified current application copy.

Run against a staged copy of the CURRENT deployment, never overwrite live files
with a stale checkout. The caller verifies expected source hashes separately.
"""
from pathlib import Path


def install(root):
    root = Path(root)
    edits = {}
    path = root / "geological_agent/team/server.py"
    text = path.read_text(encoding="utf-8")
    anchor = "    install_knowledge_routes(app, auth, body)"
    if "install_graph_routes(app, auth)" not in text:
        if text.count(anchor) != 1:
            raise ValueError("Knowledge route installation anchor changed")
        text = text.replace(anchor,anchor+"\n    from .knowledge_graph import install_graph_routes\n    install_graph_routes(app, auth)")
    edits[path] = text
    path = root / "geological_agent/team/web/index.html"
    text = path.read_text(encoding="utf-8")
    if 'id="knowledge-tab-graph"' not in text:
        anchor = '<button id="knowledge-tab-detail"'
        if text.count(anchor) != 1:
            raise ValueError("Knowledge tab anchor changed")
        tab = '<button id="knowledge-tab-graph" data-knowledge-tab="graph" type="button" role="tab" aria-selected="false" aria-controls="knowledge-panel-graph" tabindex="-1">知识图谱</button>'
        text = text.replace(anchor,tab+anchor)
        anchor = '    <section id="knowledge-panel-detail"'
        if text.count(anchor) != 1:
            raise ValueError("Knowledge panel anchor changed")
        text = text.replace(anchor,'    <section id="knowledge-panel-graph" role="tabpanel" aria-labelledby="knowledge-tab-graph" hidden></section>\n'+anchor)
        text = text.replace('</head>','<link rel="stylesheet" href="/knowledge-graph-assets/knowledge-graph.css?v=1">\n</head>')
        text = text.replace('</body>','<script src="/knowledge-graph-assets/knowledge-graph.js?v=1" defer></script>\n</body>')
    edits[path] = text
    path = root / "geological_agent/team/web/knowledge.js"
    text = path.read_text(encoding="utf-8")
    if 'geoagent:graph-source' not in text:
        anchor = "const tabs = ['library', 'detail', 'search'];"
        if text.count(anchor) != 1:
            raise ValueError("Knowledge tab controller changed")
        text = text.replace(anchor,"const tabs = ['library', 'graph', 'detail', 'search'];")
        anchor = "  async function openDocument("
        if text.count(anchor) != 1:
            raise ValueError("Source reader hook changed")
        text = text.replace(anchor,"  document.addEventListener('geoagent:graph-source', event => {\n    const source = event.detail;\n    if (!view.hidden && source?.document_id) openDocument(source.document_id, source.hit || null, 'graph');\n  });\n"+anchor)
        text = text.replace("detailOrigin === 'search' ? '返回检索结果' : '返回文献库'", "detailOrigin === 'graph' ? '返回知识图谱' : detailOrigin === 'search' ? '返回检索结果' : '返回文献库'")
    edits[path] = text
    # Validate every hook before writing anything.
    for path, text in edits.items():
        path.write_text(text,encoding="utf-8",newline="\n")
    return [str(path.relative_to(root)) for path in edits]


if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    print(json.dumps(install(parser.parse_args().root)))
