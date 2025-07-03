// Initialize with file data
const fileContent = String(window.escaped_content || '');
const fileName = String(window.escaped_filename || '');
const filePath = String(window.escaped_file_path || '');

// Global variables
let lines = [];
let highlightedKeywords = {};
let bookmarks = new Set();
let selectedText = '';
let currentLine = 1;
let bookmarkCurrentLine = -1;
let searchResults = [];
let currentSearchIndex = -1;
let searchRegex = null;
let isStaticPage = false;
let currentSearchState = null;  // Store current search highlights
// 優化的搜尋實現
let searchDebounceTimer = null;
let isSearching = false;
let visibleRange = { start: 0, end: 100 }; // 追蹤可見範圍
let hoveredLine = null; // 追蹤滑鼠懸停的行號
let aiAnalyzer = null;

// Search optimization variables
const SEARCH_DELAY = 500; // 500ms 延遲
const MIN_SEARCH_LENGTH = 2; // 最少輸入 2 個字元才搜尋

// AI Panel State
let isAIPanelOpen = false;
let selectedModel = 'claude-sonnet-4-20250514';
let conversationHistory = [];
let isAnalyzing = false;  // 防止重複請求
let useSmartAnalysis = true;  // 啟用智能分析

// 添加這個缺失的變數
let isAskingQuestion = false;  // 防止重複發送問題

// 全屏功能
let isAIFullscreen = false;

// 新增：分析模式配置
const ANALYSIS_MODES = {
    'auto': {
        name: '智能分析',
        description: '自動選擇最佳策略',
        icon: '🤖',
        badge: '推薦',
        badgeClass: 'recommended',
        buttonText: '開始智能分析',
        buttonColor: 'linear-gradient(135deg, #667eea, #764ba2)'
    },
    'quick': {
        name: '快速分析',
        description: '30秒內獲得結果',
        icon: '⚡',
        badge: '最快',
        badgeClass: '',
        buttonText: '快速分析 (30秒)',
        buttonColor: 'linear-gradient(135deg, #ffd700, #ffed4b)'
    },
    'comprehensive': {
        name: '深度分析',
        description: '全面深入的診斷',
        icon: '🔍',
        badge: '最詳細',
        badgeClass: '',
        buttonText: '深度分析 (2-5分鐘)',
        buttonColor: 'linear-gradient(135deg, #4ec9b0, #45d3b8)'
    }
};

// 當前選中的分析模式
let selectedAnalysisMode = 'auto';

function toggleAIFullscreen() {
    const rightPanel = document.getElementById('rightPanel');
    const fullscreenIcon = document.getElementById('fullscreenIcon');
    const mainContainer = document.querySelector('.main-container');
    // 添加 modelPopup 到要移動的彈窗列表
    const modals = document.querySelectorAll('.ai-info-modal, .export-modal, .segmented-analysis-dialog, #modelPopup');

    isAIFullscreen = !isAIFullscreen;

    if (isAIFullscreen) {
        rightPanel.classList.add('fullscreen-mode');
        mainContainer.classList.add('ai-fullscreen');
        fullscreenIcon.textContent = '⛶';

        // 將彈窗掛入 rightPanel（包括 modelPopup）
        modals.forEach(modal => {
            if (modal) rightPanel.appendChild(modal);
        });

        // 使用原生全螢幕 API
        if (rightPanel.requestFullscreen) {
            rightPanel.requestFullscreen();
        } else if (rightPanel.webkitRequestFullscreen) {
            rightPanel.webkitRequestFullscreen();
        } else if (rightPanel.msRequestFullscreen) {
            rightPanel.msRequestFullscreen();
        }
    } else {
        rightPanel.classList.remove('fullscreen-mode');
        mainContainer.classList.remove('ai-fullscreen');
        fullscreenIcon.textContent = '⛶';

        // 將彈窗移回 body
        modals.forEach(modal => {
            if (modal) document.body.appendChild(modal);
        });

        // 退出原生全螢幕
        if (document.exitFullscreen) {
            document.exitFullscreen();
        } else if (document.webkitExitFullscreen) {
            document.webkitExitFullscreen();
        } else if (document.msExitFullscreen) {
            document.msExitFullscreen();
        }
    }
}

// 監聽 ESC 鍵退出全屏
document.addEventListener('fullscreenchange', function() {
	if (!document.fullscreenElement) {
		// 關閉所有彈出框
		document.querySelectorAll('.model-popup, .ai-info-modal, .export-modal').forEach(modal => {
			modal.classList.remove('show');
			modal.style.display = 'none';
		});
		
		// 關閉背景遮罩
		const backdrop = document.querySelector('.modal-backdrop');
		if (backdrop) {
			backdrop.classList.remove('show');
		}
	}
});

// 在 AI 聊天區域添加回到頂部按鈕
function addAIScrollToTop() {
	const aiChatArea = document.getElementById('aiChatArea');
	if (!aiChatArea) return;
	
	// 創建回到頂部按鈕
	const scrollToTopBtn = document.createElement('button');
	scrollToTopBtn.className = 'ai-scroll-to-top';
	scrollToTopBtn.id = 'aiScrollToTop';
	scrollToTopBtn.innerHTML = '↑';
	scrollToTopBtn.title = '回到頂部';
	scrollToTopBtn.onclick = scrollToAITop;
	
	// 添加到聊天區域
	aiChatArea.style.position = 'relative';
	aiChatArea.appendChild(scrollToTopBtn);
	
	// 監聽滾動事件
	aiChatArea.addEventListener('scroll', function() {
		if (this.scrollTop > 300) {
			scrollToTopBtn.classList.add('show');
		} else {
			scrollToTopBtn.classList.remove('show');
		}
	});
}

// 滾動到 AI 內容頂部
function scrollToAITop() {
	const aiChatArea = document.getElementById('aiChatArea');
	if (aiChatArea) {
		aiChatArea.scrollTo({
			top: 0,
			behavior: 'smooth'
		});
	}
}        
// Toggle AI Panel
function toggleAIPanel(e) {
    if (e) {
        e.stopPropagation(); 
    }
    
    const rightPanel = document.getElementById('rightPanel');
    const resizeHandle = document.getElementById('resizeHandle');
    const aiBtn = document.getElementById('aiToggleBtn');
    
    isAIPanelOpen = !isAIPanelOpen;
    
    if (isAIPanelOpen) {
        rightPanel.classList.add('active');
        resizeHandle.classList.add('active');
        aiBtn.classList.add('active');
    } else {
        rightPanel.classList.remove('active');
        resizeHandle.classList.remove('active');
        aiBtn.classList.remove('active');
        if (isAIFullscreen)
            toggleAIFullscreen();
            
    }
}

// 重置分析按鈕狀態
function resetAnalyzeButton() {
    const btn = document.getElementById('analyzeBtn');
    const modeConfig = ANALYSIS_MODES[selectedAnalysisMode];
    
    if (btn && modeConfig) {
        btn.disabled = false;
        btn.classList.remove('loading');
        btn.innerHTML = `<span id="analyzeIcon">${modeConfig.icon}</span> <span id="analyzeText">${modeConfig.buttonText}</span>`;
        btn.style.background = modeConfig.buttonColor;
    }
    
    isAnalyzing = false;
}

document.addEventListener('DOMContentLoaded', function() {

    // 初始化 AI 分析器
    if (typeof AIAnalyzer !== 'undefined' && document.getElementById('analyzeBtn')) {
        aiAnalyzer = new AIAnalyzer();
        window.aiAnalyzer = aiAnalyzer;  // 確保全局可訪問
    }

    // 綁定模式按鈕事件
    document.querySelectorAll('.ai-mode-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const mode = this.dataset.mode;
            executeAIAnalysis(mode);
        });
    });
    
    // 綁定模型選擇按鈕
    const modelSelectBtn = document.getElementById('modelSelectInlineBtn');
    if (modelSelectBtn) {
        modelSelectBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            toggleModelPopup();
        });
    }
    
    // 綁定 Provider 選擇器
    const providerSelect = document.getElementById('providerSelectInline');
    if (providerSelect) {
        providerSelect.addEventListener('change', function(e) {
            if (window.aiAnalyzer) {
                window.aiAnalyzer.switchProvider(e.target.value);
            }
        });
    }
    
    // 綁定發送按鈕
    const askBtn = document.getElementById('askBtnInline');
    if (askBtn) {
        askBtn.addEventListener('click', function(e) {
            e.preventDefault();
            askCustomQuestion();
        });
    }
    
    // 監聽輸入框變化
    const customQuestion = document.getElementById('customQuestion');
    if (customQuestion) {
        customQuestion.addEventListener('input', function() {
            const hasContent = this.value.trim().length > 0;
            if (askBtn) {
                askBtn.disabled = !hasContent;
            }
        });
    }

	// 設置 AI 面板初始狀態
	const aiResponse = document.getElementById('aiResponse');
	if (aiResponse) {
		const responseContent = aiResponse.querySelector('.ai-response-content');
		if (!responseContent || responseContent.children.length === 0) {
			const defaultContent = ``;
			
			if (responseContent) {
				responseContent.innerHTML = defaultContent;
			} else if (aiResponse) {
				aiResponse.innerHTML = `
					<div class="ai-response-header">
						<div class="ai-response-title">
							<span>📝</span> AI 分析結果
						</div>
					</div>
					<div class="ai-response-content" id="aiResponseContent">
						${defaultContent}
					</div>
				`;
			}
		}
	}
	
	// 確保 AI 面板結構正確
	const rightPanel = document.getElementById('rightPanel');
	if (rightPanel) {
		// 檢查是否需要重新組織結構
		const hasNewStructure = rightPanel.querySelector('.ai-panel-main');
		if (!hasNewStructure) {
			console.log('更新 AI 面板結構...');
			reorganizeAIPanel();
		}
	}
	
	// 綁定 ESC 鍵關閉彈出視窗
	document.addEventListener('keydown', function(e) {
		if (e.key === 'Escape') {
			const modal = document.getElementById('aiInfoModal');
			if (modal && modal.style.display === 'flex') {
				toggleAIInfo();
			}
		}
	}); 

	// 綁定模式卡片點擊事件
    document.querySelectorAll('.mode-card').forEach(card => {
        card.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            const mode = this.dataset.mode;
            selectAnalysisMode(mode);
        });
    });
    
    // 初始化默認選中的模式
    selectAnalysisMode('auto');

});

// 控制 AI 使用限制彈出視窗
function toggleAIInfo() {
    const existingModal = document.getElementById('aiInfoModal');
    if (existingModal && existingModal.style.display === 'flex') {
        existingModal.style.display = 'none';
        return;
    }
    
    // 如果 modal 不存在，直接使用現有的結構
    if (existingModal) {
        existingModal.style.display = 'flex';
    }
}

async function executeAIAnalysis(mode) {
    // 如果有 aiAnalyzer 實例，使用它的流式輸出
    if (window.aiAnalyzer) {
        window.aiAnalyzer.currentMode = mode;
        await window.aiAnalyzer.startAnalysis();
        return;
    }
    
    // 否則使用本地的流式實現
    const btn = document.querySelector(`.ai-mode-btn[data-mode="${mode}"]`);
    if (!btn || isAnalyzing) return;
    
    isAnalyzing = true;
    
    // 禁用所有按鈕
    document.querySelectorAll('.ai-mode-btn').forEach(b => {
        b.disabled = true;
        b.classList.add('disabled');
    });
    
    // 保存原始內容
    const originalContent = btn.innerHTML;
    
    // 顯示 loading
    btn.classList.add('analyzing');
    btn.innerHTML = `
        <div class="ai-spinner"></div>
        <span class="mode-name">分析中...</span>
    `;
    
    const responseDiv = document.getElementById('aiResponse');
    const responseContent = document.getElementById('aiResponseContent');
    responseDiv.classList.add('active');
    
    // 創建新的對話項目（使用流式輸出）
    const conversationItem = createConversationItem(mode);
    responseContent.appendChild(conversationItem);
    
    const contentDiv = conversationItem.querySelector('.ai-response-text');
    const thinkingDiv = conversationItem.querySelector('.ai-thinking');
    
    try {
        // 使用流式請求
        const response = await fetch('/api/ai/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: Date.now().toString(),
                provider: 'anthropic',
                model: selectedModel,
                mode: mode,
                file_path: filePath,
                file_name: fileName,
                content: fileContent,
                stream: true  // 啟用流式輸出
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        // 讀取流式響應
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let accumulatedContent = '';
        
        // 隱藏思考動畫
        if (thinkingDiv) {
            thinkingDiv.style.display = 'none';
        }
        
        // 創建內容容器
        contentDiv.innerHTML = '<div class="message-area"></div><div class="content-area"></div>';
        const contentArea = contentDiv.querySelector('.content-area');
        const messageArea = contentDiv.querySelector('.message-area');
        
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        
                        switch (data.type) {
                            case 'content':
                                // 累積內容並實時更新
                                accumulatedContent += data.content;
                                updateStreamingContent(contentArea, accumulatedContent);
                                break;
                                
                            case 'info':
                            case 'warning':
                                displayMessage(messageArea, data.type, data.message);
                                break;
                                
                            case 'complete':
                                // 完成時更新統計信息
                                updateUsageInfo(conversationItem, data);
                                break;
                                
                            case 'error':
                                throw new Error(data.error);
                        }
                    } catch (e) {
                        console.error('解析流數據錯誤:', e);
                    }
                }
            }
        }
        
    } catch (error) {
        console.error('Analysis error:', error);
        if (contentDiv) {
            contentDiv.innerHTML = `
                <div class="ai-error">
                    <h3>❌ 分析失敗</h3>
                    <p>${escapeHtml(error.message)}</p>
                </div>
            `;
        }
    } finally {
        // 恢復按鈕
        btn.innerHTML = originalContent;
        btn.classList.remove('analyzing');
        
        document.querySelectorAll('.ai-mode-btn').forEach(b => {
            b.disabled = false;
            b.classList.remove('disabled');
        });
        
        isAnalyzing = false;
    }
}

// 流式更新內容，使用 requestAnimationFrame 優化性能
let updateTimer = null;
function updateStreamingContent(container, content) {
    if (updateTimer) {
        cancelAnimationFrame(updateTimer);
    }
    
    updateTimer = requestAnimationFrame(() => {
        const formatted = formatStreamingContent(content);
        container.innerHTML = formatted;
        
        // 保持滾動在底部
        const chatArea = document.getElementById('aiChatArea');
        if (chatArea) {
            chatArea.scrollTop = chatArea.scrollHeight;
        }
    });
}

// 格式化流式內容（支援 Markdown）
function formatStreamingContent(text) {
    if (!text) return '';
    
    let html = '<div class="chatgpt-content">';
    
    // 處理代碼塊
    text = text.replace(/```([\w]*)\n([\s\S]*?)```/g, function(match, lang, code) {
        return `<pre class="gpt-code-block"><code class="language-${lang || 'text'}">${escapeHtml(code.trim())}</code></pre>`;
    });
    
    // 處理標題
    text = text.replace(/^### (.+)$/gm, '<h3 class="gpt-h3">$1</h3>');
    text = text.replace(/^## (.+)$/gm, '<h2 class="gpt-h2">$1</h2>');
    text = text.replace(/^# (.+)$/gm, '<h1 class="gpt-h1">$1</h1>');
    
    // 處理粗體和斜體
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
    
    // 處理行內代碼
    text = text.replace(/`([^`]+)`/g, '<code class="gpt-inline-code">$1</code>');
    
    // 處理列表
    const lines = text.split('\n');
    let inList = false;
    let listType = null;
    let processedLines = [];
    
    for (let line of lines) {
        // 編號列表
        const olMatch = line.match(/^(\d+)\.\s+(.+)$/);
        if (olMatch) {
            if (!inList || listType !== 'ol') {
                if (inList) processedLines.push(`</${listType}>`);
                processedLines.push('<ol class="gpt-numbered-list">');
                inList = true;
                listType = 'ol';
            }
            processedLines.push(`<li class="gpt-list-item">${olMatch[2]}</li>`);
            continue;
        }
        
        // 無序列表
        const ulMatch = line.match(/^[-*]\s+(.+)$/);
        if (ulMatch) {
            if (!inList || listType !== 'ul') {
                if (inList) processedLines.push(`</${listType}>`);
                processedLines.push('<ul class="gpt-bullet-list">');
                inList = true;
                listType = 'ul';
            }
            processedLines.push(`<li class="gpt-list-item">${ulMatch[1]}</li>`);
            continue;
        }
        
        // 非列表項目
        if (inList) {
            processedLines.push(`</${listType}>`);
            inList = false;
            listType = null;
        }
        
        // 處理段落
        if (line.trim()) {
            processedLines.push(`<p class="gpt-paragraph">${line}</p>`);
        }
    }
    
    if (inList) {
        processedLines.push(`</${listType}>`);
    }
    
    html += processedLines.join('\n');
    html += '</div>';
    
    return html;
}

// 顯示消息
function displayMessage(container, type, message) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `ai-${type}-message`;
    msgDiv.innerHTML = `<span class="${type}-icon">${type === 'info' ? 'ℹ️' : '⚠️'}</span> ${message}`;
    container.appendChild(msgDiv);
}

// 更新使用信息
function updateUsageInfo(conversationItem, data) {
    const usageDiv = conversationItem.querySelector('.ai-usage-info');
    if (usageDiv && data.usage) {
        conversationItem.querySelector('.input-tokens').textContent = data.usage.input.toLocaleString();
        conversationItem.querySelector('.output-tokens').textContent = data.usage.output.toLocaleString();
        conversationItem.querySelector('.total-cost').textContent = (data.cost || 0).toFixed(4);
        usageDiv.style.display = 'flex';
    }
}

// 重新組織 AI 面板結構（如果需要）
function reorganizeAIPanel() {
	const rightPanel = document.getElementById('rightPanel');
	if (!rightPanel) return;
	
	// 獲取現有的元素
	const header = rightPanel.querySelector('.ai-panel-header');
	const content = rightPanel.querySelector('.ai-panel-content');
	const customQuestion = rightPanel.querySelector('.custom-question');
	const aiInfoBox = rightPanel.querySelector('.ai-info-box');
	
	if (!header) return;
	
	// 更新標題區的按鈕
	const headerButtons = header.querySelector('div');
	if (headerButtons && !headerButtons.querySelector('.info-btn')) {
		const infoBtn = document.createElement('button');
		infoBtn.className = 'info-btn';
		infoBtn.setAttribute('onclick', 'toggleAIInfo()');
		infoBtn.setAttribute('title', '使用限制');
		infoBtn.textContent = 'ℹ️';
		
		// 插入到第一個按鈕之前
		headerButtons.insertBefore(infoBtn, headerButtons.firstChild);
	}
	
	// 創建新的結構
	if (!rightPanel.querySelector('.ai-panel-main')) {
		// 創建主要內容區
		const mainDiv = document.createElement('div');
		mainDiv.className = 'ai-panel-main';
		
		const scrollableDiv = document.createElement('div');
		scrollableDiv.className = 'ai-panel-scrollable';
		
		// 移動所有內容到可滾動區域（除了標題和自訂問題）
		const children = Array.from(rightPanel.children);
		children.forEach(child => {
			if (child !== header && 
				!child.classList.contains('ai-panel-footer') && 
				!child.classList.contains('custom-question')) {
				scrollableDiv.appendChild(child);
			}
		});
		
		mainDiv.appendChild(scrollableDiv);
		
		// 創建底部固定區域
		const footerDiv = document.createElement('div');
		footerDiv.className = 'ai-panel-footer';
		
		// 如果有自訂問題區，移動到底部
		if (customQuestion) {
			footerDiv.appendChild(customQuestion);
		}
		
		// 組裝新結構
		rightPanel.appendChild(mainDiv);
		rightPanel.appendChild(footerDiv);
	}
	
	// 隱藏或移除 AI 使用限制區塊
	if (aiInfoBox) {
		aiInfoBox.style.display = 'none';
	}
	
	// 創建彈出視窗（如果不存在）
	if (!document.getElementById('aiInfoModal')) {
		createAIInfoModal();
	}
}

// 創建 AI 使用限制彈出視窗
function createAIInfoModal() {
	const modal = document.createElement('div');
	modal.className = 'ai-info-modal';
	modal.id = 'aiInfoModal';
	modal.style.display = 'none';
	
	modal.innerHTML = `
		<div class="ai-info-modal-content">
			<div class="ai-info-modal-header">
				<h4>ℹ️ AI 使用限制</h4>
				<button class="modal-close-btn" onclick="toggleAIInfo()">×</button>
			</div>
			<div class="ai-info-modal-body">
				<ul>
					<li>單次分析最大支援約 50,000 字元（50KB）</li>
					<li>超過限制時會自動截取關鍵部分分析</li>
					<li>支援 ANR 和 Tombstone 日誌分析</li>
					<li>回應最多 4000 個 tokens（約 3000 中文字）</li>
					<li>請避免頻繁請求，建議間隔 5 秒以上</li>
				</ul>
			</div>
		</div>
	`;
	
	document.body.appendChild(modal);
}

// 確保快速問題功能正常運作
async function useQuickQuestion(question) {
    if (isAskingQuestion) return;
    
    isAskingQuestion = true;
    
    const responseDiv = document.getElementById('aiResponse');
    const responseContent = document.getElementById('aiResponseContent');
    
    if (!responseDiv || !responseContent) {
        isAskingQuestion = false;
        return;
    }
    
    responseDiv.classList.add('active');
    
    // 創建對話項目
    const conversationItem = createQuestionConversationItem(question);
    responseContent.appendChild(conversationItem);
    
    const contentDiv = conversationItem.querySelector('.ai-response-text');
    const thinkingDiv = conversationItem.querySelector('.ai-thinking');
    
    try {
        // 使用流式請求（如果有 aiAnalyzer）
        if (window.aiAnalyzer) {
            window.aiAnalyzer.messages.push({
                role: 'user',
                content: question
            });
            
            // 使用 aiAnalyzer 的流式方法
            const response = await fetch('/api/ai/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: window.aiAnalyzer.sessionId,
                    provider: 'anthropic',
                    model: selectedModel,
                    mode: 'quick',
                    file_path: filePath,
                    file_name: fileName,
                    content: fileContent,
                    stream: true,
                    context: [{
                        role: 'user',
                        content: question
                    }]
                })
            });
            
            // 處理流式響應
            await handleStreamResponse(response, conversationItem);
        } else {
            // 使用非流式後備方案
            const response = await fetch('/api/ai/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: Date.now().toString(),
                    provider: 'anthropic',
                    model: selectedModel,
                    mode: 'quick',
                    file_path: filePath,
                    file_name: fileName,
                    content: fileContent,
                    stream: false,
                    context: [{
                        role: 'user',
                        content: question
                    }]
                })
            });
            
            const data = await response.json();
            
            if (thinkingDiv) {
                thinkingDiv.style.display = 'none';
            }
            
            if (response.ok && data.success) {
                contentDiv.innerHTML = formatStreamingContent(data.result || data.analysis);
                updateUsageInfo(conversationItem, data);
            } else {
                throw new Error(data.error || '分析失敗');
            }
        }
        
    } catch (error) {
        console.error('Quick question error:', error);
        if (thinkingDiv) {
            thinkingDiv.style.display = 'none';
        }
        contentDiv.innerHTML = `
            <div class="ai-error">
                <h3>❌ 分析失敗</h3>
                <p>${escapeHtml(error.message)}</p>
            </div>
        `;
    } finally {
        isAskingQuestion = false;
        
        // 關閉快速問題選單
        const menu = document.getElementById('quickQuestionsMenu');
        if (menu) {
            menu.classList.remove('show');
        }
    }
}

async function handleStreamResponse(response, conversationItem) {
    const contentDiv = conversationItem.querySelector('.ai-response-text');
    const thinkingDiv = conversationItem.querySelector('.ai-thinking');
    
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let accumulatedContent = '';
    
    // 隱藏思考動畫
    if (thinkingDiv) {
        thinkingDiv.style.display = 'none';
    }
    
    // 創建內容容器
    contentDiv.innerHTML = '<div class="message-area"></div><div class="content-area"></div>';
    const contentArea = contentDiv.querySelector('.content-area');
    const messageArea = contentDiv.querySelector('.message-area');
    
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');
        
        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const data = JSON.parse(line.slice(6));
                    
                    switch (data.type) {
                        case 'content':
                            accumulatedContent += data.content;
                            updateStreamingContent(contentArea, accumulatedContent);
                            break;
                            
                        case 'info':
                        case 'warning':
                            displayMessage(messageArea, data.type, data.message);
                            break;
                            
                        case 'complete':
                            updateUsageInfo(conversationItem, data);
                            break;
                            
                        case 'error':
                            throw new Error(data.error);
                    }
                } catch (e) {
                    console.error('解析流數據錯誤:', e);
                }
            }
        }
    }
}

function createQuestionConversationItem(question) {
    const conversationItem = document.createElement('div');
    conversationItem.className = 'ai-conversation-item';
    conversationItem.id = `conversation-${Date.now()}`;
    
    const shortQuestion = question.length > 50 ? question.substring(0, 50) + '...' : question;
    
    conversationItem.innerHTML = `
        <div class="ai-conversation-header">
            <div class="conversation-meta">
                <span class="mode-indicator">
                    <span class="mode-icon">💡</span>
                    <span class="mode-text">快速問題</span>
                </span>
                <span class="model-info">${selectedModel}</span>
                <span class="timestamp">${new Date().toLocaleTimeString()}</span>
            </div>
            <div class="conversation-actions">
                <button class="copy-btn" onclick="copyAIResponse('${conversationItem.id}')">
                    📋 複製
                </button>
                <button class="export-html-btn" onclick="exportSingleResponse('${conversationItem.id}', 'html')">
                    🌐 HTML
                </button>
                <button class="export-md-btn" onclick="exportSingleResponse('${conversationItem.id}', 'markdown')">
                    📝 MD
                </button>
            </div>
        </div>
        <div class="user-question">
            ${escapeHtml(question)}
        </div>
        <div class="ai-conversation-content">
            <div class="ai-thinking">
                <span class="thinking-dots">
                    <span>.</span><span>.</span><span>.</span>
                </span>
                正在分析：${escapeHtml(shortQuestion)}
            </div>
            <div class="ai-response-text"></div>
            <div class="ai-usage-info" style="display: none;">
                <span class="token-count">Tokens: <span class="input-tokens">0</span> / <span class="output-tokens">0</span></span>
                <span class="cost-info">成本: $<span class="total-cost">0.00</span></span>
            </div>
        </div>
    `;
    
    conversationHistory.push(conversationItem);
    
    // 滾動到新內容
    setTimeout(() => {
        conversationItem.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 100);
    
    return conversationItem;
}

// 匯出對話功能
function exportAIChat() {
    const existingModal = document.getElementById('exportModal');
    if (existingModal) {
        existingModal.style.display = 'flex';
    }
}

function closeExportModal() {
	const modal = document.getElementById('exportModal');
	if (modal) {
		modal.style.display = 'none';
	}
}

// 執行匯出
function exportChat(format) {

	if (conversationHistory.length === 0) {
		alert('沒有對話記錄可以匯出');
		closeExportModal();
		return;
	}
	
	let content = '';
	let filename = `AI對話_${fileName}_${new Date().toISOString().slice(0, 10)}`;
	
	switch (format) {
		case 'markdown':
			content = generateMarkdown();
			filename += '.md';
			downloadFile(content, filename, 'text/markdown');
			break;
			
		case 'html':
			content = generateHTML();
			filename += '.html';
			downloadFile(content, filename, 'text/html');
			break;
			
		case 'text':
			content = generatePlainText();
			filename += '.txt';
			downloadFile(content, filename, 'text/plain');
			break;
	}
	
	closeExportModal();
}

// 生成 Markdown
function generateMarkdown() {
	let markdown = `# AI 對話記錄\n\n`;
	markdown += `**檔案：** ${fileName}\n`;
	markdown += `**日期：** ${new Date().toLocaleString('zh-TW')}\n\n`;
	markdown += `---\n\n`;
	
	conversationHistory.forEach((item, index) => {
		const element = item;
		const timeElement = element.querySelector('.conversation-time');
		const time = timeElement ? timeElement.textContent : '';
		
		// 提取對話類型
		const typeElement = element.querySelector('.conversation-type');
		const type = typeElement ? typeElement.textContent : '';
		
		markdown += `## 對話 ${index + 1} - ${type}\n`;
		markdown += `*${time}*\n\n`;
		
		// 如果有使用者問題
		const userQuestion = element.querySelector('.user-question');
		if (userQuestion) {
			const questionText = userQuestion.textContent.trim();
			markdown += `### 💬 使用者問題\n`;
			markdown += `> ${questionText}\n\n`;
		}
		
		// AI 回應
		const aiContent = element.querySelector('.ai-analysis-content');
		if (aiContent) {
			markdown += `### 🤖 AI 回應\n`;
			markdown += extractTextContent(aiContent) + '\n\n';
		}
		
		markdown += `---\n\n`;
	});
	
	return markdown;
}

// 生成 HTML
function generateHTML() {
	let html = `<!DOCTYPE html>
<html lang="zh-TW">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>AI 對話記錄 - ${fileName}</title>
	<style>
		body {
			font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
			max-width: 800px;
			margin: 0 auto;
			padding: 20px;
			background: #f5f5f5;
			color: #333;
		}
		.header {
			background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
			color: white;
			padding: 20px;
			border-radius: 10px;
			margin-bottom: 20px;
		}
		.conversation {
			background: white;
			padding: 20px;
			margin-bottom: 20px;
			border-radius: 10px;
			box-shadow: 0 2px 4px rgba(0,0,0,0.1);
		}
		.conversation-header {
			color: #666;
			font-size: 14px;
			margin-bottom: 10px;
		}
		.user-question {
			background: #f0f0f0;
			padding: 15px;
			border-left: 4px solid #667eea;
			margin-bottom: 15px;
			border-radius: 5px;
		}
		.ai-response {
			padding: 15px;
			line-height: 1.6;
		}
		code {
			background: #f5f5f5;
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
		h3 {
			color: #667eea;
		}
	</style>
</head>
<body>
	<div class="header">
		<h1>AI 對話記錄</h1>
		<p>檔案：${escapeHtml(fileName)}</p>
		<p>日期：${new Date().toLocaleString('zh-TW')}</p>
	</div>`;
	
	conversationHistory.forEach((item, index) => {
		const element = item;
		html += `<div class="conversation">`;
		
		// 複製整個對話內容
		const conversationContent = element.innerHTML;
		html += conversationContent;
		
		html += `</div>`;
	});
	
	html += `</body></html>`;
	return html;
}

// 生成純文字
function generatePlainText() {
	let text = `AI 對話記錄\n`;
	text += `================\n\n`;
	text += `檔案：${fileName}\n`;
	text += `日期：${new Date().toLocaleString('zh-TW')}\n\n`;
	text += `================\n\n`;
	
	conversationHistory.forEach((item, index) => {
		const element = item;
		const timeElement = element.querySelector('.conversation-time');
		const time = timeElement ? timeElement.textContent : '';
		const typeElement = element.querySelector('.conversation-type');
		const type = typeElement ? typeElement.textContent : '';
		
		text += `【對話 ${index + 1} - ${type}】\n`;
		text += `時間：${time}\n\n`;
		
		// 使用者問題
		const userQuestion = element.querySelector('.user-question');
		if (userQuestion) {
			text += `使用者問題：\n`;
			text += userQuestion.textContent.trim() + '\n\n';
		}
		
		// AI 回應
		const aiContent = element.querySelector('.ai-analysis-content');
		if (aiContent) {
			text += `AI 回應：\n`;
			text += extractTextContent(aiContent) + '\n\n';
		}
		
		text += `----------------------------------------\n\n`;
	});
	
	return text;
}

// 提取純文字內容
function extractTextContent(element) {
	// 複製元素以避免修改原始內容
	const clone = element.cloneNode(true);
	
	// 處理 <br> 標籤
	clone.querySelectorAll('br').forEach(br => {
		br.replaceWith('\n');
	});
	
	// 處理列表
	clone.querySelectorAll('li').forEach(li => {
		li.innerHTML = '• ' + li.innerHTML + '\n';
	});
	
	return clone.textContent.trim();
}

// 下載檔案
function downloadFile(content, filename, mimeType) {
	const blob = new Blob([content], { type: mimeType + ';charset=utf-8' });
	const link = document.createElement('a');
	link.href = URL.createObjectURL(blob);
	link.download = filename;
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
	URL.revokeObjectURL(link.href);
}

function improvedResizeDivider() {
	const divider = document.getElementById('aiResizeDivider');
	const chatArea = document.getElementById('aiChatArea');
	const inputArea = document.getElementById('aiInputArea');
	const rightPanel = document.getElementById('rightPanel');
	
	if (!divider || !chatArea || !inputArea || !rightPanel) return;
	
	let isResizing = false;
	let currentY = 0;
	let animationFrame = null;
	
	// 使用 requestAnimationFrame 優化性能
	function updateSizes() {
		if (!isResizing) return;
		
		const rect = rightPanel.getBoundingClientRect();
		const headerHeight = rightPanel.querySelector('.ai-panel-header').offsetHeight;
		const dividerHeight = divider.offsetHeight;
		
		// 計算相對於面板的位置
		const relativeY = currentY - rect.top - headerHeight;
		const availableHeight = rect.height - headerHeight - dividerHeight;
		
		// 計算新高度
		let newChatHeight = relativeY - dividerHeight / 2;
		let newInputHeight = availableHeight - newChatHeight;
		
		// 最小高度限制
		const minHeight = 50;
		
		// 應用限制
		newChatHeight = Math.max(minHeight, Math.min(newChatHeight, availableHeight - minHeight));
		newInputHeight = availableHeight - newChatHeight;
		
		// 設定高度
		chatArea.style.height = `${newChatHeight}px`;
		inputArea.style.height = `${newInputHeight}px`;
		
		// 繼續動畫
		if (isResizing) {
			animationFrame = requestAnimationFrame(updateSizes);
		}
	}
	
	divider.addEventListener('mousedown', function(e) {
		isResizing = true;
		currentY = e.clientY;
		
		divider.classList.add('dragging');
		document.body.style.cursor = 'ns-resize';
		document.body.style.userSelect = 'none';
		
		// 添加覆蓋層防止 iframe 等元素干擾
		const overlay = document.createElement('div');
		overlay.id = 'resize-overlay';
		overlay.style.cssText = `
			position: fixed;
			top: 0;
			left: 0;
			right: 0;
			bottom: 0;
			z-index: 99999;
			cursor: ns-resize;
		`;
		document.body.appendChild(overlay);
		
		e.preventDefault();
		updateSizes();
	});
	
	document.addEventListener('mousemove', function(e) {
		if (!isResizing) return;
		currentY = e.clientY;
	});
	
	document.addEventListener('mouseup', function() {
		if (!isResizing) return;
		
		isResizing = false;
		cancelAnimationFrame(animationFrame);
		
		divider.classList.remove('dragging');
		document.body.style.cursor = '';
		document.body.style.userSelect = '';
		
		// 移除覆蓋層
		const overlay = document.getElementById('resize-overlay');
		if (overlay) overlay.remove();
	});
	
	// 添加雙擊重置
	addDoubleClickReset(divider, chatArea, inputArea, rightPanel);
}

function addDoubleClickReset(divider, chatArea, inputArea, rightPanel) {
	divider.addEventListener('dblclick', function() {
		const totalHeight = rightPanel.offsetHeight;
		const headerHeight = rightPanel.querySelector('.ai-panel-header').offsetHeight;
		const dividerHeight = divider.offsetHeight;
		const availableHeight = totalHeight - headerHeight - dividerHeight;
		
		// 重置為預設比例（70% / 30%）
		const defaultChatHeight = availableHeight * 0.7;
		const defaultInputHeight = availableHeight * 0.3;
		
		// 添加過渡動畫
		chatArea.style.transition = 'height 0.3s ease';
		inputArea.style.transition = 'height 0.3s ease';
		
		chatArea.style.height = `${defaultChatHeight}px`;
		inputArea.style.height = `${defaultInputHeight}px`;
		
		// 移除過渡
		setTimeout(() => {
			chatArea.style.transition = '';
			inputArea.style.transition = '';
		}, 300);
		
		console.log('Reset to default proportions (70% / 30%)');
	});
}
	
// 自動調整輸入框高度
function setupAutoResizeTextarea() {
	const textarea = document.getElementById('customQuestion');
	if (!textarea) return;
	
	function adjustHeight() {
		// 重置高度以獲取正確的 scrollHeight
		textarea.style.height = 'auto';
		
		// 計算新高度
		const newHeight = Math.min(textarea.scrollHeight, 400); // 最大 400px
		textarea.style.height = newHeight + 'px';
		
		// 如果超過最大高度，顯示滾動條
		if (textarea.scrollHeight > 400) {
			textarea.style.overflowY = 'auto';
		} else {
			textarea.style.overflowY = 'hidden';
		}
	}
	
	// 監聽輸入事件
	textarea.addEventListener('input', adjustHeight);
	
	// 監聽視窗調整
	window.addEventListener('resize', adjustHeight);
	
	// 初始調整
	adjustHeight();
}

// 快速問題下拉選單控制
function toggleQuickQuestions() {
	const menu = document.getElementById('quickQuestionsMenu');
	if (menu) {
		menu.classList.toggle('show');
		
		// 點擊外部關閉
		if (menu.classList.contains('show')) {
			document.addEventListener('click', handleQuickQuestionsOutsideClick);
		} else {
			document.removeEventListener('click', handleQuickQuestionsOutsideClick);
		}
	}
}

function handleQuickQuestionsOutsideClick(e) {
	const dropdown = document.querySelector('.quick-questions-dropdown');
	if (!dropdown.contains(e.target)) {
		const menu = document.getElementById('quickQuestionsMenu');
		menu.classList.remove('show');
		document.removeEventListener('click', handleQuickQuestionsOutsideClick);
	}
}

// 在 AI 回應中顯示 token 使用情況
function displayTokenUsage(estimatedTokens) {
	const maxTokens = 200000;
	const percentage = (estimatedTokens / maxTokens * 100).toFixed(1);
	const barWidth = Math.min(percentage, 100);
	
	return `
		<div style="margin: 10px 0; padding: 10px; background: #f0f0f0; border-radius: 6px;">
			<div style="font-size: 12px; color: #666; margin-bottom: 5px;">
				Token 使用量：${estimatedTokens.toLocaleString()} / ${maxTokens.toLocaleString()} (${percentage}%)
			</div>
			<div style="background: #e0e0e0; height: 20px; border-radius: 10px; overflow: hidden;">
				<div style="background: ${percentage > 75 ? '#ff9800' : '#4caf50'}; 
							width: ${barWidth}%; 
							height: 100%; 
							transition: width 0.3s;">
				</div>
			</div>
		</div>
	`;
}

// 更準確的 token 估算
function estimateTokens(text) {
	if (!text) return 0;
	
	// 分別計算不同類型字元
	const englishChars = (text.match(/[a-zA-Z0-9\s]/g) || []).length;
	const chineseChars = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
	const punctuation = (text.match(/[.,!?;:'"()\[\]{}<>]/g) || []).length;
	const otherChars = text.length - englishChars - chineseChars - punctuation;
	
	// 更保守的估算
	const estimatedTokens = Math.ceil(
		englishChars / 3.5 +      // 英文更保守
		chineseChars / 2 +         // 中文約 2 字元一個 token
		punctuation / 4 +          // 標點符號
		otherChars / 2.5           // 其他字元
	);
	
	// 加上 10% 的緩衝
	return Math.ceil(estimatedTokens * 1.1);
}

// 設置輸入框的即時 token 顯示
function setupRealtimeTokenCount() {
	const customQuestion = document.getElementById('customQuestion');
	const inputArea = document.getElementById('aiInputArea');
	
	if (!customQuestion || !inputArea) return;

	// 先檢查是否已存在，如果存在就先移除
	let tokenCountDiv = document.getElementById('realtimeTokenCount');
	if (tokenCountDiv) {
		tokenCountDiv.remove();
	} 
	
	// 檢查是否已存在
	if (!tokenCountDiv) {
		// 創建 token 顯示區
		tokenCountDiv = document.createElement('div');
		tokenCountDiv.id = 'realtimeTokenCount';
		tokenCountDiv.className = 'token-usage-top';
		
		// 插入到 wrapper 的最上方
		const wrapper = document.querySelector('.custom-question-wrapper');
		if (wrapper) {
			wrapper.insertBefore(tokenCountDiv, wrapper.firstChild);
		}
	}


	
	let updateTimer = null;
	
	// 更新 token 計數的函數（加入防抖動）
	function updateTokenCount() {
		clearTimeout(updateTimer);
		updateTimer = setTimeout(() => {
			const question = customQuestion.value;
			const fullContent = `檔案名稱: ${fileName}\n檔案路徑: ${filePath}\n=== 當前檔案內容 ===\n${fileContent}\n=== 檔案內容結束 ===\n\n使用者問題：${question}`;
			const tokens = estimateTokens(fullContent);
			
			tokenCountDiv.innerHTML = createTokenUsageBar(tokens, '預計發送 Token');
		}, 1000); // 1000ms 延遲
	}
	
	// 移除可能存在的舊事件監聽器
	customQuestion.removeEventListener('input', updateTokenCount);
	
	// 初始顯示
	updateTokenCount();
	
	// 監聽輸入變化
	customQuestion.addEventListener('input', updateTokenCount);
	
	// 將更新函數儲存為元素的屬性，方便後續清理
	customQuestion._updateTokenCount = updateTokenCount;
}

// 在 DOMContentLoaded 中調用
document.addEventListener('DOMContentLoaded', function() {
	setupRealtimeTokenCount();
});

// 生成 Token 使用狀態條
function createTokenUsageBar(estimatedTokens, label = 'Token 使用量') {
	const maxTokens = 200000;
	const percentage = (estimatedTokens / maxTokens * 100).toFixed(1);
	const barWidth = Math.min(percentage, 100);
	
	// 根據使用率決定顏色
	let barColor = '#4caf50'; // 綠色
	if (percentage > 75) barColor = '#ff5722'; // 紅色
	else if (percentage > 50) barColor = '#ff9800'; // 橘色
	
	return `
		<div class="token-usage-container" style="margin: 0px 0; padding: 5px; background: #2d2d30; border-radius: 6px; border: 1px solid #3e3e42;">
			<div style="font-size: 12px; color: #d4d4d4; margin-bottom: 8px; display: flex; justify-content: space-between;">
				<span>${label}</span>
				<span style="color: ${barColor}; font-weight: bold;">
					${estimatedTokens.toLocaleString()} / ${maxTokens.toLocaleString()} (${percentage}%)
				</span>
			</div>
			<div style="background: #1e1e1e; height: 8px; border-radius: 4px; overflow: hidden;">
				<div style="background: ${barColor}; 
							width: ${barWidth}%; 
							height: 100%; 
							transition: width 0.3s ease;">
				</div>
			</div>
			${percentage > 75 ? `
				<div style="font-size: 11px; color: #ff9800; margin-top: 5px;">
					⚠️ 接近 token 上限，內容可能會被截取
				</div>
			` : ''}
		</div>
	`;
}

// Ask custom question
async function askCustomQuestion() {
    // 防止重複點擊
    if (isAskingQuestion) {
        console.log('正在處理中，請稍候...');
        return;
    }
    
    const customQuestionElement = document.getElementById('customQuestion');
    const responseDiv = document.getElementById('aiResponse');
    const responseContent = document.getElementById('aiResponseContent');
    const askBtn = document.getElementById('askBtnInline');
    
    if (!askBtn || !customQuestionElement || !responseDiv || !responseContent) {
        console.error('找不到必要的元素');
        return;
    }
    
    const customQuestion = customQuestionElement.value.trim();
    
    if (!customQuestion) {
        alert('請輸入您的問題');
        return;
    }
    
    // 設置發送狀態
    isAskingQuestion = true;
    
    // 保存問題內容（因為要清空輸入框）
    const questionToSend = customQuestion;
    
    // 立即清空輸入框
    customQuestionElement.value = '';
    
    // 禁用輸入框和按鈕，防止重複提交
    customQuestionElement.disabled = true;
    askBtn.disabled = true;
    //askBtn.innerHTML = '➤ 發送中...';
    
    responseDiv.classList.add('active');
    
    // 創建新的 loading 元素
	const loadingDiv = createLoadingElement(getModelDisplayName(selectedModel));
    responseContent.appendChild(loadingDiv);
    
    // 滾動到 loading 元素
    setTimeout(() => {
        loadingDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, 100);
    
    try {
        // 構建包含檔案內容的上下文
        const fileInfo = `檔案名稱: ${fileName}\n檔案路徑: ${filePath}\n`;
        
        // 限制檔案內容長度（避免超過 token 限制）
        const maxContentLength = 100000; // 約 100KB
        let truncatedContent = fileContent;
        let truncated = false;
        
        if (fileContent.length > maxContentLength) {
            truncatedContent = fileContent.substring(0, maxContentLength);
            truncated = true;
        }
        
        const fileContext = `=== 當前檔案內容 ===\n${truncatedContent}\n=== 檔案內容結束 ===\n\n`;
        
        // 組合問題和檔案上下文
        const fullContent = `${fileInfo}${fileContext}使用者問題：${questionToSend}`;

        // 發送自訂問題請求 - 確保不觸發分段分析
        const response = await fetch('/api/ai/analyze', {  // 改為正確的端點
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				session_id: aiAnalyzer ? aiAnalyzer.sessionId : Date.now().toString(),
				provider: 'anthropic',
				model: selectedModel,
				mode: 'quick',
				file_path: filePath,
				file_name: fileName,
				content: `${fileInfo}${fileContext}使用者問題：${questionToSend}`,
				stream: false,
				context: []
			})
		});

        // 移除 loading
        if (loadingDiv && loadingDiv.parentNode) {
            loadingDiv.remove();
        }
        
        const data = await response.json();
        
        if (response.ok && data.success) {
			displayAIAnalysisWithContext(
				data.analysis || data.result || '無分析結果',
				data.truncated || truncated,
				data.model || selectedModel,
				questionToSend,
				data.thinking || null,
				data.analyzed_length || truncatedContent.length,
				data.original_length || fileContent.length
			);
		}
        
    } catch (error) {
        console.error('AI analysis error:', error);
        
        // 移除 loading
        if (loadingDiv && loadingDiv.parentNode) {
            loadingDiv.remove();
        }
        
        const errorDiv = document.createElement('div');
        errorDiv.className = 'ai-error';
        errorDiv.innerHTML = `
            <h3>❌ 請求錯誤</h3>
            <p>無法連接到 AI 分析服務：${error.message}</p>
            <p style="margin-top: 10px;">
                <button class="retry-btn" onclick="retryQuestion('${escapeHtml(questionToSend)}')">🔄 重試</button>
            </p>
        `;
        responseContent.appendChild(errorDiv);
        
        conversationHistory.push(errorDiv);


    } finally {
        // 確保最後重置狀態
        isAskingQuestion = false;
        customQuestionElement.disabled = false;
        askBtn.disabled = !customQuestionElement.value.trim();
        askBtn.innerHTML = `
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 2L11 13"></path>
                <path d="M22 2L15 22L11 13L2 9L22 2Z"></path>
            </svg>
        `;
    }

	// 修改 askCustomQuestion 函數中創建 loading 的部分
	function createLoadingElement(modelName) {
		const loadingDiv = document.createElement('div');
		loadingDiv.className = 'ai-loading';
		loadingDiv.innerHTML = `
			<div class="ai-spinner"></div>
			<div>正在使用 ${modelName} 處理您的問題...</div>
		`;
		return loadingDiv;
	}
		
}

// 添加重試函數
function retryQuestion(question) {
	const customQuestionElement = document.getElementById('customQuestion');
	if (customQuestionElement) {
		customQuestionElement.value = question;
		askCustomQuestion();
	}
}

// 更新進度條
function updateProgressBar(container, data) {
	const progressFill = container.querySelector('#analysisProgress');
	const progressText = container.querySelector('#progressText');
	const currentSegment = container.querySelector('#currentSegment');
	const progressMessage = container.querySelector('#progressMessage');
	
	if (progressFill) {
		progressFill.style.width = `${data.percentage}%`;
	}
	
	if (progressText) {
		progressText.textContent = `${data.percentage}%`;
	}
	
	if (currentSegment) {
		currentSegment.textContent = `當前：${data.current}/${data.total}`;
	}
	
	if (progressMessage && data.message) {
		progressMessage.textContent = data.message;
	}
}

// 監聽輸入框變化，啟用/禁用發送按鈕
document.addEventListener('DOMContentLoaded', function() {
	const customQuestion = document.getElementById('customQuestion');
	const sendBtn = document.getElementById('askBtnInline');
	
	if (customQuestion && sendBtn) {
		customQuestion.addEventListener('input', function() {
			const hasContent = this.value.trim().length > 0;
			sendBtn.disabled = !hasContent;
		});
		
		// 自動調整高度
		customQuestion.addEventListener('input', function() {
			this.style.height = 'auto';
			this.style.height = Math.min(this.scrollHeight, 200) + 'px';
		});
	}
	
	// 初始化回到頂部按鈕
	addAIScrollToTop();
});

// 設置 Enter 鍵送出功能
function setupEnterKeySubmit() {
	const customQuestion = document.getElementById('customQuestion');
	if (!customQuestion) return;
	
	function handleEnterKey(e) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			e.stopPropagation();
			
			// 如果正在發送中，不要重複發送
			if (isAskingQuestion) {
				console.log('正在處理中，請稍候...');
				return;
			}
			
			const content = this.value.trim();
			if (content) {
				askCustomQuestion();
			}
		}
	}
	
	customQuestion.addEventListener('keydown', handleEnterKey);
}

document.addEventListener('DOMContentLoaded', function() {
	
	// 使用改進的拖曳功能
	improvedResizeDivider();

	// 設定輸入框自動調整高度
	setupAutoResizeTextarea();

	// 設置 Enter 鍵送出
	setupEnterKeySubmit();

	// 點擊 ESC 關閉彈出視窗
	document.addEventListener('keydown', function(e) {
		if (e.key === 'Escape') {
			const exportModal = document.getElementById('exportModal');
			const infoModal = document.getElementById('aiInfoModal');
			const quickMenu = document.getElementById('quickQuestionsMenu');
			
			if (exportModal && exportModal.style.display === 'flex') {
				closeExportModal();
			}
			if (infoModal && infoModal.style.display === 'flex') {
				toggleAIInfo();
			}
			if (quickMenu && quickMenu.classList.contains('show')) {
				quickMenu.classList.remove('show');
			}
		}
	});
});

// 新增專門處理帶上下文的 AI 回應顯示函數
function displayAIAnalysisWithContext(analysis, truncated, model, originalQuestion, thinking = null, analyzedLength = 0, originalLength = 0) {
	const responseContent = document.getElementById('aiResponseContent');
	
	// 檢查並確保 analysis 有值
	if (!analysis) {
		console.error('沒有收到分析內容');
		analysis = '分析失敗：沒有收到有效的回應內容';
	}
	
	// 計算回應的 token
	const responseTokens = estimateTokens(analysis);
	const totalTokens = estimateTokens(originalQuestion) + responseTokens;

	if (!responseContent) {
		console.error('找不到 AI 回應區域');
		return;
	}
	
	// 移除任何現有的 loading 元素
	const existingLoading = responseContent.querySelector('.ai-loading');
	if (existingLoading) {
		existingLoading.remove();
	}
	
	// 安全地格式化分析結果
	let formattedAnalysis = '';
	try {
		// 確保 analysis 是字串
		const analysisText = String(analysis || '');
		
		formattedAnalysis = analysisText
			.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
			.replace(/`([^`]+)`/g, '<code>$1</code>')
			.replace(/^(\d+\.\s.*?)$/gm, '<li>$1</li>')
			.replace(/^-\s(.*?)$/gm, '<li>$1</li>')
			.replace(/(<li>.*?<\/li>\s*)+/g, '<ul>$&</ul>')
			.replace(/<\/li>\s*<li>/g, '</li><li>');
		
		// 處理標題
		formattedAnalysis = formattedAnalysis.replace(/^(\d+\.\s*[^:：]+[:：])/gm, '<h3>$1</h3>');
		
		// 處理代碼塊
		formattedAnalysis = formattedAnalysis.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
	} catch (error) {
		console.error('格式化分析內容時出錯:', error);
		formattedAnalysis = '<p>' + escapeHtml(analysis || '分析失敗') + '</p>';
	}
	
	// 建立對話項目
	const conversationItem = document.createElement('div');
	conversationItem.className = 'conversation-item';
	
	// 構建 HTML 內容
	let conversationHTML = `
		<div class="conversation-header">
			<span class="conversation-icon">👤</span>
			<span class="conversation-type">您的問題（基於當前檔案）</span>
			<span class="conversation-time">${new Date().toLocaleString('zh-TW')}</span>
		</div>
		<div class="user-question">
			${escapeHtml(originalQuestion || '')}
			<div style="margin-top: 5px; font-size: 11px; color: #969696;">
				📄 關於檔案: ${escapeHtml(fileName || '')}
				${truncated ? `<span style="color: #ff9800; margin-left: 10px;">⚠️ 內容已截取</span>` : ''}
			</div>
		</div>
		
		<!-- Token 使用統計 -->
		<div style="margin: 10px 0;">
			${createTokenUsageBar(totalTokens, '本次對話 Token 使用')}
		</div>
		
		<div class="ai-response-item">
			<div class="ai-icon">🤖</div>
			<div class="ai-message">
	`;
	
	// 如果內容被截取，在回應頂部顯示明顯警告
	if (truncated) {
		// 使用傳入的參數或計算預設值
		const truncatedLengthKB = analyzedLength > 0 ? (analyzedLength/1024).toFixed(1) : '100.0';
		const originalLengthKB = originalLength > 0 ? (originalLength/1024).toFixed(1) : (fileContent.length/1024).toFixed(1);
		
		conversationHTML += `
			<div style="background: #ff9800; color: white; padding: 10px; border-radius: 6px; margin-bottom: 15px;">
				<strong>⚠️ 注意：</strong>由於檔案過大，AI 只分析了前 ${truncatedLengthKB}KB 的內容（原始檔案大小：${originalLengthKB}KB）。
				如需完整分析，請考慮分段詢問或使用更小的檔案。
			</div>
		`;
	}
	
	// 如果有 thinking 內容，顯示它
	if (thinking) {
		conversationHTML += `
			<details class="ai-thinking-section" style="margin-bottom: 15px;">
				<summary style="cursor: pointer; color: #4ec9b0; font-weight: 600; margin-bottom: 10px;">
					🧠 AI 思考過程 (點擊展開)
				</summary>
				<div style="background: #2d2d30; padding: 15px; border-radius: 6px; margin-top: 10px; border-left: 3px solid #4ec9b0;">
					<pre style="white-space: pre-wrap; color: #969696; font-size: 13px; margin: 0;">${escapeHtml(thinking || '')}</pre>
				</div>
			</details>
		`;
	}
	
	conversationHTML += `
				<div class="ai-analysis-content">
					${formattedAnalysis}
				</div>
				<div class="ai-footer">
					<span>由 ${getModelDisplayName(model)} 提供分析</span>
					${thinking ? '<span style="margin-left: 10px;">• 包含深度思考</span>' : ''}
					<span style="margin-left: 10px;">• 基於當前檔案內容</span>
				</div>
			</div>
		</div>
	`;
	
	conversationItem.innerHTML = conversationHTML;
	
	// 添加到對話歷史
	conversationHistory.push(conversationItem);
	
	// 保留所有對話，不清空
	responseContent.appendChild(conversationItem);
	
	// 自動滾動到最新內容
	autoScrollToBottom();
}        

// 為 thinking 部分添加 CSS 樣式
const thinkingStyles = `
<style>
.ai-thinking-section {
	background: #1e1e1e;
	border-radius: 6px;
	padding: 10px;
	margin: 10px 0;
}

.ai-thinking-section summary {
	outline: none;
}

.ai-thinking-section summary::-webkit-details-marker {
	color: #4ec9b0;
}

.ai-thinking-section[open] summary {
	margin-bottom: 10px;
}

details.ai-thinking-section {
	transition: all 0.3s ease;
}
</style>`;

// 在頁面載入時注入樣式
document.addEventListener('DOMContentLoaded', function() {
	const styleElement = document.createElement('div');
	styleElement.innerHTML = thinkingStyles;
	document.head.appendChild(styleElement.querySelector('style'));
});

// 確保 DOM 載入完成後再執行初始化
document.addEventListener('DOMContentLoaded', function() {
	// 檢查所有必要的元素是否存在
	const requiredElements = [
		'aiResponse',
		'aiResponseContent',
		'analyzeBtn',
		'askBtnInline',
		'customQuestion'
	];
	
	let missingElements = [];
	requiredElements.forEach(id => {
		if (!document.getElementById(id)) {
			missingElements.push(id);
		}
	});
	
	if (missingElements.length > 0) {
		console.warn('某些元素未找到:', missingElements.join(', '));
		// 不要阻止繼續執行，因為有些元素可能是可選的
	}
});

// Get model display name
function getModelDisplayName(modelId) {
    const names = {
        'claude-opus-4-20250514': 'Claude 4 Opus',
        'claude-sonnet-4-20250514': 'Claude 4 Sonnet',
        'claude-3-5-sonnet-20241022': 'Claude 3.5 Sonnet',
        'claude-3-5-haiku-20241022': 'Claude 3.5 Haiku',
        'claude-3-opus-20240229': 'Claude 3 Opus',
        'claude-3-haiku-20240307': 'Claude 3 Haiku'
    };
    return names[modelId] || modelId;
}

// 自動滾動函數
function autoScrollToBottom() {
	const aiChatArea = document.getElementById('aiChatArea');
	const aiResponse = document.getElementById('aiResponse');
	
	setTimeout(() => {
		// 滾動聊天區域到底部
		if (aiChatArea) {
			aiChatArea.scrollTop = aiChatArea.scrollHeight;
		}
		
		// 如果回應區域也有滾動條，也滾動到底部
		if (aiResponse) {
			aiResponse.scrollTop = aiResponse.scrollHeight;
		}
	}, 100);
}

function displayAIAnalysis(analysis, truncated, model, isCustomQuestion = false, thinking = null) {
    const responseContent = document.getElementById('aiResponseContent');
    
    if (!responseContent) {
        console.error('找不到 AI 回應區域');
        return;
    }
    
    // 如果是智能分析的結果，轉到新的顯示函數
    if (analysis && typeof analysis === 'object' && analysis.analysis_mode) {
        return displaySmartAnalysisResult(analysis, ANALYSIS_MODES[analysis.analysis_mode] || ANALYSIS_MODES.auto);
    }
	
	// 確保 analysis 存在
	if (!analysis) {
		console.error('沒有分析內容');
		analysis = '分析失敗：沒有收到有效的回應內容';
	}
	
	// 移除任何現有的 loading 元素
	const existingLoading = responseContent.querySelector('.ai-loading');
	if (existingLoading) {
		existingLoading.remove();
	}
	
	// 安全地格式化分析結果
	let formattedAnalysis = '';
	try {
		formattedAnalysis = analysis
			.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
			.replace(/`([^`]+)`/g, '<code>$1</code>')
			.replace(/^(\d+\.\s.*?)$/gm, '<li>$1</li>')
			.replace(/^-\s(.*?)$/gm, '<li>$1</li>')
			.replace(/(<li>.*?<\/li>\s*)+/g, '<ul>$&</ul>')
			.replace(/<\/li>\s*<li>/g, '</li><li>');
		
		// 處理標題
		formattedAnalysis = formattedAnalysis.replace(/^(\d+\.\s*[^:：]+[:：])/gm, '<h3>$1</h3>');
		
		// 處理代碼塊
		formattedAnalysis = formattedAnalysis.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
	} catch (error) {
		console.error('格式化分析內容時出錯:', error);
		formattedAnalysis = '<p>' + escapeHtml(analysis) + '</p>';
	}
	
	// 建立對話項目
	const conversationItem = document.createElement('div');
	conversationItem.className = 'conversation-item';
	conversationItem.innerHTML = `
		<div class="conversation-header">
			<span class="conversation-icon">${isCustomQuestion ? '👤' : '🔍'}</span>
			<span class="conversation-type">${isCustomQuestion ? '您的問題' : '檔案分析'}</span>
			<span class="conversation-time">${new Date().toLocaleString('zh-TW')}</span>
		</div>
		${isCustomQuestion ? `
			<div class="user-question">
				${escapeHtml(document.getElementById('customQuestion')?.value || '檔案分析請求')}
			</div>
		` : ''}
		<div class="ai-response-item">
			<div class="ai-icon">🤖</div>
			<div class="ai-message">
				${truncated ? '<div class="ai-warning">⚠️ 由於日誌過長，僅分析了關鍵部分</div>' : ''}
				${thinking ? `
					<details class="ai-thinking-section" style="margin-bottom: 15px;">
						<summary style="cursor: pointer; color: #4ec9b0; font-weight: 600; margin-bottom: 10px;">
							🧠 AI 思考過程 (點擊展開)
						</summary>
						<div style="background: #2d2d30; padding: 15px; border-radius: 6px; margin-top: 10px; border-left: 3px solid #4ec9b0;">
							<pre style="white-space: pre-wrap; color: #969696; font-size: 13px; margin: 0;">${escapeHtml(thinking || '')}</pre>
						</div>
					</details>
				` : ''}
				<div class="ai-analysis-content">
					${formattedAnalysis}
				</div>
				<div class="ai-footer">
					<span>由 ${getModelDisplayName(model)} 提供分析</span>
					${thinking ? '<span style="margin-left: 10px;">• 包含深度思考</span>' : ''}
				</div>
			</div>
		</div>
	`;
	
	// 添加到對話歷史
	conversationHistory.push(conversationItem);
	
	// 保留所有對話，不清空
	responseContent.appendChild(conversationItem);
	
	// 自動滾動到最新內容
	autoScrollToBottom();
}

// Setup resize handle
function setupResizeHandle() {
	const resizeHandle = document.getElementById('resizeHandle');
	const leftPanel = document.querySelector('.left-panel');
	const rightPanel = document.querySelector('.right-panel');
	let isResizing = false;
	let startX = 0;
	let startWidth = 0;
	
	resizeHandle.addEventListener('mousedown', (e) => {
		isResizing = true;
		startX = e.clientX;
		startWidth = rightPanel.offsetWidth;
		document.body.style.cursor = 'col-resize';
		e.preventDefault();
	});
	
	document.addEventListener('mousemove', (e) => {
		if (!isResizing) return;
		
		const width = startWidth + (startX - e.clientX);
		const minWidth = 400;
		const maxWidth = window.innerWidth * 0.6;
		
		if (width >= minWidth && width <= maxWidth) {
			rightPanel.style.width = width + 'px';
		}
	});
	
	document.addEventListener('mouseup', () => {
		isResizing = false;
		document.body.style.cursor = '';
	});
}

// Model selection handlers
function setupModelSelection() {
	const modelOptions = document.querySelectorAll('.model-option');
	
	modelOptions.forEach(option => {
		option.addEventListener('click', function() {
			modelOptions.forEach(opt => opt.classList.remove('selected'));
			this.classList.add('selected');
		});
		
		// Initialize selected state
		const radio = option.querySelector('input[type="radio"]');
		if (radio.checked) {
			option.classList.add('selected');
		}
	});
}

// Initialize - 修改初始化部分
document.addEventListener('DOMContentLoaded', function() {
	// Set file info
	document.getElementById('filename').textContent = fileName;
	document.getElementById('filepath').textContent = filePath;
	
	// Process content
	lines = fileContent.split('\n');
	
	// Setup line numbers and content
	setupLineNumbers();
	updateContent();
	
	// Update file size info
	const fileSize = new Blob([fileContent]).size;
	document.getElementById('fileSizeInfo').textContent = formatFileSize(fileSize);
	
	// Setup event listeners
	setupEventListeners();
	
	// Sync scroll
	syncScroll();
	
	// Setup AI panel
	setupResizeHandle();
	setupModelSelection();
});

// 在 custom-question div 中添加提示文字
document.addEventListener('DOMContentLoaded', function() {
	const customQuestionDiv = document.querySelector('.custom-question');
	if (customQuestionDiv) {
		// 在標題下方添加提示
		const existingH3 = customQuestionDiv.querySelector('h3');
		if (existingH3) {
			const hint = document.createElement('p');
			hint.style.cssText = 'color: #969696; font-size: 12px; margin: 5px 0 10px 0;';
			hint.innerHTML = '💡 AI 會基於當前檔案內容回答您的問題';
			existingH3.parentNode.insertBefore(hint, existingH3.nextSibling);
		}
		
		// 更新 placeholder
		const questionInput = document.getElementById('customQuestion');
		if (questionInput) {
			questionInput.placeholder = '詢問關於這個檔案的任何問題，例如：\n• 這個崩潰的根本原因是什麼？\n• 哪個函數導致了問題？\n• 如何修復這個錯誤？';
		}
	}
});        

// 保留所有原有的函數（escapeRegex, formatFileSize, setupLineNumbers 等）
// 這些函數保持不變...

function escapeRegex(string) {
	return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function formatFileSize(bytes) {
	if (bytes < 1024) return bytes + ' B';
	else if (bytes < 1048576) return Math.round(bytes / 1024) + ' KB';
	else return Math.round(bytes / 1048576 * 10) / 10 + ' MB';
}

function setupLineNumbers() {
	const lineNumbersDiv = document.getElementById('lineNumbers');
	lineNumbersDiv.innerHTML = '';
	
	for (let i = 1; i <= lines.length; i++) {
		const lineDiv = document.createElement('div');
		lineDiv.className = 'line-number';
		lineDiv.textContent = i;
		lineDiv.id = 'line-' + i;
		lineDiv.onclick = function(e) {
			e.preventDefault();
			e.stopPropagation();
			toggleBookmarkForLine(i);
		};

		// 新增滑鼠懸停追蹤
		lineDiv.addEventListener('mouseenter', function() {
			hoveredLine = i;
		});

		lineDiv.addEventListener('mouseleave', function() {
			if (hoveredLine === i) {
				hoveredLine = null;
			}
		});
		
		if (bookmarks.has(i)) {
			lineDiv.classList.add('bookmarked');
		}
		
		lineNumbersDiv.appendChild(lineDiv);
	}
}

function updateContent(preserveSearchHighlights = false) {
	const contentDiv = document.getElementById('content');
	let html = '';
	
	for (let i = 0; i < lines.length; i++) {
		let line = escapeHtml(lines[i]);
		
		// 先應用關鍵字高亮
		for (const [keyword, colorIndex] of Object.entries(highlightedKeywords)) {
			const escapedKeyword = escapeRegex(escapeHtml(keyword));
			const regex = new RegExp(escapedKeyword, 'g');
			line = line.replace(regex, 
				`<span class="highlight-${colorIndex}" data-keyword="${escapeHtml(keyword)}">${escapeHtml(keyword)}</span>`);
		}
		
		html += `<span class="line" data-line="${i + 1}">${line}</span>\n`;
	}
	
	contentDiv.innerHTML = html;
	updateKeywordsList();
	
	// 如果需要保留搜尋高亮，重新應用
	if (preserveSearchHighlights && searchResults.length > 0) {
		applySearchHighlights();
	}
}

function escapeHtml(text) {
	if (!text) return '';
	const div = document.createElement('div');
	text = String(text);
	div.textContent = text;
	return div.innerHTML;
}

function escapeRegex(string) {
	// 正確轉義所有正則表達式特殊字符
	return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function setupEventListeners() {
	document.getElementById('content').addEventListener('mouseup', updateLineInfo);
	document.getElementById('content').addEventListener('keydown', updateLineInfo);
	document.getElementById('contentArea').addEventListener('scroll', function() {
		// 更新當前可見的行
		const contentArea = this;
		const scrollTop = contentArea.scrollTop;
		const lineHeight = 20;
		const visibleLine = Math.floor(scrollTop / lineHeight) + 1;
		
		if (visibleLine !== currentLine && visibleLine <= lines.length) {
			currentLine = visibleLine;
			updateLineInfo();
		}
	});
	
	// Context menu
	document.addEventListener('contextmenu', function(e) {
		e.preventDefault();
		
		const selection = window.getSelection();
		selectedText = selection.toString().trim();
		
		if (selectedText) {
			const contextMenu = document.getElementById('contextMenu');
			contextMenu.style.display = 'block';
			contextMenu.style.left = e.pageX + 'px';
			contextMenu.style.top = e.pageY + 'px';
		}
	});
	
	// Click to hide context menu
	document.addEventListener('click', function() {
		document.getElementById('contextMenu').style.display = 'none';
	});
	
	// Keyboard shortcuts
	document.addEventListener('keydown', function(e) {
		// F1 - Help
		if (e.key === 'F1') {
			e.preventDefault();
			toggleHelp();
		}
		// F2 - Toggle bookmark
		else if (e.key === 'F2') {
			e.preventDefault();
			toggleBookmark();
		}
		// F3 - Next bookmark
		else if (e.key === 'F3') {
			e.preventDefault();
			if (e.shiftKey) {
				previousBookmark();
			} else {
				nextBookmark();
			}
		}
		// Ctrl+F - Search
		else if (e.ctrlKey && e.key === 'f') {
			e.preventDefault();
			document.getElementById('searchBox').focus();
		}
		// Ctrl+G - Go to line
		else if (e.ctrlKey && e.key === 'g') {
			e.preventDefault();
			const lineNum = prompt('跳到行號：', currentLine);
			if (lineNum) {
				goToLine(parseInt(lineNum));
			}
		}
		// Escape - Clear search/selection
		else if (e.key === 'Escape') {
			clearSearch();
			window.getSelection().removeAllRanges();
		}
		// Enter in search box
		else if (e.key === 'Enter' && e.target.id === 'searchBox') {
			e.preventDefault();
			if (e.shiftKey) {
				findPrevious();
			} else {
				findNext();
			}
		}
	});
	
	// Search box with debounce
	let searchDebounceTimer = null;
	const SEARCH_DELAY = 300;
	const MIN_SEARCH_LENGTH = 2;
	
	document.getElementById('searchBox').addEventListener('input', function(e) {
		clearTimeout(searchDebounceTimer);
		const searchText = e.target.value;
		const useRegex = document.getElementById('regexToggle').checked;
		
		if (!searchText) {
			clearSearch();
			return;
		}
		
		// 在 regex 模式下，降低最小長度要求
		const minLength = useRegex ? 1 : MIN_SEARCH_LENGTH;
		
		if (searchText.length < minLength) {
			document.getElementById('searchInfo').textContent = 
				`請輸入至少 ${minLength} 個字元`;
			return;
		}
		
		document.getElementById('searchInfo').textContent = '輸入中...';
		
		searchDebounceTimer = setTimeout(() => {
			performSearch();
		}, SEARCH_DELAY);
	});
	
	// Regex toggle
	document.getElementById('regexToggle').addEventListener('change', function() {
		clearTimeout(searchDebounceTimer);
		const searchText = document.getElementById('searchBox').value;
		
		if (searchText) {
			// 立即執行搜尋
			performSearch();
		}
	});
				
	// Enter key for immediate search
	document.getElementById('searchBox').addEventListener('keydown', function(e) {
		if (e.key === 'Enter') {
			e.preventDefault();
			clearTimeout(searchDebounceTimer);
			
			const searchText = this.value;
			const useRegex = document.getElementById('regexToggle').checked;
			const minLength = useRegex ? 1 : MIN_SEARCH_LENGTH;
			
			if (searchText && searchText.length >= minLength) {
				performSearch();
			}
		}
	});
	
	// Update line info on click
	document.getElementById('content').addEventListener('click', updateLineInfo);
	document.getElementById('content').addEventListener('keyup', updateLineInfo);
	
	// Mouse tracking in content area
	document.getElementById('content').addEventListener('mousemove', function(e) {
		const lineElements = document.querySelectorAll('.line');
		for (let i = 0; i < lineElements.length; i++) {
			const rect = lineElements[i].getBoundingClientRect();
			if (e.clientY >= rect.top && e.clientY <= rect.bottom) {
				hoveredLine = i + 1;
				return;
			}
		}
		hoveredLine = null;
	});
	
	document.getElementById('content').addEventListener('mouseleave', function() {
		hoveredLine = null;
	});            
}

function syncScroll() {
	const contentArea = document.getElementById('contentArea');
	const lineNumbers = document.getElementById('lineNumbers');
	
	contentArea.addEventListener('scroll', function() {
		lineNumbers.scrollTop = contentArea.scrollTop;
	});
}

function highlightKeyword(colorIndex) {
	if (!selectedText) return;
	
	highlightedKeywords[selectedText] = colorIndex;
	updateContent(true);
	
	if (searchResults.length > 0) {
		applySearchHighlights();
	}
	
	document.getElementById('contextMenu').style.display = 'none';
	window.getSelection().removeAllRanges();
}

function removeHighlight() {
	if (!selectedText) return;
	
	delete highlightedKeywords[selectedText];
	updateContent(true);
	
	if (searchResults.length > 0) {
		applySearchHighlights();
	}
	
	document.getElementById('contextMenu').style.display = 'none';
	window.getSelection().removeAllRanges();
}

function clearAllHighlights() {
	highlightedKeywords = {};
	updateContent(true);
	
	if (searchResults.length > 0) {
		applySearchHighlights();
	}
}

function updateKeywordsList() {
	const keywordList = document.getElementById('keywordList');
	const keywordsBar = document.getElementById('keywordsBar');
	
	const tags = keywordList.querySelectorAll('.keyword-tag');
	tags.forEach(tag => tag.remove());
	
	for (const [keyword, colorIndex] of Object.entries(highlightedKeywords)) {
		const tag = document.createElement('span');
		tag.className = 'keyword-tag highlight-' + colorIndex;
		tag.innerHTML = escapeHtml(keyword) + ' <span class="remove">×</span>';
		tag.onclick = function() {
			delete highlightedKeywords[keyword];
			updateContent(true);
			
			if (searchResults.length > 0) {
				applySearchHighlights();
			}
		};
		keywordList.appendChild(tag);
	}
	
	keywordsBar.classList.toggle('active', Object.keys(highlightedKeywords).length > 0);
}

function toggleBookmark() {
	const targetLine = hoveredLine || currentLine;
	toggleBookmarkForLine(targetLine);
}

function toggleBookmarkForLine(lineNum) {
	if (!lineNum || lineNum < 1 || lineNum > lines.length) return;
	
	if (bookmarks.has(lineNum)) {
		bookmarks.delete(lineNum);
	} else {
		bookmarks.add(lineNum);
	}
	
	const lineElement = document.getElementById('line-' + lineNum);
	if (lineElement) {
		lineElement.classList.toggle('bookmarked');
	}
}

function nextBookmark() {
	if (bookmarks.size === 0) {
		alert('沒有設置書籤');
		return;
	}
	
	const sortedBookmarks = Array.from(bookmarks).sort((a, b) => a - b);
	const next = sortedBookmarks.find(line => line > bookmarkCurrentLine);
	if (next) {
		bookmarkCurrentLine = next;            
		goToLine(next);
	} else {
		// 循環到第一個書籤
		bookmarkCurrentLine = sortedBookmarks[0];
		goToLine(sortedBookmarks[0]);
	}
}

function previousBookmark() {
	if (bookmarks.size === 0) {
		alert('沒有設置書籤');
		return;
	}
	
	const sortedBookmarks = Array.from(bookmarks).sort((a, b) => a - b);
	const prev = sortedBookmarks.reverse().find(line => line < currentLine);
	
	if (prev) {
		goToLine(prev);
	} else {
		// 循環到最後一個書籤
		goToLine(sortedBookmarks[0]); // 因為已經 reverse 了，所以 [0] 是最後一個
	}
}

function goToLine(lineNum) {
	if (lineNum < 1 || lineNum > lines.length) return;
	
	currentLine = lineNum;
	
	// 更新行號高亮
	document.querySelectorAll('.line-number').forEach(el => {
		el.classList.remove('current-line');
	});
	
	const targetLineElement = document.getElementById('line-' + lineNum);
	if (targetLineElement) {
		targetLineElement.classList.add('current-line');
		// 確保行號可見
		targetLineElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
	}
	
	// 滾動到內容區的對應行
	const lineElements = document.querySelectorAll('.line');
	if (lineElements[lineNum - 1]) {
		lineElements[lineNum - 1].scrollIntoView({ behavior: 'smooth', block: 'center' });
	}
	
	updateLineInfo();
}

function performSearch() {
	const searchText = document.getElementById('searchBox').value;
	const useRegex = document.getElementById('regexToggle').checked;

	// 在 regex 模式下，允許更短的搜尋文字
	const minLength = useRegex ? 1 : MIN_SEARCH_LENGTH;
	
	if (searchText && searchText.length < minLength) {
		document.getElementById('searchInfo').textContent = 
			`請輸入至少 ${minLength} 個字元`;
		return;
	}
	
	clearSearchHighlights();
	
	if (!searchText) {
		searchResults = [];
		updateSearchInfo();
		return;
	}
	
	searchResults = [];
	
	try {
		let searchPattern;
		if (useRegex) {
			// Regex 模式：直接使用使用者輸入作為正則表達式
			try {
				searchPattern = new RegExp(searchText, 'gi');
			} catch (e) {
				// 如果使用者輸入的正則表達式無效
				document.getElementById('searchInfo').textContent = '無效的正則表達式';
				return;
			}
		} else {
			// 一般模式：轉義所有特殊字符，進行字面搜尋
			const escapedText = escapeRegex(searchText);
			searchPattern = new RegExp(escapedText, 'gi');
		}
		
		const content = document.getElementById('content');
		const text = content.textContent;
		let match;
		
		// 重置 lastIndex 以確保從頭開始搜尋
		searchPattern.lastIndex = 0;
		
		while ((match = searchPattern.exec(text)) !== null) {
			searchResults.push({
				index: match.index,
				length: match[0].length,
				text: match[0]
			});
			
			// 防止無限循環（對於零寬度匹配）
			if (match.index === searchPattern.lastIndex) {
				searchPattern.lastIndex++;
			}
		}
		
		if (searchResults.length > 0) {
			highlightSearchResults();
			currentSearchIndex = 0;
			scrollToSearchResult(0);
		}
		
	} catch (e) {
		console.error('Search error:', e);
		document.getElementById('searchInfo').textContent = '搜尋錯誤';
		return;
	}
	
	updateSearchInfo();
}

function highlightSearchResults() {
	const content = document.getElementById('content');
	if (!content) return;
	
	// 移除所有舊的高亮
	const keywordHighlights = [];
	content.querySelectorAll('[class*="highlight-"]').forEach(elem => {
		if (!elem.classList.contains('search-highlight')) {
			keywordHighlights.push({
				element: elem,
				className: elem.className,
				keyword: elem.dataset.keyword
			});
		}
	});
	
	// 清除搜尋高亮
	const existingSearchHighlights = content.querySelectorAll('.search-highlight');
	existingSearchHighlights.forEach(span => {
		const parent = span.parentNode;
		while (span.firstChild) {
			parent.insertBefore(span.firstChild, span);
		}
		parent.removeChild(span);
	});

	// 遍歷 TextNode 並應用新的高亮
	let globalTextIndex = 0;

	function processNode(node) {
		if (node.nodeType === Node.TEXT_NODE) {
			const textContent = node.nodeValue;
			let currentOffsetInTextNode = 0;
			const fragment = document.createDocumentFragment();
			let hasMatchInThisNode = false;

			const relevantResults = searchResults.filter(result => {
				const textNodeEndGlobalIndex = globalTextIndex + textContent.length;
				return result.index < textNodeEndGlobalIndex && (result.index + result.length) > globalTextIndex;
			}).sort((a, b) => a.index - b.index);

			relevantResults.forEach(result => {
				const startInTextNode = Math.max(0, result.index - globalTextIndex);
				const endInTextNode = Math.min(textContent.length, (result.index + result.length) - globalTextIndex);

				if (startInTextNode > currentOffsetInTextNode) {
					fragment.appendChild(document.createTextNode(textContent.substring(currentOffsetInTextNode, startInTextNode)));
				}

				const span = document.createElement('span');
				const isCurrent = searchResults.indexOf(result) === currentSearchIndex; 
				span.className = isCurrent ? 'search-highlight current' : 'search-highlight';
				span.textContent = textContent.substring(startInTextNode, endInTextNode);
				fragment.appendChild(span);
				hasMatchInThisNode = true;

				currentOffsetInTextNode = endInTextNode;
			});

			if (currentOffsetInTextNode < textContent.length) {
				fragment.appendChild(document.createTextNode(textContent.substring(currentOffsetInTextNode)));
			}

			if (hasMatchInThisNode) {
				node.parentNode.replaceChild(fragment, node);
			}

			globalTextIndex += textContent.length; 

		} else if (node.nodeType === Node.ELEMENT_NODE) {
			if (node.classList.contains('search-highlight')) {
				if (node.textContent) {
					globalTextIndex += node.textContent.length;
				}
				return;
			}

			const children = Array.from(node.childNodes); 
			children.forEach(child => processNode(child));
		}
	}

	const initialChildren = Array.from(content.childNodes);
	initialChildren.forEach(child => processNode(child));
}

function clearSearchHighlights() {
	const content = document.getElementById('content');
	const highlights = content.querySelectorAll('.search-highlight');
	highlights.forEach(highlight => {
		const text = highlight.textContent;
		highlight.replaceWith(text);
	});
}

// 只更新可見範圍的高亮
function updateVisibleHighlights() {
	const lines = document.querySelectorAll('.line');
	
	// 建立行號到結果的映射
	const resultsByLine = new Map();
	searchResults.forEach((result, index) => {
		// 只處理可見範圍內的結果
		if (result.line >= visibleRange.start && result.line <= visibleRange.end) {
			if (!resultsByLine.has(result.line)) {
				resultsByLine.set(result.line, []);
			}
			resultsByLine.get(result.line).push({ ...result, globalIndex: index });
		}
	});
	
	// 批量更新 DOM
	requestAnimationFrame(() => {
		resultsByLine.forEach((results, lineNum) => {
			const lineElement = lines[lineNum - 1];
			if (!lineElement) return;
			
			// 如果這行已經處理過，跳過
			if (lineElement.dataset.highlighted === 'true') return;
			
			let lineText = lineElement.textContent;
			let lineHTML = '';
			let lastIndex = 0;
			
			// 按位置排序
			results.sort((a, b) => a.offset - b.offset);
			
			results.forEach(result => {
				const isCurrent = result.globalIndex === currentSearchIndex;
				const className = isCurrent ? 'search-highlight current' : 'search-highlight';
				
				// 構建高亮的 HTML
				lineHTML += escapeHtml(lineText.substring(lastIndex, result.offset));
				lineHTML += `<span class="${className}" data-index="${result.globalIndex}">`;
				lineHTML += escapeHtml(lineText.substring(result.offset, result.offset + result.length));
				lineHTML += '</span>';
				lastIndex = result.offset + result.length;
			});
			
			// 添加剩餘的文本
			lineHTML += escapeHtml(lineText.substring(lastIndex));
			
			lineElement.innerHTML = lineHTML;
			lineElement.dataset.highlighted = 'true';
		});
	});
}

// 優化的滾動到結果
function scrollToSearchResult(index) {
	if (searchResults.length === 0 || !searchResults[index]) return;
	
	const result = searchResults[index];
	
	// 確保高亮是最新的
	updateCurrentHighlight();
	
	// 使用 setTimeout 確保 DOM 更新完成
	setTimeout(() => {
		// 找到所有高亮元素
		const allHighlights = document.querySelectorAll('.search-highlight');
		
		// 使用索引找到目標高亮
		if (allHighlights[index]) {
			// 捲動到視圖中央
			allHighlights[index].scrollIntoView({ 
				behavior: 'smooth', 
				block: 'center',
				inline: 'center'
			});
			
			// 確保是當前高亮
			allHighlights[index].classList.add('current');
		} else {
			// 備用方案：捲動到行
			const lineElement = document.querySelector(`.line[data-line="${result.line}"]`);
			if (lineElement) {
				lineElement.scrollIntoView({ 
					behavior: 'smooth', 
					block: 'center' 
				});
			}
		}
		
		// 更新行號資訊
		currentLine = result.line;
		updateLineInfo();
		
		// 高亮當前行號
		document.querySelectorAll('.line-number').forEach(el => {
			el.classList.remove('current-line');
		});
		document.getElementById('line-' + result.line)?.classList.add('current-line');
	}, 50);
}

// 優化的查找下一個/上一個
function findNext() {
	if (searchResults.length === 0) return;
	currentSearchIndex = (currentSearchIndex + 1) % searchResults.length;
	// 不需要重新高亮所有結果，只需要更新當前高亮
	updateCurrentHighlight();            
	updateSearchInfo();
}

function findPrevious() {
	if (searchResults.length === 0) return;
	currentSearchIndex = (currentSearchIndex - 1 + searchResults.length) % searchResults.length;
	// 不需要重新高亮所有結果，只需要更新當前高亮
	updateCurrentHighlight();            
	updateSearchInfo();
}

function updateCurrentHighlight() {
	// 移除所有 current 類別
	document.querySelectorAll('.search-highlight.current').forEach(el => {
		el.classList.remove('current');
	});
	
	// 找到並高亮當前結果
	const allHighlights = document.querySelectorAll('.search-highlight');
	if (allHighlights[currentSearchIndex]) {
		allHighlights[currentSearchIndex].classList.add('current');
	}
}

function scrollToSearchResult(index) {
	if (searchResults.length === 0 || !searchResults[index]) return;
	
	const result = searchResults[index];
	
	// 先確保目標行的高亮是最新的
	updateCurrentHighlight();
	
	// 方法1：先捲動到行，再捲動到具體的高亮
	const lineElement = document.querySelector(`.line[data-line="${result.line}"]`);
	if (lineElement) {
		// 先捲動到該行
		lineElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
		
		// 延遲一下再捲動到具體的高亮元素
		setTimeout(() => {
			const highlights = document.querySelectorAll('.search-highlight');
			if (highlights[index]) {
				highlights[index].scrollIntoView({ behavior: 'smooth', block: 'center' });
				
				// 添加視覺反饋（可選）
				highlights[index].style.animation = 'pulse 0.5s ease-in-out';
			}
		}, 100);
		
		// 更新當前行號
		currentLine = result.line;
		updateLineInfo();
		
		// 更新行號高亮
		document.querySelectorAll('.line-number').forEach(el => {
			el.classList.remove('current-line');
		});
		const lineNumberElement = document.getElementById('line-' + result.line);
		if (lineNumberElement) {
			lineNumberElement.classList.add('current-line');
		}
	}
}

function clearSearch() {
	document.getElementById('searchBox').value = '';
	clearTimeout(searchDebounceTimer);
	clearSearchHighlights();
	searchResults = [];
	currentSearchIndex = -1;
	updateSearchInfo();
	document.getElementById('grepIndicator').classList.remove('active');
	document.getElementById('prevSearchBtn').style.display = 'none';
	document.getElementById('nextSearchBtn').style.display = 'none';
}

function updateSearchInfo() {
	const info = document.getElementById('searchInfo');
	const prevBtn = document.getElementById('prevSearchBtn');
	const nextBtn = document.getElementById('nextSearchBtn');
	
	if (searchResults.length > 0) {
		info.textContent = `${currentSearchIndex + 1} / ${searchResults.length} 個結果`;
		
		prevBtn.style.display = 'inline-flex';
		nextBtn.style.display = 'inline-flex';
		
		if (searchResults.length === 1) {
			prevBtn.disabled = true;
			nextBtn.disabled = true;
		} else {
			prevBtn.disabled = false;
			nextBtn.disabled = false;
		}
	} else if (document.getElementById('searchBox').value) {
		info.textContent = '沒有找到結果';
		prevBtn.style.display = 'none';
		nextBtn.style.display = 'none';
	} else {
		info.textContent = '';
		prevBtn.style.display = 'none';
		nextBtn.style.display = 'none';
	}
}

function updateLineInfo() {
	const selection = window.getSelection();
	const info = document.getElementById('lineInfo');
	const selInfo = document.getElementById('selectionInfo');
	
	if (selection.rangeCount > 0) {
		const range = selection.getRangeAt(0);
		const container = range.startContainer;
		
		let lineElement = container.nodeType === Node.TEXT_NODE ? 
			container.parentElement : container;
		
		while (lineElement && !lineElement.classList.contains('line')) {
			lineElement = lineElement.parentElement;
		}
		
		if (lineElement) {
			const lineNum = parseInt(lineElement.dataset.line);
			currentLine = lineNum || currentLine;
			
			let column = 1;
			if (container.nodeType === Node.TEXT_NODE) {
				column = range.startOffset + 1;
			}
			
			info.textContent = `行 ${currentLine}, 列 ${column}`;
		}
	}
	
	if (selection.toString()) {
		selInfo.textContent = `已選取 ${selection.toString().length} 個字元`;
	} else {
		selInfo.textContent = '';
	}
}

function toggleHelp() {
	const help = document.getElementById('shortcutsHelp');
	help.style.display = help.style.display === 'none' ? 'block' : 'none';
}		

function downloadAsHTML() {
	// 創建一個臨時的 DOM 副本
	const tempDiv = document.createElement('div');
	tempDiv.innerHTML = document.body.innerHTML;

	// 移除不需要的按鈕
	const exportBtn = tempDiv.querySelector('.btn-success');
	const downloadBtn = tempDiv.querySelector('a.btn[href*="download=true"]');

	if (exportBtn) exportBtn.remove();
	if (downloadBtn) downloadBtn.remove();

	// 準備 HTML 內容
	const htmlContent = `<!DOCTYPE html>
	<html lang="zh-TW">
	<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>${escapeHtml(fileName)} - Exported</title>
	<style>
	${document.querySelector('style').textContent}
	</style>
	</head>
	<body>
	${tempDiv.innerHTML}
	<script>
	// 標記為靜態匯出頁面
	const isStaticExport = true;

	// Initialize with current state
	const fileContent = ${JSON.stringify(fileContent)};
	const fileName = ${JSON.stringify(fileName)};
	const filePath = ${JSON.stringify(filePath)};
	let lines = ${JSON.stringify(lines)};
	let highlightedKeywords = ${JSON.stringify(highlightedKeywords)};
	let bookmarks = new Set(${JSON.stringify(Array.from(bookmarks))});
	let selectedText = '';
	let currentLine = 1;
	let searchResults = [];
	let currentSearchIndex = -1;
	let searchRegex = null;
	let hoveredLine = null; // 追蹤滑鼠懸停的行號

	// 移除匯出功能
	window.downloadAsHTML = function() {
		alert('此為靜態匯出頁面，無法再次匯出');
	};

	${document.querySelector('script').textContent}
	</script>    
	</body>
	</html>`;
		
		// 創建下載
		const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' });
		const link = document.createElement('a');
		link.href = URL.createObjectURL(blob);
		link.download = fileName + '_viewer.html';
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(link.href);
}


//==================================================================================================

// 切換模型選擇彈出卡片
function toggleModelPopup() {
    const existingModal = document.querySelector('.model-popup-modal');
    if (existingModal) {
        existingModal.remove();
        document.querySelector('.modal-backdrop')?.remove();
        return;
    }
    
    const contentHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h4>🤖 選擇 AI 模型</h4>
                <button class="modal-close-btn" onclick="this.closest('.model-popup-modal').remove(); document.querySelector('.modal-backdrop').remove();">×</button>
            </div>
            <div class="modal-body">
                <div class="model-popup-grid">
                    <!-- Claude 4 系列 -->
                    <div class="model-card" data-model="claude-opus-4-20250514" onclick="selectModel(this)">
                        <div class="model-card-name">Claude 4 Opus</div>
                        <div class="model-card-desc">🚀 最強大，300K tokens，複雜分析首選</div>
                        <div class="model-card-badge new">NEW</div>
                    </div>
                    <div class="model-card selected" data-model="claude-sonnet-4-20250514" onclick="selectModel(this)">
                        <div class="model-card-name">Claude 4 Sonnet</div>
                        <div class="model-card-desc">⚡ 推薦！250K tokens，平衡效能</div>
                        <div class="model-card-badge new">NEW</div>
                    </div>
                    
                    <!-- Claude 3.5 系列 -->
                    <div class="model-card" data-model="claude-3-5-sonnet-20241022" onclick="selectModel(this)">
                        <div class="model-card-name">Claude 3.5 Sonnet</div>
                        <div class="model-card-desc">快速準確，適合一般分析</div>
                    </div>
                    <div class="model-card" data-model="claude-3-5-haiku-20241022" onclick="selectModel(this)">
                        <div class="model-card-name">Claude 3.5 Haiku</div>
                        <div class="model-card-desc">輕量快速，簡單分析</div>
                    </div>
                    
                    <!-- Claude 3 系列 -->
                    <div class="model-card" data-model="claude-3-opus-20240229" onclick="selectModel(this)">
                        <div class="model-card-name">Claude 3 Opus</div>
                        <div class="model-card-desc">深度分析，詳細但較慢</div>
                    </div>
                    <div class="model-card" data-model="claude-3-haiku-20240307" onclick="selectModel(this)">
                        <div class="model-card-name">Claude 3 Haiku</div>
                        <div class="model-card-desc">經濟實惠，基本分析</div>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    const modal = showModalDialog(contentHTML);
    modal.dialog.classList.add('model-popup-modal');
    
    // 選中當前模型
    const currentModelCard = modal.dialog.querySelector(`.model-card[data-model="${selectedModel}"]`);
    if (currentModelCard) {
        currentModelCard.classList.add('selected');
    }
}

// 統一的彈跳視窗顯示函數
// 統一的彈跳視窗顯示函數
function showModalDialog(contentHTML, onResolve) {
    // 檢查是否在全屏模式
    const rightPanel = document.querySelector('.right-panel.fullscreen-mode');
    const isFullscreen = !!rightPanel;
    
    // 創建背景遮罩
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    
    if (isFullscreen) {
        // 全屏模式下
        backdrop.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.6);
            z-index: 999998;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        rightPanel.appendChild(backdrop);
    } else {
        // 正常模式
        backdrop.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.6);
            z-index: 999998;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        document.body.appendChild(backdrop);
    }
    
    // 創建對話框容器
    const modalContainer = document.createElement('div');
    
    if (isFullscreen) {
        modalContainer.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 999999;
            pointer-events: none;
        `;
        rightPanel.appendChild(modalContainer);
    } else {
        modalContainer.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 999999;
            pointer-events: none;
        `;
        document.body.appendChild(modalContainer);
    }
    
    // 創建對話框
    const dialog = document.createElement('div');
    dialog.className = 'modal-dialog';
    dialog.style.cssText = `
        pointer-events: all;
        max-width: 600px;
        width: 90%;
        max-height: 80vh;
        background: #252526;
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        animation: modalSlideIn 0.3s ease;
        position: relative;
        z-index: 999999;
    `;
    
    dialog.innerHTML = contentHTML;
    modalContainer.appendChild(dialog);
    
    // 返回控制對象
    return {
        close: () => {
            backdrop.remove();
            modalContainer.remove();
        },
        backdrop,
        dialog,
        container: modalContainer
    };
}

function handleModelPopupOutsideClick(e) {
	const selector = document.querySelector('.model-selector');
	if (!selector || !selector.contains(e.target)) {
		const popup = document.getElementById('modelPopup');
		if (popup) {
			popup.classList.remove('show');
		}
		document.removeEventListener('click', handleModelPopupOutsideClick);
	}
}

// 選擇模型
function selectModel(card) {
    const model = card.dataset.model;
    const modelName = card.querySelector('.model-card-name').textContent;
    
    // 更新選中狀態
    document.querySelectorAll('.model-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    
    // 更新顯示的模型名稱
    const selectedModelNameInline = document.getElementById('selectedModelNameInline');
    if (selectedModelNameInline) {
        selectedModelNameInline.textContent = modelName;
    }
    
    // 更新全局變量
    selectedModel = model;
    console.log('Selected model:', selectedModel);
    
    // 關閉彈窗 - 修正這裡
    const popup = document.getElementById('modelPopup');
    if (popup) {
        popup.style.display = 'none';
    }
    
    // 移除背景遮罩
    const backdrop = document.querySelector('.modal-backdrop');
    if (backdrop) {
        backdrop.remove();
    }
}

// 新增模型選擇按鈕樣式
const modelSelectBtnStyle = `
<style>
.model-select-btn {
	display: flex;
	align-items: center;
	gap: 8px;
	background: #2d2d30;
	border: 1px solid #3e3e42;
	border-radius: 6px;
	padding: 8px 12px;
	color: #d4d4d4;
	font-size: 13px;
	cursor: pointer;
	transition: all 0.2s;
	height: 36px;
}

.model-select-btn:hover {
	border-color: #007acc;
	background: #3e3e42;
}

.dropdown-arrow {
	font-size: 10px;
	opacity: 0.7;
}

/* 調整輸入控制區佈局 */
.input-controls {
	display: flex;
	gap: 10px;
	align-items: center;
	justify-content: space-between;  /* 兩端對齊 */
	height: 36px;
}

/* 調整發送按鈕樣式 */
.ask-ai-btn {
	height: 36px;
	padding: 0 20px;
	font-size: 14px;
}
</style>`;

// 在 DOMContentLoaded 時注入樣式
document.addEventListener('DOMContentLoaded', function() {
	const styleElement = document.createElement('div');
	styleElement.innerHTML = modelSelectBtnStyle;
	document.head.appendChild(styleElement.querySelector('style'));

	document.getElementById('modelSelectInlineBtn').onclick = function(e) {
		e.preventDefault();
		e.stopPropagation();

		const popup = document.getElementById('modelPopup');
		const modelSelectInlineBtn = document.getElementById('modelSelectInlineBtn');

		if (popup.style.display === 'block') {
			popup.style.display = 'none';
			const backdrop = document.querySelector('.modal-backdrop');
			if (backdrop) backdrop.remove();
		} else {
			// 先創建背景遮罩
			let backdrop = document.querySelector('.modal-backdrop');
			if (!backdrop) {
				backdrop = document.createElement('div');
				backdrop.className = 'modal-backdrop';
				
				// 檢查是否在全屏模式
				const rightPanel = document.querySelector('.right-panel.fullscreen-mode');
				
				if (rightPanel) {
					// 全屏模式下
					backdrop.style.cssText = `
						position: absolute;
						top: 0;
						left: 0;
						width: 100%;
						height: 100%;
						background: rgba(0, 0, 0, 0.6);
						z-index: 999998;  /* 比彈窗低 */
					`;
					rightPanel.appendChild(backdrop);
				} else {
					// 正常模式
					backdrop.style.cssText = `
						position: fixed;
						top: 0;
						left: 0;
						width: 100%;
						height: 100%;
						background: rgba(0, 0, 0, 0.6);
						z-index: 999998;  /* 比彈窗低 */
					`;
					document.body.appendChild(backdrop);
				}
				
				backdrop.onclick = () => {
					popup.style.display = 'none';
					backdrop.remove();
				};
			}

			// 顯示彈窗
			popup.style.display = 'block';

			// 檢查是否在全屏模式
			const isFullscreen = document.querySelector('.right-panel.fullscreen-mode');
			
			if (isFullscreen) {
				// 全屏模式下使用相對定位
				popup.style.cssText = `
					display: block !important;
					position: absolute !important;
					top: 50% !important;
					left: 50% !important;
					transform: translate(-50%, -50%) !important;
					background: #252526 !important;
					border: 2px solid #667eea !important;
					border-radius: 12px !important;
					box-shadow: 0 8px 32px rgba(0, 0, 0, 0.8) !important;
					padding: 15px !important;
					z-index: 999999 !important;  /* 確保在背景遮罩之上 */
					min-width: 500px !important;
					min-height: 200px !important;
					height: auto !important;
					max-height: 80vh !important;
					overflow-y: auto !important;
				`;
				
				// 確保彈窗在 rightPanel 內部
				const rightPanel = document.querySelector('.right-panel');
				if (popup.parentElement !== rightPanel) {
					rightPanel.appendChild(popup);
				}
			} else {
				// 正常模式下的定位
				const buttonRect = modelSelectInlineBtn.getBoundingClientRect();
				const popupTop = buttonRect.bottom - 150;
				const popupLeft = buttonRect.left - 100;
				
				popup.style.cssText = `
					display: block !important;
					position: fixed !important;
					top: ${popupTop}px !important;
					left: ${popupLeft}px !important;
					background: #252526 !important;
					border: 2px solid #667eea !important;
					border-radius: 12px !important;
					box-shadow: 0 8px 32px rgba(0, 0, 0, 0.8) !important;
					padding: 15px !important;
					z-index: 999999 !important;  /* 確保在背景遮罩之上 */
					min-width: 500px !important;
					min-height: 200px !important;
					height: auto !important;
				`;
			}
		}
	};
	
	// 綁定模型卡片點擊事件
	document.querySelectorAll('.model-card').forEach(card => {
		card.addEventListener('click', function(e) {
			e.preventDefault();
			e.stopPropagation();
			selectModel(this);
		});
	});

	// 初始化選中的模型卡片
	const initialModel = document.querySelector(`.model-card[data-model="${selectedModel}"]`);
	if (initialModel) {
		initialModel.classList.add('selected');
	}
});  

// 更新清空對話歷史的功能
function clearConversationHistory() {
	if (confirm('確定要清空所有對話記錄嗎？')) {
		conversationHistory = [];
		const responseContent = document.getElementById('aiResponseContent');
		if (responseContent) {
			// 清空所有內容
			responseContent.innerHTML = ``;
		}
		console.log('對話歷史已清空');
	}
}
	
// AI 分析配置
const AI_ANALYSIS_CONFIG = {
	enableThinking: true,
	autoSegment: true,
	showProgress: true,
	maxRetries: 3
};

// 檢查檔案大小
async function checkFileSizeForAI() {
	try {
		const response = await fetch('/check-file-size-for-ai', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ content: fileContent })
		});
		
		return await response.json();
	} catch (error) {
		console.error('Size check error:', error);
		return { strategy: 'single', suggested_segments: 1 };
	}
}

// 顯示分段分析對話框
async function showSegmentedAnalysisDialog(sizeInfo) {
    return new Promise((resolve) => {
        const contentHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h4>📊 ${getAnalysisModeTitle()}</h4>
                    <button class="modal-close-btn" onclick="window.resolveDialog(false)">×</button>
                </div>
                <div class="modal-body">
                    <p>${getAnalysisModeDescription(sizeInfo)}</p>
                    <div class="dialog-info">
                        <div class="info-item">
                            <span class="info-label">檔案大小：</span>
                            <span class="info-value">${(sizeInfo.content_length / 1024 / 1024).toFixed(1)} MB</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">預估 Token：</span>
                            <span class="info-value">${sizeInfo.estimated_tokens.toLocaleString()}</span>
                        </div>
                        ${sizeInfo.suggested_segments > 1 ? `
                        <div class="info-item">
                            <span class="info-label">建議分段：</span>
                            <span class="info-value">${sizeInfo.suggested_segments} 段</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">預估時間：</span>
                            <span class="info-value">約 ${Math.ceil(sizeInfo.estimated_time / 60)} 分鐘</span>
                        </div>
                        ` : ''}
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="window.resolveDialog(false)">取消</button>
                    <button class="btn btn-primary" onclick="window.resolveDialog(true)">繼續分析</button>
                </div>
            </div>
        `;
        
        const modal = showModalDialog(contentHTML);
        
        window.resolveDialog = (proceed) => {
            modal.close();
            resolve(proceed);
        };
        
        // 點擊背景關閉
        modal.backdrop.addEventListener('click', (e) => {
            if (e.target === modal.backdrop) {
                modal.close();
                resolve(false);
            }
        });
    });
}

// 更新進度容器以顯示速率限制信息
function createProgressContainer(sizeInfo) {
	const container = document.createElement('div');
	container.className = 'analysis-progress-container';
	
	// 計算預估時間
	const estimatedSeconds = sizeInfo.suggested_segments * 5; // 每段約5秒
	const estimatedMinutes = Math.ceil(estimatedSeconds / 60);
	
	container.innerHTML = `
		<div class="progress-header">
			<h3>🔄 正在分析檔案...</h3>
			<div class="progress-stats">
				<span>總段數：${sizeInfo.suggested_segments || 1}</span>
				<span id="currentSegment">當前：1</span>
				<span id="elapsedTime">已用時：0秒</span>
			</div>
		</div>
		<div class="progress-info">
			<p>預計需要 <strong>${estimatedMinutes}</strong> 分鐘完成分析</p>
			<p id="progressMessage">正在準備分析...</p>
		</div>
		<div class="progress-bar-container">
			<div class="progress-bar">
				<div class="progress-fill animated" id="analysisProgress" style="width: 0%">
					<div class="progress-glow"></div>
				</div>
			</div>
			<div class="progress-text" id="progressText">0%</div>
		</div>
		<div class="segment-results" id="segmentResults"></div>
	`;
	
	// 開始計時
	startProgressTimer();
	
	return container;
}

// 計時器功能
let progressStartTime = null;
let progressTimerInterval = null;

function startProgressTimer() {
	progressStartTime = Date.now();
	progressTimerInterval = setInterval(updateProgressTimer, 1000);
}

function updateProgressTimer() {
	if (!progressStartTime) return;
	
	const elapsed = Math.floor((Date.now() - progressStartTime) / 1000);
	const minutes = Math.floor(elapsed / 60);
	const seconds = elapsed % 60;
	
	const elapsedTimeElement = document.getElementById('elapsedTime');
	if (elapsedTimeElement) {
		if (minutes > 0) {
			elapsedTimeElement.textContent = `已用時：${minutes}分${seconds}秒`;
		} else {
			elapsedTimeElement.textContent = `已用時：${seconds}秒`;
		}
	}
}

function stopProgressTimer() {
	if (progressTimerInterval) {
		clearInterval(progressTimerInterval);
		progressTimerInterval = null;
	}
	progressStartTime = null;
}

// 更新進度訊息
function updateProgressMessage(message) {
	const messageElement = document.getElementById('progressMessage');
	if (messageElement) {
		messageElement.textContent = message;
	}
}

// 更新顯示分段分析結果以處理速率限制
async function displaySegmentedAnalysis(data, progressContainer) {
	const segmentResults = document.getElementById('segmentResults');
	const progressFill = document.getElementById('analysisProgress');
	const progressText = document.getElementById('progressText');
	const currentSegmentSpan = document.getElementById('currentSegment');
	
	// 顯示初始進度
	let processedSegments = 0;
	
	// 如果是實時更新，使用 WebSocket 或輪詢
	// 這裡使用模擬的漸進式更新
	for (let i = 0; i < data.segments.length; i++) {
		const segment = data.segments[i];
		if (!segment) continue;
		
		processedSegments++;
		const progress = (processedSegments / data.total_segments * 100).toFixed(0);
		
		// 更新進度條
		progressFill.style.width = `${progress}%`;
		progressText.textContent = `${progress}%`;
		currentSegmentSpan.textContent = `當前：${processedSegments}`;
		
		// 更新進度訊息
		updateProgressMessage(`正在處理第 ${processedSegments} 段，共 ${data.total_segments} 段...`);
		
		// 顯示段落結果
		const segmentDiv = createSegmentResultDiv(segment, processedSegments, data.total_segments);
		segmentResults.appendChild(segmentDiv);
		
		// 添加動畫延遲，讓進度條有時間更新
		await new Promise(resolve => setTimeout(resolve, 200));
		segmentDiv.classList.add('show');
	}
	
	// 確保最後顯示 100%
	progressFill.style.width = '100%';
	progressText.textContent = '100%';
	updateProgressMessage('分析完成！正在生成報告...');
	
	// 分析完成，停止計時器
	stopProgressTimer();

	// 如果有錯誤，顯示錯誤摘要（包含速率限制信息）
	if (data.errors && data.errors.length > 0) {
		const errorSummary = document.createElement('div');
		errorSummary.className = 'error-summary';
		
		errorSummary.innerHTML = `
			<div class="ai-warning">
				⚠️ 有 ${data.errors.length} 個段落分析失敗
				<details>
					<summary>查看詳情</summary>
					<ul>
						${data.errors.map(err => 
							`<li>段落 ${err.segment}: ${escapeHtml(err.error)}
							${err.retry_count ? ` (重試 ${err.retry_count} 次)` : ''}</li>`
						).join('')}
					</ul>
				</details>
			</div>
		`;
		segmentResults.appendChild(errorSummary);
	}
	
	// 延遲顯示完整分析
	setTimeout(() => {
		if (progressContainer && progressContainer.parentNode) {
			progressContainer.remove();
		}
		
		// 只有在有有效段落時才顯示完整分析
		if (hasValidSegments) {
			displayFullAnalysis(data);
		} else {
			showAnalysisError('所有段落分析都失敗了，可能是速率限制問題。請稍後再試或使用較小的檔案。');
		}
	}, 1000);
}

// 注入樣式
function showAnalysisError(errorMessage) {
    const responseContent = document.getElementById('aiResponseContent');
    if (!responseContent) return;
    
    const errorDiv = document.createElement('div');
    errorDiv.className = 'ai-error';
    errorDiv.innerHTML = `
        <h3>❌ 分析失敗</h3>
        <p>${escapeHtml(errorMessage || '發生未知錯誤')}</p>
        <p style="margin-top: 10px;">
            <button class="retry-btn" onclick="startSmartAnalysis()">🔄 重試</button>
        </p>
    `;
    
    responseContent.appendChild(errorDiv);
    conversationHistory.push(errorDiv);
}

// 創建段落結果顯示
function createSegmentResultDiv(segment, num, total) {
	const div = document.createElement('div');
	div.className = 'segment-result-item';
	
	const hasError = segment.error || !segment.success;
	const errorMessage = segment.error_message || '未知錯誤';
	
	div.innerHTML = `
		<div class="segment-header">
			<span class="segment-number">段落 ${num}/${total}</span>
			<span class="segment-range">${segment.char_range || ''}</span>
			${hasError ? 
				`<span class="error-badge" title="${escapeHtml(errorMessage)}">錯誤</span>` : 
				'<span class="success-badge">完成</span>'
			}
		</div>
		${segment.thinking && !hasError ? `
			<details class="segment-thinking">
				<summary>🧠 思考過程</summary>
				<pre>${escapeHtml(segment.thinking)}</pre>
			</details>
		` : ''}
		<div class="segment-summary">
			${hasError ? 
				`<div class="error-content">
					<strong>分析失敗：</strong> ${escapeHtml(errorMessage)}
					${errorMessage.includes('prompt is too long') ? 
						'<br><small>提示：這個段落太大，請考慮使用更小的檔案或聯繫技術支援。</small>' : 
						''
					}
				</div>` : 
				extractSegmentSummary(segment.analysis)
			}
		</div>
	`;
	
	return div;
}

// 顯示單次分析結果（非分段）
function displaySingleAnalysis(data) {
	const responseContent = document.getElementById('aiResponseContent');
	
	if (!responseContent) {
		console.error('找不到 AI 回應區域');
		return;
	}
	
	// 移除 loading
	const loadingDiv = responseContent.querySelector('.ai-loading');
	if (loadingDiv) {
		loadingDiv.remove();
	}
	
	// 使用現有的 displayAIAnalysis 函數
	displayAIAnalysis(
		data.analysis,
		data.truncated,
		data.model,
		false,
		data.thinking
	);
}

// 添加分析警告樣式
const analysisWarningStyle = `
<style>
.analysis-warning {
	background: #ff9800;
	color: white;
	padding: 15px;
	border-radius: 8px;
	margin: 15px 0;
}

.analysis-warning strong {
	font-weight: 600;
}

.analysis-warning details {
	margin-top: 10px;
}

.analysis-warning summary {
	cursor: pointer;
	font-weight: 500;
	outline: none;
}

.analysis-warning ul {
	margin: 10px 0 0 20px;
	padding: 0;
}

.analysis-warning li {
	list-style: disc;
	margin: 5px 0;
}

/* 確保對話項目有正確的間距 */
.conversation-item {
	margin-bottom: 20px;
	padding-bottom: 20px;
	border-bottom: 1px solid #3e3e42;
	animation: fadeInUp 0.5s ease;
}

.conversation-item:last-child {
	border-bottom: none;
}

/* 添加淡入動畫 */
@keyframes fadeInUp {
	from {
		opacity: 0;
		transform: translateY(20px);
	}
	to {
		opacity: 1;
		transform: translateY(0);
	}
}
</style>`;

// 在 DOMContentLoaded 時注入樣式
document.addEventListener('DOMContentLoaded', function() {
	// 注入分析警告樣式
	const styleElement = document.createElement('div');
	styleElement.innerHTML = analysisWarningStyle;
	const style = styleElement.querySelector('style');
	if (style) {
		document.head.appendChild(style);
	}
});

// 顯示完整分析結果（包含思考日誌）
function displayFullAnalysis(data) {
	const responseContent = document.getElementById('aiResponseContent');
	
	if (!responseContent) {
		console.error('找不到 AI 回應區域');
		return;
	}
	
	// 建立完整的分析顯示
	let analysisHTML = `
		<div class="full-analysis-container">
			<div class="analysis-header">
				<h3>📊 綜合分析結果</h3>
				<div class="analysis-meta">
					<span>模型：${getModelDisplayName(data.model || selectedModel)}</span>
					<span>分析段數：${data.total_segments}</span>
					${data.thinking_log ? '<span>包含深度思考</span>' : ''}
				</div>
			</div>
	`;
	
	// 如果有錯誤，顯示警告
	if (data.errors && data.errors.length > 0) {
		analysisHTML += `
			<div class="analysis-warning">
				<strong>⚠️ 注意：</strong>有 ${data.errors.length} 個段落分析失敗，結果可能不完整。
				<details style="margin-top: 10px;">
					<summary>查看失敗詳情</summary>
					<ul style="margin-top: 5px;">
						${data.errors.map(err => 
							`<li>段落 ${err.segment}: ${escapeHtml(err.error)}</li>`
						).join('')}
					</ul>
				</details>
			</div>
		`;
	}
	
	// 如果有思考日誌，顯示它
	if (data.thinking_log && data.thinking_log.length > 0) {
		analysisHTML += `
			<div class="thinking-log-container">
				<details class="thinking-log">
					<summary>
						<span class="thinking-icon">🧠</span>
						深度思考過程（點擊展開）
					</summary>
					<div class="thinking-content">
						${data.thinking_log.map(log => `
							<div class="thinking-stage">
								<h4>${escapeHtml(log.stage)}</h4>
								<pre>${escapeHtml(log.content || '')}</pre>
							</div>
						`).join('')}
					</div>
				</details>
			</div>
		`;
	}
	
	// 主要分析內容
	const fullAnalysis = data.full_analysis || '無分析結果';
	analysisHTML += `
		<div class="analysis-content">
			${formatAnalysisContent(fullAnalysis)}
		</div>
	`;
	
	// 段落詳細信息（可選）
	if (data.segments && data.segments.length > 1) {
		const validSegments = data.segments.filter(seg => !seg.error && seg.analysis);
		if (validSegments.length > 0) {
			analysisHTML += `
				<details class="segments-detail">
					<summary>📋 查看各段落詳細分析 (${validSegments.length}/${data.segments.length} 成功)</summary>
					<div class="segments-list">
						${validSegments.map((seg, i) => `
							<div class="segment-detail">
								<h4>段落 ${seg.segment_number}</h4>
								<div class="segment-analysis">
									${formatAnalysisContent(seg.analysis)}
								</div>
							</div>
						`).join('')}
					</div>
				</details>
			`;
		}
	}
	
	analysisHTML += '</div>';
	
	// 創建對話項目
	const conversationItem = createConversationItem('分段分析', analysisHTML, data);
	
	// 添加到對話歷史
	conversationHistory.push(conversationItem);
	
	responseContent.appendChild(conversationItem);
	
	// 滾動到結果
	setTimeout(() => {
		conversationItem.scrollIntoView({ behavior: 'smooth', block: 'end' });
	}, 100);
}

// 創建對話項目
function createConversationItem(mode) {
    const modeInfo = {
        'smart': { icon: '🧠', name: '智能分析' },
        'quick': { icon: '⚡', name: '快速分析' },
        'deep': { icon: '🔍', name: '深度分析' }
    }[mode];
    
    const conversationItem = document.createElement('div');
    conversationItem.className = 'ai-conversation-item';
    conversationItem.id = `conversation-${Date.now()}`;
    
    conversationItem.innerHTML = `
        <div class="ai-conversation-header">
            <div class="conversation-meta">
                <span class="mode-indicator">
                    <span class="mode-icon">${modeInfo.icon}</span>
                    <span class="mode-text">${modeInfo.name}</span>
                </span>
                <span class="model-info">${selectedModel}</span>
                <span class="timestamp">${new Date().toLocaleTimeString()}</span>
            </div>
            <div class="conversation-actions">
                <button class="copy-btn" onclick="copyAIResponse('${conversationItem.id}')">
                    📋 複製
                </button>
                <button class="export-html-btn" onclick="exportSingleResponse('${conversationItem.id}', 'html')">
                    🌐 HTML
                </button>
                <button class="export-md-btn" onclick="exportSingleResponse('${conversationItem.id}', 'markdown')">
                    📝 MD
                </button>
            </div>
        </div>
        <div class="ai-conversation-content">
            <div class="ai-thinking">
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
    
    // 添加到對話歷史
    conversationHistory.push(conversationItem);
    
    return conversationItem;
}

// 提取段落摘要
function extractSegmentSummary(analysisText) {
	// 檢查輸入
	if (!analysisText || typeof analysisText !== 'string') {
		return '無摘要內容';
	}
	
	try {
		// 提取前幾行或關鍵發現
		const lines = analysisText.split('\n').filter(line => line.trim());
		
		if (lines.length === 0) {
			return '無摘要內容';
		}
		
		const summary = lines.slice(0, 3).join('<br>');
		return summary.length > 200 ? summary.substring(0, 200) + '...' : summary;
	} catch (error) {
		console.error('Error extracting segment summary:', error);
		return analysisText.substring(0, 200) + '...';
	}
}

//====================================================================================

// 修正的智能分析函數
async function startSmartAnalysis() {
    const btn = document.getElementById('analyzeBtn');
    const responseDiv = document.getElementById('aiResponse');
    const responseContent = document.getElementById('aiResponseContent');
    
    if (!btn || !responseContent || isAnalyzing) return;
    
    isAnalyzing = true;
    
    // 使用選中的模式
    const mode = selectedAnalysisMode;
    const modeConfig = ANALYSIS_MODES[mode];
    
    console.log('開始智能分析 - 模式:', mode);
    
    // 更新按鈕狀態
    btn.disabled = true;
    btn.classList.add('loading');
    btn.innerHTML = `<div class="ai-spinner"></div> ${modeConfig.icon} 分析中...`;
    
    responseDiv.classList.add('active');
    
    // 快速分析模式：跳過檔案大小檢查，直接分析
    if (mode === 'quick') {
        // 直接執行快速分析，不檢查檔案大小
        try {
            const progressDiv = createQuickAnalysisProgress();
            responseContent.appendChild(progressDiv);
            
            const response = await fetch('/smart-analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_path: filePath,
                    content: fileContent,
                    mode: 'quick',  // 強制快速模式
                    file_type: filePath.toLowerCase().includes('tombstone') ? 'Tombstone' : 'ANR',
                    force_single_analysis: true,  // 強制單次分析
                    skip_size_check: true  // 跳過大小檢查
                })
            });
            
            const data = await response.json();
            progressDiv.remove();
            
            if (response.ok && data.success) {
                const normalizedData = normalizeAnalysisData(data, mode);
                displaySmartAnalysisResult(normalizedData, modeConfig);
            } else {
                throw new Error(data.error || '分析失敗');
            }
			
        } catch (error) {
            console.error('Quick analysis error:', error);
            showAnalysisError(error.message);			
        } finally {
            resetAnalyzeButton();
        }
        return;
    }
    
    // 其他模式：先檢查檔案大小
    try {
        // 檢查檔案大小（但傳遞模式信息）
        const sizeCheck = await checkFileSizeWithMode(mode);
        
        // 根據模式決定是否顯示分段對話框
        if (shouldShowSegmentDialog(mode, sizeCheck)) {
            const proceed = await showSegmentedAnalysisDialog(sizeCheck);
            if (!proceed) {
                resetAnalyzeButton();
                return;
            }
        }

        // 執行分析
        const response = await fetch('/smart-analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                file_path: filePath,
                content: fileContent,
                mode: mode,
                file_type: filePath.toLowerCase().includes('tombstone') ? 'Tombstone' : 'ANR',
                enable_thinking: document.getElementById('enableDeepThinking')?.checked || false
            })
        });
        
        const data = await response.json();

        if (response.ok && data.success) {
            const normalizedData = normalizeAnalysisData(data, mode);
            displaySmartAnalysisResult(normalizedData, modeConfig);
        } else {
            throw new Error(data.error || '分析失敗');
        }
        
    } catch (error) {
        console.error('Analysis error:', error);
    } finally {
        resetAnalyzeButton();
    }
}

async function checkFileSizeWithMode(mode) {
    try {
        const response = await fetch('/check-file-size-for-ai', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                content: fileContent,
                mode: mode  // 傳遞模式信息
            })
        });
        
        return await response.json();
    } catch (error) {
        console.error('Size check error:', error);
        return { strategy: 'single', suggested_segments: 1 };
    }
}

function createQuickAnalysisProgress() {
    const div = document.createElement('div');
    div.className = 'analysis-progress quick-mode';
    div.innerHTML = `
        <h4>⚡ 正在執行快速分析...</h4>
        <div class="ai-loading">
            <div class="ai-spinner"></div>
            <div>預計 30 秒內完成</div>
        </div>
        <div class="progress-stats">
            <span class="mode-indicator" style="color: #ffd700;">快速模式</span>
        </div>
    `;
    return div;
}

function createAnalysisProgress(mode) {
    const div = document.createElement('div');
    div.className = 'analysis-progress';
    
    const modeMessages = {
        'quick': '正在執行快速分析，預計 30 秒內完成...',
        'comprehensive': '正在執行深度分析，可能需要 2-5 分鐘...',
        'max_tokens': '正在最大化分析內容...',
        'auto': '正在智能分析檔案...'
    };
    
    div.innerHTML = `
        <div class="ai-loading">
            <div class="ai-spinner"></div>
            <div>${modeMessages[mode] || '正在分析...'}</div>
        </div>
    `;
    
    return div;
}

function createQuickAnalysisDisplay(data, modeConfig) {
    return `
        <div class="quick-analysis-content">
            <div class="result-header">
                <div class="mode-indicator">
                    <span class="mode-icon">${modeConfig.icon}</span>
                    <span class="mode-name">${modeConfig.name}</span>
                    <span class="mode-badge">${modeConfig.badge}</span>
                </div>
                <div class="result-meta">
                    <span>模型：${getModelDisplayName(data.model)}</span>
                    <span>耗時：${data.elapsed_time}</span>
                </div>
            </div>
            <div class="analysis-summary">
                ${formatAnalysisContent(data.analysis)}
            </div>
            ${data.analyzed_size ? `
                <div class="analysis-info">
                    分析了 ${(data.analyzed_size/1024).toFixed(1)}KB / ${(data.original_size/1024).toFixed(1)}KB
                </div>
            ` : ''}
        </div>
    `;
}

function createSegmentedAnalysisDisplay(data, modeConfig) {
    let html = `
        <div class="segmented-analysis-content">
            <div class="result-header">
                <div class="mode-indicator">
                    <span class="mode-icon">${modeConfig.icon}</span>
                    <span class="mode-name">${modeConfig.name}</span>
                    <span class="mode-badge">${modeConfig.badge}</span>
                </div>
                <div class="result-meta">
                    <span>模型：${getModelDisplayName(data.model)}</span>
                    <span>分 ${data.total_segments} 段分析</span>
                </div>
            </div>
    `;
    
    // 顯示綜合分析
    html += `
        <div class="final-analysis">
            <h3>📊 綜合分析結果</h3>
            ${formatAnalysisContent(data.analysis)}
        </div>
    `;
    
    // 可選：顯示各段落詳情
    if (data.segments && data.segments.length > 0) {
        html += `
            <details class="segments-detail">
                <summary>查看各段落分析詳情</summary>
                <div class="segments-list">
                    ${data.segments.map(seg => `
                        <div class="segment-item">
                            <h4>段落 ${seg.segment_number || seg.segment}</h4>
                            <div>${seg.analysis || '無內容'}</div>
                        </div>
                    `).join('')}
                </div>
            </details>
        `;
    }
    
    html += '</div>';
    return html;
}

function createStandardAnalysisDisplay(data, modeConfig) {
    return `
        <div class="standard-analysis-content">
            <div class="result-header">
                <div class="mode-indicator">
                    <span class="mode-icon">${modeConfig.icon}</span>
                    <span class="mode-name">${modeConfig.name}</span>
                    <span class="mode-badge">${modeConfig.badge}</span>
                </div>
                <div class="result-meta">
                    <span>模型：${getModelDisplayName(data.model)}</span>
                    <span>耗時：${data.elapsed_time}</span>
                </div>
            </div>
            <div class="ai-response-item">
                <div class="ai-icon">🤖</div>
                <div class="ai-message">
                    ${data.truncated ? '<div class="ai-warning">⚠️ 由於檔案過大，只分析了部分內容</div>' : ''}
                    <div class="ai-analysis-content">
                        ${formatAnalysisContent(data.analysis)}
                    </div>
                    ${data.thinking ? `
                        <details class="ai-thinking-section">
                            <summary>🧠 AI 思考過程</summary>
                            <div class="thinking-content">
                                <pre>${escapeHtml(data.thinking)}</pre>
                            </div>
                        </details>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
}

function formatStructuredResult(result) {
    // 格式化結構化的分析結果
    let formatted = '';
    
    if (result.summary) {
        formatted += `<h3>📋 問題摘要</h3><p>${result.summary}</p>`;
    }
    
    if (result.root_cause) {
        formatted += `<h3>🎯 根本原因</h3><p>${result.root_cause}</p>`;
    }
    
    if (result.affected_processes && result.affected_processes.length > 0) {
        formatted += `<h3>📱 受影響的進程</h3><ul>`;
        result.affected_processes.forEach(proc => {
            formatted += `<li>${escapeHtml(proc)}</li>`;
        });
        formatted += '</ul>';
    }
    
    if (result.recommendations && result.recommendations.length > 0) {
        formatted += `<h3>💡 建議解決方案</h3><ul>`;
        result.recommendations.forEach(rec => {
            formatted += `<li>${escapeHtml(rec)}</li>`;
        });
        formatted += '</ul>';
    }
    
    return formatted;
}

function normalizeAnalysisData(data, mode) {
    // 確保數據格式一致
    const normalized = {
        success: true,
        analysis_mode: mode,
        model: data.model || selectedModel,
        elapsed_time: data.elapsed_time || 'N/A',
        is_segmented: data.is_segmented || false,
        truncated: data.truncated || false
    };
    
    // 根據不同的返回格式提取分析內容
    if (data.analysis) {
        normalized.analysis = data.analysis;
    } else if (data.result) {
        // 處理結構化結果
        if (typeof data.result === 'object') {
            normalized.analysis = formatStructuredResult(data.result);
            normalized.structured_result = data.result;
        } else {
            normalized.analysis = data.result;
        }
    } else if (data.final_report) {
        normalized.analysis = data.final_report;
    } else {
        normalized.analysis = '無分析結果';
    }
    
    // 處理分段結果
    if (data.is_segmented) {
        normalized.segments = data.segments || data.segment_results || [];
        normalized.total_segments = data.total_segments || normalized.segments.length;
    }
    
    // 額外的元數據
    if (data.analyzed_size) normalized.analyzed_size = data.analyzed_size;
    if (data.original_size) normalized.original_size = data.original_size;
    if (data.thinking) normalized.thinking = data.thinking;
    
    return normalized;
}

function selectAnalysisMode(mode, showToast = true) {
    if (!ANALYSIS_MODES[mode]) return;
    
    // 更新選中狀態
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    const selectedBtn = document.querySelector(`.mode-btn[data-mode="${mode}"]`);
    if (selectedBtn) {
        selectedBtn.classList.add('active');
    }
    
    // 更新描述
    const descriptions = {
        'auto': '自動選擇最佳分析策略，平衡速度與深度',
        'quick': '30秒內快速獲得關鍵分析結果',
        'comprehensive': '深入分析每個細節，提供完整診斷報告',
        'max_tokens': '在 token 限制內最大化分析內容'
    };
    
    const descElement = document.getElementById('modeDescription');
    if (descElement) {
        descElement.textContent = descriptions[mode] || '';
    }
    
    // 更新全局變量
    selectedAnalysisMode = mode;
    
    // 更新分析按鈕
    updateAnalyzeButton(mode);
    
    // 只在需要時顯示選擇提示
    if (showToast) {
        showModeSelectionToast(mode);
    }
}

// 更新分析按鈕的函數
function updateAnalyzeButton(mode) {
    const btn = document.getElementById('analyzeBtn');
    const icon = document.getElementById('analyzeIcon');
    const text = document.getElementById('analyzeText');
    
    if (!btn || !ANALYSIS_MODES[mode]) return;
    
    const modeConfig = ANALYSIS_MODES[mode];
    
    // 更新按鈕內容
    if (icon) icon.textContent = modeConfig.icon;
    if (text) text.textContent = modeConfig.buttonText;
    
    // 更新按鈕樣式
    btn.style.background = modeConfig.buttonColor;
    btn.style.transform = 'scale(1.05)';
    setTimeout(() => {
        btn.style.transform = 'scale(1)';
    }, 200);
}

// 顯示模式選擇提示
function showModeSelectionToast(mode) {
    const modeConfig = ANALYSIS_MODES[mode];
    if (!modeConfig) return;
    
    // 移除舊的提示
    const oldToast = document.querySelector('.mode-selection-toast');
    if (oldToast) oldToast.remove();
    
    // 創建新提示
    const toast = document.createElement('div');
    toast.className = 'mode-selection-toast';
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: #667eea;
        color: white;
        padding: 12px 24px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        z-index: 10000;
        animation: slideIn 0.3s ease;
        display: flex;
        align-items: center;
        gap: 10px;
    `;
    
    toast.innerHTML = `
        <span style="font-size: 20px;">${modeConfig.icon}</span>
        <span>已選擇：${modeConfig.name} 模式</span>
    `;
    
    document.body.appendChild(toast);
    
    // 3秒後自動消失
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// 顯示智能分析結果
function displaySmartAnalysisResult(data, modeConfig) {
    const responseContent = document.getElementById('aiResponseContent');
    
    if (!responseContent) {
        console.error('找不到 AI 回應區域');
        return;
    }
    
    // 創建對話項目
    const conversationItem = document.createElement('div');
    conversationItem.className = 'conversation-item smart-analysis-result';
    
    let resultHTML = `
        <div class="conversation-header">
            <span class="conversation-icon">${modeConfig.icon}</span>
            <span class="conversation-type">${modeConfig.name}</span>
            <span class="conversation-time">${new Date().toLocaleString('zh-TW')}</span>
        </div>
    `;
    
    // 檢查是否有分段結果
    if (data.is_segmented && data.segments && data.segments.length > 0) {
        // 分段分析結果
        resultHTML += `
            <div class="segmented-analysis-result">
                <div class="result-header">
                    <div class="mode-indicator">
                        <span class="mode-icon">${modeConfig.icon}</span>
                        <span class="mode-name">${modeConfig.name}</span>
                        ${modeConfig.badge ? `<span class="mode-badge">${modeConfig.badge}</span>` : ''}
                    </div>
                    <div class="result-meta">
                        <span>模型：${getModelDisplayName(data.model)}</span>
                        <span>分 ${data.total_segments} 段分析</span>
                        ${data.elapsed_time ? `<span>耗時：${data.elapsed_time}</span>` : ''}
                    </div>
                </div>
                
                <!-- 綜合分析 -->
                <div class="final-analysis-section">
                    <h3 class="section-title">📊 綜合分析結果</h3>
                    <div class="analysis-content">
                        ${formatAnalysisContent(data.analysis || data.full_analysis || '')}
                    </div>
                </div>
                
                <!-- 各段落詳情 -->
                ${data.segments.length > 0 ? `
                    <details class="segments-details">
                        <summary class="segments-summary">
                            <span class="summary-icon">📋</span>
                            查看各段落詳細分析（共 ${data.segments.length} 段）
                        </summary>
                        <div class="segments-container">
                            ${data.segments.map((seg, index) => `
                                <div class="segment-item ${seg.success ? 'success' : 'error'}">
                                    <div class="segment-header">
                                        <span class="segment-number">段落 ${seg.segment_number || index + 1}</span>
                                        ${seg.success ? 
                                            '<span class="segment-status success">✓ 完成</span>' : 
                                            '<span class="segment-status error">✗ 失敗</span>'
                                        }
                                    </div>
                                    <div class="segment-content">
                                        ${seg.success ? 
                                            formatAnalysisContent(seg.analysis || '') : 
                                            `<p class="error-message">${escapeHtml(seg.error || '分析失敗')}</p>`
                                        }
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </details>
                ` : ''}
            </div>
        `;
    } else {
        // 單次分析結果
        resultHTML += `
            <div class="single-analysis-result">
                <div class="result-header">
                    <div class="mode-indicator">
                        <span class="mode-icon">${modeConfig.icon}</span>
                        <span class="mode-name">${modeConfig.name}</span>
                        ${modeConfig.badge ? `<span class="mode-badge">${modeConfig.badge}</span>` : ''}
                    </div>
                    <div class="result-meta">
                        <span>模型：${getModelDisplayName(data.model)}</span>
                        ${data.elapsed_time ? `<span>耗時：${data.elapsed_time}</span>` : ''}
                    </div>
                </div>
                <div class="analysis-content">
                    ${formatAnalysisContent(data.analysis || '')}
                </div>
            </div>
        `;
    }
    
    conversationItem.innerHTML = resultHTML;
    
    // 添加到對話歷史
    conversationHistory.push(conversationItem);
    responseContent.appendChild(conversationItem);
    
    // 自動滾動到結果
    setTimeout(() => {
        conversationItem.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 100);
}

// 格式化分析內容
function formatAnalysisContent(content) {
    if (!content || typeof content !== 'string') {
        return '<p>無分析內容</p>';
    }
    
    try {
        let formatted = content;
        
        // 先處理特殊字符
        formatted = formatted.replace(/\*\*\*/g, '');  // 移除多餘的星號
        
        // 處理編號標題（例如：1. 標題、2. 標題）
        formatted = formatted.replace(/^(\d+)\.\s*([^：:]+)[:：]\s*$/gm, 
            '<h3 class="gpt-numbered-title"><span class="title-number">$1.</span> $2</h3>');
        
        // 處理帶圖標的標題
        formatted = formatted.replace(/^([🎯🔍📋💡🛡️⚠️🚨📊🔧💾📚#]+)\s*(.+?)[:：]?\s*$/gm, 
            '<h3 class="gpt-icon-title"><span class="title-icon">$1</span> $2</h3>');
        
        // 處理 Markdown 標題
        formatted = formatted.replace(/^####\s+(.+)$/gm, '<h5 class="gpt-h5">$1</h5>');
        formatted = formatted.replace(/^###\s+(.+)$/gm, '<h4 class="gpt-h4">$1</h4>');
        formatted = formatted.replace(/^##\s+(.+)$/gm, '<h3 class="gpt-h3">$1</h3>');
        formatted = formatted.replace(/^#\s+(.+)$/gm, '<h2 class="gpt-h2">$1</h2>');
        
        // 處理子編號（例如：1.1, 2.3）
        formatted = formatted.replace(/^(\d+\.\d+)\s+(.+)$/gm, 
            '<div class="gpt-sub-numbered"><span class="sub-number">$1</span> $2</div>');
        
        // 處理列表項目
        formatted = formatted.replace(/^\s*[-•]\s+(.+)$/gm, 
            '<div class="gpt-bullet-item"><span class="bullet">•</span> $1</div>');
        
        // 處理縮進的列表項目
        formatted = formatted.replace(/^\s{2,}[-•]\s+(.+)$/gm, 
            '<div class="gpt-sub-bullet"><span class="sub-bullet">◦</span> $1</div>');
        
        // 處理數字列表
        formatted = formatted.replace(/^(\d+)\.\s+([^：:\n]+)$/gm, 
            '<div class="gpt-numbered-item"><span class="number">$1.</span> $2</div>');
        
        // 處理粗體
        formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        
        // 處理行內代碼
        formatted = formatted.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
        
        // 處理代碼塊
        formatted = formatted.replace(/```(\w*)\n([\s\S]*?)```/g, function(match, lang, code) {
            return `<pre class="code-block"><code class="language-${lang}">${escapeHtml(code.trim())}</code></pre>`;
        });
        
        // 處理段落和空行
        const lines = formatted.split('\n');
        const processedLines = [];
        let inParagraph = false;
        let paragraphContent = [];
        
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            
            if (!line) {
                // 空行，結束當前段落
                if (paragraphContent.length > 0) {
                    processedLines.push(`<p class="gpt-paragraph">${paragraphContent.join(' ')}</p>`);
                    paragraphContent = [];
                    inParagraph = false;
                }
                continue;
            }
            
            // 檢查是否是已處理的特殊格式
            if (line.match(/^<[^>]+>/)) {
                // 先處理未完成的段落
                if (paragraphContent.length > 0) {
                    processedLines.push(`<p class="gpt-paragraph">${paragraphContent.join(' ')}</p>`);
                    paragraphContent = [];
                    inParagraph = false;
                }
                processedLines.push(line);
            } else {
                // 普通文本，加入段落
                paragraphContent.push(line);
                inParagraph = true;
            }
        }
        
        // 處理最後的段落
        if (paragraphContent.length > 0) {
            processedLines.push(`<p class="gpt-paragraph">${paragraphContent.join(' ')}</p>`);
        }
        
        return `<div class="gpt-content">${processedLines.join('\n')}</div>`;
        
    } catch (error) {
        console.error('格式化錯誤:', error);
        return `<div class="gpt-content"><p>${escapeHtml(content)}</p></div>`;
    }
}

// 判斷是否需要顯示分段對話框
function shouldShowSegmentDialog(mode, sizeInfo) {
    // 快速分析：永遠不顯示
    if (mode === 'quick') return false;
    
    // 其他模式的邏輯保持不變
    if (mode === 'max_tokens') {
        return sizeInfo.estimated_tokens > sizeInfo.max_tokens_per_request;
    }
    
    if (mode === 'comprehensive') {
        return sizeInfo.suggested_segments > 2;
    }
    
    if (mode === 'auto') {
        return sizeInfo.strategy === 'segmented' && sizeInfo.suggested_segments > 3;
    }
    
    return false;
}

// 獲取分析模式標題
function getAnalysisModeTitle() {
    const titles = {
        'comprehensive': '深度分析模式',
        'max_tokens': '最大化分析模式',
        'auto': '智能分析模式'
    };
    return titles[selectedAnalysisMode] || '檔案分析';
}

// 獲取分析模式描述
function getAnalysisModeDescription(sizeInfo) {
    if (selectedAnalysisMode === 'comprehensive') {
        return `檔案較大，深度分析需要分成 ${sizeInfo.suggested_segments} 段進行詳細診斷。這將提供最全面的分析結果。`;
    } else if (selectedAnalysisMode === 'max_tokens') {
        return `檔案超過單次分析限制，將分成 ${sizeInfo.suggested_segments} 段，在 token 限制內提供最大化的分析。`;
    } else if (selectedAnalysisMode === 'auto') {
        return `根據檔案特徵，系統建議分成 ${sizeInfo.suggested_segments} 段進行智能分析，以獲得最佳結果。`;
    }
    return `檔案將分成 ${sizeInfo.suggested_segments} 段進行分析。`;
}

// 顯示選擇提示的函數
function showSelectionToast(mode) {
    // 移除舊的提示
    const oldToast = document.querySelector('.mode-selection-toast');
    if (oldToast) oldToast.remove();
    
    // 創建新提示
    const toast = document.createElement('div');
    toast.className = 'mode-selection-toast';
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: #667eea;
        color: white;
        padding: 12px 24px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        z-index: 10000;
        animation: slideIn 0.3s ease;
    `;
    
    const modeNames = {
        'auto': '智能分析',
        'quick': '快速分析',
        'comprehensive': '深度分析',
        'max_tokens': '最大化分析'
    };
    
    toast.textContent = `已選擇：${modeNames[mode] || mode} 模式`;
    document.body.appendChild(toast);
    
    // 3秒後自動消失
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// 添加滑入滑出動畫
const toastStyle = document.createElement('style');
toastStyle.innerHTML = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(toastStyle);

document.addEventListener('DOMContentLoaded', function() {
    // 初始化分析模式
    initializeAnalysisModes();

    // 1. 分析按鈕 - 處理 4 種模式
    const analyzeBtn = document.getElementById('analyzeBtn');
    if (analyzeBtn) {
        analyzeBtn.addEventListener('click', function(e) {
            e.preventDefault();
            startSmartAnalysis();  // 會根據 selectedAnalysisMode 執行
        });
    }
    
    // 2. 自定義問題發送按鈕
    const askBtn = document.getElementById('askBtnInline');
    if (askBtn) {
        askBtn.addEventListener('click', function(e) {
            e.preventDefault();
            askCustomQuestion();  // 處理使用者輸入
        });
    }
    
    // 3. Enter 鍵發送
    const customQuestion = document.getElementById('customQuestion');
    if (customQuestion) {
        customQuestion.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey && !isAskingQuestion) {
                e.preventDefault();
                askCustomQuestion();
            }
        });
    }
});

function initializeAnalysisModes() {
    // 設置默認模式，但不顯示提示
    selectedAnalysisMode = 'auto';
    
    // 更新按鈕狀態
    const autoBtn = document.querySelector('.mode-btn[data-mode="auto"]');
    if (autoBtn) {
        autoBtn.classList.add('active');
        updateAnalyzeButton('auto');
    }
    
    // 設置描述
    const descElement = document.getElementById('modeDescription');
    if (descElement) {
        descElement.textContent = '自動選擇最佳分析策略，平衡速度與深度';
    }
}

// 更新深度分析顯示
function createComprehensiveAnalysisDisplay(data, modeConfig) {
    return `
        <div class="comprehensive-analysis-content">
            <div class="result-header">
                <div class="mode-indicator">
                    <span class="mode-icon">${modeConfig.icon}</span>
                    <span class="mode-name">${modeConfig.name}</span>
                    ${modeConfig.badge ? `<span class="mode-badge">${modeConfig.badge}</span>` : ''}
                </div>
                <div class="result-meta">
                    <span>模型：${getModelDisplayName(data.model)}</span>
                    ${data.elapsed_time ? `<span>耗時：${data.elapsed_time}</span>` : ''}
                </div>
            </div>
            ${createStructuredAnalysisDisplay(data.analysis)}
        </div>
    `;
}

function createStructuredAnalysisDisplay(content) {
    // 解析內容，識別不同的部分
    const sections = parseAnalysisContent(content);
    
    let html = '<div class="structured-analysis">';
    
    sections.forEach(section => {
        html += `
            <div class="analysis-section">
                <h3 class="section-title">
                    <span class="section-icon">${section.icon}</span>
                    ${section.title}
                </h3>
                <div class="section-content">
                    ${formatSectionContent(section.content)}
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    return html;
}

// 解析分析內容
function parseAnalysisContent(content) {
    const sections = [];
    
    // 定義區段模式和對應的圖標（ChatGPT 風格）
    const sectionPatterns = [
        { pattern: /^🔍\s*(.+?)[:：]?$/m, icon: '🔍', title: null },
        { pattern: /^🎯\s*(.+?)[:：]?$/m, icon: '🎯', title: null },
        { pattern: /^📋\s*(.+?)[:：]?$/m, icon: '📋', title: null },
        { pattern: /^💡\s*(.+?)[:：]?$/m, icon: '💡', title: null },
        { pattern: /^⚠️\s*(.+?)[:：]?$/m, icon: '⚠️', title: null },
        { pattern: /^🚨\s*(.+?)[:：]?$/m, icon: '🚨', title: null },
        { pattern: /^🛡️\s*(.+?)[:：]?$/m, icon: '🛡️', title: null },
        { pattern: /^📊\s*(.+?)[:：]?$/m, icon: '📊', title: null },
        { pattern: /^🔧\s*(.+?)[:：]?$/m, icon: '🔧', title: null },
        { pattern: /^💾\s*(.+?)[:：]?$/m, icon: '💾', title: null },
    ];
    
    // 使用更智能的分段方式
    let currentPos = 0;
    const contentLength = content.length;
    
    while (currentPos < contentLength) {
        let found = false;
        let nearestMatch = null;
        let nearestPos = contentLength;
        
        // 尋找下一個區段
        for (const { pattern, icon } of sectionPatterns) {
            const match = content.slice(currentPos).match(pattern);
            if (match && match.index < nearestPos) {
                nearestMatch = {
                    match: match,
                    icon: icon,
                    title: match[1],
                    position: currentPos + match.index
                };
                nearestPos = match.index;
                found = true;
            }
        }
        
        if (found && nearestMatch) {
            // 提取這個區段的內容
            const nextSectionStart = findNextSectionStart(content, nearestMatch.position + nearestMatch.match[0].length, sectionPatterns);
            const sectionContent = content.slice(nearestMatch.position + nearestMatch.match[0].length, nextSectionStart).trim();
            
            sections.push({
                icon: nearestMatch.icon,
                title: nearestMatch.title,
                content: sectionContent
            });
            
            currentPos = nextSectionStart;
        } else {
            // 沒有找到更多區段
            break;
        }
    }
    
    // 如果沒有找到任何區段，將整個內容作為一個區段
    if (sections.length === 0) {
        sections.push({
            icon: '📄',
            title: '分析結果',
            content: content
        });
    }
    
    return sections;
}

function findNextSectionStart(content, fromIndex, patterns) {
    let nearestPos = content.length;
    
    for (const { pattern } of patterns) {
        const match = content.slice(fromIndex).match(pattern);
        if (match && fromIndex + match.index < nearestPos) {
            nearestPos = fromIndex + match.index;
        }
    }
    
    return nearestPos;
}

// 格式化區段內容
function formatSectionContent(content) {
    if (!content) return '';
    
    // 處理代碼塊
    content = content.replace(/```([\s\S]*?)```/g, '<pre class="code-block"><code>$1</code></pre>');
    
    // 處理編號列表 (1. 2. 3. 等)
    content = content.replace(/^(\d+)\.\s+(.+)$/gm, (match, num, text) => {
        return `<li class="numbered-item" data-number="${num}">${text}</li>`;
    });
    
    // 處理無序列表
    content = content.replace(/^\s*[-•]\s+(.+)$/gm, '<li class="bullet-item">$1</li>');
    
    // 將連續的列表項包裝起來
    content = content.replace(/(<li class="numbered-item"[^>]*>.*?<\/li>\s*)+/g, 
        '<ol class="formatted-list numbered">$&</ol>');
    content = content.replace(/(<li class="bullet-item">.*?<\/li>\s*)+/g, 
        '<ul class="formatted-list bullet">$&</ul>');
    
    // 處理粗體和代碼
    content = content
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    
    // 處理子標題 (##, ###)
    content = content.replace(/^###\s+(.+)$/gm, '<h4 class="sub-heading">$1</h4>');
    content = content.replace(/^##\s+(.+)$/gm, '<h3 class="sub-heading">$1</h3>');
    
    // 處理段落
    const lines = content.split('\n');
    let formatted = '';
    let inParagraph = false;
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        
        if (!line) {
            if (inParagraph) {
                formatted += '</p>';
                inParagraph = false;
            }
            continue;
        }
        
        // 如果是 HTML 標籤開頭，直接添加
        if (line.startsWith('<')) {
            if (inParagraph) {
                formatted += '</p>';
                inParagraph = false;
            }
            formatted += line + '\n';
        } else {
            // 否則作為段落處理
            if (!inParagraph) {
                formatted += '<p class="formatted-paragraph">';
                inParagraph = true;
            }
            formatted += line + ' ';
        }
    }
    
    if (inParagraph) {
        formatted += '</p>';
    }
    
    return formatted;
}

// 在分析前儲存動作，以便重試
function saveLastAnalysisAction(action) {
    window.lastAnalysisAction = action;
}

// 修改 startSmartAnalysis 以儲存動作
const originalStartSmartAnalysis = startSmartAnalysis;
startSmartAnalysis = async function() {
    saveLastAnalysisAction(() => originalStartSmartAnalysis());
    return originalStartSmartAnalysis();
};

// 修改 askCustomQuestion 以儲存動作
const originalAskCustomQuestion = askCustomQuestion;
askCustomQuestion = async function() {
    const question = document.getElementById('customQuestion').value;
    saveLastAnalysisAction(() => {
        document.getElementById('customQuestion').value = question;
        originalAskCustomQuestion();
    });
    return originalAskCustomQuestion();
};