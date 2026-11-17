"""
HTML Document Assembler.
Combines CSS styles (`styles.py`), Canvas JS engine (`canvas_engine.py`),
and compact serialized graph data into a standalone HTML file.
"""

import html
import json
from typing import Dict, Any
from .styles import PCB_CSS
from .canvas_engine import CANVAS_ENGINE_JS_TEMPLATE


class HtmlGraphGenerator:
    """
    Renders a lightweight standalone HTML document by assembling modular CSS and JS templates.
    """

    def __init__(self, embed_assets: bool = True):
        self.embed_assets = embed_assets

    def generate_html(self, compact_data: Dict[str, Any], title: str = "Arch PCB Circuit Map") -> str:
        json_data = json.dumps(compact_data, separators=(",", ":"), ensure_ascii=False)
        # Safely escape characters that could terminate the <script> block or cause syntax errors
        json_data = (
            json_data.replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )
        stats = compact_data.get("stats", {})
        total_nodes = stats.get("total_nodes", len(compact_data.get("nodes", [])))
        total_edges = stats.get("total_edges", len(compact_data.get("links", [])))
        packages_count = stats.get("packages_count", len(compact_data.get("packages", [])))

        script_body = CANVAS_ENGINE_JS_TEMPLATE.replace("__JSON_DATA__", json_data)

        escaped_title = html.escape(title)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escaped_title}</title>
  <style>{PCB_CSS}</style>
</head>
<body>

  <canvas id="circuit-canvas"></canvas>

  <button id="btn-view-code" class="glass" title="View Defining Code Block" style="display: none;">
    <span style="color: var(--neon-cyan); font-weight: bold;">&lt;/&gt;</span>
    <span>VIEW CODE</span>
  </button>

  <div id="top-bar" class="glass">
    <div class="logo-badge">
      <span>☵</span> ARCH PCB BOARD
    </div>
    <span class="status-badge">{packages_count} PACKAGES · {total_nodes} COMPONENTS · {total_edges} TRACES</span>

    <div class="search-wrap">
      <span class="search-icon">⚲</span>
      <input type="text" id="search-input" placeholder="Search chip, symbol, pin..." autocomplete="off">
      <div id="search-results"></div>
    </div>
  </div>

  <div id="legend-bar" class="glass">
    <div class="legend-title">
      <span>CIRCUIT COMPONENT MAPPING</span>
      <span style="color: var(--neon-cyan);">OBSTACLE-FREE ORTHOGONAL ROUTING</span>
    </div>
    <div class="legend-grid">
      <div class="legend-cell"><span class="legend-dot" style="background: #38bdf8;"></span>IC Package (File)</div>
      <div class="legend-cell"><span class="legend-dot" style="background: #a855f7;"></span>Core Unit (Class)</div>
      <div class="legend-cell"><span class="legend-dot" style="background: #10b981;"></span>Logic Gate (Method)</div>
      <div class="legend-cell"><span class="legend-dot" style="background: #06b6d4;"></span>Sub-Circuit (Fn)</div>
      <div class="legend-cell"><span class="legend-dot" style="background: #14b8a6;"></span>Constructor</div>
      <div class="legend-cell"><span class="legend-dot" style="background: #f59e0b;"></span>Bus Pin (Field)</div>
      <div class="legend-cell"><span class="legend-dot" style="background: #64748b;"></span>Ext Connector</div>
      <div class="legend-cell"><span class="legend-dot" style="background: #ec4899;"></span>Def Via</div>
    </div>

    <div class="legend-traces">
      <div class="trace-item"><span class="trace-line" style="background: #10b981;"></span>Calls (Green Trace)</div>
      <div class="trace-item"><span class="trace-line" style="background: #eab308;"></span>Inherits (Gold)</div>
      <div class="trace-item"><span class="trace-line" style="background: #38bdf8; height: 3px;"></span>Hub Stub ([⇒ Name])</div>
      <div class="trace-item"><span style="color: #10b981; font-weight: 700; font-size: 9px; padding: 1px 4px; border: 1px solid #10b981; border-radius: 3px;">×N</span> Multiplicity Pill</div>
    </div>
  </div>

  <div id="controls-bar">
    <button class="btn-ctrl" id="btn-zoom-in" title="Zoom In">+</button>
    <button class="btn-ctrl" id="btn-zoom-out" title="Zoom Out">−</button>
    <button class="btn-ctrl" id="btn-fit" title="Zoom to Fit Board">⛶</button>
    <button class="btn-ctrl" id="btn-reset" title="Reset View (1:1)">1:1</button>
  </div>

  <div id="inspector" class="glass">
    <div class="inspector-head">
      <div>
        <div style="display: flex; gap: 6px; align-items: center; margin-bottom: 4px;">
          <span class="status-badge" id="insp-type">COMPONENT</span>
          <span class="hub-badge" id="insp-hub-badge" style="display: none;">GLOBAL HUB</span>
        </div>
        <div class="inspector-title" id="insp-title">Title</div>
      </div>
      <button class="inspector-close" id="insp-close">✕</button>
    </div>

    <div class="field-row" id="insp-path-row">
      <div class="field-label">Package Location</div>
      <div class="field-val" id="insp-path"></div>
    </div>

    <div class="field-row" id="insp-ports-row" style="display: none;">
      <div class="field-label">Terminal Ports (Data Flow)</div>
      <table class="ports-table" id="insp-ports-table">
        <thead>
          <tr><th>Port</th><th>Direction</th><th>Type</th></tr>
        </thead>
        <tbody id="insp-ports-body"></tbody>
      </table>
    </div>

    <div class="field-row" id="insp-sig-row" style="display: none;">
      <div class="field-label">Terminal Signature</div>
      <div class="code-box" id="insp-sig"></div>
    </div>

    <div class="field-row" id="insp-doc-row" style="display: none;">
      <div class="field-label">Documentation</div>
      <div class="field-val" id="insp-doc" style="font-style: italic;"></div>
    </div>

    <div class="field-row" id="insp-raw-row">
      <div class="field-label">SCIP Pin Identifier</div>
      <div class="field-val" id="insp-raw" style="color: #64748b; font-size: 10px;"></div>
    </div>

    <div class="field-row" id="insp-code-row" style="display: none;">
      <div class="field-label">Defining Code</div>
      <button class="btn-view-code-inline" id="btn-view-code-inline">
        <span>&lt;/&gt;</span> Open Code Viewer
      </button>
    </div>

    <div class="field-row">
      <div class="field-label">Connected Traces (<span id="insp-conn-count">0</span>)</div>
      <div class="pins-list" id="insp-connections"></div>
    </div>
  </div>

  <div id="code-viewer-backdrop"></div>
  <div id="code-viewer-modal" class="glass">
    <div class="code-modal-head">
      <div class="code-modal-info">
        <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 4px;">
          <span class="status-badge" id="code-modal-type">FUNCTION</span>
          <span class="code-modal-file" id="code-modal-loc">src/example.py</span>
        </div>
        <div class="code-modal-title" id="code-modal-title">Symbol Title</div>
      </div>
      <div class="code-modal-actions">
        <button class="btn-code-action" id="btn-copy-code" title="Copy code to clipboard">
          <span id="btn-copy-icon">📋</span> <span id="btn-copy-text">Copy</span>
        </button>
        <button class="inspector-close" id="code-modal-close" title="Close (Esc)">✕</button>
      </div>
    </div>
    <div class="code-modal-body">
      <div class="code-viewer-wrap">
        <div class="code-gutter" id="code-gutter"></div>
        <pre class="code-content"><code id="code-text"></code></pre>
      </div>
    </div>
    <div class="code-modal-foot">
      <span>Defining Code Block</span>
      <span>Press <kbd style="background: rgba(255,255,255,0.1); padding: 1px 4px; border-radius: 3px;">Esc</kbd> to close</span>
    </div>
  </div>

  <script>{script_body}</script>
</body>
</html>"""
