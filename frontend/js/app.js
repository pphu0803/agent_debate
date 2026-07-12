/* ============================================
   思想孵化机 - 前端应用逻辑 (ChatGPT风格)
   ============================================ */

const state = {
    debateId: null,
    eventSource: null,
    isDebating: false,
    isPaused: false,
    scores: { innovator: 0, critic: 0, scholar: 0 },
    scoreThreshold: 6,
    currentReport: null,
    currentTopic: '',
    lastSeq: -1,
    renderedRounds: new Set(),
    currentRoundBlock: null,  // 当前回合的DOM容器（4列grid）
};

const $ = (id) => document.getElementById(id);
const els = {
    topicInput: $('topicInput'),
    maxRounds: $('maxRounds'),
    scoreThreshold: $('scoreThreshold'),
    btnStart: $('btnStart'),
    btnStop: $('btnStop'),
    btnPause: $('btnPause'),
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
    bottombarInput: $('bottombarInput'),
    userInput: $('userInput'),
    btnSend: $('btnSend'),
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
    btnExport: $('btnExport'),
    exportMenuSidebar: $('exportMenuSidebar'),
    debateActions: $('debateActions'),
    btnViewReport: $('btnViewReport'),
    btnContinue: $('btnContinue'),
    debateContinue: $('debateContinue'),
    continueInput: $('continueInput'),
    btnContinueSend: $('btnContinueSend'),
};

const AGENTS = {
    innovator: { name: '创新者', icon: '💡', color: '#ff6b6b' },
    critic:    { name: '批判者', icon: '⚔️', color: '#4ecdc4' },
    scholar:   { name: '严谨者', icon: '🔍', color: '#95e1d3' },
    moderator: { name: '组织者', icon: '🎭', color: '#a78bfa' },
};

// 后端API地址：同源时自动检测，部署到Cloudflare Pages时需改为后端实际地址
// 例如: const API_BASE = 'https://your-backend.example.com';
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
    } else if (data.has_placeholder_key) {
        els.configStatus.className = 'config-status error';
        els.configStatus.textContent = '⚠️ 当前API Key是占位符，请填写真实密钥';
    } else {
        els.configStatus.className = 'config-status error';
        els.configStatus.textContent = '未配置API Key，请填写后再开始';
    }
}

// ===== 绑定事件 =====
function bindEvents() {
    els.btnStart.addEventListener('click', startDebate);
    els.btnStop.addEventListener('click', stopDebate);
    els.btnPause.addEventListener('click', togglePause);
    els.btnSettings.addEventListener('click', openSettings);
    els.btnHistory.addEventListener('click', openHistory);

    els.btnSend.addEventListener('click', sendUserMessage);
    els.userInput.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') sendUserMessage();
    });

    // 历史筛选标签
    document.querySelectorAll('.history-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.history-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            historyFilter = tab.dataset.filter;
            openHistory();
        });
    });

    $('closeSettings').addEventListener('click', closeSettings);
    $('cancelSettings').addEventListener('click', closeSettings);
    $('saveSettings').addEventListener('click', saveSettings);

    $('closeHistory').addEventListener('click', closeHistory);
    $('closeReport').addEventListener('click', closeReport);
    $('closeReportBtn').addEventListener('click', closeReport);

    // 导出菜单：通用化绑定，支持多个导出下拉（报告弹窗 + 侧边栏常驻）
    document.querySelectorAll('.export-dropdown').forEach(dd => {
        const trigger = dd.querySelector('button:not(.export-option)');
        if (trigger) {
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                // 关闭其他下拉
                document.querySelectorAll('.export-menu').forEach(m => {
                    if (m !== dd.querySelector('.export-menu')) m.classList.add('hidden');
                });
                dd.querySelector('.export-menu')?.classList.toggle('hidden');
            });
        }
    });
    document.querySelectorAll('.export-option').forEach(btn => {
        btn.addEventListener('click', () => {
            exportDebate(btn.dataset.format);
            document.querySelectorAll('.export-menu').forEach(m => m.classList.add('hidden'));
        });
    });
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.export-dropdown')) {
            document.querySelectorAll('.export-menu').forEach(m => m.classList.add('hidden'));
        }
    });

    [els.settingsModal, els.historyModal, els.reportModal].forEach(m => {
        m.addEventListener('click', (e) => { if (e.target === m) m.classList.add('hidden'); });
    });

    els.topicInput.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') startDebate();
    });

    // 辩论结束后操作：查看报告 / 继续讨论
    els.btnViewReport.addEventListener('click', () => {
        if (state.currentReport) showReport(state.currentReport);
    });
    els.btnContinue.addEventListener('click', () => {
        els.debateContinue.classList.toggle('hidden');
        if (!els.debateContinue.classList.contains('hidden')) {
            els.continueInput?.focus();
        }
    });
    els.btnContinueSend.addEventListener('click', startContinuedDebate);
    els.continueInput.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') startContinuedDebate();
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
            // 区分"完全没配置"和"检测到占位符密钥"
            if (data.has_placeholder_key) {
                showToast('检测到 API Key 是占位符，请先配置真实密钥', 'error');
            } else {
                showToast('请先在设置中配置API Key', 'error');
            }
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
        state.lastSeq = -1;
        state.renderedRounds.clear();
        state.currentRoundBlock = null;

        clearMessages();
        setDebatingState(true);
        showChatUI(topic);
        renderScores();
        connectSSE(data.debate_id);
    } catch (e) {
        showToast('创建辩论失败: ' + e.message, 'error');
    }
}

// ===== 续作新辩论（基于上一轮结论）=====
async function startContinuedDebate() {
    const userInput = els.continueInput.value.trim();
    if (!userInput) { showToast('请输入你想补充或延续的内容', 'error'); return; }

    // 把上一轮报告的核心结论摘要 + 用户新输入拼成新议题
    // 报告可能很长，截取前300字作为上下文锚点
    const prevSummary = state.currentReport
        ? state.currentReport.slice(0, 300).replace(/[#*`\n]/g, ' ').trim()
        : '';
    const newTopic = prevSummary
        ? `【延续讨论】基于上一轮辩论结论：${prevSummary}……\n\n用户补充：${userInput}`
        : userInput;

    // 填入议题框并启动新辩论
    els.topicInput.value = newTopic;
    els.debateActions?.classList.add('hidden');
    els.debateContinue?.classList.add('hidden');
    if (els.continueInput) els.continueInput.value = '';
    startDebate();
}
function connectSSE(debateId) {
    if (state.eventSource) state.eventSource.close();
    state.eventSource = new EventSource(`${API_BASE}/api/debates/${debateId}/stream`);

    state.eventSource.onmessage = (event) => {
        try {
            handleSSEEvent(JSON.parse(event.data));
        } catch (e) { console.error('SSE解析失败:', e); }
    };

    state.eventSource.onerror = () => {
        if (state.isDebating) {
            console.log('SSE断开，等待自动重连...');
        } else {
            // 辩论已结束，关闭SSE避免无限重连
            if (state.eventSource) {
                state.eventSource.close();
                state.eventSource = null;
            }
        }
    };
}

// ===== SSE事件处理 =====
function handleSSEEvent(data) {
    // 去重：基于seq跳过已处理的事件（SSE重连时后端会回放所有历史事件）
    if (data.seq !== undefined) {
        if (data.seq <= state.lastSeq) return;
        state.lastSeq = data.seq;
    }

    switch (data.type) {
        case 'reset':
            removeThinkingCard();
            state.scores = data.scores || { innovator: 0, critic: 0, scholar: 0 };
            if (data.current_round) updateTopbar({ round: data.current_round });
            if (data.status) updateTopbar({ status: data.status });
            renderScores();
            updateConsensus();
            // 如果辩论已终止，关闭SSE
            if (data.status === 'terminated') {
                state.isDebating = false;
                if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
                setDebatingState(false);
            }
            // 已完成的辩论：保持SSE连接等待complete事件
            // （不要在这里关闭连接，否则complete事件无法被接收，报告弹窗不会弹出）
            if (data.status === 'completed') {
                state.isDebating = false;
                setDebatingState(false);
            }
            if (data.final_summary) {
                state.currentReport = data.final_summary;
            }
            // 同步暂停状态
            if (data.is_paused && !state.isPaused) {
                state.isPaused = true;
                setPausedState(true);
            }
            break;

        case 'start':
            updateTopbar({ status: 'ongoing' });
            updateBottombar('辩论进行中');
            break;

        case 'paused':
            state.isPaused = true;
            removeThinkingCard();
            setPausedState(true);
            updateBottombar('已暂停 - 可输入观点参与讨论');
            showToast('辩论已暂停', 'info');
            break;

        case 'resumed':
            state.isPaused = false;
            setPausedState(false);
            updateBottombar('辩论进行中');
            showToast('辩论已恢复', 'info');
            break;

        case 'user_message':
            removeThinkingCard();
            addUserBubble(data.content, data.round);
            break;

        case 'round_start':
            updateTopbar({ round: data.round });
            if (!state.renderedRounds.has(data.round)) {
                addRoundDivider(data.round);
                state.renderedRounds.add(data.round);
            }
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

        case 'agent_skip':
            removeThinkingCard();
            addSkipCard(data);
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

        case 'topic_redirect':
            addSystemNotice(`⚠️ 讨论偏题提醒：${data.redirect_topic || data.message}`, 'redirect');
            break;

        case 'dead_end':
            removeThinkingCard();
            addSystemNotice(`🔬 ${data.message || '讨论已达到需要实验/实证验证的瓶颈'}`, 'deadend');
            break;

        case 'generating_report':
            removeThinkingCard();
            addSystemNotice('正在生成思想孵化报告...', 'info');
            updateBottombar('生成报告中...');
            break;

        case 'complete':
            if (state.isDebating) handleComplete(data);
            break;

        case 'stopped':
            removeThinkingCard();
            if (state.isDebating) {
                if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
                showToast('辩论已终止', 'info');
                setDebatingState(false);
                updateTopbar({ status: 'terminated' });
                updateBottombar('辩论已终止');
            }
            break;

        case 'error':
            removeThinkingCard();
            if (state.isDebating) {
                if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
                showToast(data.message || '发生错误', 'error');
                setDebatingState(false);
            }
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
    let inner = $('.messages-inner');
    if (!inner) {
        inner = document.createElement('div');
        inner.className = 'messages-inner';
        els.messagesContainer.appendChild(inner);
    }

    // 插入4列固定表头（仅首次）
    if (!$('.grid-header')) {
        inner.appendChild(buildGridHeader());
    }

    // 添加用户议题消息（仅首次）
    const existing = $('.chat-msg-user');
    if (!existing) {
        addUserMessage(state.currentTopic || topic);
    }
}

// 构建4列网格表头
function buildGridHeader() {
    const header = document.createElement('div');
    header.className = 'grid-header';
    const cols = ['innovator', 'critic', 'scholar', 'moderator'];
    header.innerHTML = cols.map(key => {
        const cfg = AGENTS[key];
        return `
            <div class="grid-header-cell" data-agent="${key}">
                <span class="gh-icon">${cfg.icon}</span>
                <span>${cfg.name}</span>
                <span class="gh-score" data-score-key="${key}">-</span>
            </div>
        `;
    }).join('');
    return header;
}

// 更新表头中的评分显示
function updateGridHeaderScores() {
    document.querySelectorAll('.gh-score').forEach(el => {
        const key = el.dataset.scoreKey;
        const score = state.scores[key] || 0;
        el.textContent = score > 0 ? score : '-';
    });
}

function clearMessagesKeepUser() {
    const inner = getMessagesInner();
    // 保留表头和用户议题消息，清空其余内容
    const header = inner.querySelector('.grid-header');
    const userMsg = inner.querySelector('.chat-msg-user');
    inner.innerHTML = '';
    if (header) inner.appendChild(header);
    if (userMsg) inner.appendChild(userMsg);
    els.emptyState?.classList.add('hidden');
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
    // DOM级去重：检查是否已存在相同seq的消息
    const container = getRoundContainer();
    if (data.seq !== undefined) {
        const existing = container.querySelector(`[data-seq="${data.seq}"]`);
        if (existing) return;
    }
    const cfg = AGENTS[data.agent] || { name: data.agent_name, icon: data.agent_icon, color: '#8e8e8e' };
    const scoreClass = data.score >= 7 ? 'high' : data.score >= 4 ? 'mid' : 'low';
    const contentHtml = marked.parse(data.content || '');
    const el = document.createElement('div');
    el.className = 'chat-msg';
    el.setAttribute('data-agent', data.agent);
    el.style.setProperty('--agent-color', cfg.color);
    if (data.seq !== undefined) el.setAttribute('data-seq', data.seq);
    el.innerHTML = `
        <div class="msg-avatar">${cfg.icon}</div>
        <div class="msg-content-wrap">
            <div class="msg-header">
                <span class="msg-name">${cfg.name}</span>
                <span class="msg-score ${scoreClass}">${data.score}/10</span>
            </div>
            <div class="msg-body">${contentHtml}</div>
            ${data.score_reason ? `<div class="msg-score-reason">📊 ${escapeHtml(data.score_reason)}</div>` : ''}
        </div>
    `;
    container.appendChild(el);
    scrollToBottom();
}

function addSkipCard(data) {
    const cfg = AGENTS[data.agent] || { name: data.agent_name, icon: data.agent_icon, color: '#8e8e8e' };
    const scoreClass = data.score >= 7 ? 'high' : data.score >= 4 ? 'mid' : 'low';
    const el = document.createElement('div');
    el.className = 'chat-msg-skip';
    el.setAttribute('data-agent', data.agent);
    el.style.setProperty('--agent-color', cfg.color);
    if (data.seq !== undefined) el.setAttribute('data-seq', data.seq);
    el.innerHTML = `
        <div class="msg-avatar">${cfg.icon}</div>
        <div class="msg-content-wrap">
            <div class="msg-header">
                <span class="msg-name">${cfg.name}</span>
                <span class="msg-score ${scoreClass}">${data.score}/10</span>
                <span class="skip-badge">跳过</span>
            </div>
            <div class="skip-reason">${escapeHtml(data.score_reason || '认可当前讨论方向')}</div>
        </div>
    `;
    getRoundContainer().appendChild(el);
    scrollToBottom();
}

function addThinkingCard(data) {
    removeThinkingCard();
    const cfg = AGENTS[data.agent] || { name: data.agent_name, icon: data.agent_icon, color: '#8e8e8e' };
    const el = document.createElement('div');
    el.className = 'chat-msg-thinking';
    el.id = 'thinkingCard';
    el.setAttribute('data-agent', data.agent);
    el.style.setProperty('--agent-color', cfg.color);
    el.innerHTML = `
        <div class="msg-avatar">${cfg.icon}</div>
        <div class="thinking-content">
            <div class="thinking-name">${cfg.name}</div>
            <div class="thinking-dots">
                <span>思考中</span>
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
            </div>
        </div>
    `;
    getRoundContainer().appendChild(el);
    scrollToBottom();
}

function removeThinkingCard() {
    const card = $('thinkingCard');
    if (card) card.remove();
}

function addRoundDivider(round) {
    // 每个回合独立一个4列grid容器，回合内消息放入其中，避免跨回合行号错乱
    const block = document.createElement('div');
    block.className = 'round-block';
    block.dataset.round = round;
    const label = document.createElement('div');
    label.className = 'round-divider';
    label.textContent = `第 ${round} 轮`;
    block.appendChild(label);
    getMessagesInner().appendChild(block);
    state.currentRoundBlock = block;
    scrollToBottom();
}

// 获取当前回合容器：优先用currentRoundBlock，否则回退到messages-inner
function getRoundContainer() {
    return state.currentRoundBlock || getMessagesInner();
}

function addSystemNotice(text, type = 'info') {
    const el = document.createElement('div');
    el.className = `system-notice ${type}`;
    el.textContent = text;
    getRoundContainer().appendChild(el);
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
    updateGridHeaderScores();
}

function updateConsensus() {
    // 共识只看前三个Agent，组织者评分不参与共识判断
    const consensusKeys = ['innovator', 'critic', 'scholar'];
    const scores = consensusKeys.map(k => state.scores[k] || 0);
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
        paused: { text: '已暂停', cls: 'paused' },
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
    // 关闭SSE连接，避免辩论结束后无限重连
    if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
    }
    updateTopbar({ status: 'completed' });
    state.currentReport = data.report;
    // 显示结束操作区（查看报告 / 继续讨论）
    els.debateActions?.classList.remove('hidden');
    els.debateContinue?.classList.add('hidden');
    if (data.consensus) {
        showToast(`辩论完成 - ${data.total_rounds}轮达成共识`, 'success');
        addSystemNotice(`辩论完成 - ${data.total_rounds}轮后三方达成共识`, 'info');
        updateBottombar('已完成 - 达成共识');
    } else if (data.end_reason) {
        showToast(`辩论结束 - ${data.end_reason}`, 'info');
        addSystemNotice(`辩论结束 - 共${data.total_rounds}轮。${data.end_reason}`, 'info');
        updateBottombar('已结束 - 遇到瓶颈');
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

function exportDebate(format) {
    if (!state.debateId) { showToast('没有可导出的辩论', 'error'); return; }

    // PDF格式：前端打印方案
    if (format === 'pdf') {
        exportAsPDF();
        return;
    }

    const url = `${API_BASE}/api/debates/${state.debateId}/export?format=${format}`;
    fetch(url).then(res => {
        if (!res.ok) throw new Error('导出失败');
        return res.blob();
    }).then(blob => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const ext = format === 'json' ? 'json' : 'md';
        const name = {
            report: '思想孵化报告',
            md: '完整辩论记录',
            summary: '精简纪要',
            json: '辩论数据',
        }[format] || '导出';
        a.download = `${name}_${new Date().toISOString().slice(0, 10)}.${ext}`;
        a.click();
        URL.revokeObjectURL(url);
        showToast('导出成功', 'success');
    }).catch(e => showToast('导出失败: ' + e.message, 'error'));
}

async function exportAsPDF() {
    if (!state.currentReport) { showToast('报告尚未生成', 'error'); return; }
    const html = marked.parse(state.currentReport);
    const w = window.open('', '_blank');
    if (!w) { showToast('请允许弹出窗口', 'error'); return; }
    w.document.write(`
        <html><head><title>思想孵化报告</title>
        <style>
            body { font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; padding: 40px; line-height: 1.8; color: #1a1a2e; max-width: 800px; margin: 0 auto; }
            h2 { border-bottom: 2px solid #ddd; padding-bottom: 6px; color: #333; }
            h3 { color: #555; }
            blockquote { border-left: 3px solid #10a37f; padding-left: 14px; color: #666; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px 12px; }
            th { background: #f5f5f5; }
            code { background: #f0f0f0; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
        </style>
        </head><body>${html}</body></html>
    `);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 300);
}

function closeReport() { els.reportModal.classList.add('hidden'); }

// ===== 终止辩论 =====
async function stopDebate() {
    if (!state.debateId) return;
    try {
        await fetch(`${API_BASE}/api/debates/${state.debateId}/stop`, { method: 'POST' });
        if (state.eventSource) state.eventSource.close();
        state.eventSource = null;
        state.isPaused = false;
        setDebatingState(false);
        removeThinkingCard();
        updateTopbar({ status: 'terminated' });
        updateBottombar('辩论已终止');
        showToast('辩论已终止', 'info');
    } catch (e) { showToast('终止失败', 'error'); }
}

// ===== UI状态 =====
function setDebatingState(debating) {
    state.isDebating = debating;
    els.btnStart.classList.toggle('loading', debating);
    els.btnStart.disabled = debating;
    els.btnPause.classList.toggle('hidden', !debating);
    els.btnStop.classList.toggle('hidden', !debating);
    els.topicInput.disabled = debating;
    els.maxRounds.disabled = debating;
    els.scoreThreshold.disabled = debating;
    // 导出按钮：只要有debateId就可用（辩论进行中也可导出）
    if (els.btnExport) els.btnExport.disabled = !state.debateId;
    // 开始新辩论时隐藏结束操作区
    if (debating) {
        els.debateActions?.classList.add('hidden');
        els.debateContinue?.classList.add('hidden');
    }
}

function setPausedState(paused) {
    state.isPaused = paused;
    els.btnPause.textContent = paused ? '继续' : '暂停';
    els.bottombarInput.classList.toggle('hidden', !paused);
    if (paused) {
        els.userInput?.focus();
    } else {
        if (els.userInput) els.userInput.value = '';
    }
}

async function togglePause() {
    if (!state.debateId) return;
    const endpoint = state.isPaused ? 'resume' : 'pause';
    try {
        const res = await fetch(`${API_BASE}/api/debates/${state.debateId}/${endpoint}`, { method: 'POST' });
        if (!res.ok) {
            const err = await res.json();
            showToast(err.detail || '操作失败', 'error');
        }
    } catch (e) { showToast('操作失败', 'error'); }
}

async function sendUserMessage() {
    const content = els.userInput.value.trim();
    if (!content) return;
    if (!state.debateId) return;

    try {
        const res = await fetch(`${API_BASE}/api/debates/${state.debateId}/inject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });
        if (res.ok) {
            els.userInput.value = '';
        } else {
            const err = await res.json();
            showToast(err.detail || '发送失败', 'error');
        }
    } catch (e) { showToast('发送失败', 'error'); }
}

function addUserBubble(content, round) {
    // DOM级去重
    const root = getRoundContainer().parentElement;  // 回合容器或messages-inner
    const existing = root.querySelector(`[data-user-seq="${state.lastSeq}"]`)
        || getMessagesInner().querySelector(`[data-user-seq="${state.lastSeq}"]`);
    if (existing) return;

    const el = document.createElement('div');
    el.className = 'chat-msg-user-inject';
    el.setAttribute('data-user-seq', state.lastSeq);
    el.innerHTML = `
        <div class="msg-avatar user-inject-avatar">YOU</div>
        <div class="msg-content-wrap">
            <div class="msg-header">
                <span class="msg-name user-inject-name">用户</span>
                ${round ? `<span class="msg-round">第${round}轮</span>` : ''}
                <span class="msg-tag">参与发言</span>
            </div>
            <div class="msg-body"><div class="msg-content">${escapeHtml(content)}</div></div>
        </div>
    `;
    getRoundContainer().appendChild(el);
    scrollToBottom();
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
let historyFilter = 'all';

async function openHistory() {
    els.historyModal.classList.remove('hidden');
    els.historyList.innerHTML = '<p class="loading-text">加载中...</p>';
    try {
        const res = await fetch(`${API_BASE}/api/debates`);
        let debates = await res.json();

        // 按筛选过滤
        if (historyFilter === 'resumable') {
            debates = debates.filter(d => d.is_resumable);
        } else if (historyFilter === 'completed') {
            debates = debates.filter(d => d.status === 'completed');
        }

        if (!debates.length) {
            els.historyList.innerHTML = '<p class="loading-text">暂无符合条件的辩论</p>';
            return;
        }

        els.historyList.innerHTML = debates.map(d => `
            <div class="history-item ${d.is_resumable ? 'resumable' : ''}" data-id="${d.id}">
                <div class="history-topic">${escapeHtml(d.topic)}</div>
                <div class="history-meta">
                    <span class="history-status ${d.status}">${statusText(d.status)}</span>
                    <span>${d.current_round}轮</span>
                    <span>${d.message_count}条</span>
                    <span>${formatDate(d.created_at)}</span>
                    ${d.is_resumable ? '<span class="resume-badge">可恢复</span>' : ''}
                </div>
                ${d.is_resumable ? `
                    <div class="history-actions">
                        <button class="btn-resume" data-id="${d.id}">恢复辩论</button>
                    </div>
                ` : ''}
            </div>
        `).join('');

        // 绑定恢复按钮
        document.querySelectorAll('.btn-resume').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                loadDebate(btn.dataset.id, true);
            });
        });

        // 绑定历史项点击（查看已完成）
        document.querySelectorAll('.history-item').forEach(item => {
            item.addEventListener('click', () => loadDebate(item.dataset.id, false));
        });
    } catch { els.historyList.innerHTML = '<p class="loading-text">加载失败</p>'; }
}

function closeHistory() { els.historyModal.classList.add('hidden'); }

// ===== 加载历史辩论 =====
async function loadDebate(debateId, resume = false) {
    closeHistory();

    // 如果有正在进行的辩论，先终止其SSE连接（但不终止后端辩论）
    if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
    }

    // 重置所有状态
    state.isDebating = false;
    state.isPaused = false;
    state.lastSeq = -1;
    state.renderedRounds.clear();
    state.currentRoundBlock = null;
    state.currentReport = null;

    try {
        const res = await fetch(`${API_BASE}/api/debates/${debateId}`);
        const debate = await res.json();

        state.debateId = debateId;
        state.currentTopic = debate.topic;
        state.scores = debate.scores || { innovator: 0, critic: 0, scholar: 0 };
        state.scoreThreshold = debate.config?.score_threshold || 6;

        // 先彻底清空消息区域
        clearMessages();
        showChatUI(debate.topic);

        // showChatUI会设pending状态，这里覆盖为实际状态
        updateTopbar({ round: debate.current_round, status: debate.status });

        // 渲染历史消息
        addUserMessage(debate.topic);

        let lastRound = 0;
        for (const msg of debate.messages || []) {
            if (msg.is_summary) {
                addSystemNotice('上下文已自动压缩', 'compress');
            } else if (msg.is_user) {
                addUserBubble(msg.content, msg.round);
            } else {
                if (msg.round !== lastRound) {
                    lastRound = msg.round;
                    addRoundDivider(msg.round);
                }
                if (msg.is_skip) {
                    addSkipCard({
                        agent: msg.agent || msg.role,
                        round: msg.round,
                        score: msg.score,
                        score_reason: msg.score_reason || msg.content,
                    });
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
        }

        renderScores();
        updateConsensus();

        // 如果有最终报告，弹窗显示
        if (debate.final_summary) {
            state.currentReport = debate.final_summary;
            setTimeout(() => showReport(debate.final_summary), 500);
        }

        // 根据状态决定后续行为
        if (resume && ['ongoing', 'paused'].includes(debate.status)) {
            setDebatingState(true);
            if (debate.status === 'paused') {
                state.isPaused = true;
                setPausedState(true);
                updateBottombar('已暂停 - 可输入观点参与讨论');
            } else {
                updateBottombar('辩论进行中');
            }
            showToast('正在恢复辩论...', 'info');
            connectSSE(debateId);
        } else if (debate.status === 'completed') {
            setDebatingState(false);
            updateBottombar('已完成');
            // 报告已在上面处理
            // 加载的是已完成辩论时，也显示结束操作区（查看报告/继续讨论）
            if (debate.final_summary) els.debateActions?.classList.remove('hidden');
        } else if (debate.status === 'terminated') {
            setDebatingState(false);
            updateBottombar('辩论已终止');
        } else {
            setDebatingState(false);
            updateBottombar('已加载历史辩论');
        }
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
    return { pending: '等待中', ongoing: '进行中', paused: '已暂停', completed: '已完成', terminated: '已终止' }[s] || s;
}

function formatDate(s) {
    if (!s) return '';
    try {
        const d = new Date(s);
        return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
    } catch { return ''; }
}

// ===== 启动 =====
init();
