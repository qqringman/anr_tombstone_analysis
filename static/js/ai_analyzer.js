// AI 分析器的前端邏輯
class AIAnalyzer {
    constructor() {
        this.sessionId = this.generateSessionId();
        this.currentProvider = 'anthropic';
        this.currentModel = 'claude-sonnet-4-20250514';
        this.isAnalyzing = false;
        this.eventSource = null;
        this.currentMode = 'smart';
        this.messages = [];
        this.markdownParser = null;
        this.currentResponseArea = null;  // 追蹤當前的回應區域
        this.accumulatedContent = '';     // 累積完整內容
        this.infoMessages = new Set();  // 追蹤已顯示的信息消息        
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
        modelGrid.innerHTML = models.map(model => `
            <div class="model-card" data-model="${model.id}" onclick="aiAnalyzer.selectModel('${model.id}')">
                <div class="model-card-name">${model.name}</div>
                <div class="model-card-desc">${model.description}</div>
                <div class="model-pricing">
                    輸入: $${model.pricing.input}/1K tokens | 
                    輸出: $${model.pricing.output}/1K tokens
                </div>
            </div>
        `).join('');
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
        if (!text) return '';
        
        let html = '';
        const lines = text.split('\n');
        let i = 0;
        
        while (i < lines.length) {
            const line = lines[i];
            
            // 1. 檢查代碼塊開始
            if (line.trim().startsWith('```')) {
                const lang = line.trim().slice(3).trim();
                let codeLines = [];
                i++; // 跳過開始標記
                
                // 收集代碼內容直到找到結束標記
                while (i < lines.length && !lines[i].trim().startsWith('```')) {
                    codeLines.push(lines[i]);
                    i++;
                }
                
                if (i < lines.length) { // 找到結束標記
                    html += `<pre class="gpt-code-block"><code class="language-${lang || 'text'}">${this.escapeHtml(codeLines.join('\n'))}</code></pre>\n`;
                    i++; // 跳過結束標記
                }
                continue;
            }
            
            // 2. 檢查標題 (####, ###, ##, #)
            const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
            if (headingMatch) {
                const level = headingMatch[1].length;
                const content = this.processInlineElements(headingMatch[2]);
                html += `<h${level} class="gpt-h${level}">${content}</h${level}>\n`;
                i++;
                continue;
            }
            
            // 3. 檢查編號列表
            const orderedMatch = line.match(/^(\d+)\.\s+(.+)$/);
            if (orderedMatch) {
                let listItems = [];
                
                // 收集所有連續的編號列表項
                while (i < lines.length) {
                    const currentLine = lines[i];
                    const match = currentLine.match(/^(\d+)\.\s+(.+)$/);
                    if (match) {
                        listItems.push(this.processInlineElements(match[2]));
                        i++;
                    } else if (currentLine.trim() === '') {
                        i++;
                        break; // 空行結束列表
                    } else {
                        break; // 非列表項結束列表
                    }
                }
                
                if (listItems.length > 0) {
                    html += '<ol class="gpt-numbered-list">\n';
                    listItems.forEach(item => {
                        html += `  <li class="gpt-list-item">${item}</li>\n`;
                    });
                    html += '</ol>\n';
                }
                continue;
            }
            
            // 4. 檢查無序列表 (•, -, *)
            const bulletMatch = line.match(/^[•\-\*]\s+(.+)$/);
            if (bulletMatch) {
                let listItems = [];
                
                // 收集所有連續的無序列表項
                while (i < lines.length) {
                    const currentLine = lines[i];
                    const match = currentLine.match(/^[•\-\*]\s+(.+)$/);
                    if (match) {
                        listItems.push(this.processInlineElements(match[1]));
                        i++;
                    } else if (currentLine.trim() === '') {
                        i++;
                        break; // 空行結束列表
                    } else {
                        break; // 非列表項結束列表
                    }
                }
                
                if (listItems.length > 0) {
                    html += '<ul class="gpt-bullet-list">\n';
                    listItems.forEach(item => {
                        html += `  <li class="gpt-list-item">${item}</li>\n`;
                    });
                    html += '</ul>\n';
                }
                continue;
            }
            
            // 5. 檢查是否是空行
            if (line.trim() === '') {
                i++;
                continue; // 跳過空行
            }
            
            // 6. 處理普通段落
            let paragraphLines = [];
            
            // 收集連續的非特殊格式行作為一個段落
            while (i < lines.length) {
                const currentLine = lines[i];
                
                // 如果是空行，段落結束
                if (currentLine.trim() === '') {
                    break;
                }
                
                // 如果是特殊格式（標題、列表、代碼塊），段落結束
                if (currentLine.match(/^#{1,6}\s+/) || 
                    currentLine.match(/^\d+\.\s+/) || 
                    currentLine.match(/^[•\-\*]\s+/) ||
                    currentLine.trim().startsWith('```')) {
                    break;
                }
                
                paragraphLines.push(currentLine);
                i++;
            }
            
            if (paragraphLines.length > 0) {
                const paragraphText = paragraphLines.join(' ').trim();
                if (paragraphText) {
                    html += `<p class="gpt-paragraph">${this.processInlineElements(paragraphText)}</p>\n`;
                }
            }
        }
        
        return `<div class="gpt-content">${html}</div>`;
    }
    
    // 處理行內元素（粗體、斜體、行內代碼等）
    processInlineElements(text) {
        if (!text) return '';
        
        // 先轉義 HTML
        text = this.escapeHtml(text);
        
        // 處理行內代碼（優先處理，避免內部的特殊字符被處理）
        text = text.replace(/`([^`]+)`/g, (match, code) => {
            return `<code class="gpt-inline-code">${code}</code>`;
        });
        
        // 處理粗體（**text**）
        text = text.replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>');
        
        // 處理斜體（*text*）- 注意不要和粗體衝突
        text = text.replace(/(?<!\*)\*([^\*]+)\*(?!\*)/g, '<em>$1</em>');
        
        // 處理鏈接 [text](url)
        text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
        
        return text;
    }
    
    // 新增輔助函數：格式化行內元素
    formatInlineElements(text) {
        if (!text) return '';
        
        // 先轉義 HTML
        text = this.escapeHtml(text);
        
        // 處理行內代碼（先處理，避免被其他規則影響）
        text = text.replace(/`([^`]+)`/g, '<code class="gpt-inline-code">$1</code>');
        
        // 處理粗體
        text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        
        // 處理斜體
        text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        
        // 處理鏈接
        text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
        
        return text;
    }
    
    // 新增輔助函數：創建列表
    createList(type, items) {
        if (items.length === 0) return '';
        
        const tag = type === 'ol' ? 'ol' : 'ul';
        const className = type === 'ol' ? 'gpt-numbered-list' : 'gpt-bullet-list';
        
        let html = `<${tag} class="${className}">`;
        items.forEach(item => {
            html += `<li class="gpt-list-item">${item}</li>`;
        });
        html += `</${tag}>`;
        
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
                this.infoMessages.clear();
                // 如果是重試，顯示提示
                if (data.retry_count > 0) {
                    contentDiv.innerHTML = `
                        <div class="ai-info-message">
                            <span class="info-icon">🔄</span> 
                            正在重試 (第 ${data.retry_count} 次)
                        </div>
                    `;
                } else {
                    contentDiv.innerHTML = '<div class="message-area"></div><div class="content-area"></div>';
                }
                break;
            case 'rate_limit_info':
                // 更新速率限制顯示
                this.updateRateLimitDisplay(data.usage);
                break;
            case 'rate_limit_wait':
                // 顯示速率限制等待
                this.showRateLimitWait(data, contentDiv);
                break;
            case 'retry':
                // 顯示重試信息
                if (!contentDiv.querySelector('.retry-notice')) {
                    const retryDiv = document.createElement('div');
                    retryDiv.className = 'retry-notice';
                    retryDiv.innerHTML = `
                        <div class="ai-warning-message">
                            <span class="warning-icon">⚠️</span>
                            ${data.message}
                            <div class="retry-progress">
                                <div class="retry-countdown" id="retry-countdown">${data.delay}</div>
                                <div class="retry-info">重試 ${data.retry_count}/${data.max_retries}</div>
                            </div>
                        </div>
                    `;
                    contentDiv.appendChild(retryDiv);
                    
                    // 倒計時
                    let countdown = data.delay;
                    const countdownInterval = setInterval(() => {
                        countdown--;
                        const countdownEl = document.getElementById('retry-countdown');
                        if (countdownEl) {
                            countdownEl.textContent = countdown;
                        }
                        if (countdown <= 0) {
                            clearInterval(countdownInterval);
                            // 移除重試通知
                            const retryNotice = contentDiv.querySelector('.retry-notice');
                            if (retryNotice) {
                                retryNotice.remove();
                            }
                        }
                    }, 1000);
                }
                break;
                
            case 'info':
            case 'warning':
                if (data.message && !this.infoMessages.has(data.message)) {
                    this.infoMessages.add(data.message);
                    this.addInfoMessage(contentDiv, data.type, data.message);
                }
                break;
                
            case 'content':
                // 移除任何重試通知
                const retryNotice = contentDiv.querySelector('.retry-notice');
                if (retryNotice) {
                    retryNotice.remove();
                }
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

    updateRateLimitDisplay(usage) {
        // 可以在 UI 中顯示當前使用情況
        console.log('速率限制狀態:', usage);
        
        // 如果接近限制，顯示警告
        if (usage.tpm_current / usage.tpm_limit > 0.8) {
            this.showRateLimitWarning();
        }
    }

    showRateLimitWarning() {
        // 在 UI 某處顯示速率限制警告
        const warning = document.createElement('div');
        warning.className = 'rate-limit-warning';
        warning.innerHTML = `
            <div class="ai-warning-message">
                <span class="warning-icon">⚠️</span>
                接近速率限制，請減少請求頻率
            </div>
        `;
        
        // 添加到合適的位置
        const chatArea = document.getElementById('aiChatArea');
        if (chatArea && !chatArea.querySelector('.rate-limit-warning')) {
            chatArea.insertBefore(warning, chatArea.firstChild);
            
            // 5秒後自動移除
            setTimeout(() => warning.remove(), 5000);
        }
    }
        
    showRateLimitWait(data, container) {
        const waitDiv = document.createElement('div');
        waitDiv.className = 'rate-limit-wait';
        waitDiv.innerHTML = `
            <div class="ai-warning-message">
                <span class="warning-icon">⏱️</span>
                <div>
                    <div>達到速率限制：${data.reason}</div>
                    <div>等待 ${Math.ceil(data.wait_time)} 秒後自動重試...</div>
                    <div class="wait-countdown" id="wait-countdown">${Math.ceil(data.wait_time)}</div>
                </div>
            </div>
        `;
        container.appendChild(waitDiv);
        
        // 倒計時
        let remaining = Math.ceil(data.wait_time);
        const interval = setInterval(() => {
            remaining--;
            const countdown = document.getElementById('wait-countdown');
            if (countdown) {
                countdown.textContent = remaining;
            }
            if (remaining <= 0) {
                clearInterval(interval);
                waitDiv.remove();
            }
        }, 1000);
    }

    addInfoMessage(container, type, message) {
        const messageArea = container.querySelector('.message-area');
        if (!messageArea) return;
        
        const msgDiv = document.createElement('div');
        msgDiv.className = `ai-${type}-message`;
        msgDiv.innerHTML = `<span class="${type}-icon">${type === 'info' ? 'ℹ️' : '⚠️'}</span> ${message}`;
        messageArea.appendChild(msgDiv);
    }

    displayMessage(container, type, message) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `ai-${type}-message`;
        msgDiv.innerHTML = `<span class="${type}-icon">${type === 'info' ? 'ℹ️' : '⚠️'}</span> ${message}`;
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
        return this.formatMarkdown(text);
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
});

// 導出全域函數供 HTML 使用
window.aiAnalyzer = aiAnalyzer;