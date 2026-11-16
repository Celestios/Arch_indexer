"""
CSS Stylesheet for the Interactive PCB Circuit Board HTML Visualizer.
"""

PCB_CSS = """
    :root {
      --pcb-bg: #070b12;
      --card-bg: rgba(13, 19, 33, 0.94);
      --border: rgba(255, 255, 255, 0.12);
      --text: #e2e8f0;
      --text-muted: #8492a6;
      --neon-cyan: #38bdf8;
      --neon-green: #10b981;
      --neon-magenta: #ec4899;
      --neon-purple: #a855f7;
      --neon-amber: #f59e0b;
      --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      width: 100vw;
      height: 100vh;
      overflow: hidden;
      background-color: var(--pcb-bg);
      font-family: var(--font-mono);
      color: var(--text);
      user-select: none;
    }

    #circuit-canvas {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      display: block;
      cursor: crosshair;
    }

    .glass {
      background: var(--card-bg);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 12px 36px rgba(0, 0, 0, 0.65);
      z-index: 50;
      font-size: 11px;
    }

    #top-bar {
      position: absolute;
      top: 14px;
      left: 14px;
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 8px 14px;
    }

    .logo-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      font-weight: 700;
      letter-spacing: 1px;
      color: var(--neon-cyan);
      text-transform: uppercase;
    }

    .status-badge {
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: var(--neon-cyan);
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 10px;
    }

    .hub-badge {
      background: rgba(245, 158, 11, 0.2);
      border: 1px solid rgba(245, 158, 11, 0.5);
      color: var(--neon-amber);
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 9px;
      font-weight: 700;
    }

    .search-wrap {
      position: relative;
    }

    #search-input {
      background: rgba(0, 0, 0, 0.5);
      border: 1px solid var(--border);
      color: #fff;
      padding: 6px 10px 6px 26px;
      border-radius: 4px;
      font-family: var(--font-mono);
      font-size: 11px;
      width: 240px;
      outline: none;
      transition: width 0.2s ease, border-color 0.2s ease;
    }

    #search-input:focus {
      width: 340px;
      border-color: var(--neon-cyan);
      box-shadow: 0 0 10px rgba(56, 189, 248, 0.3);
    }

    .search-icon {
      position: absolute;
      left: 8px;
      top: 7px;
      font-size: 11px;
      color: var(--text-muted);
      pointer-events: none;
    }

    #search-results {
      position: absolute;
      top: 34px;
      left: 0;
      width: 100%;
      max-height: 280px;
      overflow-y: auto;
      background: #0d1321;
      border: 1px solid var(--border);
      border-radius: 4px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.7);
      display: none;
      z-index: 100;
    }

    .search-item {
      padding: 8px 12px;
      cursor: pointer;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .search-item:hover {
      background: rgba(56, 189, 248, 0.15);
    }

    #legend-bar {
      position: absolute;
      bottom: 14px;
      left: 14px;
      padding: 10px 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .legend-title {
      font-size: 10px;
      font-weight: 700;
      color: var(--text-muted);
      letter-spacing: 0.5px;
      display: flex;
      justify-content: space-between;
      gap: 16px;
    }

    .legend-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 6px 14px;
    }

    .legend-cell {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 10px;
    }

    .legend-dot {
      width: 8px;
      height: 8px;
      border-radius: 2px;
      flex-shrink: 0;
    }

    .legend-traces {
      display: flex;
      align-items: center;
      gap: 14px;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      padding-top: 6px;
      font-size: 10px;
    }

    .trace-item {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .trace-line {
      width: 14px;
      height: 2px;
      border-radius: 1px;
    }

    #controls-bar {
      position: absolute;
      bottom: 14px;
      right: 14px;
      display: flex;
      gap: 6px;
      z-index: 50;
    }

    .btn-ctrl {
      width: 32px;
      height: 32px;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text);
      font-family: var(--font-mono);
      font-size: 13px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.15s ease, border-color 0.15s ease;
    }

    .btn-ctrl:hover {
      background: rgba(56, 189, 248, 0.18);
      border-color: var(--neon-cyan);
      color: #fff;
    }

    #btn-view-code {
      position: absolute;
      top: 14px;
      right: 14px;
      z-index: 60;
      display: none;
      align-items: center;
      gap: 8px;
      padding: 7px 14px;
      background: var(--card-bg);
      border: 1px solid var(--neon-cyan);
      border-radius: 6px;
      color: #fff;
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.5px;
      cursor: pointer;
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.28), 0 8px 24px rgba(0, 0, 0, 0.65);
      transition: all 0.18s ease;
    }

    #btn-view-code:hover {
      background: rgba(56, 189, 248, 0.2);
      border-color: #7dd3fc;
      box-shadow: 0 0 24px rgba(56, 189, 248, 0.5), 0 8px 28px rgba(0, 0, 0, 0.75);
      transform: translateY(-1px);
    }

    #btn-view-code.disabled {
      opacity: 0.45;
      cursor: not-allowed;
      border-color: var(--border);
      box-shadow: none;
    }

    #inspector {
      position: absolute;
      top: 58px;
      right: 14px;
      width: 360px;
      max-height: calc(100vh - 120px);
      overflow-y: auto;
      padding: 16px;
      display: none;
    }

    .inspector-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
      margin-bottom: 12px;
    }

    .inspector-title {
      font-size: 14px;
      font-weight: 700;
      color: #fff;
      word-break: break-all;
    }

    .inspector-close {
      background: none;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 14px;
      padding: 2px;
    }

    .inspector-close:hover {
      color: #fff;
    }

    .field-row {
      margin-bottom: 12px;
    }

    .field-label {
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin-bottom: 4px;
    }

    .field-val {
      font-size: 11px;
      color: var(--text);
      word-break: break-all;
    }

    .code-box {
      background: rgba(0, 0, 0, 0.45);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 4px;
      padding: 8px;
      font-size: 10px;
      line-height: 1.4;
      overflow-x: auto;
      white-space: pre-wrap;
      color: #38bdf8;
    }

    .ports-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 10px;
      margin-top: 4px;
    }

    .ports-table th, .ports-table td {
      padding: 4px 6px;
      text-align: left;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    }

    .ports-table th {
      color: var(--text-muted);
      font-size: 9px;
      text-transform: uppercase;
    }

    .pins-list {
      display: flex;
      flex-direction: column;
      gap: 4px;
      max-height: 180px;
      overflow-y: auto;
    }

    .pin-row {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 4px 6px;
      background: rgba(255, 255, 255, 0.03);
      border-radius: 4px;
      cursor: pointer;
    }

    .pin-row:hover {
      background: rgba(56, 189, 248, 0.15);
    }

    .btn-view-code-inline {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      width: 100%;
      padding: 6px 12px;
      margin-top: 4px;
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid var(--neon-cyan);
      border-radius: 4px;
      color: var(--neon-cyan);
      font-family: var(--font-mono);
      font-size: 10px;
      font-weight: 700;
      cursor: pointer;
      transition: background 0.15s ease, color 0.15s ease;
    }

    .btn-view-code-inline:hover {
      background: rgba(56, 189, 248, 0.25);
      color: #fff;
    }

    #code-viewer-backdrop {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: rgba(5, 8, 16, 0.72);
      backdrop-filter: blur(5px);
      -webkit-backdrop-filter: blur(5px);
      z-index: 99;
      display: none;
    }

    #code-viewer-modal {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: min(940px, 92vw);
      height: min(720px, 86vh);
      display: none;
      flex-direction: column;
      z-index: 100;
      box-shadow: 0 24px 64px rgba(0, 0, 0, 0.85), 0 0 32px rgba(56, 189, 248, 0.25);
      border: 1px solid rgba(56, 189, 248, 0.4);
      border-radius: 10px;
      overflow: hidden;
      padding: 0;
    }

    .code-modal-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 18px;
      background: rgba(13, 19, 33, 0.98);
      border-bottom: 1px solid var(--border);
    }

    .code-modal-info {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }

    .code-modal-file {
      font-size: 10px;
      color: var(--neon-cyan);
      font-family: var(--font-mono);
    }

    .code-modal-title {
      font-size: 14px;
      font-weight: 700;
      color: #fff;
    }

    .code-modal-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .btn-code-action {
      display: flex;
      align-items: center;
      gap: 5px;
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid var(--border);
      border-radius: 4px;
      color: var(--text);
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 5px 10px;
      cursor: pointer;
      transition: all 0.15s ease;
    }

    .btn-code-action:hover {
      background: rgba(56, 189, 248, 0.25);
      color: #fff;
      border-color: var(--neon-cyan);
    }

    .code-modal-body {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      background: #050811;
    }

    .code-viewer-wrap {
      flex: 1;
      display: flex;
      overflow: auto;
      font-family: var(--font-mono);
      font-size: 11.5px;
      line-height: 1.5;
    }

    .code-gutter {
      padding: 14px 10px 14px 14px;
      background: rgba(10, 15, 28, 0.85);
      border-right: 1px solid rgba(255, 255, 255, 0.08);
      color: #475569;
      text-align: right;
      user-select: none;
      min-width: 48px;
    }

    .code-gutter div {
      font-size: 11px;
    }

    .code-content {
      flex: 1;
      padding: 14px 18px;
      margin: 0;
      background: transparent;
      color: #e2e8f0;
      white-space: pre;
      overflow-x: auto;
    }

    .code-content code {
      font-family: inherit;
    }

    .code-modal-foot {
      padding: 8px 18px;
      background: rgba(10, 15, 28, 0.95);
      border-top: 1px solid rgba(255, 255, 255, 0.06);
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 10px;
      color: var(--text-muted);
    }
"""
