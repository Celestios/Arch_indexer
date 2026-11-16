"""
Client-Side HTML5 Canvas Rendering & Interactive Inspector Engine.
Renders Left-to-Right Directory Funnel Zone Enclosures, parent-to-child folder branch guides,
and LCA-routed orthogonal traces.
"""

CANVAS_ENGINE_JS_TEMPLATE = """
    const data = __JSON_DATA__;
    const STRINGS = data.strings || [];
    const getString = idx => (idx >= 0 && idx < STRINGS.length) ? STRINGS[idx] : '';

    const NODE_TYPES = ["file", "class", "function", "method", "constructor", "field", "module", "occurrence_def", "occurrence_ref", "external", "local"];
    const NODE_COLORS = ["#38bdf8", "#a855f7", "#06b6d4", "#10b981", "#14b8a6", "#f59e0b", "#6366f1", "#ec4899", "#f97316", "#64748b", "#94a3b8"];

    const EDGE_TYPES = ["calls", "defines", "references", "ref_to_def", "contains", "inherits", "located_in"];
    const EDGE_COLORS = ["#10b981", "#ec4899", "#f97316", "#a855f7", "#38bdf8", "#eab308", "#475569"];
    const PASSIVE_EDGE_COLORS = [
      "rgba(16, 185, 129, 0.78)",
      "rgba(244, 114, 182, 0.82)",
      "rgba(251, 146, 60, 0.82)",
      "rgba(192, 132, 252, 0.82)",
      "rgba(56, 189, 248, 0.75)",
      "rgba(250, 204, 21, 0.85)",
      "rgba(148, 163, 184, 0.65)"
    ];

    const rawNodes = data.nodes || [];
    const nodeCount = rawNodes.length;
    const nodes = new Array(nodeCount);

    for (let i = 0; i < nodeCount; i++) {
      const n = rawNodes[i];
      let inPorts = [];
      if (n[13] >= 0) {
        try { inPorts = JSON.parse(getString(n[13])); } catch(e) { inPorts = []; }
      }
      nodes[i] = {
        id: i,
        label: n[0],
        type: n[1],
        x: n[2],
        y: n[3],
        w: n[4],
        h: n[5],
        fileIdx: n[6],
        line: n[7],
        col: n[8],
        sigIdx: n[9],
        symIdx: n[10],
        docIdx: n[11],
        isHub: n[12] === 1,
        inPorts: inPorts,
        outType: getString(n[14]),
        codeIdx: n[15] !== undefined ? n[15] : -1,
        endLine: n[16] !== undefined ? n[16] : -1,
      };
    }

    const rawPackages = data.packages || [];
    const packages = rawPackages.map(p => ({
      id: getString(p[0]),
      x: p[1],
      y: p[2],
      w: p[3],
      h: p[4],
      zone: p[5] || 0,
      color: getString(p[6]) || '#38bdf8',
      filename: getString(p[7]) || (getString(p[0]).split(/[\\\\/]/).pop()),
      tabW: p[8] || 120,
      classes: (p[9] || []).map(c => ({
        label: getString(c[0]),
        x: c[1],
        y: c[2],
        w: c[3],
        h: c[4],
        id: getString(c[5]),
      })),
    }));

    const rawBanners = data.banners || [];
    const banners = rawBanners.map(b => ({
      name: getString(b[0]),
      color: getString(b[1]),
      y: b[2],
      count: b[3],
      x: b[4] !== undefined ? b[4] : 100,
      w: b[5] !== undefined ? b[5] : 600,
      h: b[6] !== undefined ? b[6] : 200,
      colIdx: b[7] !== undefined ? b[7] : 0,
      parentX: b[8] !== undefined ? b[8] : -1,
      parentY: b[9] !== undefined ? b[9] : -1,
    }));

    const rawLinks = data.links || [];
    const linkCount = rawLinks.length;
    const links = new Array(linkCount);
    const linkBuckets = Array.from({ length: 7 }, () => []);
    const neighbors = Array.from({ length: nodeCount }, () => []);
    const nodeLinkIndices = Array.from({ length: nodeCount }, () => []);
    const hubCallers = Array.from({ length: nodeCount }, () => []);

    for (let i = 0; i < linkCount; i++) {
      const l = rawLinks[i];
      const s = l[0];
      const t = l[1];
      const type = l[2];
      const callCount = l[3] || 1;
      const isHubStub = l[4] === 1;
      const waypoints = l[5] || [];
      const hubTarget = getString(l[6]);

      const linkObj = {
        idx: i,
        s,
        t,
        type,
        callCount,
        isHubStub,
        waypoints,
        hubTarget,
      };
      links[i] = linkObj;
      linkBuckets[type].push(linkObj);
      neighbors[s].push(t);
      neighbors[t].push(s);
      nodeLinkIndices[s].push(i);
      nodeLinkIndices[t].push(i);
      if (isHubStub) {
        hubCallers[t].push(i);
      }
    }

    const CELL_SIZE = 128;
    const spatialGrid = new Map();
    for (let i = 0; i < nodeCount; i++) {
      const n = nodes[i];
      const minCx = Math.floor((n.x - n.w / 2) / CELL_SIZE);
      const maxCx = Math.floor((n.x + n.w / 2) / CELL_SIZE);
      const minCy = Math.floor((n.y - n.h / 2) / CELL_SIZE);
      const maxCy = Math.floor((n.y + n.h / 2) / CELL_SIZE);
      for (let cx = minCx; cx <= maxCx; cx++) {
        for (let cy = minCy; cy <= maxCy; cy++) {
          const key = cx + ',' + cy;
          let cell = spatialGrid.get(key);
          if (!cell) {
            cell = [];
            spatialGrid.set(key, cell);
          }
          cell.push(i);
        }
      }
    }

    function findNodeAt(wx, wy) {
      const cx = Math.floor(wx / CELL_SIZE);
      const cy = Math.floor(wy / CELL_SIZE);
      const cell = spatialGrid.get(cx + ',' + cy);
      if (!cell) return null;
      for (let i = cell.length - 1; i >= 0; i--) {
        const n = nodes[cell[i]];
        const halfW = (n.w || 14) / 2 + 3;
        const halfH = (n.h || 14) / 2 + 3;
        if (Math.abs(wx - n.x) <= halfW && Math.abs(wy - n.y) <= halfH) {
          return n;
        }
      }
      return null;
    }

    const canvas = document.getElementById('circuit-canvas');
    const ctx = canvas.getContext('2d');

    let scale = 0.8;
    let panX = 60;
    let panY = 60;

    let hoveredNode = null;
    const selectedNodes = new Set();

    let isDragging = false;
    let hasDragged = false;
    let downX = 0;
    let downY = 0;
    let dragStartX = 0;
    let dragStartY = 0;

    let isBoxSelecting = false;
    let boxStartWorld = null;
    let boxEndWorld = null;

    let dashOffset = 0;
    let animFrameId = null;
    let lastFrameTime = 0;

    function startFlowAnimation() {
      if (animFrameId !== null) return;
      lastFrameTime = performance.now();
      const tick = (now) => {
        if (selectedNodes.size === 0 && !hoveredNode) {
          animFrameId = null;
          return;
        }
        const dt = Math.min(50, now - lastFrameTime);
        lastFrameTime = now;
        dashOffset = (dashOffset + dt * 0.035) % 28;
        render();
        animFrameId = requestAnimationFrame(tick);
      };
      animFrameId = requestAnimationFrame(tick);
    }

    function stopFlowAnimation() {
      if (animFrameId !== null) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
      }
    }

    function resizeCanvas() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      render();
    }
    window.addEventListener('resize', resizeCanvas);

    function toWorld(sx, sy) {
      return { x: (sx - panX) / scale, y: (sy - panY) / scale };
    }

    function render() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const vwMinX = -panX / scale - 60;
      const vwMinY = -panY / scale - 60;
      const vwMaxX = (canvas.width - panX) / scale + 60;
      const vwMaxY = (canvas.height - panY) / scale + 60;

      drawGrid();

      ctx.save();
      ctx.translate(panX, panY);
      ctx.scale(scale, scale);

      drawZoneBanners(vwMinX, vwMinY, vwMaxX, vwMaxY);
      drawPackages(vwMinX, vwMinY, vwMaxX, vwMaxY);
      drawTracesBatched(vwMinX, vwMinY, vwMaxX, vwMaxY);

      if (hoveredNode || selectedNodes.size > 0) {
        drawActiveNet();
        startFlowAnimation();
      } else {
        stopFlowAnimation();
      }

      drawComponents(vwMinX, vwMinY, vwMaxX, vwMaxY);

      if (isBoxSelecting && boxStartWorld && boxEndWorld) {
        const bx = Math.min(boxStartWorld.x, boxEndWorld.x);
        const by = Math.min(boxStartWorld.y, boxEndWorld.y);
        const bw = Math.abs(boxEndWorld.x - boxStartWorld.x);
        const bh = Math.abs(boxEndWorld.y - boxStartWorld.y);

        ctx.fillStyle = 'rgba(56, 189, 248, 0.10)';
        ctx.fillRect(bx, by, bw, bh);
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1.2;
        ctx.setLineDash([5, 3]);
        ctx.strokeRect(bx, by, bw, bh);
        ctx.setLineDash([]);
      }

      ctx.restore();
    }

    function drawGrid() {
      const gridSize = 24 * scale;
      if (gridSize < 10) return;
      const offsetX = panX % gridSize;
      const offsetY = panY % gridSize;
      ctx.fillStyle = 'rgba(255, 255, 255, 0.03)';
      for (let x = offsetX; x < canvas.width; x += gridSize) {
        for (let y = offsetY; y < canvas.height; y += gridSize) {
          ctx.fillRect(x, y, 1.2, 1.2);
        }
      }
    }

    function drawZoneBanners(minX, minY, maxX, maxY) {
      // Pass 1: Draw parent-to-child folder funnel branch connectors
      for (let i = 0; i < banners.length; i++) {
        const b = banners[i];
        if (b.parentX >= 0 && b.parentY >= 0) {
          const childMidY = b.y + b.h / 2;
          const midX = (b.parentX + b.x) / 2;
          ctx.strokeStyle = 'rgba(148, 163, 184, 0.18)';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([6, 6]);
          ctx.beginPath();
          ctx.moveTo(b.parentX, b.parentY);
          ctx.lineTo(midX, b.parentY);
          ctx.lineTo(midX, childMidY);
          ctx.lineTo(b.x, childMidY);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }

      // Pass 2: Draw full 2D Folder Zone Enclosure Boxes
      for (let i = 0; i < banners.length; i++) {
        const b = banners[i];
        if (b.x + b.w < minX - 120 || b.x > maxX + 120 || b.y + b.h < minY - 120 || b.y > maxY + 120) continue;

        ctx.fillStyle = 'rgba(15, 23, 42, 0.28)';
        ctx.fillRect(b.x, b.y, b.w, b.h);

        ctx.strokeStyle = b.color;
        ctx.lineWidth = 1.4;
        ctx.setLineDash([8, 6]);
        ctx.strokeRect(b.x, b.y, b.w, b.h);
        ctx.setLineDash([]);

        const labelText = 'COL ' + b.colIdx + ' :: ' + b.name + ' [' + b.count + ' FILES]';
        ctx.font = 'bold 11px monospace';
        const plateW = Math.max(300, ctx.measureText(labelText).width + 32);

        ctx.fillStyle = '#0a101d';
        ctx.fillRect(b.x + 8, b.y - 14, plateW, 26);
        ctx.strokeStyle = b.color;
        ctx.lineWidth = 1.2;
        ctx.strokeRect(b.x + 8, b.y - 14, plateW, 26);

        ctx.fillStyle = b.color;
        ctx.textAlign = 'left';
        ctx.fillText(labelText, b.x + 20, b.y + 3);
      }
    }

    function drawPackages(minX, minY, maxX, maxY) {
      for (let i = 0; i < packages.length; i++) {
        const p = packages[i];
        if (p.x + p.w < minX || p.x > maxX || p.y + p.h < minY || p.y - 24 > maxY) continue;

        const zoneColor = p.color || '#38bdf8';

        const tabW = Math.max(88, p.tabW || 120);
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(p.x, p.y - 20, tabW, 20);
        ctx.strokeStyle = zoneColor;
        ctx.lineWidth = 1.2;
        ctx.strokeRect(p.x, p.y - 20, tabW, 20);

        if (scale > 0.18) {
          ctx.fillStyle = zoneColor;
          ctx.font = 'bold 10px monospace';
          ctx.textAlign = 'left';
          ctx.fillText('  ' + p.filename, p.x + 8, p.y - 6);
        }

        ctx.fillStyle = '#090e18';
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.14)';
        ctx.lineWidth = 1.2;
        ctx.fillRect(p.x, p.y, p.w, p.h);
        ctx.strokeRect(p.x, p.y, p.w, p.h);

        ctx.fillStyle = zoneColor;
        ctx.fillRect(p.x, p.y, 3, p.h);

        if (p.classes && p.classes.length > 0) {
          for (let cIdx = 0; cIdx < p.classes.length; cIdx++) {
            const c = p.classes[cIdx];
            ctx.fillStyle = 'rgba(168, 85, 247, 0.035)';
            ctx.fillRect(c.x, c.y, c.w, c.h);
            ctx.strokeStyle = 'rgba(168, 85, 247, 0.32)';
            ctx.lineWidth = 1.0;
            ctx.setLineDash([4, 2]);
            ctx.strokeRect(c.x, c.y, c.w, c.h);
            ctx.setLineDash([]);
          }
        }
      }
    }

    function drawTracesBatched(minX, minY, maxX, maxY) {
      const hasActive = Boolean(hoveredNode || selectedNodes.size > 0);

      for (let layer = 0; layer < 7; layer++) {
        const bucket = linkBuckets[layer];
        if (!bucket || bucket.length === 0) continue;

        ctx.beginPath();
        ctx.strokeStyle = hasActive ? 'rgba(71, 85, 105, 0.22)' : PASSIVE_EDGE_COLORS[layer];
        ctx.lineWidth = 1.6;
        if (layer === 3) ctx.setLineDash([5, 3]); else ctx.setLineDash([]);

        for (let i = 0; i < bucket.length; i++) {
          const l = bucket[i];
          const pts = l.waypoints;
          if (!pts || pts.length < 4) continue;

          let minPx = pts[0], maxPx = pts[0], minPy = pts[1], maxPy = pts[1];
          for (let p = 2; p < pts.length; p += 2) {
            if (pts[p] < minPx) minPx = pts[p];
            if (pts[p] > maxPx) maxPx = pts[p];
            if (pts[p+1] < minPy) minPy = pts[p+1];
            if (pts[p+1] > maxPy) maxPy = pts[p+1];
          }
          if (maxPx + 40 < minX || minPx - 40 > maxX || maxPy + 40 < minY || minPy - 40 > maxY) continue;

          ctx.moveTo(pts[0], pts[1]);
          for (let p = 2; p < pts.length; p += 2) {
            ctx.lineTo(pts[p], pts[p + 1]);
          }
        }
        ctx.stroke();
      }
      ctx.setLineDash([]);

      if (scale > 0.45 && !hasActive) {
        drawMultiplicityAndStubs(null);
      }
    }

    function drawMultiplicityAndStubs(activeLinkSet) {
      for (let i = 0; i < linkCount; i++) {
        if (activeLinkSet && !activeLinkSet.has(i)) continue;
        const l = links[i];
        const pts = l.waypoints;
        if (!pts || pts.length < 4) continue;

        const isActive = Boolean(activeLinkSet);

        if (l.isHubStub) {
          const endX = pts[pts.length - 2];
          const endY = pts[pts.length - 1];
          const label = '  ' + (l.hubTarget || 'HUB');
          ctx.font = 'bold 8.5px monospace';
          const textW = ctx.measureText(label).width;
          ctx.fillStyle = isActive ? '#0369a1' : 'rgba(15, 23, 42, 0.88)';
          ctx.fillRect(endX - textW / 2 - 4, endY, textW + 8, 13);
          ctx.strokeStyle = isActive ? '#38bdf8' : 'rgba(2, 132, 199, 0.55)';
          ctx.lineWidth = 1;
          ctx.strokeRect(endX - textW / 2 - 4, endY, textW + 8, 13);
          ctx.fillStyle = isActive ? '#ffffff' : '#38bdf8';
          ctx.textAlign = 'center';
          ctx.fillText(label, endX, endY + 9.5);
        } else if (l.callCount > 1) {
          const midIdx = Math.floor(pts.length / 4) * 2;
          const mx = (pts[midIdx] + pts[midIdx - 2]) / 2;
          const my = (pts[midIdx + 1] + pts[midIdx - 1]) / 2;
          const badge = 'x' + l.callCount;
          ctx.font = 'bold 8.5px monospace';
          const bW = ctx.measureText(badge).width + 6;
          ctx.fillStyle = isActive ? '#065f46' : 'rgba(6, 78, 59, 0.85)';
          ctx.fillRect(mx - bW / 2, my - 6, bW, 12);
          ctx.strokeStyle = '#10b981';
          ctx.lineWidth = 0.8;
          ctx.strokeRect(mx - bW / 2, my - 6, bW, 12);
          ctx.fillStyle = '#6ee7b7';
          ctx.textAlign = 'center';
          ctx.fillText(badge, mx, my + 3);
        }
      }
    }

    function drawActiveNet() {
      const targetIds = new Set(selectedNodes);
      if (hoveredNode) targetIds.add(hoveredNode.id);
      if (targetIds.size === 0) return;

      const activeLinkSet = new Set();
      targetIds.forEach((id) => {
        (nodeLinkIndices[id] || []).forEach((lIdx) => activeLinkSet.add(lIdx));
        const n = nodes[id];
        if (n && n.isHub) {
          (hubCallers[id] || []).forEach((cIdx) => activeLinkSet.add(cIdx));
        }
      });
      if (activeLinkSet.size === 0) return;

      const activeLinks = Array.from(activeLinkSet);
      const activePath = new Path2D();
      for (let i = 0; i < activeLinks.length; i++) {
        const pts = links[activeLinks[i]].waypoints;
        if (!pts || pts.length < 4) continue;
        activePath.moveTo(pts[0], pts[1]);
        for (let p = 2; p < pts.length; p += 2) {
          activePath.lineTo(pts[p], pts[p + 1]);
        }
      }

      ctx.save();
      ctx.lineWidth = 2.2;
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.35)';
      ctx.stroke(activePath);

      ctx.lineWidth = 2.6;
      ctx.shadowColor = '#38bdf8';
      ctx.shadowBlur = 8;
      ctx.strokeStyle = '#7dd3fc';
      ctx.setLineDash([8, 20]);
      ctx.lineDashOffset = -dashOffset;
      ctx.stroke(activePath);

      ctx.setLineDash([]);
      ctx.shadowBlur = 0;

      for (let i = 0; i < activeLinks.length; i++) {
        const pts = links[activeLinks[i]].waypoints;
        if (!pts || pts.length < 6) continue;
        for (let p = 2; p < pts.length - 2; p += 2) {
          ctx.fillStyle = '#ffffff';
          ctx.beginPath();
          ctx.arc(pts[p], pts[p + 1], 2.6, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = '#070b12';
          ctx.beginPath();
          ctx.arc(pts[p], pts[p + 1], 1.0, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      drawMultiplicityAndStubs(activeLinkSet);
      ctx.restore();
    }

    function drawComponents(minX, minY, maxX, maxY) {
      const showDetails = scale >= 0.45;
      const showPortLabels = scale >= 0.85;

      for (let i = 0; i < nodeCount; i++) {
        const n = nodes[i];
        if (n.x + n.w < minX || n.x - n.w > maxX || n.y + n.h < minY || n.y - n.h > maxY) continue;

        const isHovered = hoveredNode && hoveredNode.id === n.id;
        const isSelected = selectedNodes.has(n.id);
        const col = NODE_COLORS[n.type];

        ctx.fillStyle = isHovered || isSelected ? '#1f293d' : '#0d1527';
        ctx.strokeStyle = isHovered || isSelected ? '#38bdf8' : col;
        ctx.lineWidth = isHovered || isSelected ? 2.0 : 1.0;

        ctx.fillRect(n.x - n.w / 2, n.y - n.h / 2, n.w, n.h);
        ctx.strokeRect(n.x - n.w / 2, n.y - n.h / 2, n.w, n.h);

        ctx.fillStyle = col;
        ctx.fillRect(n.x - 2, n.y - n.h / 2 - 2, 4, 2);
        ctx.fillRect(n.x - 2, n.y + n.h / 2, 4, 2);

        if (n.inPorts && n.inPorts.length > 0) {
          const numInputs = n.inPorts.length;
          for (let pIdx = 0; pIdx < numInputs; pIdx++) {
            const ty = n.y - n.h / 2 + (pIdx + 1) * (n.h / (numInputs + 1));
            ctx.fillStyle = '#06b6d4';
            ctx.fillRect(n.x - n.w / 2 - 4, ty - 1, 4, 2);
          }
          if (showPortLabels || isHovered || isSelected) {
            const summary = n.inPorts.slice(0, 2).map(p => p.name).join(', ') + (n.inPorts.length > 2 ? ', ...' : '');
            ctx.font = '8px monospace';
            ctx.fillStyle = isHovered || isSelected ? '#38bdf8' : 'rgba(148, 163, 184, 0.85)';
            ctx.textAlign = 'right';
            ctx.fillText(summary, n.x - n.w / 2 - 7, n.y + 2.5);
          }
        }

        if (n.outType) {
          ctx.fillStyle = '#10b981';
          ctx.fillRect(n.x + n.w / 2, n.y - 1, 4, 2);
          if (showPortLabels || isHovered || isSelected) {
            const shortOut = n.outType.length > 18 ? n.outType.slice(0, 16) + '..' : n.outType;
            ctx.font = '8px monospace';
            ctx.fillStyle = isHovered || isSelected ? '#10b981' : 'rgba(16, 185, 129, 0.8)';
            ctx.textAlign = 'left';
            ctx.fillText('-> ' + shortOut, n.x + n.w / 2 + 7, n.y + 2.5);
          }
        }

        if (n.isHub) {
          ctx.fillStyle = '#f59e0b';
          ctx.fillRect(n.x + n.w / 2 - 12, n.y - n.h / 2 - 4, 12, 4);
        }

        if (showDetails || isHovered || isSelected) {
          ctx.fillStyle = isHovered || isSelected ? '#ffffff' : '#e2e8f0';
          ctx.font = n.type === 1 ? 'bold 10px monospace' : '10px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(n.label, n.x, n.y + 3.5);
        }
      }
    }

    canvas.addEventListener('mousedown', (e) => {
      downX = e.clientX;
      downY = e.clientY;
      hasDragged = false;
      if (e.shiftKey) {
        isBoxSelecting = true;
        boxStartWorld = toWorld(e.clientX, e.clientY);
        boxEndWorld = boxStartWorld;
      } else {
        isDragging = true;
        dragStartX = e.clientX - panX;
        dragStartY = e.clientY - panY;
      }
    });

    window.addEventListener('mousemove', (e) => {
      if (isBoxSelecting) {
        if (Math.hypot(e.clientX - downX, e.clientY - downY) > 4) {
          hasDragged = true;
        }
        boxEndWorld = toWorld(e.clientX, e.clientY);
        render();
        return;
      }
      if (isDragging) {
        if (Math.hypot(e.clientX - downX, e.clientY - downY) > 4) {
          hasDragged = true;
        }
        panX = e.clientX - dragStartX;
        panY = e.clientY - dragStartY;
        render();
        return;
      }
      const world = toWorld(e.clientX, e.clientY);
      const hit = findNodeAt(world.x, world.y);
      if (hit !== hoveredNode) {
        hoveredNode = hit;
        canvas.style.cursor = hit ? 'pointer' : 'crosshair';
        render();
      }
    });

    window.addEventListener('mouseup', () => {
      if (isBoxSelecting) {
        isBoxSelecting = false;
        if (hasDragged && boxStartWorld && boxEndWorld) {
          const minX = Math.min(boxStartWorld.x, boxEndWorld.x);
          const maxX = Math.max(boxStartWorld.x, boxEndWorld.x);
          const minY = Math.min(boxStartWorld.y, boxEndWorld.y);
          const maxY = Math.max(boxStartWorld.y, boxEndWorld.y);
          for (let i = 0; i < nodeCount; i++) {
            const n = nodes[i];
            if (n.x >= minX && n.x <= maxX && n.y >= minY && n.y <= maxY) {
              selectedNodes.add(n.id);
            }
          }
          syncSelectionUI();
        }
        boxStartWorld = null;
        boxEndWorld = null;
        render();
      }
      isDragging = false;
    });

    canvas.addEventListener('click', (e) => {
      if (hasDragged) {
        hasDragged = false;
        return;
      }
      const world = toWorld(e.clientX, e.clientY);
      const hit = findNodeAt(world.x, world.y);
      const isAdditive = e.shiftKey || e.ctrlKey || e.metaKey;
      if (hit) {
        if (isAdditive) {
          if (selectedNodes.has(hit.id)) {
            selectedNodes.delete(hit.id);
          } else {
            selectedNodes.add(hit.id);
          }
        } else {
          selectedNodes.clear();
          selectedNodes.add(hit.id);
        }
        syncSelectionUI();
      } else if (!isAdditive) {
        deselectNode();
      }
    });

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const modal = document.getElementById('code-viewer-modal');
        if (modal && modal.style.display === 'flex') {
          closeCodeViewer();
          return;
        }
        if (selectedNodes.size > 0) {
          deselectNode();
        }
      }
    });

    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
      const mouseWorld = toWorld(e.clientX, e.clientY);
      scale = Math.min(Math.max(scale * zoomFactor, 0.02), 6.0);
      panX = e.clientX - mouseWorld.x * scale;
      panY = e.clientY - mouseWorld.y * scale;
      render();
    }, { passive: false });

    function selectNode(node) {
      selectedNodes.clear();
      selectedNodes.add(node.id);
      syncSelectionUI();
    }

    function deselectNode() {
      selectedNodes.clear();
      stopFlowAnimation();
      document.getElementById('inspector').style.display = 'none';
      const btnViewCode = document.getElementById('btn-view-code');
      if (btnViewCode) btnViewCode.style.display = 'none';
      closeCodeViewer();
      render();
    }

    function focusNode(node) {
      selectNode(node);
      scale = 1.5;
      panX = canvas.width / 2 - node.x * scale;
      panY = canvas.height / 2 - node.y * scale;
      render();
    }

    function syncSelectionUI() {
      render();
      const insp = document.getElementById('inspector');
      const btnViewCode = document.getElementById('btn-view-code');
      if (selectedNodes.size === 0) {
        insp.style.display = 'none';
        if (btnViewCode) btnViewCode.style.display = 'none';
        closeCodeViewer();
        return;
      }
      if (selectedNodes.size === 1) {
        const singleId = Array.from(selectedNodes)[0];
        renderSingleNodeInspector(nodes[singleId]);
        return;
      }
      if (btnViewCode) btnViewCode.style.display = 'none';
      document.getElementById('insp-type').textContent = 'MULTI-SELECT';
      document.getElementById('insp-type').style.color = '#38bdf8';
      document.getElementById('insp-hub-badge').style.display = 'none';
      document.getElementById('insp-title').textContent = `${selectedNodes.size} Components Selected`;
      document.getElementById('insp-path-row').style.display = 'none';
      document.getElementById('insp-ports-row').style.display = 'none';
      document.getElementById('insp-sig-row').style.display = 'none';
      document.getElementById('insp-doc-row').style.display = 'none';
      document.getElementById('insp-raw-row').style.display = 'none';

      const unionLinks = new Set();
      selectedNodes.forEach((id) => {
        (nodeLinkIndices[id] || []).forEach((lIdx) => unionLinks.add(lIdx));
      });
      document.getElementById('insp-conn-count').textContent = unionLinks.size;

      const connContainer = document.getElementById('insp-connections');
      connContainer.innerHTML = '';
      selectedNodes.forEach((id) => {
        const target = nodes[id];
        if (!target) return;
        const row = document.createElement('div');
        row.className = 'pin-row';
        row.innerHTML = `
          <span class="legend-dot" style="background: ${NODE_COLORS[target.type]}"></span>
          <span style="color: #f1f5f9; font-weight: 600;">${target.label}</span>
          <span style="color: #64748b; font-size: 9px; margin-left: auto;">${NODE_TYPES[target.type]}</span>
        `;
        row.onclick = () => focusNode(target);
        connContainer.appendChild(row);
      });
      insp.style.display = 'block';
    }

    function renderSingleNodeInspector(node) {
      const insp = document.getElementById('inspector');
      document.getElementById('insp-type').textContent = (NODE_TYPES[node.type] || 'COMPONENT').toUpperCase();
      document.getElementById('insp-type').style.color = NODE_COLORS[node.type];
      document.getElementById('insp-title').textContent = node.label;

      const hubBadge = document.getElementById('insp-hub-badge');
      hubBadge.style.display = node.isHub ? 'inline-block' : 'none';

      const filePath = getString(node.fileIdx);
      const pathRow = document.getElementById('insp-path-row');
      if (filePath) {
        pathRow.style.display = 'block';
        let loc = filePath;
        if (node.line !== -1) loc += `:${node.line}:${node.col !== -1 ? node.col : 0}`;
        document.getElementById('insp-path').textContent = loc;
      } else {
        pathRow.style.display = 'none';
      }

      const portsRow = document.getElementById('insp-ports-row');
      const portsBody = document.getElementById('insp-ports-body');
      portsBody.innerHTML = '';
      let hasPorts = false;
      if (node.inPorts && node.inPorts.length > 0) {
        hasPorts = true;
        node.inPorts.forEach(inp => {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><strong style="color: #38bdf8;">${inp.name}</strong></td><td style="color: #64748b;">IN</td><td style="color: #94a3b8;">${inp.type || 'Any'}</td>`;
          portsBody.appendChild(tr);
        });
      }
      if (node.outType) {
        hasPorts = true;
        const tr = document.createElement('tr');
        tr.innerHTML = `<td><strong style="color: #10b981;">return</strong></td><td style="color: #64748b;">OUT</td><td style="color: #10b981;">${node.outType}</td>`;
        portsBody.appendChild(tr);
      }
      portsRow.style.display = hasPorts ? 'block' : 'none';

      const sig = getString(node.sigIdx);
      const sigRow = document.getElementById('insp-sig-row');
      if (sig) {
        sigRow.style.display = 'block';
        document.getElementById('insp-sig').textContent = sig;
      } else {
        sigRow.style.display = 'none';
      }

      const doc = getString(node.docIdx);
      const docRow = document.getElementById('insp-doc-row');
      if (doc) {
        docRow.style.display = 'block';
        document.getElementById('insp-doc').textContent = doc;
      } else {
        docRow.style.display = 'none';
      }

      const raw = getString(node.symIdx);
      const rawRow = document.getElementById('insp-raw-row');
      if (raw) {
        rawRow.style.display = 'block';
        document.getElementById('insp-raw').textContent = raw;
      } else {
        rawRow.style.display = 'none';
      }

      const code = getString(node.codeIdx);
      const codeRow = document.getElementById('insp-code-row');
      if (codeRow) {
        codeRow.style.display = code ? 'block' : 'none';
      }

      const btnViewCode = document.getElementById('btn-view-code');
      if (btnViewCode) {
        btnViewCode.style.display = 'flex';
        if (code) {
          btnViewCode.classList.remove('disabled');
          btnViewCode.title = 'View Defining Code for ' + node.label;
        } else {
          btnViewCode.classList.add('disabled');
          btnViewCode.title = 'No defining code block available for this symbol';
        }
      }

      const activeLinkSet = new Set(nodeLinkIndices[node.id] || []);
      if (node.isHub) {
        const callers = hubCallers[node.id] || [];
        callers.forEach(cIdx => activeLinkSet.add(cIdx));
      }
      const activeLinks = Array.from(activeLinkSet);

      document.getElementById('insp-conn-count').textContent = activeLinks.length;
      const connContainer = document.getElementById('insp-connections');
      connContainer.innerHTML = '';

      activeLinks.slice(0, 60).forEach(lIdx => {
        const l = links[lIdx];
        const isOutgoing = l.s === node.id;
        const otherId = isOutgoing ? l.t : l.s;
        const target = nodes[otherId];
        if (target) {
          const row = document.createElement('div');
          row.className = 'pin-row';
          const badgeMult = l.callCount > 1 ? `<span style="color:#10b981;font-size:9px;margin-left:4px;">(x${l.callCount})</span>` : '';
          const dirArrow = isOutgoing ? '->' : '<-';
          const stubFlag = l.isHubStub ? `<span style="color:#38bdf8;font-size:9px;">[STUB]</span>` : '';
          row.innerHTML = `
            <span style="color: ${EDGE_COLORS[l.type]}; font-weight: 700;">${dirArrow}</span>
            <span class="legend-dot" style="background: ${NODE_COLORS[target.type]}"></span>
            <span style="color: #f1f5f9; font-weight: 600;">${target.label}</span>
            ${badgeMult} ${stubFlag}
            <span style="color: #64748b; font-size: 9px; margin-left: auto;">${NODE_TYPES[target.type]}</span>
          `;
          row.onclick = () => focusNode(target);
          connContainer.appendChild(row);
        }
      });

      insp.style.display = 'block';
    }

    document.getElementById('btn-zoom-in').onclick = () => {
      scale = Math.min(6.0, scale * 1.3);
      render();
    };
    document.getElementById('btn-zoom-out').onclick = () => {
      scale = Math.max(0.02, scale / 1.3);
      render();
    };
    document.getElementById('btn-reset').onclick = () => {
      scale = 1.0;
      panX = 80;
      panY = 80;
      render();
    };
    document.getElementById('btn-fit').onclick = () => {
      fitBoard();
    };
    document.getElementById('insp-close').onclick = () => {
      deselectNode();
    };

    function fitBoard() {
      if (!nodes.length) return;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (let i = 0; i < packages.length; i++) {
        const p = packages[i];
        if (p.x < minX) minX = p.x;
        if (p.y < minY) minY = p.y;
        if (p.x + p.w > maxX) maxX = p.x + p.w;
        if (p.y + p.h > maxY) maxY = p.y + p.h;
      }
      const boardW = Math.max(800, maxX - minX + 280);
      const boardH = Math.max(600, maxY - minY + 280);
      scale = Math.min(canvas.width / boardW, canvas.height / boardH, 1.2);
      panX = (canvas.width - boardW * scale) / 2 - minX * scale + 140 * scale;
      panY = (canvas.height - boardH * scale) / 2 - minY * scale + 140 * scale;
      render();
    }

    const searchInput = document.getElementById('search-input');
    const searchResults = document.getElementById('search-results');

    searchInput.addEventListener('input', (e) => {
      const q = e.target.value.trim().toLowerCase();
      if (!q) {
        searchResults.style.display = 'none';
        return;
      }
      const matches = [];
      for (let i = 0; i < nodeCount && matches.length < 15; i++) {
        const n = nodes[i];
        if (n.label && n.label.toLowerCase().includes(q)) {
          matches.push(n);
        }
      }
      if (matches.length === 0) {
        searchResults.style.display = 'none';
        return;
      }
      searchResults.innerHTML = '';
      matches.forEach(m => {
        const div = document.createElement('div');
        div.className = 'search-item';
        div.innerHTML = `
          <span class="legend-dot" style="background: ${NODE_COLORS[m.type]}"></span>
          <span style="font-weight: 600; color: #fff;">${m.label}</span>
          <span style="color: #64748b; font-size: 9px; margin-left: auto;">${NODE_TYPES[m.type]}</span>
        `;
        div.onclick = () => {
          focusNode(m);
          searchResults.style.display = 'none';
          searchInput.value = '';
        };
        searchResults.appendChild(div);
      });
      searchResults.style.display = 'block';
    });

    document.addEventListener('click', (e) => {
      if (!e.target.closest('.search-wrap')) {
        searchResults.style.display = 'none';
      }
    });

    let currentCodeNode = null;

    function openCodeViewer(node) {
      if (!node) return;
      currentCodeNode = node;
      const modal = document.getElementById('code-viewer-modal');
      const backdrop = document.getElementById('code-viewer-backdrop');
      const typeSpan = document.getElementById('code-modal-type');
      const locSpan = document.getElementById('code-modal-loc');
      const titleSpan = document.getElementById('code-modal-title');
      const codeText = document.getElementById('code-text');
      const gutter = document.getElementById('code-gutter');

      const code = getString(node.codeIdx);
      const filePath = getString(node.fileIdx) || 'unknown';
      const startLine = node.line > 0 ? node.line : 1;
      const endLine = node.endLine > 0 ? node.endLine : (startLine + (code ? code.split('\n').length - 1 : 0));

      typeSpan.textContent = (NODE_TYPES[node.type] || 'SYMBOL').toUpperCase();
      typeSpan.style.color = NODE_COLORS[node.type] || '#38bdf8';
      titleSpan.textContent = node.label;
      locSpan.textContent = `${filePath} : L${startLine}${endLine > startLine ? ' - L' + endLine : ''}`;

      if (code) {
        codeText.textContent = code;
        const lineCount = code.split('\n').length;
        let gutterHtml = '';
        for (let i = 0; i < lineCount; i++) {
          gutterHtml += `<div>${startLine + i}</div>`;
        }
        gutter.innerHTML = gutterHtml;
        gutter.style.display = 'block';
      } else {
        codeText.textContent = `// No defining source code block available in the database for:\n// ${node.label} (${getString(node.symIdx) || 'Unknown Symbol'})\n// Location: ${filePath}:${startLine}`;
        gutter.style.display = 'none';
      }

      backdrop.style.display = 'block';
      modal.style.display = 'flex';
    }

    function closeCodeViewer() {
      const modal = document.getElementById('code-viewer-modal');
      const backdrop = document.getElementById('code-viewer-backdrop');
      if (modal) modal.style.display = 'none';
      if (backdrop) backdrop.style.display = 'none';
      currentCodeNode = null;
    }

    function toggleCodeViewerForSelected() {
      const modal = document.getElementById('code-viewer-modal');
      if (modal && modal.style.display === 'flex') {
        closeCodeViewer();
      } else if (selectedNodes.size === 1) {
        const singleId = Array.from(selectedNodes)[0];
        openCodeViewer(nodes[singleId]);
      }
    }

    const btnViewCode = document.getElementById('btn-view-code');
    if (btnViewCode) {
      btnViewCode.onclick = () => toggleCodeViewerForSelected();
    }

    const btnViewCodeInline = document.getElementById('btn-view-code-inline');
    if (btnViewCodeInline) {
      btnViewCodeInline.onclick = () => toggleCodeViewerForSelected();
    }

    const modalClose = document.getElementById('code-modal-close');
    if (modalClose) {
      modalClose.onclick = () => closeCodeViewer();
    }

    const modalBackdrop = document.getElementById('code-viewer-backdrop');
    if (modalBackdrop) {
      modalBackdrop.onclick = () => closeCodeViewer();
    }

    const btnCopy = document.getElementById('btn-copy-code');
    if (btnCopy) {
      btnCopy.onclick = () => {
        if (!currentCodeNode) return;
        const code = getString(currentCodeNode.codeIdx);
        if (code) {
          navigator.clipboard.writeText(code).then(() => {
            const copyText = document.getElementById('btn-copy-text');
            if (copyText) {
              const orig = copyText.textContent;
              copyText.textContent = 'Copied!';
              setTimeout(() => { copyText.textContent = orig; }, 1500);
            }
          });
        }
      };
    }

    resizeCanvas();
    setTimeout(fitBoard, 50);
"""
