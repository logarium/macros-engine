/* GAMMARIA — MACROS Engine v4.0 Frontend
   Vanilla JS, WebSocket client, 5-tab SPA. */

let ws = null;
let state = null;
let reconnectTimer = null;

// ─── WEBSOCKET ───

function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => {
        document.getElementById('connection-status').textContent = 'connected';
        document.getElementById('connection-status').className = 'ws-connected';
        if (reconnectTimer) {
            clearInterval(reconnectTimer);
            reconnectTimer = null;
            showToast('Reconnected to engine.', 'success', 3000);
        }
    };

    ws.onclose = () => {
        document.getElementById('connection-status').textContent = 'disconnected';
        document.getElementById('connection-status').className = 'ws-disconnected';
        // DG-23: Auto-save on disconnect
        fetch('/api/save', { method: 'POST' }).catch(() => {});
        showToast('Connection lost. State auto-saved.', 'warning');
        if (!reconnectTimer) { reconnectTimer = setInterval(connectWS, 3000); }
    };

    ws.onerror = () => {};

    ws.onmessage = (evt) => {
        const msg = JSON.parse(evt.data);
        handleEvent(msg.event, msg.data);
    };
}

function handleEvent(event, data) {
    switch (event) {
        case 'state_update':
            state = data;
            renderAll();
            break;
        case 'phase_change':
            if (state) { state.phase = data.phase; }
            renderPhase();
            break;
        case 'narration':
            addNarration(data.type, data.text);
            break;
        case 'log_entry':
            addLogEntry(data);
            // Mirror to side panel live log
            addSidePanelLogEntry(document.getElementById('sp-log-feed'), data);
            break;
        case 'creative_pending':
            showWaiting(data.count, data.types);
            break;
        case 'creative_resolved':
            hideWaiting();
            break;
        case 'combat_update':
            if (state) { state.combat = data; }
            renderCombatDashboard();
            break;
        case 'error':
            showToast(data.message || 'An error occurred', 'error');
            addLogEntry({type: 'ERROR', detail: data.message || 'An error occurred',
                         timestamp: new Date().toISOString()});
            break;
    }
}

// ─── TABS ───

document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.add('active');
        if (btn.dataset.tab === 'map-tab' && typeof _mapFitRecalc === 'function') _mapFitRecalc();
    });
});

// ─── RENDER ───

function renderAll() {
    if (!state) return;
    renderHeader();
    renderPlay();
    renderParty();
    renderTrack();
    renderForge();
    renderLogs();
    renderSidePanel();
    renderFooter();
}

function renderHeader() {
    const m = state.meta || {};
    document.getElementById('h-session').textContent = `Session ${m.session_id || '—'}`;
    document.getElementById('h-date').textContent = m.in_game_date || '—';
    document.getElementById('h-zone').textContent = m.pc_zone || '—';
    document.getElementById('h-season').textContent = m.season || '—';
    document.getElementById('h-intensity').textContent = m.campaign_intensity || '—';

    // Danger clocks
    const dc = document.getElementById('danger-clocks');
    dc.innerHTML = '';
    (state.danger_clocks || []).forEach(c => {
        const badge = document.createElement('span');
        badge.className = 'danger-badge';
        badge.textContent = `${c.name} ${c.progress}/${c.max_progress}`;
        dc.appendChild(badge);
    });

    // DG-25: Call budget in header
    const callCount = state.creative_call_count || 0;
    const budgetEl = document.getElementById('h-call-budget');
    if (callCount > 0) {
        budgetEl.textContent = `Calls: ${callCount}/20`;
        if (callCount >= 18) { budgetEl.className = 'call-budget-badge danger'; }
        else if (callCount >= 15) { budgetEl.className = 'call-budget-badge caution'; }
        else { budgetEl.className = 'call-budget-badge safe'; }
    } else {
        budgetEl.textContent = '';
        budgetEl.className = 'call-budget-badge';
    }
}

function renderPlay() {
    renderPhase();

    // Narration buffer
    if (state.narration && state.narration.length > 0) {
        const area = document.getElementById('narration-area');
        area.innerHTML = '';
        state.narration.forEach(n => {
            addNarrationElement(area, n.type, n.text);
        });
    }
}

function renderPhase() {
    const phase = state ? state.phase : 'idle';
    const cpArea = document.getElementById('cp-area');
    const waiting = document.getElementById('waiting-overlay');
    const combatArea = document.getElementById('combat-area');

    const combatStartArea = document.getElementById('combat-start-area');

    if (phase === 'idle') {
        cpArea.style.display = 'block';
        waiting.classList.remove('active');
        combatArea.style.display = 'none';
        renderCPs();
        renderCombatStartArea();
        renderModeBar(true);
    } else if (phase === 'in_combat') {
        cpArea.style.display = 'none';
        waiting.classList.remove('active');
        combatArea.style.display = 'flex';
        if (combatStartArea) combatStartArea.style.display = 'none';
        renderCombatDashboard();
        renderModeBar(false);
    } else if (phase === 'await_creative') {
        cpArea.style.display = 'none';
        combatArea.style.display = 'none';
        if (combatStartArea) combatStartArea.style.display = 'none';
        showWaiting(state.creative_pending, []);
        renderModeBar(false);
    } else {
        cpArea.style.display = 'none';
        combatArea.style.display = 'none';
        if (combatStartArea) combatStartArea.style.display = 'none';
        waiting.classList.remove('active');
        renderModeBar(false);
    }
}

function renderCPs() {
    const container = document.getElementById('cp-buttons');
    container.innerHTML = '';
    const cps = state.crossing_points || [];

    if (cps.length === 0) {
        container.innerHTML = '<span style="color: var(--text-dim)">No crossing points available</span>';
        return;
    }

    cps.forEach(cp => {
        const btn = document.createElement('button');
        btn.className = 'cp-btn';
        btn.textContent = cp.label;
        btn.addEventListener('click', () => doTravel(cp.destination));
        container.appendChild(btn);
    });
}

function renderCombatStartArea() {
    const area = document.getElementById('combat-start-area');
    const container = document.getElementById('combat-start-buttons');
    if (!area || !container) return;

    // Find NPCs in current zone with BX stats (non-companions)
    const npcs = (state.other_npcs || []).filter(n =>
        n.zone === state.meta.pc_zone && (n.bx_ac || n.bx_hd) &&
        n.status !== 'dead' && n.status !== 'destroyed'
    );

    if (npcs.length === 0) {
        area.style.display = 'none';
        return;
    }

    area.style.display = 'block';
    container.innerHTML = '';
    npcs.forEach(npc => {
        const btn = document.createElement('button');
        btn.className = 'combat-start-btn';
        btn.textContent = `${npc.name} (AC${npc.bx_ac} HD${npc.bx_hd})`;
        btn.addEventListener('click', () => doStartCombat(npc.name));
        container.appendChild(btn);
    });
}

async function doStartCombat(npcName) {
    try {
        const resp = await fetch('/api/combat/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({npc_name: npcName}),
        });
        const data = await resp.json();
        if (!data.success) {
            showToast(data.error || 'Failed to start combat', 'error');
        }
    } catch (e) {
        showToast('Combat start failed: ' + e.message, 'error');
    }
}

let _responsePollTimer = null;

function showWaiting(count, types) {
    const overlay = document.getElementById('waiting-overlay');
    overlay.classList.add('active');
    document.getElementById('waiting-text').textContent =
        `Waiting for Claude... (${count || '?'} requests)`;
    document.getElementById('waiting-sub').textContent =
        'Open Claude Desktop and process pending creative requests';
    // Start polling for response file (fallback when MCP forward fails)
    startResponsePolling();
}

function hideWaiting() {
    document.getElementById('waiting-overlay').classList.remove('active');
    document.getElementById('cp-area').style.display = 'block';
    stopResponsePolling();
    // Refresh state
    fetchState();
}

function startResponsePolling() {
    if (_responsePollTimer) return; // already polling
    _responsePollTimer = setInterval(async () => {
        try {
            const resp = await fetch('/api/creative/check_response');
            const result = await resp.json();
            if (result.success) {
                // Response was picked up from file — stop polling
                stopResponsePolling();
                // state_update and creative_resolved come via WebSocket broadcast
            }
        } catch (e) {
            // ignore — server might be busy
        }
    }, 3000);
}

function stopResponsePolling() {
    if (_responsePollTimer) {
        clearInterval(_responsePollTimer);
        _responsePollTimer = null;
    }
}

function addNarration(type, text) {
    const area = document.getElementById('narration-area');
    addNarrationElement(area, type, text);
    area.scrollTop = area.scrollHeight;
}

function addNarrationElement(container, type, text) {
    const div = document.createElement('div');
    div.className = `narration-entry ${type}`;

    const label = document.createElement('div');
    label.className = 'narration-label';
    const labelMap = { 'PLAYER_INPUT': 'Thoron', 'NARR_PLAYER_RESPONSE': 'Narrator' };
    label.textContent = labelMap[type] || type.replace(/_/g, ' ');

    const content = document.createElement('div');
    content.textContent = text;

    div.appendChild(label);
    div.appendChild(content);
    container.appendChild(div);
}

// ─── REST (voluntary T&P) ───

async function restDays() {
    const days = parseInt(document.getElementById('rest-days').value) || 1;
    try {
        const resp = await fetch('/api/rest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days }),
        });
        const result = await resp.json();
        if (!result.success) {
            showToast(result.error || 'Rest failed', 'error');
        }
    } catch (e) {
        showToast('Rest failed', 'error');
    }
}

// ─── CHAT INPUT ───

async function submitPlayerInput() {
    const input = document.getElementById('player-input');
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    try {
        const resp = await fetch('/api/chat/input', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });
        const result = await resp.json();
        if (!result.success) {
            showToast(result.error || 'Failed to send input', 'error');
        }
    } catch (e) {
        showToast('Failed to send input', 'error');
    }
}

// Enter key on chat input
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('player-input');
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitPlayerInput();
            }
        });
    }
});

// ─── MAP TAB (pan & zoom) ───

var _mapFitRecalc = null;
(function initMap() {
    let scale = 1, fitScale = 1, needsInitFit = true;
    let panning = false, startX, startY, scrollLeft, scrollTop;
    const container = document.getElementById('map-container');
    const img = document.getElementById('map-image');
    if (!container || !img) return;

    function calcFitScale() {
        if (!img.naturalWidth || !container.clientWidth || !container.clientHeight) return 0;
        return Math.min(
            container.clientWidth / img.naturalWidth,
            container.clientHeight / img.naturalHeight
        );
    }

    function applyScale() {
        img.style.width = (img.naturalWidth * scale) + 'px';
        img.style.height = (img.naturalHeight * scale) + 'px';
    }

    function fitToWindow() {
        const fs = calcFitScale();
        if (fs <= 0) return;
        fitScale = fs;
        scale = fitScale;
        applyScale();
        needsInitFit = false;
    }

    _mapFitRecalc = function() {
        if (needsInitFit) fitToWindow();
    };

    img.addEventListener('load', fitToWindow);

    window.addEventListener('resize', () => {
        const newFit = calcFitScale();
        if (newFit <= 0) return;
        if (scale === fitScale) { fitScale = newFit; scale = newFit; applyScale(); }
        else { fitScale = newFit; }
    });

    container.addEventListener('mousedown', (e) => {
        panning = true;
        startX = e.clientX;
        startY = e.clientY;
        scrollLeft = container.scrollLeft;
        scrollTop = container.scrollTop;
    });
    window.addEventListener('mouseup', () => { panning = false; });
    window.addEventListener('mousemove', (e) => {
        if (!panning) return;
        container.scrollLeft = scrollLeft - (e.clientX - startX);
        container.scrollTop = scrollTop - (e.clientY - startY);
    });

    container.addEventListener('wheel', (e) => {
        e.preventDefault();
        const rect = container.getBoundingClientRect();
        const mx = e.clientX - rect.left + container.scrollLeft;
        const my = e.clientY - rect.top + container.scrollTop;
        const imgX = mx / scale;
        const imgY = my / scale;

        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const maxScale = img.naturalWidth ? (img.naturalWidth / container.clientWidth) * 2 : 5;
        scale = Math.min(Math.max(scale * delta, fitScale * 0.5), maxScale);
        applyScale();

        container.scrollLeft = imgX * scale - (e.clientX - rect.left);
        container.scrollTop = imgY * scale - (e.clientY - rect.top);
    }, { passive: false });
})();

// ─── PARTY TAB ───

// Track expanded cards across re-renders
const _expandedCards = new Set();

// Portrait mapping: first name (lowercase) → image path
const PORTRAIT_MAP = {
    'thoron': '/images/thoron_gpt.png',
    'valania': '/images/valania_gpt.png',
    'suzanne': '/images/suzanne_gpt.png',
    'lalholm': '/images/lalholm_gpt.png',
    'lithoe': '/images/lithoe_gpt.png',
    'guldur': '/images/guldur_gpt.png',
    'crandurth': '/images/crandurth_gpt.png',
};

function getPortraitUrl(name) {
    if (!name) return '';
    // Match on first name or any word in the full name
    const words = name.toLowerCase().split(/\s+/);
    for (const w of words) {
        if (PORTRAIT_MAP[w]) return PORTRAIT_MAP[w];
    }
    return '';
}

function portraitImg(name, cssClass) {
    const url = getPortraitUrl(name);
    if (!url) return '';
    return `<img src="${url}" alt="${esc(name)}" class="${cssClass}" onerror="this.style.display='none'">`;
}

function _detailRow(label, value) {
    if (!value) return '';
    return `<div class="detail-row"><span class="detail-label">${esc(label)}</span><span class="detail-value">${esc(value)}</span></div>`;
}

function _detailBlock(label, items) {
    if (!items || !items.length) return '';
    return `<div class="detail-block"><div class="detail-block-label">${esc(label)}</div>${items.map(i => `<div class="detail-value" style="font-size:12px;margin-left:8px">- ${esc(i)}</div>`).join('')}</div>`;
}

function _historyEntries(history) {
    if (!history || !history.length) return '';
    return `<div class="detail-block"><div class="detail-block-label">Recent History</div>${history.map(h => `<div class="history-entry"><span class="hist-session">S${h.session || '?'}</span> ${esc(h.event || h.description || '')}</div>`).join('')}</div>`;
}

function _trustBadge(level) {
    if (!level || level === 'unknown') return '<span class="status-badge trust-unknown">trust ?</span>';
    return `<span class="status-badge trust-${level}">trust ${esc(level)}</span>`;
}

function _stressBadge(level) {
    if (!level || level === 'unknown') return '<span class="status-badge stress-unknown">stress ?</span>';
    return `<span class="status-badge stress-${level}">stress ${esc(level)}</span>`;
}

function renderParty() {
    // PC
    const pcSection = document.getElementById('pc-section');
    pcSection.innerHTML = '';
    const pc = state.pc;
    if (pc) {
        const card = document.createElement('div');
        const pcKey = 'pc';
        card.className = 'pc-card' + (_expandedCards.has(pcKey) ? ' expanded' : '');
        card.onclick = () => {
            card.classList.toggle('expanded');
            if (card.classList.contains('expanded')) _expandedCards.add(pcKey);
            else _expandedCards.delete(pcKey);
        };

        // Build expanded detail section
        let detailHtml = '';
        const psych = pc.psychological_state;
        if (psych && psych.length) {
            detailHtml += _detailBlock('Psychological State', psych);
        }
        if (pc.secrets && pc.secrets.length) {
            detailHtml += _detailBlock('Secrets', pc.secrets);
        }
        if (pc.affection_summary) {
            detailHtml += _detailRow('Affection', pc.affection_summary);
        }
        const repLvls = pc.reputation_levels;
        if (repLvls && Object.keys(repLvls).length) {
            detailHtml += '<div class="detail-block"><div class="detail-block-label">Reputation Levels</div>';
            for (const [fac, lvl] of Object.entries(repLvls)) {
                detailHtml += `<div class="detail-row" style="margin-left:8px"><span class="detail-label" style="min-width:auto">${esc(fac)}</span><span class="detail-value">${esc(lvl)}</span></div>`;
            }
            detailHtml += '</div>';
        }
        detailHtml += _historyEntries(pc.history);

        card.innerHTML = `
            <div class="card-layout">
                <div class="card-content">
                    <div class="comp-header">
                        <div class="comp-header-text">
                            <div class="name">${esc(pc.name)}</div>
                            <div class="comp-class">${esc(pc.class_level || '')}</div>
                        </div>
                    </div>
                    <div class="comp-stats">${esc(pc.stats || '')}</div>
                    <div class="detail">${esc(pc.zone || '—')} | ${esc(pc.reputation || '—')}</div>
                    ${pc.conditions && pc.conditions.length ? `<div class="detail" style="color:var(--red)">Conditions: ${esc(pc.conditions.join(', '))}</div>` : ''}
                    ${pc.equipment_notes ? `<div class="detail">Gear: ${esc(pc.equipment_notes)}</div>` : ''}
                    ${pc.goals && pc.goals.length ? `<div class="detail" style="margin-top:8px">Goals:<ul>${pc.goals.map(g => `<li>${esc(g)}</li>`).join('')}</ul></div>` : ''}
                </div>
                ${portraitImg(pc.name, 'portrait portrait-lg')}
            </div>
            ${detailHtml ? `<div class="card-detail">${detailHtml}</div>` : ''}
        `;
        pcSection.appendChild(card);
    }

    // Companions
    const compSection = document.getElementById('companions-section');
    compSection.innerHTML = '';
    (state.companions || []).forEach(npc => {
        const card = document.createElement('div');
        const compKey = 'comp:' + npc.name;
        card.className = 'companion-card' + (_expandedCards.has(compKey) ? ' expanded' : '');
        card.onclick = () => {
            card.classList.toggle('expanded');
            if (card.classList.contains('expanded')) _expandedCards.add(compKey);
            else _expandedCards.delete(compKey);
        };
        const nameClass = npc.with_pc ? 'comp-name with-pc' : 'comp-name';
        const wpBadge = npc.with_pc ? '<span class="wp-badge">WITH YOU</span>' : '';
        const zoneColor = npc.with_pc ? 'var(--gold)' : 'var(--blue)';

        // Stat line
        const stats = [];
        if (npc.bx_ac) stats.push(`AC ${npc.bx_ac}`);
        if (npc.bx_hd) stats.push(`HD ${npc.bx_hd}`);
        if (npc.bx_hp_max) stats.push(`HP ${npc.bx_hp}/${npc.bx_hp_max}`);
        if (npc.bx_at) stats.push(`AT +${npc.bx_at}`);
        if (npc.bx_dmg) stats.push(`Dmg ${npc.bx_dmg}`);
        if (npc.bx_ml) stats.push(`ML ${npc.bx_ml}`);
        const statLine = stats.join(' | ');

        // Relationship to PC (compact view)
        let relLine = '';
        if (npc.affection_levels) {
            const toPC = npc.affection_levels['Thoron'] || npc.affection_levels['thoron'];
            if (toPC) relLine = `<div class="comp-rel">Thoron: ${esc(toPC)}</div>`;
        }

        // Build expanded detail section
        let detailHtml = '';
        if (npc.appearance) detailHtml += _detailRow('Appearance', npc.appearance);
        if (npc.faction) detailHtml += _detailRow('Faction', npc.faction);
        detailHtml += `<div style="margin:6px 0">${_trustBadge(npc.trust_in_pc)}${_stressBadge(npc.stress_or_fatigue)}</div>`;
        if (npc.motivation_shift) detailHtml += _detailRow('Motivation', npc.motivation_shift);
        if (npc.loyalty_change) detailHtml += _detailRow('Loyalty', npc.loyalty_change);
        if (npc.grievances) detailHtml += _detailRow('Grievances', npc.grievances);
        if (npc.future_flashpoints) detailHtml += _detailRow('Flashpoints', npc.future_flashpoints);
        if (npc.agency_notes) detailHtml += _detailRow('Agency', npc.agency_notes);

        // Full affection levels
        if (npc.affection_levels && Object.keys(npc.affection_levels).length) {
            detailHtml += '<div class="detail-block"><div class="detail-block-label">Affection Levels</div><div>';
            for (const [name, level] of Object.entries(npc.affection_levels)) {
                detailHtml += `<span class="affection-row"><span class="aff-name">${esc(name)}</span>: <span class="aff-level">${esc(level)}</span></span>`;
            }
            detailHtml += '</div></div>';
        }

        if (npc.knowledge) detailHtml += _detailRow('Knowledge', npc.knowledge);
        if (npc.next_action) detailHtml += _detailRow('Next Action', npc.next_action);
        detailHtml += _historyEntries(npc.history);

        const portraitClass = 'portrait' + (npc.with_pc ? ' with-pc' : '');
        card.innerHTML = `
            <div class="card-layout">
                <div class="card-content">
                    <div class="comp-header">
                        <div class="comp-header-text">
                            <div class="${nameClass}">${esc(npc.name)} ${wpBadge}</div>
                            <div class="comp-class">${esc(npc.class_level)}</div>
                        </div>
                    </div>
                    <div class="comp-stats">${statLine}</div>
                    <div class="comp-zone" style="color:${zoneColor}">${esc(npc.zone)}${npc.with_pc ? '' : ' (away)'}</div>
                    <div class="comp-traits">${esc(npc.trait)}</div>
                    ${npc.objective ? `<div class="comp-obj">${esc(npc.objective)}</div>` : ''}
                    ${relLine}
                </div>
                ${portraitImg(npc.name, portraitClass)}
            </div>
            ${detailHtml ? `<div class="card-detail">${detailHtml}</div>` : ''}
        `;
        compSection.appendChild(card);
    });

    // Other NPCs
    if (state.other_npcs && state.other_npcs.length > 0) {
        const header = document.createElement('div');
        header.className = 'section-header';
        header.textContent = `Other NPCs (${state.other_npcs.length})`;
        compSection.appendChild(header);

        const table = document.createElement('table');
        table.className = 'data-table';
        table.innerHTML = `<thead><tr><th>Name</th><th>Zone</th><th>Role</th><th>Status</th></tr></thead>`;
        const tbody = document.createElement('tbody');

        state.other_npcs.forEach(npc => {
            const npcKey = 'npc:' + npc.name;
            const row = document.createElement('tr');
            const statusColor = npc.status === 'dead' ? 'var(--red)' : 'inherit';
            row.innerHTML = `
                <td>${esc(npc.name)}</td>
                <td style="color:var(--blue)">${esc(npc.zone)}</td>
                <td>${esc(npc.role)}</td>
                <td style="color:${statusColor}">${esc(npc.status)}</td>
            `;

            // Build detail row
            const detailRow = document.createElement('tr');
            detailRow.className = 'npc-detail-row' + (_expandedCards.has(npcKey) ? ' visible' : '');
            let npcDetail = '';
            if (npc.trait) npcDetail += _detailRow('Trait', npc.trait);
            if (npc.appearance) npcDetail += _detailRow('Appearance', npc.appearance);
            if (npc.faction) npcDetail += _detailRow('Faction', npc.faction);
            if (npc.objective) npcDetail += _detailRow('Objective', npc.objective);
            if (npc.next_action) npcDetail += _detailRow('Next Action', npc.next_action);
            // BX stat line
            const npcStats = [];
            if (npc.bx_ac) npcStats.push(`AC ${npc.bx_ac}`);
            if (npc.bx_hd) npcStats.push(`HD ${npc.bx_hd}`);
            if (npc.bx_hp_max) npcStats.push(`HP ${npc.bx_hp}/${npc.bx_hp_max}`);
            if (npc.bx_at) npcStats.push(`AT +${npc.bx_at}`);
            if (npc.bx_dmg) npcStats.push(`Dmg ${npc.bx_dmg}`);
            if (npc.bx_ml) npcStats.push(`ML ${npc.bx_ml}`);
            if (npcStats.length) npcDetail += _detailRow('Stats', npcStats.join(' | '));
            if (npc.knowledge) npcDetail += _detailRow('Knowledge', npc.knowledge);

            detailRow.innerHTML = `<td colspan="4"><div class="npc-detail-content">${npcDetail || '<em style="color:var(--text-dim)">No additional detail</em>'}</div></td>`;

            row.onclick = () => {
                detailRow.classList.toggle('visible');
                if (detailRow.classList.contains('visible')) _expandedCards.add(npcKey);
                else _expandedCards.delete(npcKey);
            };

            tbody.appendChild(row);
            tbody.appendChild(detailRow);
        });
        table.appendChild(tbody);
        compSection.appendChild(table);
    }
}

// ─── TRACK TAB ───

function renderTrack() {
    renderClocks('active-clocks', state.active_clocks || [], 'active');
    renderClocks('fired-clocks', state.fired_clocks || [], 'fired');
    renderClocks('halted-clocks', state.halted_clocks || [], 'halted');

    // Engines
    const engSection = document.getElementById('engines-section');
    engSection.innerHTML = '';
    (state.engines || []).forEach(eng => {
        const row = document.createElement('div');
        row.className = 'engine-row';
        const statusClass = eng.status === 'active' ? 'active' : 'dormant';
        row.innerHTML = `
            <span>${esc(eng.name)}</span>
            <span class="engine-status ${statusClass}">[${esc(eng.version)}] ${esc(eng.status).toUpperCase()}</span>
        `;
        engSection.appendChild(row);
    });

    // Factions
    const facSection = document.getElementById('factions-section');
    facSection.innerHTML = '';
    if (state.factions && state.factions.length > 0) {
        const table = document.createElement('table');
        table.className = 'data-table';
        table.innerHTML = '<tr><th>Faction</th><th>Status</th><th>Disposition</th><th>Trend</th></tr>';
        state.factions.forEach(f => {
            const dispColor = f.disposition === 'hostile' ? 'var(--red)' :
                              f.disposition === 'friendly' ? 'var(--green)' : 'inherit';
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${esc(f.name)}</td>
                <td>${esc(f.status)}</td>
                <td style="color:${dispColor}">${esc(f.disposition)}</td>
                <td>${esc(f.trend || '—')}</td>
            `;
            table.appendChild(row);
        });
        facSection.appendChild(table);
    }

    // Threads
    const thrSection = document.getElementById('threads-section');
    thrSection.innerHTML = '';
    (state.open_threads || []).forEach(t => {
        const div = document.createElement('div');
        div.style.cssText = 'padding:3px 0;font-size:12px;color:var(--purple)';
        const zone = t.zone ? ` [${t.zone}]` : '';
        div.textContent = `${t.description}${zone}`;
        thrSection.appendChild(div);
    });
}

function renderClocks(containerId, clocks, mode) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';

    if (clocks.length === 0) {
        container.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:4px 0">None</div>';
        return;
    }

    clocks.forEach(c => {
        const row = document.createElement('div');
        row.className = 'clock-row';

        const pct = c.max_progress > 0 ? c.progress / c.max_progress : 0;
        let nameColor, barClass;
        if (mode === 'fired') { nameColor = 'var(--text-dim)'; barClass = 'fired'; }
        else if (mode === 'halted') { nameColor = 'var(--yellow)'; barClass = 'yellow'; }
        else if (pct >= 0.75) { nameColor = 'var(--red)'; barClass = 'red'; }
        else if (pct >= 0.5) { nameColor = 'var(--yellow)'; barClass = 'yellow'; }
        else { nameColor = 'var(--green)'; barClass = 'green'; }

        let tags = '';
        if (c.is_cadence) tags += '<span class="clock-tag cadence">CADENCE</span> ';
        if (c.trigger_fired) tags += '<span class="clock-tag fired">FIRED</span> ';
        if (mode === 'halted') tags += '<span class="clock-tag halted">HALTED</span> ';

        const progressText = mode === 'fired' ? 'FIRED' : `${c.progress}/${c.max_progress}`;

        row.innerHTML = `
            <span class="clock-name" style="color:${nameColor}">${esc(c.name)} ${tags}</span>
            <div class="clock-bar-bg">
                <div class="clock-bar-fill ${barClass}" style="width:${pct * 100}%"></div>
            </div>
            <span class="clock-progress" style="color:${nameColor}">${progressText}</span>
        `;

        container.appendChild(row);
    });
}

// ─── FORGE TAB ───

const FORGE_TYPES = [
    { type: 'NPC_FORGE',  name: 'NPC-FORGE',  desc: 'Create a new named NPC (delta-ready insert)' },
    { type: 'EL_FORGE',   name: 'EL-FORGE',   desc: 'Design one encounter list for a zone' },
    { type: 'FAC_FORGE',  name: 'FAC-FORGE',  desc: 'Create or update a faction' },
    { type: 'CL_FORGE',   name: 'CL-FORGE',   desc: 'Design one clock' },
    { type: 'CAN_FORGE',  name: 'CAN-FORGE',  desc: 'Canonicalize a zone (NPCs, clocks, EL, PE, UA)' },
    { type: 'PE_FORGE',   name: 'PE-FORGE',   desc: 'Design one persistent procedural engine' },
    { type: 'UA_FORGE',   name: 'UA-FORGE',   desc: 'Create an Unknown Actor (persistent threat)' },
];

function renderForge() {
    const grid = document.getElementById('forge-grid');
    const status = document.getElementById('forge-status');
    grid.innerHTML = '';

    const isIdle = state && state.phase === 'idle';

    FORGE_TYPES.forEach(ft => {
        const btn = document.createElement('button');
        btn.className = 'forge-btn';
        btn.disabled = !isIdle;
        btn.innerHTML = `<div class="forge-btn-name">${esc(ft.name)}</div><div class="forge-btn-desc">${esc(ft.desc)}</div>`;
        btn.addEventListener('click', () => showForgeModal(ft));
        grid.appendChild(btn);
    });

    if (!isIdle && state) {
        status.textContent = state.phase === 'await_creative'
            ? 'Waiting for Claude to resolve pending request...'
            : `Forge unavailable during ${state.phase} phase`;
    } else {
        status.textContent = '';
    }
}

function _zoneOptions() {
    return (state && state.zones) ? state.zones : [];
}

function _factionOptions() {
    return (state && state.factions) ? state.factions.map(f => f.name) : [];
}

function _npcOptions() {
    const names = [];
    if (state && state.companions) state.companions.forEach(c => names.push(c.name));
    if (state && state.other_npcs) state.other_npcs.forEach(n => names.push(n.name));
    return names;
}

function _selectField(id, label, options, allowBlank) {
    let optHtml = allowBlank ? '<option value="">— none —</option>' : '';
    options.forEach(o => { optHtml += `<option value="${esc(o)}">${esc(o)}</option>`; });
    return `<div class="forge-form-group"><label for="${id}">${label}</label><select id="${id}" class="forge-select">${optHtml}</select></div>`;
}

function _textField(id, label, placeholder) {
    return `<div class="forge-form-group"><label for="${id}">${label}</label><input id="${id}" class="forge-input" type="text" placeholder="${esc(placeholder || '')}"></div>`;
}

function showForgeModal(ft) {
    let formHtml = '';

    switch (ft.type) {
        case 'NPC_FORGE':
            formHtml += _selectField('fg-zone', 'Zone', _zoneOptions(), false);
            formHtml += _textField('fg-role-hint', 'Role Hint (optional)', 'e.g. merchant, guard');
            formHtml += _selectField('fg-faction-hint', 'Faction Hint (optional)', _factionOptions(), true);
            break;
        case 'EL_FORGE':
            formHtml += _selectField('fg-zone', 'Zone', _zoneOptions(), false);
            break;
        case 'FAC_FORGE':
            formHtml += _selectField('fg-faction-name', 'Faction (blank = create new)', _factionOptions(), true);
            formHtml += _selectField('fg-zone-hint', 'Zone Hint (optional)', _zoneOptions(), true);
            break;
        case 'CL_FORGE':
            formHtml += _textField('fg-owner', 'Owner', 'e.g. faction name, NPC name');
            formHtml += _textField('fg-trigger-context', 'Trigger Context (optional)', 'What should fire the clock?');
            break;
        case 'CAN_FORGE':
            formHtml += _selectField('fg-zone', 'Zone', _zoneOptions(), false);
            break;
        case 'PE_FORGE':
            formHtml += _textField('fg-engine-name', 'Engine Name', 'e.g. Cairn Patrol, Trade Route Pressure');
            formHtml += _selectField('fg-zone-scope', 'Zone Scope', _zoneOptions(), false);
            formHtml += _textField('fg-trigger-event', 'Trigger Event (optional)', 'e.g. PC enters zone, clock fires');
            break;
        case 'UA_FORGE':
            formHtml += _selectField('fg-zone', 'Zone', _zoneOptions(), false);
            formHtml += _textField('fg-trigger-context', 'Trigger Context (optional)', '');
            break;
    }

    const overlay = document.createElement('div');
    overlay.id = 'forge-modal-overlay';
    const modal = document.createElement('div');
    modal.id = 'forge-modal';
    modal.innerHTML = `
        <div class="forge-modal-title">${esc(ft.name)}</div>
        ${formHtml}
        <div class="forge-modal-actions">
            <button class="forge-modal-cancel" id="fg-cancel">Cancel</button>
            <button class="forge-modal-confirm" id="fg-confirm">Forge</button>
        </div>
    `;
    overlay.appendChild(modal);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);

    document.getElementById('fg-cancel').addEventListener('click', () => overlay.remove());
    document.getElementById('fg-confirm').addEventListener('click', async () => {
        const params = _gatherForgeParams(ft.type);
        const btn = document.getElementById('fg-confirm');
        btn.disabled = true;
        btn.textContent = 'Forging...';
        await doForge(ft.type, params);
        overlay.remove();
    });
}

function _gatherForgeParams(forgeType) {
    const val = (id) => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
    switch (forgeType) {
        case 'NPC_FORGE':
            return { zone: val('fg-zone'), role_hint: val('fg-role-hint'), faction_hint: val('fg-faction-hint') };
        case 'EL_FORGE':
            return { zone: val('fg-zone') };
        case 'FAC_FORGE':
            return { faction_name: val('fg-faction-name'), zone_hint: val('fg-zone-hint') };
        case 'CL_FORGE':
            return { owner: val('fg-owner'), trigger_context: val('fg-trigger-context') };
        case 'CAN_FORGE':
            return { zone: val('fg-zone') };
        case 'PE_FORGE':
            return { engine_name: val('fg-engine-name'), zone_scope: val('fg-zone-scope'), trigger_event: val('fg-trigger-event') };
        case 'UA_FORGE':
            return { zone: val('fg-zone'), trigger_context: val('fg-trigger-context') };
        default:
            return {};
    }
}

async function doForge(forgeType, params) {
    try {
        const resp = await fetch('/api/forge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ forge_type: forgeType, params }),
        });
        const result = await resp.json();
        if (!result.success) {
            showToast('Forge failed: ' + (result.error || 'unknown error'), 'error');
        }
        // State update + creative_pending come via WebSocket
    } catch (e) {
        showToast('Forge error: ' + e.message, 'error');
    }
}

// ─── COMBAT DASHBOARD (DG-16) ───

function renderCombatDashboard() {
    const area = document.getElementById('combat-area');
    const combat = state ? state.combat : null;

    if (!combat) {
        area.style.display = 'none';
        return;
    }

    const round = combat.round || 0;
    const ended = combat.ended || false;
    const endReason = combat.end_reason || '';

    // Build combatant cards
    function renderCombatant(c) {
        const pct = c.hp_max > 0 ? c.hp / c.hp_max : 0;
        let barClass;
        if (c.hp <= 0) barClass = 'dead';
        else if (pct > 0.5) barClass = 'green';
        else if (pct > 0.25) barClass = 'yellow';
        else barClass = 'red';

        const nameClass = c.is_pc ? 'cbt-name pc' : c.is_companion ? 'cbt-name companion' : 'cbt-name foe';
        const downClass = c.is_down ? ' is-down' : '';
        const brokenClass = c.is_broken ? ' is-broken' : '';

        let tags = '';
        if (c.is_pc) tags += '<span class="combat-tag pc">PC</span>';
        if (c.is_companion) tags += '<span class="combat-tag companion">ALLY</span>';
        if (c.is_down) tags += '<span class="combat-tag down">DOWN</span>';
        if (c.is_broken) tags += '<span class="combat-tag broken">BROKEN</span>';
        if (c.is_defending) tags += '<span class="combat-tag defending">DEFEND</span>';

        const hpText = c.hp_max > 0 ? `HP ${c.hp}/${c.hp_max}` : '';
        const statParts = [];
        if (c.ac) statParts.push(`AC ${c.ac}`);
        statParts.push(hpText);
        if (c.at) statParts.push(`AT +${c.at}`);
        if (c.dmg) statParts.push(c.dmg);

        return `<div class="combatant${downClass}${brokenClass}">
            <div class="${nameClass}">${esc(c.name)}</div>
            <div class="cbt-stats">${esc(statParts.join(' | '))}</div>
            <div class="cbt-hp-bar-bg"><div class="cbt-hp-bar ${barClass}" style="width:${Math.max(0, pct * 100)}%"></div></div>
            ${tags ? `<div class="cbt-tags">${tags}</div>` : ''}
        </div>`;
    }

    // Classify log entries
    function logEntryClass(line) {
        const l = line.toLowerCase();
        if (l.includes('killed') || l.includes('falls') || l.includes('down')) return 'kill';
        if (l.includes('hits') || l.includes('damage')) return 'hit';
        if (l.includes('misses') || l.includes('miss')) return 'miss';
        if (l.includes('morale') || l.includes('breaks') || l.includes('broken')) return 'morale';
        if (l.includes('initiative')) return 'init';
        if (l.includes('flee') || l.includes('free attack')) return 'flee';
        return 'info';
    }

    const pcSideHtml = (combat.pc_side || []).map(renderCombatant).join('');
    const foeSideHtml = (combat.foe_side || []).map(renderCombatant).join('');

    const logHtml = (combat.combat_log || []).map(line =>
        `<div class="combat-log-entry ${logEntryClass(line)}">${esc(line)}</div>`
    ).join('');

    let statusText = '';
    if (ended) {
        const reasons = {
            'ALL_FOES_DEAD': 'All foes defeated!',
            'FOES_BREAK': 'Foes broke and fled!',
            'FLEE_SUCCESS': 'Party fled successfully.',
            'PC_DOWN': 'Thoron has fallen...',
        };
        statusText = reasons[endReason] || endReason;
    }

    area.innerHTML = `
        <div class="combat-header">
            <span class="combat-title">COMBAT</span>
            <span class="combat-round">Round ${round}${ended ? ' — ENDED' : ''}</span>
        </div>
        <div class="combat-body">
            <div class="combat-sides">
                <div class="combat-side">
                    <div class="combat-side-label pc-side">PARTY</div>
                    ${pcSideHtml}
                </div>
                <div class="combat-side">
                    <div class="combat-side-label foe-side">FOES</div>
                    ${foeSideHtml}
                </div>
            </div>
            <div class="combat-log-panel">
                <div class="combat-log-label">MECH LOG</div>
                <div class="combat-log" id="combat-log-scroll">${logHtml}</div>
            </div>
        </div>
        <div class="combat-actions">
            <button class="combat-btn attack-btn" id="cbt-attack" ${ended ? 'disabled' : ''}>ATTACK</button>
            <button class="combat-btn flee-btn" id="cbt-flee" ${ended ? 'disabled' : ''}>FLEE</button>
            ${statusText ? `<span class="combat-status">${esc(statusText)}</span>` : ''}
        </div>
    `;

    // Scroll combat log to bottom
    const logScroll = document.getElementById('combat-log-scroll');
    if (logScroll) logScroll.scrollTop = logScroll.scrollHeight;

    // Wire up buttons
    const atkBtn = document.getElementById('cbt-attack');
    const fleeBtn = document.getElementById('cbt-flee');
    if (atkBtn && !ended) atkBtn.addEventListener('click', () => doCombatAction('ATTACK'));
    if (fleeBtn && !ended) fleeBtn.addEventListener('click', () => doCombatAction('FLEE'));
}

let _combatActionPending = false;

async function doCombatAction(action) {
    if (_combatActionPending) return;
    _combatActionPending = true;

    // Disable buttons while resolving
    const atkBtn = document.getElementById('cbt-attack');
    const fleeBtn = document.getElementById('cbt-flee');
    if (atkBtn) atkBtn.disabled = true;
    if (fleeBtn) fleeBtn.disabled = true;

    try {
        const resp = await fetch('/api/combat/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action }),
        });
        const result = await resp.json();

        if (!result.success) {
            showToast('Combat action failed: ' + (result.error || 'unknown error'), 'error');
        }
        // State update comes via WebSocket — renderAll will re-render combat
    } catch (e) {
        showToast('Combat error: ' + e.message, 'error');
    } finally {
        _combatActionPending = false;
    }
}

// ─── LOGS TAB ───

function renderLogs() {
    const container = document.getElementById('log-content');
    container.innerHTML = '';
    (state.action_log || []).forEach(entry => addLogEntryElement(container, entry));
    container.scrollTop = container.scrollHeight;
}

function addLogEntry(entry) {
    const container = document.getElementById('log-content');
    addLogEntryElement(container, entry);
    container.scrollTop = container.scrollHeight;
}

function addLogEntryElement(container, entry) {
    const div = document.createElement('div');
    div.className = `log-entry ${entry.type || ''}`;
    const ts = entry.timestamp ? entry.timestamp.split('T')[1]?.substring(0, 8) || '' : '';
    div.innerHTML = `<span class="timestamp">${ts}</span>[${esc(entry.type || '?')}] ${esc(entry.detail || '')}`;
    container.appendChild(div);
}

// ─── SIDE PANEL ───

document.getElementById('side-panel-toggle').addEventListener('click', () => {
    const panel = document.getElementById('side-panel');
    const btn = document.getElementById('side-panel-toggle');
    panel.classList.toggle('collapsed');
    btn.innerHTML = panel.classList.contains('collapsed') ? '&raquo;' : '&laquo;';
});

function renderSidePanel() {
    if (!state) return;
    renderSidePanelParty();
    renderSidePanelLog();
}

function renderSidePanelParty() {
    const pcBlock = document.getElementById('sp-pc-block');
    const compBlock = document.getElementById('sp-companions-block');
    pcBlock.innerHTML = '';
    compBlock.innerHTML = '';

    // PC compact stat block
    const pc = state.pc;
    if (pc) {
        const div = document.createElement('div');
        div.className = 'sp-pc-stat';
        let condHtml = '';
        if (pc.conditions && pc.conditions.length) {
            condHtml = `<div class="sp-conditions">${esc(pc.conditions.join(', '))}</div>`;
        }
        div.innerHTML = `
            ${portraitImg(pc.name, 'sp-portrait')}
            <div class="sp-stat-text">
                <div class="sp-name">${esc(pc.name)}</div>
                <div class="sp-stats">${esc(pc.stats || '')}</div>
                ${condHtml}
            </div>
        `;
        pcBlock.appendChild(div);
    }

    // Companion compact stat blocks (only with_pc)
    (state.companions || []).forEach(npc => {
        if (!npc.with_pc) return;
        const div = document.createElement('div');
        div.className = 'sp-comp-stat';
        const hpText = npc.bx_hp_max ? `HP ${npc.bx_hp}/${npc.bx_hp_max}` : '';
        const acText = npc.bx_ac ? `AC ${npc.bx_ac}` : '';
        const statsLine = [acText, hpText].filter(Boolean).join(' | ');
        div.innerHTML = `
            ${portraitImg(npc.name, 'sp-portrait')}
            <div class="sp-stat-text">
                <div class="sp-name">${esc(npc.name)}</div>
                <div class="sp-stats">${statsLine}</div>
            </div>
        `;
        compBlock.appendChild(div);
    });
}

function renderSidePanelLog() {
    const feed = document.getElementById('sp-log-feed');
    feed.innerHTML = '';
    (state.action_log || []).forEach(entry => addSidePanelLogEntry(feed, entry));
    feed.scrollTop = feed.scrollHeight;
}

function addSidePanelLogEntry(container, entry) {
    if (!container) return;
    const div = document.createElement('div');
    div.className = `sp-log-entry ${entry.type || ''}`;
    const ts = entry.timestamp ? entry.timestamp.split('T')[1]?.substring(0, 8) || '' : '';
    div.innerHTML = `<span class="timestamp">${ts}</span>[${esc(entry.type || '?')}] ${esc(entry.detail || '')}`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ─── FOOTER ───

let _budgetWarningFired = false;

function renderFooter() {
    const count = state.creative_call_count || 0;
    const el = document.getElementById('call-count');
    if (count >= 18) {
        el.textContent = `Claude calls: ${count}/20 — BUDGET WARNING`;
        el.style.color = 'var(--red)';
        el.style.fontWeight = 'bold';
        if (!_budgetWarningFired) {
            _budgetWarningFired = true;
            showToast('Approaching session call budget (18/20). Consider ending session.', 'warning');
        }
    } else if (count >= 15) {
        el.textContent = `Claude calls: ${count}/20`;
        el.style.color = 'var(--yellow)';
        el.style.fontWeight = 'normal';
    } else if (count > 0) {
        el.textContent = `Claude calls: ${count}/20`;
        el.style.color = '';
        el.style.fontWeight = 'normal';
    } else {
        el.textContent = '';
        el.style.color = '';
    }
}

// ─── ACTIONS ───

let _travelPending = false;

async function doTravel(destination) {
    if (_travelPending) return; // prevent double-fire
    _travelPending = true;

    // Disable CP buttons during travel
    document.querySelectorAll('.cp-btn').forEach(b => b.disabled = true);

    try {
        const resp = await fetch('/api/travel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ destination }),
        });
        const result = await resp.json();

        if (!result.success) {
            showToast('Travel failed: ' + (result.error || 'unknown error'), 'error');
            document.querySelectorAll('.cp-btn').forEach(b => b.disabled = false);
        }
        // State update will come via WebSocket
    } catch (e) {
        showToast('Travel error: ' + e.message, 'error');
    } finally {
        _travelPending = false;
    }
}

async function saveGame() {
    const resp = await fetch('/api/save', { method: 'POST' });
    const result = await resp.json();
    if (result.success) {
        // Brief visual feedback
        const btn = document.querySelector('#footer .footer-btn');
        const orig = btn.textContent;
        btn.textContent = 'Saved!';
        setTimeout(() => btn.textContent = orig, 1500);
    }
}

async function showLoadDialog() {
    const resp = await fetch('/api/saves');
    const data = await resp.json();
    const saves = data.saves || [];

    if (saves.length === 0) {
        showToast('No save files found.', 'warning');
        return;
    }

    // Build modal overlay
    const overlay = document.createElement('div');
    overlay.id = 'load-modal-overlay';
    const modal = document.createElement('div');
    modal.id = 'load-modal';
    modal.innerHTML = '<div class="load-modal-title">Load Save</div>';

    saves.forEach(s => {
        const btn = document.createElement('button');
        btn.className = 'load-modal-btn';
        btn.innerHTML = `<span class="lm-name">${esc(s.filename)}</span><span class="lm-meta">${esc(s.modified || '')}</span>`;
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.querySelector('.lm-meta').textContent = 'Loading...';
            const loadResp = await fetch('/api/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: s.filename }),
            });
            const result = await loadResp.json();
            overlay.remove();
            if (!result.success) {
                showToast('Load failed: ' + (result.error || 'unknown error'), 'error');
            }
        });
        modal.appendChild(btn);
    });

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'load-modal-cancel';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => overlay.remove());
    modal.appendChild(cancelBtn);

    overlay.appendChild(modal);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
}

// ─── SESSION LIFECYCLE (DG-19) ───

function showStartSessionDialog() {
    const sid = state && state.meta ? state.meta.session_id : '?';
    const newSid = typeof sid === 'number' ? sid + 1 : '?';

    const overlay = document.createElement('div');
    overlay.id = 'session-modal-overlay';
    const modal = document.createElement('div');
    modal.id = 'session-modal';
    modal.innerHTML = `
        <div class="session-modal-title">Start New Session</div>
        <div class="session-modal-body">
            Begin <strong>Session ${esc(newSid)}</strong>?<br>
            This will increment the session ID from ${esc(sid)} to ${esc(newSid)},
            reset session counters, and run ZONE-FORGE validation.
        </div>
        <div class="session-modal-warning">
            Session ID increment is irreversible.
        </div>
        <div class="session-modal-actions">
            <button class="session-modal-cancel" id="ssm-cancel">Cancel</button>
            <button class="session-modal-confirm" id="ssm-confirm">Start Session ${esc(newSid)}</button>
        </div>
    `;
    overlay.appendChild(modal);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);

    document.getElementById('ssm-cancel').addEventListener('click', () => overlay.remove());
    document.getElementById('ssm-confirm').addEventListener('click', async () => {
        const btn = document.getElementById('ssm-confirm');
        btn.disabled = true;
        btn.textContent = 'Starting...';
        try {
            const resp = await fetch('/api/session/start', { method: 'POST' });
            const result = await resp.json();
            overlay.remove();
            if (result.success) {
                const sessionBtn = document.querySelector('.session-btn');
                if (sessionBtn) {
                    const orig = sessionBtn.textContent;
                    sessionBtn.textContent = `Session ${result.new_session_id}!`;
                    setTimeout(() => sessionBtn.textContent = orig, 2000);
                }
            } else {
                showToast('Start session failed: ' + (result.error || 'unknown error'), 'error');
            }
        } catch (e) {
            overlay.remove();
            showToast('Session error: ' + e.message, 'error');
        }
    });
}

function showEndSessionDialog() {
    const sid = state && state.meta ? state.meta.session_id : '?';

    const overlay = document.createElement('div');
    overlay.id = 'session-modal-overlay';
    const modal = document.createElement('div');
    modal.id = 'session-modal';
    modal.innerHTML = `
        <div class="session-modal-title">End Session</div>
        <div class="session-modal-body">
            End <strong>Session ${esc(sid)}</strong>?<br>
            This will save the game, generate an HTML session report, and
            request a session summary from Claude.
        </div>
        <div class="session-modal-actions">
            <button class="session-modal-cancel" id="ends-cancel">Cancel</button>
            <button class="session-modal-confirm" id="ends-confirm">End Session ${esc(sid)}</button>
        </div>
    `;
    overlay.appendChild(modal);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);

    document.getElementById('ends-cancel').addEventListener('click', () => overlay.remove());
    document.getElementById('ends-confirm').addEventListener('click', async () => {
        const btn = document.getElementById('ends-confirm');
        btn.disabled = true;
        btn.textContent = 'Ending...';
        try {
            const resp = await fetch('/api/session/end', { method: 'POST' });
            const result = await resp.json();
            overlay.remove();
            if (result.success && result.report_url) {
                window.open(result.report_url, '_blank');
            } else if (!result.success) {
                showToast('End session failed: ' + (result.error || 'unknown error'), 'error');
            }
        } catch (e) {
            overlay.remove();
            showToast('Session error: ' + e.message, 'error');
        }
    });
}

// ─── EXPORT REPORT (DG-11) ───

function exportReport() {
    if (!state || !state.meta) {
        showToast('No state loaded.', 'warning');
        return;
    }
    const sid = state.meta.session_id;
    window.open(`/api/session/report/${sid}`, '_blank');
}

async function fetchState() {
    try {
        const resp = await fetch('/api/state');
        state = await resp.json();
        renderAll();
    } catch (e) {
        console.error('Failed to fetch state:', e);
    }
}

// ─── UTILS ───

function esc(s) {
    if (s == null) return '—';
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}

// ─── MODE MACROS (DG-22) ───

document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const mode = btn.dataset.mode;
        if (mode === 'RUMOR') {
            doRumor();
        } else {
            doSetMode(btn.classList.contains('active') ? null : mode);
        }
    });
});

async function doSetMode(mode) {
    try {
        const resp = await fetch('/api/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode }),
        });
        const result = await resp.json();
        if (!result.success) {
            showToast('Mode failed: ' + (result.error || 'unknown'), 'error');
        } else {
            showToast(mode ? `Mode: ${mode} active` : 'Mode deactivated', 'info', 2000);
        }
    } catch (e) {
        showToast('Mode error: ' + e.message, 'error');
    }
}

async function doRumor() {
    try {
        const resp = await fetch('/api/rumor', { method: 'POST' });
        const result = await resp.json();
        if (!result.success) {
            showToast('Rumor failed: ' + (result.error || 'unknown'), 'error');
        }
    } catch (e) {
        showToast('Rumor error: ' + e.message, 'error');
    }
}

function renderModeBar(enabled) {
    const status = document.getElementById('mode-status');
    const activeMode = state ? state.active_mode : null;

    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.disabled = !enabled;
        if (btn.dataset.mode === activeMode) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    status.textContent = activeMode ? `Mode: ${activeMode}` : '';
}

// ─── TOAST NOTIFICATIONS (DG-23) ───

function showToast(message, type = 'info', duration = 5000) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    if (type === 'error') {
        // Error toasts persist until clicked
        toast.style.cursor = 'pointer';
        toast.title = 'Click to dismiss';
        toast.addEventListener('click', () => toast.remove());
    } else {
        setTimeout(() => { if (toast.parentElement) toast.remove(); }, duration);
    }
    container.appendChild(toast);
}

// ─── INIT ───

connectWS();
