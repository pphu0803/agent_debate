/* ============================================
   思想孵化机 - 前端应用逻辑 (ChatGPT风格)
   ============================================ */

const state = {
    debateId: null,
    eventSource: null,
    isDebating: false,
    scores: { innovator: 0, critic: 0, scholar: 0 },
    scoreThreshold: 6,
    currentReport: null,
    currentTopic: '',
};

const $ = (id) => document.getElementById(id);
const els = {
    topicInput: $('topicInput'),
    maxRounds: $('maxRounds'),
    scoreThreshold: $('scoreThreshold'),
    btnStart: $('btnStart'),
    btnStop: $('btnStop'),
    btnSettings: $('btnSettings'),
    btnHistory: $('btnHistory'),
    scoresPanel: $('scoresPanel'),
    scoresList: $('scoresList'),
    consensusBar: $('consensusBar'),
    consensusText: $('consensusText'),
    chatTopbar: $('chatTopbar'),
    topbarTopic: $('topbarTopic'),
    topbarStatus: $('topbarStatus'),
    topbarRound: $('topbarRound'),
    messagesContainer: $('messagesContainer'),
    emptyState: $('emptyState'),
    chatBottombar: $('chatBottombar'),
    bottombarContent: $('bottombarContent'),
    settingsModal: $('settingsModal'),
    historyModal: $('historyModal'),
    reportModal: $('reportModal'),
    apiKeyInput: $('apiKeyInput'),
    apiBaseInput: $('apiBaseInput'),
    modelInput: $('modelInput'),
    configStatus: $('configStatus'),
    historyList: $('historyList'),
    reportContent: $('reportContent'),
    toastContainer: $('toastContainer'),
};

const AGENTS = {
    innovator: { name: '激进的创新者', icon: '💡', color: '#ff6b6b' },
    critic:    { name: '严厉的反对者', icon: '⚔️', color: '#4ecdc4' },
    scholar:   { name: '保守的学者', icon: '📚', color: '#95e1d3' },
};

const API_BASE = window.location.origin;

// ===== 初始化 =====
async function init() {
    marked.setOptions({ breaks: true, gfm: true });
    await loadConfig();
    bindEvents();
}

// ===== 加载配置 =====
async function loadConfig() {
    try {
        const res = await fetch(`${API_BASE}/api/config`);
        const data = await res.json();
        updateConfigStatus(data);
    } catch (e) {}
}

function updateConfigStatus(data) {
    if (data.configured) {
        els.configStatus.className = 'config-status ok';
        els.configStatus.textContent = `已配置 - 模型: ${data.model}`;
    } else {
        els.configStatus.className = 'config-status error';
        els.configStatus.textContent = '未配置API Key，请填写后再开始';
    }
}

// ===== 绑定事件 =====
function bindEvents() {
    els.btnStart.addEventListener('click', startDebate);
    els.btnStop.addEventListener('click', stopDebate);
    els.btnSettings.addEventListener('click', openSettings);
    els.btnHistory.addEventListener('click', openHistory);

    $('closeSettings').addEventListener('click', closeSettings);
    $('cancelSettings').addEventListener('click', closeSettings);
    $('saveSettings').addEventListener('click', saveSettings);

    $('closeHistory').addEventListener('click', closeHistory);
    $('closeReport').addEventListener('click', closeReport);
    $('closeReportBtn').addEventListener('click', closeReport);
    $('exportReport').addEventListener('click', exportReport);

    [els.settingsModal, els.historyModal, els.reportModal].forEach(m => {
        m.addEventListener('click', (e) => { if (e.target === m) m.classList.add('hidden'); });
    });

    els.topicInput.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') startDebate();
    });
}

// ===== 开始辩论 =====
async function startDebate() {
    const topic = els.topicInput.value.trim();
    if (!topic) { showToast('请输入辩论主题', 'error'); return; }

    try {
        const res = await fetch(`${API_BASE}/api/config`);
        const data = await res.json();
        if (!data.configured) {
            showToast('请先在设置中配置API Key', 'error');
            openSettings();
            return;
        }
    } catch { showToast('无法连接服务器', 'error'); return; }

    const maxRounds = parseInt(els.maxRounds.value) || 20;
    const scoreThreshold = parseInt(els.scoreThreshold.value) || 6;

    try {
        const res = await fetch(`${API_BASE}/api/debates`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic, max_rounds: maxRounds, score_threshold: scoreThreshold }),
        });

        if (!res.ok) {
            const err = await res.json();
            showToast(err.detail || '创建辩论失败', 'error');
            return;
        }

        const data = await res.json();
        state.debateId = data.debate_id;
        state.currentTopic = topic;
        state.scoreThreshold = scoreThreshold;
        state.scores = { innovator: 0, critic: 0, scholar: 0 };

        setDebatingState(true);
        showChatUI(topic);
        renderScores();
        connectSSE(data.debate_id);
    } catch (e) {
        showToast('创建辩论失败: ' + e.message, 'error');
    }
}

// ===== 连接SSE =====
function connectSSE(debateId) {
    if (state.eventSource) state.eventSource.close();
    state.eventSource = new EventSource(`${API_BASE}/api/debates/${debateId}/stream`);

    state.eventSource.onmessage = (event) => {
        try {
            handleSSEEvent(JSON.parse(event.data));
        } catch (e) { console.error('SSE解析失败:', e); }
    };

    state.eventSource.onerror = () => {
        if (state.isDebating) console.log('SSE断开，等待自动重连...');
    };
}

// ===== SSE事件处理 =====
function handleSSEEvent(data) {
    switch (data.type) {
        case 'reset':
            clearMessages();
            state.scores = data.scores || { innovator: 0, critic: 0, scholar: 0 };
            if (data.topic) showChatUI(data.topic);
            if (data.current_round) updateTopbar({ round: data.current_round });
            if (data.status) updateTopbar({ status: data.status });
            renderScores();
            updateConsensus();
            if (data.final_summary) state.currentReport = data.final_summary;
            break;

        case 'start':
            updateTopbar({ status: 'ongoing' });
            updateBottombar('辩论进行中');
            break;

        case 'round_start':
            updateTopbar({ round: data.round });
            addRoundDivider(data.round);
            break;

        case 'agent_thinking':
            addThinkingCard(data);
            break;

        case 'agent_message':
            removeThinkingCard();
            addAgentMessage(data);
            if (data.score !== undefined) {
                state.scores[data.agent] = data.score;
                renderScores();
                updateConsensus();
            }
            break;

        case 'context_compressed':
            removeThinkingCard();
            addSystemNotice(data.summary || '上下文已自动压缩', 'compress');
            break;

        case 'generating_report':
            removeThinkingCard();
            addSystemNotice('正在生成思想孵化报告...', 'info');
            updateBottombar('生成报告中...');
            break;

        case 'complete':
            handleComplete(data);
            break;

        case 'stopped':
            removeThinkingCard();
            showToast('辩论已终止', 'info');
            setDebatingState(false);
            updateTopbar({ status: 'terminated' });
            updateBottombar('辩论已终止');
            break;

        case 'error':
            removeThinkingCard();
            showToast(data.message || '发生错误', 'error');
            setDebatingState(false);
            break;
    }
}

// ===== UI渲染 =====
function showChatUI(topic) {
    els.emptyState?.classList.add('hidden');
    els.chatTopbar.classList.remove('hidden');
    els.chatBottombar.classList.remove('hidden');
    els.topbarTopic.textContent = topic;
    els.scoresPanel.classList.remove('hidden');
    updateTopbar({ status: 'pending', round: 0 });
    updateBottombar('等待开始...');

    // 确保有messages-inner容器
    if (!$('.messages-inner')) {
        const inner = document.createElement('div');
        inner.className = 'messages-inner';
        els.messagesContainer.appendChild(inner);
    }

    // 添加用户议题消息（仅首次）
    const existing = $('.chat-msg-user');
    if (!existing) {
        addUserMessage(state.currentTopic || topic);
    }
}

function clearMessages() {
    const inner = $('.messages-inner');
    if (inner) inner.innerHTML = '';
    else {
        els.messagesContainer.innerHTML = '';
        const ni = document.createElement('div');
        ni.className = 'messages-inner';
        els.messagesContainer.appendChild(ni);
    }
    els.emptyState?.classList.add('hidden');
    // 重新添加用户议题消息
    if (state.currentTopic) addUserMessage(state.currentTopic);
}

function getMessagesInner() {
    let inner = $('.messages-inner');
    if (!inner) {
        inner = document.createElement('div');
        inner.className = 'messages-inner';
        els.messagesContainer.appendChild(inner);
    }
    return inner;
}

function addUserMessage(text) {
    const el = document.createElement('div');
    el.className = 'chat-msg-user';
    el.innerHTML = `
        <div class="msg-avatar">YOU</div>
        <div class="msg-content-wrap">
            <div class="msg-name">议题</div>
            <div class="msg-body"><div class="msg-content">${escapeHtml(text)}</div></div>
        </div>
    `;
    getMessagesInner().appendChild(el);
    scrollToBottom();
}

function addAgentMessage(data) {
    const cfg = AGENTS[data.agent] || { name: data.agent_name, icon: data.agent_icon, color: '#8e8e8e' };
    const scoreClass = data.score >= 7 ? 'high' : data.score >= 4 ? 'mid' : 'low';
    const contentHtml = marked.parse(data.content || '');
    const el = document.createElement('div');
    el.className = 'chat-msg';
    el.style.setProperty('--agent-color', cfg.color);
    el.innerHTML = `
        <div class="msg-avatar">${cfg.icon}</div>
        <div class="msg-content-wrap">
            <div class="msg-header">
                <span class="msg-name">${cfg.name}</span>
                <span class="msg-round">第${data.round}轮</span>
                <span class="msg-score ${scoreClass}">${data.score}/10</span>
            </div>
            <div class="msg-body">${contentHtml}</div>
            ${data.score_reason ? `<div class="msg-score-reason">📊 ${escapeHtml(data.score_reason)}</div>` : ''}
        </div>
    `;
    getMessagesInner().appendChild(el);
    scrollToBottom();
}

function addThinkingCard(data) {
    removeThinkingCard();
    const cfg = AGENTS[data.agent] || { name: data.agent_name, icon: data.agent_icon, color: '#8e8e8e' };
    const el = document.createElement('div');
    el.className = 'chat-msg-thinking';
    el.id = 'thinkingCard';
    el.style.setProperty('--agent-color', cfg.color);
    el.innerHTML = `
        <div class="msg-avatar">${cfg.icon}</div>
        <div class="thinking-content">
            <div class="thinking-name">${cfg.name}</div>
            <div class="thinking-dots">
                <span>正在思考</span>
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
            </div>
        </div>
    `;
    getMessagesInner().appendChild(el);
    scrollToBottom();
}

function removeThinkingCard() {
    const card = $('thinkingCard');
    if (card) card.remove();
}

function addRoundDivider(round) {
    const el = document.createElement('div');
    el.className = 'round-divider';
    el.textContent = `第 ${round} 轮讨论`;
    getMessagesInner().appendChild(el);
    scrollToBottom();
}

function addSystemNotice(text, type = 'info') {
    const el = document.createElement('div');
    el.className = `system-notice ${type}`;
    el.textContent = text;
    getMessagesInner().appendChild(el);
    scrollToBottom();
}

// ===== 评分渲染 =====
function renderScores() {
    els.scoresList.innerHTML = Object.entries(AGENTS).map(([key, cfg]) => {
        const score = state.scores[key] || 0;
        const width = score > 0 ? (score / 10) * 100 : 0;
        return `
            <div class="score-row">
                <div class="score-avatar" style="background: ${cfg.color}22; border: 1px solid ${cfg.color}55;">${cfg.icon}</div>
                <div class="score-info">
                    <div class="score-name">${cfg.name}</div>
                    <div class="score-track">
                        <div class="score-fill" style="width: ${width}%; background: ${cfg.color};"></div>
                    </div>
                </div>
                <div class="score-val">${score > 0 ? score : '-'}</div>
            </div>
        `;
    }).join('');
}

function updateConsensus() {
    const scores = Object.values(state.scores);
    const allScored = scores.every(s => s > 0);
    const above = scores.filter(s => s >= state.scoreThreshold).length;
    const progress = allScored ? (above / 3) * 100 : 0;
    els.consensusBar.style.width = progress + '%';
    if (allScored && above === 3) {
        els.consensusText.textContent = '已达成共识';
        els.consensusText.style.color = 'var(--success)';
    } else if (allScored) {
        els.consensusText.textContent = `${above}/3 达标`;
        els.consensusText.style.color = '';
    } else {
        els.consensusText.textContent = '等待评分';
        els.consensusText.style.color = '';
    }
}

// ===== 顶部栏 & 底部栏 =====
function updateTopbar({ status, round }) {
    const statusMap = {
        pending: { text: '准备中', cls: '' },
        ongoing: { text: '进行中', cls: 'ongoing' },
        completed: { text: '已完成', cls: 'completed' },
        terminated: { text: '已终止', cls: 'terminated' },
    };
    if (status) {
        const s = statusMap[status] || statusMap.pending;
        els.topbarStatus.textContent = s.text;
        els.topbarStatus.className = `topbar-status ${s.cls}`;
    }
    if (round !== undefined) {
        els.topbarRound.textContent = round > 0 ? `第 ${round} 轮` : '';
    }
}

function updateBottombar(text) {
    els.bottombarContent.innerHTML = `<span class="pulse-dot"></span><span>${text}</span>`;
}

// ===== 辩论完成 =====
function handleComplete(data) {
    setDebatingState(false);
    updateTopbar({ status: 'completed' });
    state.currentReport = data.report;
    if (data.consensus) {
        showToast(`辩论完成 - ${data.total_rounds}轮达成共识`, 'success');
        addSystemNotice(`辩论完成 - ${data.total_rounds}轮后三方达成共识`, 'info');
        updateBottombar('已完成 - 达成共识');
    } else {
        showToast(`辩论完成 - ${data.total_rounds}轮`, 'info');
        addSystemNotice(`辩论完成 - 共${data.total_rounds}轮，未达成完全共识`, 'info');
        updateBottombar('已完成');
    }
    setTimeout(() => showReport(data.report), 800);
}

// ===== 报告 =====
function showReport(report) {
    els.reportContent.innerHTML = marked.parse(report || '暂无报告');
    els.reportModal.classList.remove('hidden');
}

function exportReport() {
    if (!state.currentReport) return;
    const blob = new Blob([state.currentReport], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `思想孵化报告_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('报告已导出', 'success');
}

function closeReport() { els.reportModal.classList.add('hidden'); }

// ===== 终止辩论 =====
async function stopDebate() {
    if (!state.debateId) return;
    try {
        await fetch(`${API_BASE}/api/debates/${state.debateId}/stop`, { method: 'POST' });
        if (state.eventSource) state.eventSource.close();
        setDebatingState(false);
        showToast('辩论已终止', 'info');
    } catch (e) { showToast('终止失败', 'error'); }
}

// ===== UI状态 =====
function setDebatingState(debating) {
    state.isDebating = debating;
    els.btnStart.classList.toggle('loading', debating);
    els.btnStart.disabled = debating;
    els.btnStop.classList.toggle('hidden', !debating);
    els.topicInput.disabled = debating;
    els.maxRounds.disabled = debating;
    els.scoreThreshold.disabled = debating;
}

// ===== 滚动 =====
function scrollToBottom() {
    requestAnimationFrame(() => {
        els.messagesContainer.scrollTop = els.messagesContainer.scrollHeight;
    });
}

// ===== 设置弹窗 =====
async function openSettings() {
    try {
        const res = await fetch(`${API_BASE}/api/config`);
        const data = await res.json();
        els.modelInput.value = data.model || '';
        els.apiBaseInput.value = data.api_base || '';
    } catch {}
    els.settingsModal.classList.remove('hidden');
}

function closeSettings() { els.settingsModal.classList.add('hidden'); }

async function saveSettings() {
    const body = {};
    if (els.apiKeyInput.value.trim()) body.api_key = els.apiKeyInput.value.trim();
    if (els.apiBaseInput.value.trim()) body.api_base = els.apiBaseInput.value.trim();
    if (els.modelInput.value.trim()) body.model = els.modelInput.value.trim();
    try {
        const res = await fetch(`${API_BASE}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        updateConfigStatus(data);
        els.apiKeyInput.value = '';
        if (data.configured) { showToast('配置已保存', 'success'); closeSettings(); }
        else showToast('请填写API Key', 'error');
    } catch (e) { showToast('保存失败', 'error'); }
}

// ===== 历史弹窗 =====
async function openHistory() {
    els.historyModal.classList.remove('hidden');
    els.historyList.innerHTML = '<p class="loading-text">加载中...</p>';
    try {
        const res = await fetch(`${API_BASE}/api/debates`);
        const debates = await res.json();
        if (!debates.length) { els.historyList.innerHTML = '<p class="loading-text">暂无历史辩论</p>'; return; }
        els.historyList.innerHTML = debates.map(d => `
            <div class="history-item" data-id="${d.id}">
                <div class="history-topic">${escapeHtml(d.topic)}</div>
                <div class="history-meta">
                    <span class="history-status ${d.status}">${statusText(d.status)}</span>
                    <span>${d.current_round}轮</span>
                    <span>${d.message_count}条</span>
                    <span>${formatDate(d.created_at)}</span>
                </div>
            </div>
        `).join('');
        document.querySelectorAll('.history-item').forEach(item => {
            item.addEventListener('click', () => loadDebate(item.dataset.id));
        });
    } catch { els.historyList.innerHTML = '<p class="loading-text">加载失败</p>'; }
}

function closeHistory() { els.historyModal.classList.add('hidden'); }

// ===== 加载历史辩论 =====
async function loadDebate(debateId) {
    closeHistory();
    try {
        const res = await fetch(`${API_BASE}/api/debates/${debateId}`);
        const debate = await res.json();

        state.debateId = debateId;
        state.currentTopic = debate.topic;
        state.scores = debate.scores || { innovator: 0, critic: 0, scholar: 0 };
        state.scoreThreshold = debate.config?.score_threshold || 6;

        showChatUI(debate.topic);
        updateTopbar({ round: debate.current_round, status: debate.status });

        // 渲染历史消息
        const inner = getMessagesInner();
        inner.innerHTML = '';
        addUserMessage(debate.topic);

        let lastRound = 0;
        for (const msg of debate.messages || []) {
            if (!msg.is_summary && msg.round !== lastRound) {
                lastRound = msg.round;
                addRoundDivider(msg.round);
            }
            if (msg.is_summary) {
                addSystemNotice('上下文已自动压缩', 'compress');
            } else {
                addAgentMessage({
                    agent: msg.agent || msg.role,
                    round: msg.round,
                    content: msg.content,
                    score: msg.score,
                    score_reason: msg.score_reason,
                });
            }
        }

        renderScores();
        updateConsensus();

        if (debate.final_summary) {
            state.currentReport = debate.final_summary;
            setTimeout(() => showReport(debate.final_summary), 500);
        }

        setDebatingState(false);
        showToast('已加载历史辩论', 'success');
    } catch (e) { showToast('加载失败', 'error'); }
}

// ===== Toast =====
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    els.toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// ===== 工具函数 =====
function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function statusText(s) {
    return { pending: '等待中', ongoing: '进行中', completed: '已完成', terminated: '已终止' }[s] || s;
}

function formatDate(s) {
    const d = new Date(s);
    return `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
}

// ===== 启动 =====
init();
