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
                <button class="ai-mode-btn smart active" data-mode="smart">
                    <span class="mode-icon">🧠</span>
                    <span class="mode-name">智能分析</span>
                    <span class="mode-desc">自動選擇最佳策略</span>
                </button>
                <button class="ai-mode-btn quick" data-mode="quick">
                    <span class="mode-icon">⚡</span>
                    <span class="mode-name">快速分析</span>
                    <span class="mode-desc">30秒內獲得結果</span>
                </button>
                <button class="ai-mode-btn deep" data-mode="deep">
                    <span class="mode-icon">🔍</span>
                    <span class="mode-name">深度分析</span>
                    <span class="mode-desc">詳細深入的診斷</span>
                </button>
            </div>
        `;
        
        // 插入到分析按鈕之前
        const analyzeSection = document.querySelector('.analyze-file-section');
        if (analyzeSection) {
            analyzeSection.insertAdjacentHTML('afterbegin', modeButtons);
        }
        
        // 綁定點擊事件
        document.querySelectorAll('.ai-mode-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.selectMode(e.currentTarget.dataset.mode);
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
		
		// 使用當前檢視的檔案內容（從 view_file.js 中的全域變數）
		const fileContent = window.fileContent || window.escaped_content;
		const fileName = window.fileName || window.escaped_filename;
		const filePath = window.filePath || window.escaped_file_path;
		
		if (!fileContent) {
			alert('沒有檔案內容可分析');
			return;
		}
		
		// 顯示檔案資訊
		console.log('準備分析檔案:', fileName);
		console.log('檔案大小:', fileContent.length, '字元');
		
		this.isAnalyzing = true;
		this.updateUIState('analyzing');
		
		// 創建新的回應區域
		const responseArea = this.createResponseArea();
		
		try {
			// 準備請求資料
			const requestData = {
				session_id: this.sessionId,
				provider: this.currentProvider,
				model: this.currentModel,
				mode: this.currentMode,
				file_path: filePath,
				file_name: fileName,
				content: fileContent,  // 使用完整的檔案內容
				stream: true,
				// 包含之前的對話上下文
				context: this.messages.slice(-5).map(msg => ({
					role: msg.role,
					content: msg.content.substring(0, 500)  // 限制長度
				}))
			};
			
			// 發送分析請求（使用 fetch + SSE）
			const response = await fetch('/api/ai/analyze', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(requestData)
			});
			
			if (!response.ok) {
				throw new Error(`HTTP error! status: ${response.status}`);
			}
			
			// 讀取流式回應
			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			
			while (true) {
				const { value, done } = await reader.read();
				if (done) break;
				
				// 檢查是否被中斷
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
		} finally {
			this.stopAnalysis();
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
    
    handleStreamData(data, responseArea) {
		const contentDiv = responseArea.querySelector('.ai-response-text');
		const thinkingDiv = responseArea.querySelector('.ai-thinking');
		const usageDiv = responseArea.querySelector('.ai-usage-info');
		
		switch (data.type) {
			case 'start':
				// 隱藏思考動畫，開始顯示內容
				thinkingDiv.style.display = 'none';
				break;
				
			case 'info':
				// 顯示信息訊息
				if (data.message) {
					const infoDiv = document.createElement('div');
					infoDiv.className = 'ai-info-message';
					infoDiv.innerHTML = `<span class="info-icon">ℹ️</span> ${data.message}`;
					contentDiv.appendChild(infoDiv);
				}
				break;
				
			case 'warning':
				// 顯示警告訊息
				if (data.message) {
					const warningDiv = document.createElement('div');
					warningDiv.className = 'ai-warning-message';
					warningDiv.innerHTML = `<span class="warning-icon">⚠️</span> ${data.message}`;
					contentDiv.appendChild(warningDiv);
				}
				break;
				
			case 'content':
				// 追加內容並格式化
				this.appendFormattedContent(contentDiv, data.content);
				break;
				
			case 'tokens':
				// 更新 token 統計
				if (data.input) {
					responseArea.querySelector('.input-tokens').textContent = data.input.toLocaleString();
				}
				if (data.output) {
					responseArea.querySelector('.output-tokens').textContent = data.output.toLocaleString();
				}
				usageDiv.style.display = 'flex';
				break;
				
			case 'complete':
				// 分析完成
				this.handleComplete(data, responseArea);
				break;
				
			case 'error':
				// 顯示錯誤
				this.handleError(data.error, responseArea);
				break;
				
			case 'stopped':
				// 分析被停止
				this.appendFormattedContent(contentDiv, '\n\n[分析已停止]');
				this.stopAnalysis();
				break;
		}
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
        // 基本的 Markdown 格式化
        let formatted = text;
        
        // 標題
        formatted = formatted.replace(/^### (.+)$/gm, '<h3 class="ai-h3">$1</h3>');
        formatted = formatted.replace(/^## (.+)$/gm, '<h2 class="ai-h2">$1</h2>');
        formatted = formatted.replace(/^# (.+)$/gm, '<h1 class="ai-h1">$1</h1>');
        
        // 粗體和斜體
        formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        formatted = formatted.replace(/\*(.+?)\*/g, '<em>$1</em>');
        
        // 代碼
        formatted = formatted.replace(/`([^`]+)`/g, '<code class="ai-inline-code">$1</code>');
        
        // 代碼塊
        formatted = formatted.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
            return `<pre class="ai-code-block"><code class="language-${lang}">${this.escapeHtml(code)}</code></pre>`;
        });
        
        // 列表
        formatted = formatted.replace(/^\d+\. (.+)$/gm, '<li class="ai-ordered-item">$1</li>');
        formatted = formatted.replace(/^- (.+)$/gm, '<li class="ai-unordered-item">$1</li>');
        
        // 將連續的列表項包裝
        formatted = formatted.replace(/(<li class="ai-ordered-item">.*<\/li>\s*)+/g, '<ol class="ai-ordered-list">$&</ol>');
        formatted = formatted.replace(/(<li class="ai-unordered-item">.*<\/li>\s*)+/g, '<ul class="ai-unordered-list">$&</ul>');
        
        // 段落
        formatted = formatted.replace(/\n\n/g, '</p><p class="ai-paragraph">');
        formatted = '<p class="ai-paragraph">' + formatted + '</p>';
        
        return formatted;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    handleComplete(data, responseArea) {
        // 更新最終統計
        responseArea.querySelector('.input-tokens').textContent = data.usage.input;
        responseArea.querySelector('.output-tokens').textContent = data.usage.output;
        responseArea.querySelector('.total-cost').textContent = data.cost.toFixed(4);
        
        // 添加到訊息歷史
        this.messages.push({
            role: 'assistant',
            content: responseArea.querySelector('.ai-response-text').innerText,
            timestamp: new Date(),
            mode: this.currentMode,
            model: this.currentModel,
            usage: data.usage,
            cost: data.cost
        });
        
        // 重置狀態
        this.stopAnalysis();
    }
    
    handleError(error, responseArea) {
        const contentDiv = responseArea.querySelector('.ai-response-text');
        const thinkingDiv = responseArea.querySelector('.ai-thinking');
        
        thinkingDiv.style.display = 'none';
        contentDiv.innerHTML = `
            <div class="ai-error">
                <span class="error-icon">❌</span>
                <span class="error-message">錯誤: ${error}</span>
            </div>
        `;
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
		
		// 立即更新 UI
		this.isAnalyzing = false;
		this.updateUIState('idle');
		
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
        
        const responseText = conversation.querySelector('.ai-response-text').innerText;
        
        navigator.clipboard.writeText(responseText).then(() => {
            // 顯示複製成功提示
            const copyBtn = conversation.querySelector('.copy-btn');
            const originalText = copyBtn.textContent;
            copyBtn.textContent = '✅ 已複製';
            setTimeout(() => {
                copyBtn.textContent = originalText;
            }, 2000);
        }).catch(err => {
            console.error('複製失敗:', err);
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