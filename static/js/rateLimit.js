// 處理速率限制錯誤
async function handleRateLimitError(error, retryAfter) {
    // 創建彈窗 HTML
    const modalHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h4>⚠️ API 速率限制</h4>
                <button class="modal-close-btn" onclick="closeRateLimitModal()">×</button>
            </div>
            <div class="modal-body">
                <div class="rate-limit-info">
                    <p><strong>已達到 API 速率限制</strong></p>
                    <p>${error.message || '請求過於頻繁，請稍後再試。'}</p>
                    
                    <div class="countdown-container">
                        <p>需要等待：</p>
                        <div class="countdown-circle">
                            <svg width="120" height="120">
                                <circle cx="60" cy="60" r="50" fill="none" stroke="#e0e0e0" stroke-width="10"/>
                                <circle cx="60" cy="60" r="50" fill="none" stroke="#ff9800" stroke-width="10"
                                        stroke-dasharray="314" stroke-dashoffset="314"
                                        transform="rotate(-90 60 60)" id="countdownCircle"/>
                            </svg>
                            <div class="countdown-text" id="rateLimitCountdown">${retryAfter}</div>
                        </div>
                    </div>
                    
                    <div class="rate-limit-details">
                        <h5>速率限制說明：</h5>
                        <ul>
                            <li>RPM: 每分鐘請求數限制</li>
                            <li>ITPM: 每分鐘輸入 Token 限制</li>
                            <li>OTPM: 每分鐘輸出 Token 限制</li>
                        </ul>
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeRateLimitModal()">取消</button>
                <button class="btn btn-primary" id="retryButton" disabled>
                    等待中... (<span id="retryCountdown">${retryAfter}</span>s)
                </button>
            </div>
        </div>
    `;
    
    const modal = showModalDialog(modalHTML);
    
    // 倒計時邏輯
    let remaining = parseInt(retryAfter) || 60;
    const countdownInterval = setInterval(() => {
        remaining--;
        
        // 更新倒計時顯示
        const countdownEl = document.getElementById('rateLimitCountdown');
        const retryCountdownEl = document.getElementById('retryCountdown');
        if (countdownEl) countdownEl.textContent = remaining;
        if (retryCountdownEl) retryCountdownEl.textContent = remaining;
        
        // 更新圓形進度
        const circle = document.getElementById('countdownCircle');
        if (circle) {
            const offset = 314 - (314 * remaining / retryAfter);
            circle.style.strokeDashoffset = offset;
        }
        
        if (remaining <= 0) {
            clearInterval(countdownInterval);
            const retryBtn = document.getElementById('retryButton');
            if (retryBtn) {
                retryBtn.disabled = false;
                retryBtn.textContent = '立即重試';
                retryBtn.onclick = () => {
                    modal.close();
                    // 重新執行上次的操作
                    if (window.lastAnalysisAction) {
                        window.lastAnalysisAction();
                    }
                };
            }
        }
    }, 1000);
    
    // 儲存關閉函數
    window.closeRateLimitModal = () => {
        clearInterval(countdownInterval);
        modal.close();
    };
    
    // 等待倒計時結束
    return new Promise(resolve => {
        setTimeout(() => {
            clearInterval(countdownInterval);
            modal.close();
            resolve();
        }, remaining * 1000);
    });
}

// 初始化速率限制狀態
async function initializeRateLimitStatus() {
    try {
        // 立即顯示載入狀態
        const container = document.getElementById('rateLimitStatusContainer');
        if (container) {
            container.innerHTML = `
                <div class="rate-limit-status loading">
                    <div class="rate-limit-header">
                        <h4>📊 API 使用狀況</h4>
                    </div>
                    <div class="loading-spinner">載入中...</div>
                </div>
            `;
        }
        
        // 獲取並顯示狀態
        await refreshRateLimitStatus();
        
        // 設置自動刷新（每 30 秒）
        if (window.rateLimitRefreshInterval) {
            clearInterval(window.rateLimitRefreshInterval);
        }
        window.rateLimitRefreshInterval = setInterval(refreshRateLimitStatus, 30000);
        
    } catch (error) {
        console.error('Failed to initialize rate limit status:', error);
    }
}

// 創建迷你速率限制指示器
function createMiniRateLimitIndicator() {
    const header = document.querySelector('.ai-panel-header');
    if (!header) return;
    
    // 檢查是否已存在
    if (document.getElementById('miniRateLimitIndicator')) return;
    
    const indicator = document.createElement('div');
    indicator.id = 'miniRateLimitIndicator';
    indicator.className = 'mini-rate-limit-indicator';
    indicator.title = '點擊查看詳細使用狀況';
    indicator.innerHTML = `
        <span class="indicator-icon">📊</span>
        <span class="indicator-value">--</span>
    `;
    
    // 點擊展開/收起詳細狀態
    indicator.onclick = toggleRateLimitDetails;
    
    // 插入到標題右側按鈕之前
    const buttonsContainer = header.querySelector('div:last-child');
    buttonsContainer.insertBefore(indicator, buttonsContainer.firstChild);
}

// 切換詳細狀態顯示
function toggleRateLimitDetails() {
    const container = document.getElementById('rateLimitStatusContainer');
    if (container) {
        container.classList.toggle('collapsed');
        
        // 如果展開了，立即刷新
        if (!container.classList.contains('collapsed')) {
            refreshRateLimitStatus();
        }
    }
}

// 全局速率限制更新函數
async function updateRateLimitDisplay() {
    try {
        const response = await fetch('/get-rate-limit-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: selectedModel })
        });
        
        if (response.ok) {
            const usage = await response.json();
            
            // 更新迷你指示器（即使主面板是收起狀態）
            updateMiniRateLimitIndicator(usage);
            
            // 如果主面板存在且展開，也更新它
            const container = document.getElementById('rateLimitStatusContainer');
            if (container && !container.classList.contains('collapsed')) {
                displayRateLimitStatus(usage);
            }
        }
    } catch (error) {
        console.error('Failed to update rate limit display:', error);
    }
}

// 修改 updateMiniRateLimitIndicator 以處理不存在的情況
function updateMiniRateLimitIndicator(usage) {
    let indicator = document.getElementById('miniRateLimitIndicator');
    
    // 如果不存在，創建它
    if (!indicator) {
        createMiniRateLimitIndicator();
        indicator = document.getElementById('miniRateLimitIndicator');
    }
    
    if (!indicator) return;
    
    const valueSpan = indicator.querySelector('.indicator-value');
    if (!valueSpan) return;

	// 保存舊值
    const oldValue = valueSpan.textContent;

    // 計算新值
    const rpmPercent = (usage.requests / usage.rpm_limit * 100);
    const itpmPercent = (usage.input_tokens / usage.itpm_limit * 100);
    const otpmPercent = (usage.output_tokens / usage.otpm_limit * 100);
    const maxPercent = Math.max(rpmPercent, itpmPercent, otpmPercent);
    const newValue = `${Math.round(maxPercent)}%`;
    
    // 如果值變化了，添加動畫
    if (oldValue !== newValue) {
        valueSpan.classList.add('updating');
        setTimeout(() => {
            valueSpan.classList.remove('updating');
        }, 500);
    }
    
    valueSpan.textContent = newValue;
    
    // 更新標題以顯示詳細信息
    indicator.title = `RPM: ${usage.requests}/${usage.rpm_limit} (${Math.round(rpmPercent)}%)\n` +
                     `ITPM: ${usage.input_tokens.toLocaleString()}/${usage.itpm_limit.toLocaleString()} (${Math.round(itpmPercent)}%)\n` +
                     `OTPM: ${usage.output_tokens.toLocaleString()}/${usage.otpm_limit.toLocaleString()} (${Math.round(otpmPercent)}%)`;
    
    // 根據使用率改變顏色和動畫
    indicator.classList.remove('low-usage', 'medium-usage', 'high-usage');
    
    if (maxPercent > 80) {
        indicator.classList.add('high-usage');
    } else if (maxPercent > 60) {
        indicator.classList.add('medium-usage');
    } else {
        indicator.classList.add('low-usage');
    }
}

document.addEventListener('DOMContentLoaded', function() {
    // 初始化速率限制功能
    setupRateLimitFeatures();
});

function setupRateLimitFeatures() {
    // 創建迷你指示器
    createMiniRateLimitIndicator();
    
    // 如果 AI 面板已經開啟，初始化狀態
    if (isAIPanelOpen) {
        initializeRateLimitStatus();
    }
}