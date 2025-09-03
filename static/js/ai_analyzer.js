class AIRequestManager {
    constructor() {
        this.currentController = null;
        this.isProcessing = false;
        this.currentMode = null;
        this.stopButton = null;
    }
    
    // 開始新請求
    startRequest(mode) {
        this.cleanup();
        this.currentController = new AbortController();
        this.isProcessing = true;
        this.currentMode = mode;
        this.showStopButton();
        return this.currentController.signal;
    }
    
    // 停止當前請求
    stopRequest() {
        console.log('執行統一停止請求...');
        
        // 1. 取消 fetch 請求
        if (this.currentController) {
            this.currentController.abort();
            console.log('已發送 abort 信號');
        }
        
        // 2. 如果有 aiAnalyzer 實例，也停止它
        if (window.aiAnalyzer && window.aiAnalyzer.isAnalyzing) {
            window.aiAnalyzer.stopAnalysis();
        }
        
        // 3. 清理狀態
        this.cleanup();
    }
    
    // 清理狀態
    cleanup() {
        this.currentController = null;
        this.isProcessing = false;
        this.currentMode = null;
        this.hideStopButton();
        this.resetAllButtons();
    }
    
    // 顯示統一的停止按鈕
    showStopButton() {
        // 移除所有現有的停止按鈕
        document.querySelectorAll('.ai-stop-btn-unified').forEach(btn => btn.remove());
        
        // 在分析區域創建統一的停止按鈕
        const analyzeSection = document.querySelector('.analyze-file-section');
        if (analyzeSection) {
            this.stopButton = document.createElement('button');
            this.stopButton.className = 'ai-stop-btn-unified';
            this.stopButton.innerHTML = `
                <span class="stop-icon">⏹️</span>
                <span>停止分析</span>
                <div class="ai-spinner"></div>
            `;
            this.stopButton.onclick = () => this.stopRequest();
            
            // 添加到分析區域
            analyzeSection.appendChild(this.stopButton);
        }
        
        // 同時在輸入區域顯示停止狀態
        this.updateInputAreaState(true);
    }
    
    // 隱藏停止按鈕
    hideStopButton() {
        if (this.stopButton) {
            this.stopButton.remove();
            this.stopButton = null;
        }
        this.updateInputAreaState(false);
    }
    
    // 更新輸入區域狀態
    updateInputAreaState(isProcessing) {
        const askBtn = document.getElementById('askBtnInline');
        const customQuestion = document.getElementById('customQuestion');
        
        if (isProcessing) {
            if (askBtn) {
                askBtn.innerHTML = '⏹️';
                askBtn.onclick = () => this.stopRequest();
                askBtn.disabled = false;
                askBtn.classList.add('stop-mode');
            }
            if (customQuestion) {
                customQuestion.disabled = true;
                customQuestion.placeholder = '分析進行中...';
            }
        } else {
            if (askBtn) {
                askBtn.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 2L11 13"></path>
                        <path d="M22 2L15 22L11 13L2 9L22 2Z"></path>
                    </svg>
                `;
                askBtn.onclick = () => askCustomQuestion();
                askBtn.disabled = !customQuestion?.value?.trim();
                askBtn.classList.remove('stop-mode');
            }
            if (customQuestion) {
                customQuestion.disabled = false;
                customQuestion.placeholder = '詢問關於這個檔案的任何問題...';
            }
        }
    }
    
    // 重置所有按鈕狀態
    resetAllButtons() {
        // 重置模式按鈕
        document.querySelectorAll('.ai-mode-btn').forEach(btn => {
            btn.disabled = false;
            btn.classList.remove('analyzing', 'disabled');
            
            const mode = btn.dataset.mode;
            const modeInfo = {
                'smart': { icon: '🧠', name: '智能分析', desc: '自動最佳策略' },
                'quick': { icon: '⚡', name: '快速分析', desc: '30秒內完成' },
                'deep': { icon: '🔍', name: '深度分析', desc: '詳細診斷' }
            }[mode];
            
            if (modeInfo) {
                btn.innerHTML = `
                    <span class="mode-icon">${modeInfo.icon}</span>
                    <span class="mode-name">${modeInfo.name}</span>
                    <span class="mode-desc">${modeInfo.desc}</span>
                `;
            }
        });
        
        // 重置分析按鈕（如果存在）
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn && typeof resetAnalyzeButton === 'function') {
            resetAnalyzeButton();
        }
        
        // 重置全局狀態
        if (typeof window.isAnalyzing !== 'undefined') {
            window.isAnalyzing = false;
        }
        if (typeof window.isAskingQuestion !== 'undefined') {
            window.isAskingQuestion = false;
        }
    }
}

// AI 分析器的前端邏輯
class AIAnalyzer {
    constructor() {
        this.sessionId = this.generateSessionId();
        this.currentProvider = 'anthropic';  // 預設
        this.currentModel = 'claude-sonnet-4-20250514';
        this.isAnalyzing = false;
        this.eventSource = null;
        this.currentMode = 'smart';
        this.messages = [];
        this.markdownParser = null;
        this.currentResponseArea = null;
        this.accumulatedContent = '';
        this.infoMessages = new Set();
        this.initializeUI();
    }
    
    generateSessionId() {
        return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }
    
    initializeUI() {
        // 初始化分析模式按鈕
        this.initializeModeButtons();
        
        // 初始化模型選擇器
        this.initializeModelSelector();
        
        // 初始化停止按鈕
        this.initializeStopButton();
        
        // 綁定鍵盤快捷鍵
        this.bindKeyboardShortcuts();
    }
    
    initializeModeButtons() {
        // 創建模式選擇按鈕組
        const modeButtons = `
            <div class="ai-mode-selector">
                <button class="ai-mode-btn smart" data-mode="smart">
                    <span class="mode-icon">🧠</span>
                    <span class="mode-name">智能分析</span>
                    <span class="mode-desc">自動最佳策略</span>
                </button>
                <button class="ai-mode-btn quick" data-mode="quick">
                    <span class="mode-icon">⚡</span>
                    <span class="mode-name">快速分析</span>
                    <span class="mode-desc">30秒內完成</span>
                </button>
                <button class="ai-mode-btn deep" data-mode="deep">
                    <span class="mode-icon">🔍</span>
                    <span class="mode-name">深度分析</span>
                    <span class="mode-desc">詳細診斷</span>
                </button>
            </div>
        `;
        
        // 插入到分析按鈕之前
        const analyzeSection = document.querySelector('.analyze-file-section');
        if (analyzeSection) {
            const analyzeBtn = analyzeSection.querySelector('#analyzeBtn');
            if (analyzeBtn) {
                analyzeBtn.insertAdjacentHTML('beforebegin', modeButtons);
            } else {
                analyzeSection.insertAdjacentHTML('afterbegin', modeButtons);
            }
        }
        
        // 綁定點擊事件
        document.querySelectorAll('.ai-mode-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const mode = e.currentTarget.dataset.mode;
                
                // 更新選中狀態
                document.querySelectorAll('.ai-mode-btn').forEach(b => b.classList.remove('active'));
                e.currentTarget.classList.add('active');
                
                // 執行分析
                this.executeAnalysis(mode);
            });
        });
    }
    
    selectMode(mode) {
        this.currentMode = mode;
        
        // 更新按鈕狀態
        document.querySelectorAll('.ai-mode-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
        
        // 更新分析按鈕文字
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            const modeTexts = {
                'smart': '開始智能分析',
                'quick': '快速分析 (30秒)',
                'deep': '深度分析 (2-3分鐘)'
            };
            analyzeBtn.querySelector('#analyzeText').textContent = modeTexts[mode];
        }
    }
    
    initializeModelSelector() {
        // 添加 Provider 選擇
        const modelSelector = document.querySelector('.model-selector-inline');
        if (modelSelector) {
            const providerSelector = `
                <select class="provider-select" id="providerSelect">
                    <option value="anthropic">Anthropic</option>
                    <option value="openai">OpenAI</option>
                </select>
            `;
            modelSelector.insertAdjacentHTML('afterbegin', providerSelector);
            
            // 綁定 Provider 切換事件
            document.getElementById('providerSelect').addEventListener('change', (e) => {
                this.switchProvider(e.target.value);
            });
        }
    }
    
    async switchProvider(provider) {
        this.currentProvider = provider;
        
        // 獲取該 Provider 的模型列表
        try {
            const response = await fetch(`/api/ai/models/${provider}`);
            const data = await response.json();
            
            if (data.models) {
                this.updateModelList(data.models);
            }
        } catch (error) {
            console.error('獲取模型列表失敗:', error);
        }
    }
    
    updateModelList(models) {
        const modelPopup = document.getElementById('modelPopup');
        if (!modelPopup) return;
        
        const modelGrid = modelPopup.querySelector('.model-popup-grid');
        modelGrid.innerHTML = models.map(model => {
            const badgeClass = this.getBadgeClass(model.id);
            const badgeText = this.getBadgeText(model.id);
            
            return `
                <div class="model-card" data-model="${model.id}" onclick="aiAnalyzer.selectModel('${model.id}')">
                    <div class="model-card-name">${model.name}</div>
                    <div class="model-card-desc">${model.description}</div>
                    ${badgeText ? `<div class="model-card-badge ${badgeClass}">${badgeText}</div>` : ''}
                    ${model.pricing ? `
                        <div class="model-pricing">
                            輸入: $${model.pricing.input}/1K tokens | 
                            輸出: $${model.pricing.output}/1K tokens
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
    }

    // 新增方法：獲取模型徽章樣式
    getBadgeClass(modelId) {
        if (modelId.includes('claude-4')) return 'new';
        if (modelId.includes('chat-')) return 'internal';
        return '';
    }
    
    // 新增方法：獲取模型徽章文字
    getBadgeText(modelId) {
        if (modelId.includes('claude-4')) return 'NEW';
        if (modelId.includes('chat-codetek') || modelId.includes('chat-chattek')) return 'INTERNAL';
        return '';
    }

    selectModel(modelId) {
        this.currentModel = modelId;
        
        // 更新顯示
        const selectedCard = document.querySelector(`.model-card[data-model="${modelId}"]`);
        if (selectedCard) {
            document.querySelectorAll('.model-card').forEach(card => {
                card.classList.remove('selected');
            });
            selectedCard.classList.add('selected');
            
            // 更新按鈕文字
            const modelName = selectedCard.querySelector('.model-card-name').textContent;
            document.getElementById('selectedModelNameInline').textContent = modelName;
        }
        
        // 關閉彈窗
        const modelPopup = document.getElementById('modelPopup');
        if (modelPopup) {
            modelPopup.style.display = 'none';
        }
    }
    
    initializeStopButton() {
        // 在分析按鈕旁添加停止按鈕
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            const stopBtn = `
                <button class="analyze-stop-btn" id="stopAnalysisBtn" style="display: none;">
                    <span>⏹️</span> 停止分析
                </button>
            `;
            analyzeBtn.insertAdjacentHTML('afterend', stopBtn);
            
            // 綁定停止事件
            document.getElementById('stopAnalysisBtn').addEventListener('click', () => {
                this.stopAnalysis();
            });
        }
    }
    
    bindKeyboardShortcuts() {
		document.addEventListener('keydown', (e) => {
			// Ctrl+Enter: 開始分析
			if (e.ctrlKey && e.key === 'Enter' && !this.isAnalyzing) {
				e.preventDefault();
				this.startAnalysis();
			}
			
			// Escape: 停止分析
			if (e.key === 'Escape' && this.isAnalyzing) {
				e.preventDefault();
				this.stopAnalysis();
			}
			
			// Ctrl+Shift+C: 清除對話
			if (e.ctrlKey && e.shiftKey && e.key === 'C') {
				e.preventDefault();
				this.clearConversation();
			}
		});
	}
    
    async startAnalysis() {
        if (this.isAnalyzing) return;
        
        const fileContent = window.fileContent || window.escaped_content;
        const fileName = window.fileName || window.escaped_filename;
        const filePath = window.filePath || window.escaped_file_path;
        
        if (!fileContent) {
            alert('沒有檔案內容可分析');
            return;
        }
        
        this.isAnalyzing = true;
        this.updateUIState('analyzing');
        
        // 重置累積內容
        this.accumulatedContent = '';
        
        // 創建新的回應區域
        const responseArea = this.createResponseArea();
        this.currentResponseArea = responseArea;
        
        try {
            const requestData = {
                session_id: this.sessionId,
                provider: this.currentProvider,
                model: this.currentModel,
                mode: this.currentMode,
                file_path: filePath,
                file_name: fileName,
                content: fileContent,
                stream: true,
                context: this.messages.slice(-5).map(msg => ({
                    role: msg.role,
                    content: msg.content.substring(0, 500)
                }))
            };
            
            const response = await fetch('/api/ai/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData)
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            while (true) {
                const { value, done } = await reader.read();
                if (done) {
                    // 流結束時，確保觸發 complete 如果沒有收到
                    if (this.isAnalyzing && this.currentResponseArea) {
                        // 給一個短暫延遲確保最後的數據被處理
                        setTimeout(() => {
                            if (this.isAnalyzing) {
                                // 如果還在分析中，手動觸發完成
                                this.handleComplete({
                                    usage: { input: 0, output: 0 },
                                    cost: 0
                                }, this.currentResponseArea);
                            }
                        }, 500);
                    }
                    break;
                }
                
                if (!this.isAnalyzing) {
                    reader.cancel();
                    break;
                }
                
                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            this.handleStreamData(data, responseArea);
                        } catch (e) {
                            console.error('解析 SSE 資料錯誤:', e);
                        }
                    }
                }
            }
            
        } catch (error) {
            console.error('分析錯誤:', error);
            this.handleError(error.message, responseArea);
        }
    }
    
    createResponseArea() {
        const responseContent = document.getElementById('aiResponseContent');
        
        // 創建新的對話項目
        const conversationItem = document.createElement('div');
        conversationItem.className = 'ai-conversation-item';
        conversationItem.id = `conversation-${Date.now()}`;
        
        const modeInfo = {
            'smart': { icon: '🧠', name: '智能分析' },
            'quick': { icon: '⚡', name: '快速分析' },
            'deep': { icon: '🔍', name: '深度分析' }
        }[this.currentMode];
        
        conversationItem.innerHTML = `
            <div class="ai-conversation-header">
                <div class="conversation-meta">
                    <span class="mode-indicator">
                        <span class="mode-icon">${modeInfo.icon}</span>
                        <span class="mode-text">${modeInfo.name}</span>
                    </span>
                    <span class="model-info">${this.currentProvider} - ${this.currentModel}</span>
                    <span class="timestamp">${new Date().toLocaleTimeString()}</span>
                </div>
                <div class="conversation-actions">
                    <button class="copy-btn" onclick="aiAnalyzer.copyResponse('${conversationItem.id}')">
                        📋 複製
                    </button>
                    <button class="export-html-btn" onclick="aiAnalyzer.exportSingleResponse('${conversationItem.id}', 'html')">
                        🌐 HTML
                    </button>
                    <button class="export-md-btn" onclick="aiAnalyzer.exportSingleResponse('${conversationItem.id}', 'markdown')">
                        📝 MD
                    </button>
                </div>
            </div>
            <div class="ai-conversation-content">
                <div class="ai-thinking" style="display: none;">
                    <span class="thinking-dots">
                        <span>.</span><span>.</span><span>.</span>
                    </span>
                    AI 正在思考中
                </div>
                <div class="ai-response-text"></div>
                <div class="ai-usage-info" style="display: none;">
                    <span class="token-count">Tokens: <span class="input-tokens">0</span> / <span class="output-tokens">0</span></span>
                    <span class="cost-info">成本: $<span class="total-cost">0.00</span></span>
                </div>
            </div>
        `;
        
        responseContent.appendChild(conversationItem);
        
        // 顯示思考動畫
        conversationItem.querySelector('.ai-thinking').style.display = 'flex';
        
        // 滾動到新內容
        conversationItem.scrollIntoView({ behavior: 'smooth', block: 'start' });
        
        return conversationItem;
    }
    
    appendFormattedContent(container, content) {
        // 將新內容添加到臨時元素中進行格式化
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = this.formatMarkdown(content);
        
        // 將格式化的內容追加到容器
        while (tempDiv.firstChild) {
            container.appendChild(tempDiv.firstChild);
        }
        
        // 保持滾動在底部
        const chatArea = document.getElementById('aiChatArea');
        if (chatArea) {
            chatArea.scrollTop = chatArea.scrollHeight;
        }
    }
    
    formatMarkdown(text) {
        console.log(text)
        const lines = text.split('\n');
        let html = '';
        let inCodeBlock = false;
        let codeLang = '';
        let listType = null; // 'ol' 或 'ul'

        for (let line of lines) {
            // 1. CODE BLOCK 開關
            if (inCodeBlock) {
            if (line.trim().startsWith('```')) {
                html += '</code></pre>';
                inCodeBlock = false;
            } else {
                html += this.escapeHtml(line) + '\n';
            }
            continue;
            }
            if (line.trim().startsWith('```')) {
            codeLang = line.trim().slice(3).trim();
            html += `<pre class="ai-code-block"><code class="language-${codeLang}">`;
            inCodeBlock = true;
            continue;
            }

            // 2. HEADING
            const hdMatch = line.match(/^(#{1,3})\s+(.*)$/);
            if (hdMatch) {
            const lvl = hdMatch[1].length;
            html += `<h${lvl} class="ai-h${lvl}">${hdMatch[2]}</h${lvl}>`;
            continue;
            }

            // 3. 有序列表
            const olMatch = line.match(/^(\d+)\.\s+(.*)$/);
            if (olMatch) {
            if (listType !== 'ol') {
                if (listType === 'ul') html += '</ul>';
                html += '<ol class="ai-ordered-list">';
                listType = 'ol';
            }
            html += `<li class="ai-ordered-item">${olMatch[2]}</li>`;
            continue;
            }

            // 4. 無序列表
            const ulMatch = line.match(/^- (.*)$/);
            if (ulMatch) {
            if (listType !== 'ul') {
                if (listType === 'ol') html += '</ol>';
                html += '<ul class="ai-unordered-list">';
                listType = 'ul';
            }
            html += `<li class="ai-unordered-item">${ulMatch[1]}</li>`;
            continue;
            }

            // 遇到空行，結束當前列表
            if (line.trim() === '') {
            if (listType === 'ol') html += '</ol>';
            if (listType === 'ul') html += '</ul>';
            listType = null;
            continue;
            }

            // 5. 段落＋行內格式
            let inline = line
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code class="ai-inline-code">$1</code>');
            html += `<p class="ai-paragraph">${inline}</p>`;
        }

        // 收尾：還沒關的 codeblock 或 list
        if (inCodeBlock) html += '</code></pre>';
        if (listType === 'ol') html += '</ol>';
        if (listType === 'ul') html += '</ul>';
        console.log(html    )
        return html;
    }
    
    handleComplete(data, responseArea) {
        // 停止任何進行中的更新
        if (this.updateTimer) {
            clearTimeout(this.updateTimer);
            this.updateTimer = null;
        }
        
        // 做最後一次完整格式化（但不要清空）
        const contentDiv = responseArea.querySelector('.ai-response-text');
        const contentArea = contentDiv.querySelector('.content-area');
        
        if (contentArea && this.accumulatedContent) {
            // 最終格式化
            const formatted = this.formatContentChatGPTStyle(this.accumulatedContent);
            contentArea.innerHTML = formatted;
        }
        
        // 更新統計信息
        const usageDiv = responseArea.querySelector('.ai-usage-info');
        if (data.usage) {
            responseArea.querySelector('.input-tokens').textContent = data.usage.input.toLocaleString();
            responseArea.querySelector('.output-tokens').textContent = data.usage.output.toLocaleString();
            responseArea.querySelector('.total-cost').textContent = data.cost.toFixed(4);
            usageDiv.style.display = 'flex';
        }
        
        // 添加到消息歷史
        this.messages.push({
            role: 'assistant',
            content: this.accumulatedContent,
            timestamp: new Date(),
            mode: this.currentMode,
            model: this.currentModel,
            usage: data.usage,
            cost: data.cost
        });
        
        // 標記分析完成但不清理內容
        this.completeAnalysis();
    }

    completeAnalysis() {
        // 只重置狀態，不清理內容
        this.isAnalyzing = false;
        this.updateUIState('idle');
        
        // 確保移除 loading
        if (this.currentResponseArea) {
            const thinkingDiv = this.currentResponseArea.querySelector('.ai-thinking');
            if (thinkingDiv) {
                thinkingDiv.style.display = 'none';
            }
            
            // 添加完成標記
            this.currentResponseArea.classList.add('analysis-complete');
        }
        
        // 重置追蹤變數但不清空內容
        this.currentResponseArea = null;
        // 不要清空 accumulatedContent，以便後續可能的使用
        this.infoMessages.clear();
    }

    forceStopAnalysis() {
        if (this.updateTimer) {
            clearTimeout(this.updateTimer);
            this.updateTimer = null;
        }
        
        this.isAnalyzing = false;
        this.updateUIState('idle');
        
        if (this.currentResponseArea) {
            const thinkingDiv = this.currentResponseArea.querySelector('.ai-thinking');
            if (thinkingDiv) {
                thinkingDiv.style.display = 'none';
            }
        }
        
        // 強制停止時才清理所有內容
        this.currentResponseArea = null;
        this.accumulatedContent = '';
        this.infoMessages.clear();
    }

    handleError(error, responseArea) {
        const contentDiv = responseArea.querySelector('.ai-response-text');
        const thinkingDiv = responseArea.querySelector('.ai-thinking');
        
        // 移除 loading
        if (thinkingDiv) {
            thinkingDiv.style.display = 'none';
        }
        
        // 顯示錯誤但保留之前的內容（如果有）
        const messageArea = contentDiv.querySelector('.message-area');
        const contentArea = contentDiv.querySelector('.content-area');
        
        if (!messageArea || !contentArea) {
            contentDiv.innerHTML = `
                <div class="ai-error">
                    <span class="error-icon">❌</span>
                    <span class="error-message">錯誤: ${error}</span>
                </div>
            `;
        } else {
            // 在現有內容後添加錯誤信息
            const errorDiv = document.createElement('div');
            errorDiv.className = 'ai-error';
            errorDiv.innerHTML = `
                <span class="error-icon">❌</span>
                <span class="error-message">錯誤: ${error}</span>
            `;
            contentArea.appendChild(errorDiv);
        }
        
        this.completeAnalysis();
    }

    finalizeAnalysis() {
        // 清理定時器
        if (this.updateTimer) {
            clearTimeout(this.updateTimer);
            this.updateTimer = null;
        }
        
        // 重置狀態
        this.isAnalyzing = false;
        this.updateUIState('idle');
        
        // 確保移除 loading
        if (this.currentResponseArea) {
            const thinkingDiv = this.currentResponseArea.querySelector('.ai-thinking');
            if (thinkingDiv) {
                thinkingDiv.style.display = 'none';
            }
        }
        
        // 清理
        this.currentResponseArea = null;
        this.accumulatedContent = '';
        this.infoMessages.clear();
    }  

	// 添加方法來追蹤對話上下文
	addToContext(role, content) {
		this.messages.push({
			role: role,
			content: content,
			timestamp: new Date(),
			mode: this.currentMode,
			model: this.currentModel
		});
		
		// 保持最近 10 條對話作為上下文
		if (this.messages.length > 10) {
			this.messages = this.messages.slice(-10);
		}
	}

    async stopAnalysis() {
        if (!this.isAnalyzing) return;
        
        console.log('正在停止分析...');
        
        // 使用強制停止
        this.forceStopAnalysis();
        
        // 發送停止請求到後端
        try {
            const response = await fetch(`/api/ai/stop/${this.sessionId}`, { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (response.ok) {
                console.log('分析已成功停止');
            }
        } catch (error) {
            console.error('停止分析時發生錯誤:', error);
        }
    }
    
    updateUIState(state) {
        const analyzeBtn = document.getElementById('analyzeBtn');
        const stopBtn = document.getElementById('stopAnalysisBtn');
        
        if (state === 'analyzing') {
            analyzeBtn.disabled = true;
            analyzeBtn.classList.add('analyzing');
            stopBtn.style.display = 'inline-flex';
        } else {
            analyzeBtn.disabled = false;
            analyzeBtn.classList.remove('analyzing');
            stopBtn.style.display = 'none';
        }
    }
    
    copyResponse(conversationId) {
        const conversation = document.getElementById(conversationId);
        if (!conversation) return;
        
        // 獲取純文字內容
        const responseTextElement = conversation.querySelector('.ai-response-text, .ai-analysis-content');
        if (!responseTextElement) return;
        
        const responseText = responseTextElement.innerText || responseTextElement.textContent;
        
        navigator.clipboard.writeText(responseText).then(() => {
            // 顯示複製成功提示
            const copyBtn = conversation.querySelector('.copy-btn');
            if (copyBtn) {
                const originalText = copyBtn.innerHTML;
                copyBtn.innerHTML = '✅ 已複製';
                setTimeout(() => {
                    copyBtn.innerHTML = originalText;
                }, 2000);
            }
        }).catch(err => {
            console.error('複製失敗:', err);
            alert('複製失敗，請手動選擇文字複製');
        });
    }
    
    exportConversation(format = 'markdown') {
        // 匯出對話歷史
        let content = '';
        
        switch (format) {
            case 'markdown':
                content = this.exportAsMarkdown();
                break;
            case 'json':
                content = JSON.stringify(this.messages, null, 2);
                break;
            case 'html':
                content = this.exportAsHTML();
                break;
        }
        
        // 下載檔案
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `ai_analysis_${new Date().toISOString().slice(0, 10)}.${format}`;
        link.click();
    }
    
    exportAsMarkdown() {
        let markdown = '# AI 分析對話記錄\n\n';
        markdown += `生成時間: ${new Date().toLocaleString()}\n\n`;
        
        this.messages.forEach((msg, index) => {
            markdown += `## 對話 ${index + 1}\n`;
            markdown += `**時間**: ${msg.timestamp.toLocaleString()}\n`;
            markdown += `**模式**: ${msg.mode} | **模型**: ${msg.model}\n`;
            
            if (msg.role === 'user') {
                markdown += `### 使用者\n${msg.content}\n\n`;
            } else {
                markdown += `### AI 回應\n${msg.content}\n`;
                if (msg.usage) {
                    markdown += `\n**Token 使用**: 輸入 ${msg.usage.input} / 輸出 ${msg.usage.output}\n`;
                    markdown += `**成本**: $${msg.cost.toFixed(4)}\n`;
                }
            }
            markdown += '\n---\n\n';
        });
        
        return markdown;
    }
    
    exportAsHTML() {
        // 實作 HTML 匯出
        let html = `<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI 分析對話記錄</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .conversation { margin-bottom: 30px; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }
        .meta { color: #666; font-size: 14px; }
        .content { margin-top: 10px; white-space: pre-wrap; }
        .ai-response { background: #f5f5f5; padding: 15px; border-radius: 5px; }
    </style>
</head>
<body>
    <h1>AI 分析對話記錄</h1>
    <p>生成時間: ${new Date().toLocaleString()}</p>
`;
        
        this.messages.forEach((msg, index) => {
            html += `
    <div class="conversation">
        <div class="meta">
            <strong>對話 ${index + 1}</strong> | 
            ${msg.timestamp.toLocaleString()} | 
            模式: ${msg.mode} | 
            模型: ${msg.model}
        </div>
        <div class="content ${msg.role === 'assistant' ? 'ai-response' : ''}">
            ${this.escapeHtml(msg.content)}
        </div>
        ${msg.usage ? `
        <div class="meta" style="margin-top: 10px;">
            Token: ${msg.usage.input} / ${msg.usage.output} | 
            成本: $${msg.cost.toFixed(4)}
        </div>
        ` : ''}
    </div>
`;
        });
        
        html += '</body></html>';
        return html;
    }

    handleStreamData(data, responseArea) {
        const contentDiv = responseArea.querySelector('.ai-response-text');
        const thinkingDiv = responseArea.querySelector('.ai-thinking');
        const usageDiv = responseArea.querySelector('.ai-usage-info');
        
        switch (data.type) {
            case 'start':
                thinkingDiv.style.display = 'none';
                this.accumulatedContent = '';
                this.infoMessages.clear();  // 清除追蹤
                // 清空內容區但保留結構
                contentDiv.innerHTML = '<div class="message-area"></div><div class="content-area"></div>';
                break;
                
            case 'info':
            case 'warning':
                // 只添加新的消息
                if (data.message && !this.infoMessages.has(data.message)) {
                    this.infoMessages.add(data.message);
                    this.addInfoMessage(contentDiv, data.type, data.message);
                }
                break;
                
            case 'content':
                // 累積內容並更新顯示
                this.accumulatedContent += data.content;
                this.updateContentDisplay(contentDiv);
                break;
                
            case 'tokens':
                if (data.input) {
                    responseArea.querySelector('.input-tokens').textContent = data.input.toLocaleString();
                }
                if (data.output) {
                    responseArea.querySelector('.output-tokens').textContent = data.output.toLocaleString();
                }
                usageDiv.style.display = 'flex';
                break;
                
            case 'complete':
                this.handleComplete(data, responseArea);
                break;
                
            case 'error':
                this.handleError(data.error, responseArea);
                break;
                
            case 'stopped':
                this.finalizeAnalysis();
                break;
        }
    }

    addInfoMessage(container, type, message) {
        const messageArea = container.querySelector('.message-area');
        if (!messageArea) return;
        
        const msgDiv = document.createElement('div');
        msgDiv.className = `ai-${type}-message`;
        // 確保圖標和文字在同一行
        msgDiv.innerHTML = `<span class="${type}-icon">${type === 'info' ? 'ℹ️' : '⚠️'}</span> <span class="${type}-text">${message}</span>`;
        messageArea.appendChild(msgDiv);
    }

    displayMessage(container, type, message) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `ai-${type}-message`;
        // 確保圖標和文字在同一行
        msgDiv.innerHTML = `<span class="${type}-icon">${type === 'info' ? 'ℹ️' : '⚠️'}</span> <span class="${type}-text">${message}</span>`;
        container.appendChild(msgDiv);
    }

    updateContentDisplay(container) {
        // 使用防抖動更新
        if (this.updateTimer) {
            clearTimeout(this.updateTimer);
        }
        
        this.updateTimer = setTimeout(() => {
            const contentArea = container.querySelector('.content-area');
            if (!contentArea) return;
            
            // 只更新內容區域，不影響消息區域
            const formatted = this.formatContentChatGPTStyle(this.accumulatedContent);
            contentArea.innerHTML = formatted;
            
            // 保持滾動在底部
            this.scrollToBottom();
        }, 100);  // 100ms 防抖
    }

    displayFormattedContent(container) {
        // 使用 requestAnimationFrame 避免頻繁更新
        if (this.updateTimer) {
            cancelAnimationFrame(this.updateTimer);
        }
        
        this.updateTimer = requestAnimationFrame(() => {
            // 清空並重新渲染（ChatGPT 風格）
            const existingMessages = container.querySelectorAll('.ai-info-message, .ai-warning-message');
            const messages = Array.from(existingMessages).map(el => ({
                type: el.className.includes('info') ? 'info' : 'warning',
                content: el.textContent
            }));
            
            container.innerHTML = '';
            
            // 重新添加信息消息
            messages.forEach(msg => {
                this.displayMessage(container, msg.type, msg.content);
            });
            
            // 格式化並顯示主要內容
            const formatted = this.formatContentChatGPTStyle(this.accumulatedContent);
            const contentWrapper = document.createElement('div');
            contentWrapper.className = 'chatgpt-style-content';
            contentWrapper.innerHTML = formatted;
            container.appendChild(contentWrapper);
            
            // 保持滾動在底部
            this.scrollToBottom();
        });
    }

    formatContentChatGPTStyle(text) {
        if (!text) return '';
        
        let html = '<div class="chatgpt-content">';
        
        // 智能分段：保留空行、標題前後的換行
        const lines = text.split('\n');
        let currentParagraph = [];
        let inCodeBlock = false;
        let codeBlockContent = [];
        let codeBlockLang = '';
        
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            
            // 處理代碼塊
            if (line.startsWith('```')) {
                if (!inCodeBlock) {
                    // 開始代碼塊
                    if (currentParagraph.length > 0) {
                        html += this.processParagraph(currentParagraph.join('\n'));
                        currentParagraph = [];
                    }
                    inCodeBlock = true;
                    codeBlockLang = line.slice(3).trim();
                    codeBlockContent = [];
                } else {
                    // 結束代碼塊
                    html += `<pre class="gpt-code-block"><code class="language-${codeBlockLang}">${this.escapeHtml(codeBlockContent.join('\n'))}</code></pre>`;
                    inCodeBlock = false;
                    codeBlockContent = [];
                }
                continue;
            }
            
            if (inCodeBlock) {
                codeBlockContent.push(line);
                continue;
            }
            
            // 檢查是否是標題
            if (line.match(/^#{1,6}\s/)) {
                // 先處理之前的段落
                if (currentParagraph.length > 0) {
                    html += this.processParagraph(currentParagraph.join('\n'));
                    currentParagraph = [];
                }
                // 處理標題
                const level = line.match(/^(#{1,6})/)[1].length;
                const title = line.replace(/^#{1,6}\s+/, '');
                html += `<h${level} class="gpt-h${level}">${this.formatInline(title)}</h${level}>`;
                continue;
            }
            
            // 空行表示段落結束
            if (line.trim() === '') {
                if (currentParagraph.length > 0) {
                    html += this.processParagraph(currentParagraph.join('\n'));
                    currentParagraph = [];
                }
                continue;
            }
            
            // 添加到當前段落
            currentParagraph.push(line);
        }
        
        // 處理最後的段落
        if (currentParagraph.length > 0) {
            html += this.processParagraph(currentParagraph.join('\n'));
        }
        
        html += '</div>';
        return html;
    }

    processParagraph(text) {
        if (!text.trim()) return '';
        
        // 檢查是否是列表
        const lines = text.split('\n').filter(line => line.trim());
        
        // 編號列表
        if (lines.every(line => line.match(/^\d+\.\s/))) {
            let html = '<ol class="gpt-numbered-list">';
            lines.forEach(line => {
                const content = line.replace(/^\d+\.\s+/, '');
                html += `<li class="gpt-list-item">${this.formatInline(content)}</li>`;
            });
            html += '</ol>';
            return html;
        }
        
        // 無序列表
        if (lines.every(line => line.match(/^[-*]\s/))) {
            let html = '<ul class="gpt-bullet-list">';
            lines.forEach(line => {
                const content = line.replace(/^[-*]\s+/, '');
                html += `<li class="gpt-list-item">${this.formatInline(content)}</li>`;
            });
            html += '</ul>';
            return html;
        }
        
        // 普通段落
        return `<p class="gpt-paragraph">${this.formatInline(text)}</p>`;
    }

    renderElement(container, element) {
        const div = document.createElement('div');
        
        switch (element.type) {
            case 'heading':
                const level = element.content.match(/^(#{1,6})/)[1].length;
                div.innerHTML = `<h${level} class="ai-h${level}">${
                    element.content.replace(/^#{1,6}\s+/, '')
                }</h${level}>`;
                break;
                
            case 'list-item':
                div.innerHTML = `<div class="ai-numbered-item">${
                    this.formatInlineMarkdown(element.content)
                }</div>`;
                break;
                
            case 'paragraph':
            case 'text':
                div.innerHTML = `<p class="ai-paragraph">${
                    this.formatInlineMarkdown(element.content)
                }</p>`;
                break;
        }
        
        container.appendChild(div.firstChild);
        
        // 保持滾動
        const chatArea = document.getElementById('aiChatArea');
        if (chatArea) {
            chatArea.scrollTop = chatArea.scrollHeight;
        }
    }

    formatInline(text) {
        // 轉義 HTML
        text = this.escapeHtml(text);
        
        // 處理格式
        return text
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code class="gpt-inline-code">$1</code>');
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    formatInlineMarkdown(text) {
        return text
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code class="ai-inline-code">$1</code>');
    }
    
    scrollToBottom() {
        const chatArea = document.getElementById('aiChatArea');
        if (chatArea) {
            chatArea.scrollTop = chatArea.scrollHeight;
        }
    }  

    async executeAnalysis(mode) {
        // 防止重複分析
        if (this.isAnalyzing) return;
        
        // 設置當前模式
        this.currentMode = mode;
        
        // 獲取按鈕
        const btn = document.querySelector(`.ai-mode-btn[data-mode="${mode}"]`);
        if (!btn) return;
        
        // 標記所有按鈕為分析中
        document.querySelectorAll('.ai-mode-btn').forEach(b => {
            b.disabled = true;
            b.classList.add('disabled');
        });
        
        // 保存原始內容
        const originalContent = btn.innerHTML;
        
        // 顯示 loading 狀態
        btn.classList.add('analyzing');
        btn.innerHTML = `
            <div class="ai-spinner"></div>
            <span class="mode-name">分析中...</span>
        `;
        
        // 添加停止按鈕
        const stopBtn = document.createElement('button');
        stopBtn.className = 'analyze-stop-btn';
        stopBtn.id = 'stopAnalysisBtn';
        stopBtn.innerHTML = '⏹️ 停止';
        stopBtn.onclick = () => this.stopAnalysis();
        btn.parentElement.appendChild(stopBtn);
        
        try {
            await this.startAnalysis();
        } finally {
            // 恢復按鈕狀態
            btn.innerHTML = originalContent;
            btn.classList.remove('analyzing');
            
            // 恢復所有按鈕
            document.querySelectorAll('.ai-mode-btn').forEach(b => {
                b.disabled = false;
                b.classList.remove('disabled');
            });
            
            // 移除停止按鈕
            const stopButton = document.getElementById('stopAnalysisBtn');
            if (stopButton) {
                stopButton.remove();
            }
        }
    }
    
    exportSingleResponse(conversationId, format) {
        const conversation = document.getElementById(conversationId);
        if (!conversation) return;
        
        const responseElement = conversation.querySelector('.ai-response-text, .ai-analysis-content');
        const timeElement = conversation.querySelector('.timestamp');
        const modeElement = conversation.querySelector('.mode-text');
        
        if (!responseElement) return;
        
        const content = responseElement.innerHTML;
        const timestamp = timeElement ? timeElement.textContent : new Date().toLocaleTimeString();
        const mode = modeElement ? modeElement.textContent : '分析';
        
        let exportContent = '';
        let filename = `AI_${mode}_${timestamp.replace(/:/g, '-')}.${format === 'html' ? 'html' : 'md'}`;
        
        if (format === 'html') {
            exportContent = this.generateSingleHTML(content, mode, timestamp);
        } else if (format === 'markdown') {
            exportContent = this.generateSingleMarkdown(responseElement, mode, timestamp);
        }
        
        // 下載檔案
        const blob = new Blob([exportContent], { type: 'text/plain;charset=utf-8' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        link.click();
        URL.revokeObjectURL(link.href);
    }
    
    generateSingleHTML(content, mode, timestamp) {
        return `<!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <title>AI ${mode} - ${timestamp}</title>
        <style>
            body { 
                font-family: -apple-system, sans-serif; 
                max-width: 800px; 
                margin: 0 auto; 
                padding: 20px;
                background: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .header {
                border-bottom: 2px solid #667eea;
                padding-bottom: 15px;
                margin-bottom: 20px;
            }
            .content { line-height: 1.8; }
            code { 
                background: #f0f0f0; 
                padding: 2px 6px; 
                border-radius: 3px;
                font-family: monospace;
            }
            pre {
                background: #f5f5f5;
                padding: 15px;
                border-radius: 5px;
                overflow-x: auto;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>AI ${mode}結果</h1>
                <p>時間：${timestamp}</p>
                <p>檔案：${window.fileName || 'Unknown'}</p>
            </div>
            <div class="content">
                ${content}
            </div>
        </div>
    </body>
    </html>`;
    }
    
    generateSingleMarkdown(element, mode, timestamp) {
        const textContent = element.innerText || element.textContent;
        return `# AI ${mode}結果\n\n**時間：** ${timestamp}\n**檔案：** ${window.fileName || 'Unknown'}\n\n---\n\n${textContent}`;
    }
    
}

// 更優雅的方案：增量解析和更新
class StreamingMarkdownParser {
    constructor() {
        this.buffer = '';
        this.parsedContent = [];
        this.lastCompleteIndex = 0;
    }
    
    // 添加新內容並返回可以安全渲染的部分
    addContent(newContent) {
        this.buffer += newContent;
        return this.parseIncrementally();
    }
    
    parseIncrementally() {
        const updates = [];
        let currentIndex = this.lastCompleteIndex;
        
        // 尋找可以安全解析的完整單元
        while (currentIndex < this.buffer.length) {
            const remaining = this.buffer.substring(currentIndex);
            
            // 檢查各種 Markdown 元素
            const element = this.findNextCompleteElement(remaining, currentIndex);
            
            if (element) {
                updates.push(element);
                currentIndex = element.endIndex;
                this.lastCompleteIndex = currentIndex;
            } else {
                // 沒有找到完整元素，等待更多內容
                break;
            }
        }
        
        return updates;
    }
    
    findNextCompleteElement(text, globalIndex) {
        // 匹配完整的段落（以雙換行結束）
        const paragraphMatch = text.match(/^([^\n]+)\n\n/);
        if (paragraphMatch) {
            return {
                type: 'paragraph',
                content: paragraphMatch[1],
                endIndex: globalIndex + paragraphMatch[0].length
            };
        }
        
        // 匹配完整的列表項
        const listMatch = text.match(/^(\d+\.\s+[^\n]+)\n/);
        if (listMatch) {
            return {
                type: 'list-item',
                content: listMatch[1],
                endIndex: globalIndex + listMatch[0].length
            };
        }
        
        // 匹配完整的標題
        const headingMatch = text.match(/^(#{1,6}\s+[^\n]+)\n/);
        if (headingMatch) {
            return {
                type: 'heading',
                content: headingMatch[1],
                endIndex: globalIndex + headingMatch[0].length
            };
        }
        
        // 如果文本結束了，返回剩餘內容
        if (text.length > 0 && !text.includes('\n')) {
            // 檢查是否可能是未完成的 Markdown
            if (this.mightBeIncomplete(text)) {
                return null;
            }
            
            return {
                type: 'text',
                content: text,
                endIndex: globalIndex + text.length
            };
        }
        
        return null;
    }
    
    mightBeIncomplete(text) {
        // 可能是未完成的粗體、代碼等
        return text.endsWith('*') || 
               text.endsWith('`') || 
               text.endsWith('#') ||
               text.match(/\d+\.\s*$/);
    }
}

// ======================================================================
// 初始化 AI 分析器
// ======================================================================

let aiAnalyzer;

document.addEventListener('DOMContentLoaded', function() {
    // 只在檢視檔案頁面初始化
    if (document.getElementById('analyzeBtn')) {
        aiAnalyzer = new AIAnalyzer();
        
        // 覆蓋原有的分析按鈕事件
        const analyzeBtn = document.getElementById('analyzeBtn');
        analyzeBtn.onclick = function(e) {
            e.preventDefault();
            aiAnalyzer.startAnalysis();
        };
    }

    // 綁定 Provider 選擇器變更事件
    const providerSelect = document.getElementById('providerSelectInline');
    if (providerSelect) {
        providerSelect.addEventListener('change', function(e) {
            const provider = e.target.value;
            
            // 根據選擇的 Provider 切換預設模型
            if (provider === 'anthropic') {
                selectedModel = 'claude-sonnet-4-20250514';
                document.getElementById('selectedModelNameInline').textContent = 'Claude 4 Sonnet';
            } else if (provider === 'openai') {
                selectedModel = 'gpt-4-turbo-preview';
                document.getElementById('selectedModelNameInline').textContent = 'GPT-4 Turbo';
            } else if (provider === 'realtek') {
                selectedModel = 'chat-codetek-qwen';
                document.getElementById('selectedModelNameInline').textContent = 'Codetek Qwen';
            }
            
            // 如果 aiAnalyzer 存在，也更新它
            if (window.aiAnalyzer) {
                window.aiAnalyzer.currentProvider = provider;
                window.aiAnalyzer.currentModel = selectedModel;
            }
            
            // 更新模型彈窗內容
            updateModelPopupForProvider(provider);
        });
    } 
});

// 導出全域函數供 HTML 使用
//window.aiAnalyzer = aiAnalyzer;

// 創建全局實例並掛載到 window
window.aiRequestManager = new AIRequestManager();