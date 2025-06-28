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

// Search optimization variables
const SEARCH_DELAY = 500; // 500ms 延遲
const MIN_SEARCH_LENGTH = 2; // 最少輸入 2 個字元才搜尋

// AI Panel State
let isAIPanelOpen = false;
let selectedModel = 'claude-4-sonnet-20250514';
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
    },
    'max_tokens': {
        name: '最大分析',
        description: '在 token 限制內最大化分析',
        icon: '📊',
        badge: '平衡',
        badgeClass: '',
        buttonText: '最大化分析',
        buttonColor: 'linear-gradient(135deg, #ff6b6b, #ff8787)'
    }
};

// 當前選中的分析模式
let selectedAnalysisMode = 'auto';

function toggleAIFullscreen() {
	const rightPanel = document.getElementById('rightPanel');
	const fullscreenIcon = document.getElementById('fullscreenIcon');
	const mainContainer = document.querySelector('.main-container');
	const modals = document.querySelectorAll('.ai-info-modal, .export-modal, .segmented-analysis-dialog');

	isAIFullscreen = !isAIFullscreen;

	if (isAIFullscreen) {
		rightPanel.classList.add('fullscreen-mode');
		mainContainer.classList.add('ai-fullscreen');
		fullscreenIcon.textContent = '⛶';

		// 將彈窗掛入 rightPanel
		modals.forEach(modal => rightPanel.appendChild(modal));

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

    if (e) { // Check if e is defined (i.e., if called from an event listener)
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
		
		// 檢查是否需要設置 token 計數
		setTimeout(() => {
			// 只有在不存在時才設置
			if (!document.getElementById('realtimeTokenCount')) {
				setupRealtimeTokenCount();
			}
		}, 300);
	} else {
		rightPanel.classList.remove('active');
		resizeHandle.classList.remove('active');
		aiBtn.classList.remove('active');
		if (isAIFullscreen)
			toggleAIFullscreen();
	}
}

// Analyze current file
async function analyzeCurrentFile() {
    const btn = document.getElementById('analyzeBtn');
    const btnText = document.getElementById('btnText');
    
    if (isAnalyzing) return;
    
    // 檢查是否有選中的分析模式
    const selectedCard = document.querySelector('.mode-card.selected');
    if (!selectedCard) {
        // 如果沒有選中，默認選擇 auto
        selectAnalysisMode('auto');
    }
    
    // 使用智能分析
    return startSmartAnalysis();
}

// 重置分析按鈕狀態
function resetAnalyzeButton() {
	const analyzeBtn = document.getElementById('analyzeBtn');
	if (analyzeBtn) {
		analyzeBtn.classList.remove('loading');
		analyzeBtn.disabled = false;
		analyzeBtn.innerHTML = '<span>🔍</span> 分析本文';
	}
	isAnalyzing = false;
}

document.addEventListener('DOMContentLoaded', function() {
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
	const modal = document.getElementById('aiInfoModal');
	if (modal) {
		if (modal.style.display === 'none' || !modal.style.display) {
			modal.style.display = 'flex';
			// 添加點擊外部關閉的功能
			modal.addEventListener('click', handleModalOutsideClick);
		} else {
			modal.style.display = 'none';
			modal.removeEventListener('click', handleModalOutsideClick);
		}
	}
}

// 點擊彈出視窗外部關閉
function handleModalOutsideClick(e) {
	const modal = document.getElementById('aiInfoModal');
	const modalContent = modal.querySelector('.ai-info-modal-content');
	
	if (e.target === modal && !modalContent.contains(e.target)) {
		toggleAIInfo();
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
function useQuickQuestion(question) {
	const customQuestionElement = document.getElementById('customQuestion');
	if (customQuestionElement) {
		customQuestionElement.value = question;
		// 關閉下拉選單
		const menu = document.getElementById('quickQuestionsMenu');
		if (menu) {
			menu.classList.remove('show');
		}
		// 自動觸發 AI 分析
		askCustomQuestion();
	}
}

// 匯出對話功能
function exportAIChat() {
	const modal = document.getElementById('exportModal');
	if (modal) {
		modal.style.display = 'flex';
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

// 更新模型選擇邏輯
function updateModelSelection() {
	const select = document.getElementById('aiModelSelect');
	if (select) {
		select.addEventListener('change', function() {
			selectedModel = this.value;
			console.log('Selected model:', selectedModel);
		});
		
		// 設定初始值
		select.value = selectedModel;
	}
}


// 拖曳分隔線功能
function initializeResizeDivider() {
	const divider = document.getElementById('aiResizeDivider');
	const chatArea = document.getElementById('aiChatArea');
	const inputArea = document.getElementById('aiInputArea');
	const rightPanel = document.getElementById('rightPanel');
	
	if (!divider || !chatArea || !inputArea || !rightPanel) return;
	
	let isResizing = false;
	let startY = 0;
	let startChatHeight = 0;
	let startInputHeight = 0;
	
	// 設定初始狀態
	function setInitialSizes() {
		const totalHeight = rightPanel.offsetHeight;
		const headerHeight = rightPanel.querySelector('.ai-panel-header').offsetHeight;
		const dividerHeight = divider.offsetHeight;
		const availableHeight = totalHeight - headerHeight - dividerHeight;
		
		// 預設：對話區 70%，輸入區 30%
		const defaultChatHeight = availableHeight * 0.7;
		const defaultInputHeight = availableHeight * 0.3;
		
		chatArea.style.height = `${defaultChatHeight}px`;
		chatArea.style.flex = 'none';
		inputArea.style.height = `${defaultInputHeight}px`;
		inputArea.style.flex = 'none';
	}
	
	// 初始化大小
	setTimeout(setInitialSizes, 100);
	
	// 拖曳開始
	divider.addEventListener('mousedown', function(e) {
		isResizing = true;
		startY = e.clientY;
		startChatHeight = chatArea.offsetHeight;
		startInputHeight = inputArea.offsetHeight;
		
		// 添加拖曳中的樣式
		divider.classList.add('dragging');
		document.body.style.cursor = 'ns-resize';
		document.body.style.userSelect = 'none';
		
		// 防止文字選取
		e.preventDefault();
	});
	
	// 拖曳移動
	document.addEventListener('mousemove', function(e) {
		if (!isResizing) return;
		
		const deltaY = e.clientY - startY;
		const totalHeight = rightPanel.offsetHeight;
		const headerHeight = rightPanel.querySelector('.ai-panel-header').offsetHeight;
		const dividerHeight = divider.offsetHeight;
		const availableHeight = totalHeight - headerHeight - dividerHeight;
		
		// 計算新的高度
		let newChatHeight = startChatHeight + deltaY;
		let newInputHeight = startInputHeight - deltaY;
		
		// 設定最小高度限制
		const minHeight = 50; // 最小高度 50px
		
		// 應用限制
		if (newChatHeight < minHeight) {
			newChatHeight = minHeight;
			newInputHeight = availableHeight - minHeight;
		} else if (newInputHeight < minHeight) {
			newInputHeight = minHeight;
			newChatHeight = availableHeight - minHeight;
		}
		
		// 確保總高度不超過可用高度
		if (newChatHeight + newInputHeight > availableHeight) {
			const ratio = availableHeight / (newChatHeight + newInputHeight);
			newChatHeight *= ratio;
			newInputHeight *= ratio;
		}
		
		// 設定高度
		chatArea.style.height = `${newChatHeight}px`;
		chatArea.style.flex = 'none';
		inputArea.style.height = `${newInputHeight}px`;
		inputArea.style.flex = 'none';
		
		// 觸發 resize 事件
		window.dispatchEvent(new Event('resize'));
	});
	
	// 拖曳結束
	document.addEventListener('mouseup', function() {
		if (isResizing) {
			isResizing = false;
			divider.classList.remove('dragging');
			document.body.style.cursor = '';
			document.body.style.userSelect = '';
			
			// 儲存當前比例（可選）
			const totalHeight = rightPanel.offsetHeight;
			const headerHeight = rightPanel.querySelector('.ai-panel-header').offsetHeight;
			const dividerHeight = divider.offsetHeight;
			const availableHeight = totalHeight - headerHeight - dividerHeight;
			
			const chatRatio = chatArea.offsetHeight / availableHeight;
			const inputRatio = inputArea.offsetHeight / availableHeight;
			
			console.log('Resize complete. Ratios:', {
				chat: (chatRatio * 100).toFixed(1) + '%',
				input: (inputRatio * 100).toFixed(1) + '%'
			});
		}
	});
	
	// 視窗大小改變時保持比例
	window.addEventListener('resize', function() {
		if (!isResizing) {
			const totalHeight = rightPanel.offsetHeight;
			const headerHeight = rightPanel.querySelector('.ai-panel-header').offsetHeight;
			const dividerHeight = divider.offsetHeight;
			const availableHeight = totalHeight - headerHeight - dividerHeight;
			
			// 保持當前比例
			const currentChatHeight = chatArea.offsetHeight;
			const currentInputHeight = inputArea.offsetHeight;
			const totalCurrent = currentChatHeight + currentInputHeight;
			
			if (totalCurrent > 0) {
				const chatRatio = currentChatHeight / totalCurrent;
				const inputRatio = currentInputHeight / totalCurrent;
				
				chatArea.style.height = `${availableHeight * chatRatio}px`;
				inputArea.style.height = `${availableHeight * inputRatio}px`;
			}
		}
	});
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
	askBtn.innerHTML = '➤ 發送中...';
	
	responseDiv.classList.add('active');
	
	// 創建新的 loading 元素
	const loadingDiv = document.createElement('div');
	loadingDiv.className = 'ai-loading';
	loadingDiv.innerHTML = `
		<div class="ai-spinner"></div>
		<div>正在使用 ${getModelDisplayName(selectedModel)} 處理您的問題...</div>
	`;
	responseContent.appendChild(loadingDiv);
	
	// 滾動到 loading 元素
	setTimeout(() => {
		loadingDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
	}, 100);
	
	try {
		// 構建包含檔案內容的上下文
		const fileInfo = `檔案名稱: ${fileName}\n檔案路徑: ${filePath}\n`;
		const fileContext = `=== 當前檔案內容 ===\n${fileContent}\n=== 檔案內容結束 ===\n\n`;
		
		// 組合問題和檔案上下文（使用保存的問題內容）
		const fullContent = `${fileInfo}${fileContext}使用者問題：${questionToSend}`;
		
		// 發送自訂問題請求
		const response = await fetch('/analyze-with-ai', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				file_path: filePath,
				content: fullContent,
				file_type: 'custom_with_context',
				model: selectedModel,
				is_custom_question: true,
				original_question: questionToSend  // 使用保存的問題內容
			})
		});
		
		// 移除 loading
		if (loadingDiv && loadingDiv.parentNode) {
			loadingDiv.remove();
		}
		
		const data = await response.json();
		
		if (response.ok && data.success) {
			// 確保所有必要的資料都存在
			const analysisText = data.analysis || '無分析結果';
			const truncatedFlag = data.truncated || false;
			const modelUsed = data.model || selectedModel;
			const questionText = questionToSend || '無問題內容';
			const thinkingContent = data.thinking || null;
			
			// 顯示分析結果
			displayAIAnalysisWithContext(
				analysisText,
				truncatedFlag,
				modelUsed,
				questionText,
				thinkingContent
			);
		} else {
			// 顯示錯誤
			const errorDiv = document.createElement('div');
			errorDiv.className = 'ai-error';
			errorDiv.innerHTML = `
				<h3>❌ 分析失敗</h3>
				<p>${escapeHtml(data.error || '無法完成 AI 分析')}</p>
				${data.details ? `<p><small>${escapeHtml(data.details)}</small></p>` : ''}
			`;
			responseContent.appendChild(errorDiv);
			conversationHistory.push(errorDiv);
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
}

// 添加重試函數
function retryQuestion(question) {
	const customQuestionElement = document.getElementById('customQuestion');
	if (customQuestionElement) {
		customQuestionElement.value = question;
		askCustomQuestion();
	}
}

// 添加分段分析按鈕
function addSegmentAnalysisOption() {
	const quickMenu = document.getElementById('quickQuestionsMenu');
	if (quickMenu) {
		const segmentOption = document.createElement('button');
		segmentOption.className = 'quick-question-item';
		segmentOption.innerHTML = '📊 分段分析大檔案';
		segmentOption.onclick = () => analyzeInSegments();
		quickMenu.appendChild(segmentOption);
	}
}

// 分段分析函數
async function analyzeInSegments(customQuestion = null) {
	const responseContent = document.getElementById('aiResponseContent');
	
	// 準備內容
	const fileInfo = `檔案名稱: ${fileName}\n檔案路徑: ${filePath}\n`;
	const fullFileContent = fileContent;
	const question = customQuestion || '請分析這個檔案';
	
	// 檢查是否需要分段
	const checkResponse = await fetch('/check-content-size', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ content: fullFileContent })
	});
	
	const sizeInfo = await checkResponse.json();
	
	if (!sizeInfo.needs_segmentation) {
		// 不需要分段，直接分析
		return askCustomQuestion();
	}
	
	// 確認分段分析
	const proceed = confirm(
		`檔案較大，建議分成 ${sizeInfo.suggested_segments} 段進行分析。\n` +
		`每段約 ${(sizeInfo.max_chars_per_segment / 1024).toFixed(0)} KB。\n\n` +
		`是否繼續？`
	);
	
	if (!proceed) return;
	
	// 顯示分段分析進度
	const progressDiv = document.createElement('div');
	progressDiv.className = 'segment-analysis-progress';
	progressDiv.innerHTML = `
		<h3>🔄 分段分析中...</h3>
		<div class="progress-bar">
			<div class="progress-fill" style="width: 0%"></div>
		</div>
		<p class="progress-text">正在分析第 1/${sizeInfo.suggested_segments} 段...</p>
	`;
	responseContent.appendChild(progressDiv);
	
	// 分段並分析
	const segmentSize = sizeInfo.max_chars_per_segment;
	const segments = [];
	let segmentContext = '';
	
	for (let i = 0; i < sizeInfo.suggested_segments; i++) {
		const start = i * segmentSize;
		const end = Math.min((i + 1) * segmentSize, fullFileContent.length);
		const segmentContent = fullFileContent.substring(start, end);
		
		// 更新進度
		const progress = ((i + 1) / sizeInfo.suggested_segments * 100).toFixed(0);
		progressDiv.querySelector('.progress-fill').style.width = `${progress}%`;
		progressDiv.querySelector('.progress-text').textContent = 
			`正在分析第 ${i + 1}/${sizeInfo.suggested_segments} 段...`;
		
		// 構建分段內容
		const segmentFullContent = 
			`${fileInfo}=== 當前檔案內容 ===\n${segmentContent}\n=== 檔案內容結束 ===\n\n使用者問題：${question}`;
		
		try {
			// 發送分段分析請求
			const response = await fetch('/analyze-with-ai', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					file_path: filePath,
					content: segmentFullContent,
					file_type: 'custom_with_context',
					model: selectedModel,
					is_custom_question: true,
					original_question: question,
					is_segment_analysis: true,
					segment_number: i + 1,
					total_segments: sizeInfo.suggested_segments,
					segment_context: segmentContext
				})
			});
			
			const result = await response.json();
			
			if (result.success) {
				segments.push(result);
				// 使用本段摘要作為下一段的上下文
				segmentContext = result.segment_summary || '';
				
				// 顯示每段的結果
				displaySegmentResult(result, i + 1, sizeInfo.suggested_segments);
			}
			
		} catch (error) {
			console.error(`分析第 ${i + 1} 段時出錯:`, error);
		}
	}
	
	// 移除進度條
	progressDiv.remove();
	
	// 顯示綜合摘要
	displaySegmentSummary(segments);
}

// 改進的前端分析函數
async function analyzeCurrentFileWithProgress() {
	if (isAnalyzing) {
		console.log('已經在分析中，請稍候...');
		return;
	}
	
	const analyzeBtn = document.getElementById('analyzeBtn');
	const responseDiv = document.getElementById('aiResponse');
	const responseContent = document.getElementById('aiResponseContent');
	
	isAnalyzing = true;
	
	// 更新按鈕狀態
	analyzeBtn.classList.add('loading');
	analyzeBtn.disabled = true;
	analyzeBtn.innerHTML = '<span>⏳</span> 準備分析...';
	
	// 創建進度容器
	const progressContainer = createProgressContainer();
	responseContent.appendChild(progressContainer);
	
	try {
		const fileType = filePath.toLowerCase().includes('tombstone') ? 'Tombstone' : 'ANR';
		
		// 使用 EventSource 進行 SSE 連接
		const eventSource = new EventSource('/analyze-with-ai-stream', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				file_path: filePath,
				content: fileContent,
				file_type: fileType,
				model: selectedModel,
				enable_thinking: true
			})
		});
		
		let segmentResults = [];
		
		eventSource.onmessage = function(event) {
			const data = JSON.parse(event.data);
			
			switch(data.type) {
				case 'init':
					console.log('分析開始', data.request_id);
					break;
					
				case 'segments':
					updateProgressInfo(progressContainer, {
						total_segments: data.total,
						message: `檔案將分成 ${data.total} 段進行分析`
					});
					break;
					
				case 'progress':
					updateProgressBar(progressContainer, data);
					break;
					
				case 'rate_limit':
					showRateLimitWarning(progressContainer, data);
					break;
					
				case 'segment_complete':
					segmentResults.push(data.result);
					displaySegmentResult(progressContainer, data.result);
					break;
					
				case 'segment_error':
					displaySegmentError(progressContainer, data);
					break;
					
				case 'synthesizing':
					updateProgressInfo(progressContainer, {
						message: data.message
					});
					break;
					
				case 'final':
					eventSource.close();
					handleFinalResult(progressContainer, data.result);
					break;
					
				case 'error':
					eventSource.close();
					showAnalysisError(data.error);
					break;
					
				case 'complete':
					eventSource.close();
					displaySingleAnalysis(data.result);
					break;
			}
		};
		
		eventSource.onerror = function(error) {
			console.error('SSE 錯誤:', error);
			eventSource.close();
			showAnalysisError('連接中斷，請重試');
			resetAnalyzeButton();
		};
		
	} catch (error) {
		console.error('分析錯誤:', error);
		showAnalysisError(error.message);
		resetAnalyzeButton();
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

// 顯示速率限制警告
function showRateLimitWarning(container, data) {
	const warningDiv = container.querySelector('#rateLimitWarning');
	const messageSpan = container.querySelector('#rateLimitMessage');
	
	if (warningDiv) {
		warningDiv.style.display = 'flex';
		if (messageSpan) {
			messageSpan.textContent = data.message;
		}
		
		// 倒計時顯示
		let remainingTime = Math.ceil(data.wait_time);
		const countdown = setInterval(() => {
			remainingTime--;
			if (remainingTime <= 0) {
				clearInterval(countdown);
				warningDiv.style.display = 'none';
			} else {
				messageSpan.textContent = `等待速率限制重置 (${remainingTime}秒)...`;
			}
		}, 1000);
	}
}

// 顯示分段結果
function displaySegmentResult(container, result) {
	const segmentResults = container.querySelector('#segmentResults');
	if (!segmentResults) return;
	
	const segmentDiv = document.createElement('div');
	segmentDiv.className = 'segment-result-item';
	
	if (result.success) {
		// 顯示成功的段落摘要
		const summary = extractSegmentSummary(result.analysis);
		segmentDiv.innerHTML = `
			<div class="segment-header">
				<span class="segment-number">段落 ${result.segment_number}</span>
				<span class="success-badge">✓ 完成</span>
			</div>
			<div class="segment-summary">${summary}</div>
		`;
	} else {
		// 顯示錯誤
		segmentDiv.innerHTML = `
			<div class="segment-header">
				<span class="segment-number">段落 ${result.segment_number}</span>
				<span class="error-badge">✗ 錯誤</span>
			</div>
			<div class="error-content">${escapeHtml(result.error || '未知錯誤')}</div>
		`;
	}
	
	segmentResults.appendChild(segmentDiv);
	
	// 添加淡入動畫
	setTimeout(() => {
		segmentDiv.classList.add('show');
	}, 50);
}

// 顯示綜合摘要
function displaySegmentSummary(segments) {
	if (segments.length === 0) return;
	
	const summaryDiv = document.createElement('div');
	summaryDiv.className = 'segment-summary';
	summaryDiv.innerHTML = `
		<h3>📊 綜合分析摘要</h3>
		<p>已完成 ${segments.length} 段的分析。</p>
		<div class="summary-content">
			${segments.map((seg, i) => `
				<div class="summary-item">
					<strong>第 ${i + 1} 段：</strong>
					${seg.segment_summary || '無摘要'}
				</div>
			`).join('')}
		</div>
	`;
	
	document.getElementById('aiResponseContent').appendChild(summaryDiv);
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
	
	// 初始化拖曳功能
	initializeResizeDivider();

	// 使用改進的拖曳功能
	improvedResizeDivider();

	// 設定輸入框自動調整高度
	setupAutoResizeTextarea();
	
	// 初始化模型選擇
	updateModelSelection();

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
function displayAIAnalysisWithContext(analysis, truncated, model, originalQuestion, thinking = null) {
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
		// 這裡需要定義 truncatedLength 和 originalLength 變數
		const truncatedLength = analysis ? analysis.length : 0;
		const originalLength = fileContent ? fileContent.length : 0;
		
		conversationHTML += `
			<div style="background: #ff9800; color: white; padding: 10px; border-radius: 6px; margin-bottom: 15px;">
				<strong>⚠️ 注意：</strong>由於檔案過大，AI 只分析了前 ${(truncatedLength/1024).toFixed(1)}KB 的內容（原始檔案大小：${(originalLength/1024).toFixed(1)}KB）。
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

	// 優化：延遲載入和虛擬滾動
	setupVirtualScrolling();
	
	// 優化：使用防抖動搜尋
	document.getElementById('searchBox').addEventListener('input', function() {
		clearTimeout(searchDebounceTimer);
		searchDebounceTimer = setTimeout(performSearchOptimized, 300);
	});
	
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

// 設置虛擬滾動以提升大檔案效能
function setupVirtualScrolling() {
	const contentArea = document.getElementById('contentArea');
	let lastScrollTop = 0;
	
	contentArea.addEventListener('scroll', function() {
		const scrollTop = contentArea.scrollTop;
		const scrollHeight = contentArea.scrollHeight;
		const clientHeight = contentArea.clientHeight;
		
		// 計算可見範圍
		const lineHeight = 20; // 每行高度
		const buffer = 50; // 緩衝行數
		
		const startLine = Math.max(0, Math.floor(scrollTop / lineHeight) - buffer);
		const endLine = Math.min(lines.length, Math.ceil((scrollTop + clientHeight) / lineHeight) + buffer);
		
		// 如果可見範圍改變，更新高亮
		if (startLine !== visibleRange.start || endLine !== visibleRange.end) {
			visibleRange = { start: startLine, end: endLine };
			
			// 如果有搜尋結果，只更新可見範圍的高亮
			if (searchResults.length > 0) {
				updateVisibleHighlights();
			}
		}
		
		lastScrollTop = scrollTop;
	});
}

// 優化的搜尋函數
async function performSearchOptimized() {
	const searchText = document.getElementById('searchBox').value;
	const useRegex = document.getElementById('regexToggle').checked;

	const minLength = useRegex ? 1 : MIN_SEARCH_LENGTH;
	
	if (searchText && searchText.length < minLength) {
		document.getElementById('searchInfo').textContent = 
			`請輸入至少 ${minLength} 個字元`;
		return;
	}
	
	if (isSearching) return;
	
	clearSearchHighlightsOptimized();
	
	if (!searchText) {
		searchResults = [];
		updateSearchInfo();
		document.getElementById('grepIndicator').classList.remove('active');
		return;
	}
	
	isSearching = true;
	document.getElementById('searchInfo').textContent = '搜尋中...';
	
	try {
		// 先嘗試使用後端搜尋
		const response = await fetch('/search-in-file', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				file_path: filePath,
				search_text: searchText,
				use_regex: useRegex,
				max_results: 10000
			})
		});
		
		const data = await response.json();
		
		if (data.success && data.used_grep) {
			document.getElementById('grepIndicator').classList.add('active');
			searchResults = data.results;
			
			if (searchResults.length > 0) {
				updateVisibleHighlights();
				currentSearchIndex = 0;
				scrollToSearchResultOptimized(0);
			}
		} else {
			// 前端搜尋作為備用方案
			document.getElementById('grepIndicator').classList.remove('active');
			performFrontendSearchOptimized(searchText, useRegex);
		}
	} catch (error) {
		console.error('Search error:', error);
		// 發生錯誤時使用前端搜尋
		document.getElementById('grepIndicator').classList.remove('active');
		performFrontendSearchOptimized(searchText, useRegex);
	} finally {
		isSearching = false;
		updateSearchInfo();
	}
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

// 優化的清除高亮
function clearSearchHighlightsOptimized() {
	// 只清除標記過的行
	const highlightedLines = document.querySelectorAll('.line[data-highlighted="true"]');
	
	highlightedLines.forEach(line => {
		line.innerHTML = escapeHtml(line.textContent);
		delete line.dataset.highlighted;
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

// 優化的滾動到結果
function scrollToSearchResultOptimized(index) {
	if (searchResults.length === 0 || !searchResults[index]) return;
	
	const result = searchResults[index];
	
	// 更新當前高亮
	updateCurrentHighlight();
	
	// 延遲執行以確保 DOM 更新完成
	setTimeout(() => {
		// 方法1：嘗試直接滾動到高亮元素
		const allHighlights = document.querySelectorAll('.search-highlight');
		let targetElement = null;
		
		// 找到對應索引的高亮元素
		if (index < allHighlights.length) {
			targetElement = allHighlights[index];
		}
		
		// 如果找到了高亮元素，滾動到它
		if (targetElement) {
			targetElement.scrollIntoView({ 
				behavior: 'smooth', 
				block: 'center',
				inline: 'center'
			});
			
			// 添加脈動動畫
			targetElement.style.animation = 'none';
			setTimeout(() => {
				targetElement.style.animation = 'pulse 0.5s ease-in-out';
			}, 10);
		} else {
			// 方法2：如果找不到高亮元素，滾動到行
			const lineElement = document.querySelector(`.line[data-line="${result.line}"]`);
			if (lineElement) {
				lineElement.scrollIntoView({ 
					behavior: 'smooth', 
					block: 'center' 
				});
			}
		}
		
		// 更新行號信息
		if (result.line) {
			currentLine = result.line;
			updateLineInfo();
			
			// 高亮當前行號
			document.querySelectorAll('.line-number').forEach(el => {
				el.classList.remove('current-line');
			});
			const lineNumberElement = document.getElementById('line-' + result.line);
			if (lineNumberElement) {
				lineNumberElement.classList.add('current-line');
				// 確保行號也在視圖中
				lineNumberElement.scrollIntoView({ 
					behavior: 'smooth', 
					block: 'nearest' 
				});
			}
		}
	}, 100);
}

// 優化的前端搜尋（限制範圍）
function performFrontendSearchOptimized(searchText, useRegex) {
	searchResults = [];
	
	try {
		let searchPattern;
		if (useRegex) {
			// Regex 模式
			try {
				searchPattern = new RegExp(searchText, 'gi');
			} catch (e) {
				document.getElementById('searchInfo').textContent = '無效的正則表達式';
				return;
			}
		} else {
			// 一般模式：轉義特殊字符
			const escapedText = escapeRegex(searchText);
			searchPattern = new RegExp(escapedText, 'gi');
		}
		
		// 搜尋所有行
		for (let i = 0; i < lines.length; i++) {
			const lineText = lines[i];
			let match;
			
			searchPattern.lastIndex = 0; // 重置 regex
			while ((match = searchPattern.exec(lineText)) !== null) {
				searchResults.push({
					line: i + 1,
					offset: match.index,
					length: match[0].length,
					text: match[0]
				});
				
				// 防止無限循環
				if (match.index === searchPattern.lastIndex) {
					searchPattern.lastIndex++;
				}
			}
		}
		
		if (searchResults.length > 0) {
			updateVisibleHighlights();
			currentSearchIndex = 0;
			scrollToSearchResultOptimized(0);
		}
		
	} catch (e) {
		console.error('Search error:', e);
		document.getElementById('searchInfo').textContent = '搜尋錯誤';
	}
}

// 優化的查找下一個/上一個
function findNext() {
	if (searchResults.length === 0) return;
	currentSearchIndex = (currentSearchIndex + 1) % searchResults.length;
	// 不需要重新高亮所有結果，只需要更新當前高亮
	updateCurrentHighlight();            
	scrollToSearchResultOptimized(currentSearchIndex);
	updateSearchInfo();
}

function findPrevious() {
	if (searchResults.length === 0) return;
	currentSearchIndex = (currentSearchIndex - 1 + searchResults.length) % searchResults.length;
	// 不需要重新高亮所有結果，只需要更新當前高亮
	updateCurrentHighlight();            
	scrollToSearchResultOptimized(currentSearchIndex);
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
    const popup = document.getElementById('modelPopup');
    let backdrop = document.querySelector('.modal-backdrop');
    
    if (!backdrop) {
        backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop';
        document.body.appendChild(backdrop);
        
        backdrop.addEventListener('click', function() {
            popup.classList.remove('show');
            popup.style.display = 'none';
            backdrop.classList.remove('show');
        });
    }
    
    if (popup.classList.contains('show')) {
        popup.classList.remove('show');
        popup.style.display = 'none';
        backdrop.classList.remove('show');
    } else {
        // 確保彈出框在正確的位置
        popup.style.display = 'block';
        popup.classList.add('show');
        backdrop.classList.add('show');
        
        // 修復高度問題
        popup.style.height = 'auto';
        popup.style.minHeight = '200px';
        
        // 強制重新計算位置
        setTimeout(() => {
            popup.style.top = '50%';
            popup.style.left = '50%';
            popup.style.transform = 'translate(-50%, -50%)';
        }, 10);
    }
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
	// 不要 stopPropagation，因為可能會阻止正常的事件流
	
	const model = card.dataset.model;
	const modelName = card.querySelector('.model-card-name').textContent;
	
	// 更新選中狀態
	document.querySelectorAll('.model-card').forEach(c => c.classList.remove('selected'));
	card.classList.add('selected');
	
	// 更新顯示的模型名稱 - 確保更新內聯選擇器的名稱
	const selectedModelNameInline = document.getElementById('selectedModelNameInline');
	if (selectedModelNameInline) {
		selectedModelNameInline.textContent = modelName;
	}
	
	// 更新全局變量
	selectedModel = model;
	console.log('Selected model:', selectedModel);
	
	// 關閉彈出框和背景
	const popup = document.getElementById('modelPopup');
	const backdrop = document.querySelector('.modal-backdrop');
	
	if (popup) {
		popup.classList.remove('show');
		setTimeout(() => {
			popup.style.display = 'none';
		}, 300);
	}
	
	if (backdrop) {
		backdrop.classList.remove('show');
		setTimeout(() => {
			backdrop.remove();
		}, 300);
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

		// 取得按鈕的位置和尺寸資訊
		const buttonRect = modelSelectInlineBtn.getBoundingClientRect();

		// 簡單的顯示/隱藏邏輯
		if (popup.style.display === 'block') {
			// 隱藏
			popup.style.display = 'none';
			const backdrop = document.querySelector('.modal-backdrop');
			if (backdrop) backdrop.remove();
		} else {
			// 顯示
			popup.style.display = 'block';

			// 根據按鈕位置計算彈出視窗的 top 和 left
			// 我們將彈出視窗放在按鈕下方，並與按鈕的左邊緣對齊
			const popupTop = buttonRect.bottom - 150; // 距離按鈕底部 10px
			const popupLeft = buttonRect.left - 100;       // 與按鈕左邊緣對齊

			// 如果希望彈出視窗在按鈕的右側：
			// const popupTop = buttonRect.top;
			// const popupLeft = buttonRect.right + 10; // 距離按鈕右側 10px

			popup.style.cssText = `
				display: block !important;
				position: fixed !important; /* 確保彈出視窗相對於視窗固定 */
				top: ${popupTop}px !important;    /* 使用計算出的 top */
				left: ${popupLeft}px !important;  /* 使用計算出的 left */
				/* 移除 transform: translate(-50%, -50%)，因為我們不再需要它來置中 */
				background: #252526 !important;
				border: 2px solid #667eea !important;
				border-radius: 12px !important;
				box-shadow: 0 8px 32px rgba(0, 0, 0, 0.8) !important;
				padding: 15px !important;
				z-index: 2147483647 !important;
				min-width: 500px !important;
				min-height: 200px !important;
				height: auto !important;
			`;

			// 創建背景
			let backdrop = document.querySelector('.modal-backdrop');
			if (!backdrop) {
				backdrop = document.createElement('div');
				backdrop.className = 'modal-backdrop';
				backdrop.style.cssText = `
					position: fixed;
					top: 0;
					left: 0;
					width: 100%;
					height: 100%;
					background: rgba(0, 0, 0, 0.6);
				`;
				backdrop.onclick = () => {
					popup.style.display = 'none';
					backdrop.remove();
				};
				document.body.appendChild(backdrop);
			}
		}

		console.log('Toggle complete - display:', popup.style.display);
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

// 改進的檔案分析函數
async function analyzeCurrentFileImproved() {
	if (isAnalyzing) {
		console.log('已經在分析中，請稍候...');
		return;
	}
	
	if (isAnalyzing) return;
	
	isAnalyzing = true;
	
	const analyzeBtn = document.getElementById('analyzeBtn');
	const responseDiv = document.getElementById('aiResponse');
	const responseContent = document.getElementById('aiResponseContent');
	
	// 先檢查檔案大小
	const sizeCheck = await checkFileSizeForAI();
	
	if (sizeCheck.strategy === 'segmented') {
		// 顯示分段分析確認
		const proceed = await showSegmentedAnalysisDialog(sizeCheck);
		if (!proceed) return;
	}
	
	isAnalyzing = true;
	
	// 更新按鈕狀態
	analyzeBtn.classList.add('loading');
	analyzeBtn.disabled = true;
	analyzeBtn.innerHTML = '<span>⏳</span> 準備分析...';
	
	responseDiv.classList.add('active');
	
	// 創建進度顯示容器
	const progressContainer = createProgressContainer(sizeCheck);
	responseContent.appendChild(progressContainer);
	
	try {
		const fileType = filePath.toLowerCase().includes('tombstone') ? 'Tombstone' : 'ANR';
		
		// 發送分析請求
		const response = await fetch('/analyze-with-ai', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				file_path: filePath,
				content: fileContent,
				file_type: fileType,
				model: selectedModel,
				enable_thinking: AI_ANALYSIS_CONFIG.enableThinking
			})
		});
		
		const data = await response.json();
		
		if (response.ok && data.success) {
			if (data.is_segmented) {
				// 處理分段結果
				await displaySegmentedAnalysis(data, progressContainer);
			} else {
				// 處理單次分析結果
				displaySingleAnalysis(data);
			}
		} else {
			showAnalysisError(data.error || '分析失敗');
		}
		
	} catch (error) {
		console.error('AI analysis error:', error);
		showAnalysisError(error.message);
	} finally {
		resetAnalyzeButton();
		isAnalyzing = false;
	}
}

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
        const dialog = document.createElement('div');
        dialog.className = 'segmented-analysis-dialog';
        dialog.innerHTML = `
            <div class="dialog-content">
                <h3>📊 ${getAnalysisModeTitle()}</h3>
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
                        <span class="info-value">約 ${Math.ceil(sizeInfo.suggested_segments * 30 / 60)} 分鐘</span>
                    </div>
                    ` : ''}
                </div>
                <div class="dialog-buttons">
                    <button class="btn btn-primary" onclick="resolveDialog(true)">繼續分析</button>
                    <button class="btn btn-secondary" onclick="resolveDialog(false)">取消</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(dialog);
        
        window.resolveDialog = (proceed) => {
            dialog.remove();
            resolve(proceed);
        };
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
		<div id="rateLimitWarning" class="rate-limit-warning" style="display: none;">
			<span>⏳</span> <span id="rateLimitMessage">等待速率限制重置...</span>
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
		
		const hasRateLimitErrors = data.errors.some(err => err.error.includes('速率限制'));
		
		errorSummary.innerHTML = `
			<div class="ai-warning">
				⚠️ 有 ${data.errors.length} 個段落分析失敗
				${hasRateLimitErrors ? '<br><small>部分失敗是由於 API 速率限制（每分鐘 40,000 tokens）</small>' : ''}
				<details>
					<summary>查看詳情</summary>
					<ul>
						${data.errors.map(err => 
							`<li>段落 ${err.segment}: ${escapeHtml(err.error)}
							${err.retry_count ? ` (重試 ${err.retry_count} 次)` : ''}</li>`
						).join('')}
					</ul>
					${hasRateLimitErrors ? `
						<div style="margin-top: 10px; padding: 10px; background: rgba(255,255,255,0.1); border-radius: 4px;">
							<strong>速率限制說明：</strong><br>
							• 您的組織每分鐘限制 40,000 個輸入 tokens<br>
							• 大檔案可能需要分多次請求<br>
							• 系統會自動等待並重試<br>
							• 考慮縮小檔案或聯繫 Anthropic 提高限制
						</div>
					` : ''}
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

// 添加速率限制相關樣式
const rateLimitStyles = `
<style>
.rate-limit-warning {
	background: #ff9800;
	color: white;
	padding: 10px 15px;
	border-radius: 6px;
	margin: 15px 0;
	display: flex;
	align-items: center;
	gap: 10px;
	font-size: 14px;
}

.rate-limit-warning span:first-child {
	font-size: 20px;
	animation: pulse 2s infinite;
}

@keyframes pulse {
	0% { opacity: 0.6; }
	50% { opacity: 1; }
	100% { opacity: 0.6; }
}

.retry-badge {
	background: #ff5722;
	color: white;
	padding: 2px 6px;
	border-radius: 10px;
	font-size: 11px;
	margin-left: 8px;
	cursor: help;
}

#tokenUsage {
	font-weight: 600;
	padding: 2px 8px;
	background: rgba(255, 152, 0, 0.2);
	border-radius: 4px;
}
</style>`;

// 注入樣式
document.addEventListener('DOMContentLoaded', function() {
	const styleElement = document.createElement('div');
	styleElement.innerHTML = rateLimitStyles;
	const style = styleElement.querySelector('style');
	if (style) {
		document.head.appendChild(style);
	}
});

function showAnalysisError(errorMessage) {
	const responseContent = document.getElementById('aiResponseContent');
	if (!responseContent) return;
	
	const errorDiv = document.createElement('div');
	errorDiv.className = 'ai-error';
	errorDiv.innerHTML = `
		<h3>❌ 分析錯誤</h3>
		<p>${escapeHtml(errorMessage || '發生未知錯誤')}</p>
		<p style="margin-top: 10px;">
			<button class="retry-btn" onclick="analyzeCurrentFileImproved()">🔄 重試</button>
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
function createConversationItem(type, content, data) {
	const conversationItem = document.createElement('div');
	conversationItem.className = 'conversation-item';
	
	const timestamp = new Date().toLocaleString('zh-TW');
	const modelName = getModelDisplayName(data.model || selectedModel);
	
	// 根據類型決定圖標和標題
	let icon = '🔍';
	let typeText = '檔案分析';
	
	if (type === '您的問題') {
		icon = '👤';
		typeText = type;
	} else if (type === '分段分析') {
		icon = '📊';
		typeText = '大檔案分段分析';
	}
	
	conversationItem.innerHTML = `
		<div class="conversation-header">
			<span class="conversation-icon">${icon}</span>
			<span class="conversation-type">${typeText}</span>
			<span class="conversation-time">${timestamp}</span>
		</div>
		${type === '您的問題' ? `
			<div class="user-question">
				${escapeHtml(data.question || '分析整個檔案')}
			</div>
		` : ''}
		<div class="ai-response-item">
			<div class="ai-icon">🤖</div>
			<div class="ai-message">
				${content}
				<div class="ai-footer">
					<span>由 ${modelName} 提供分析</span>
					${data.is_segmented ? `<span style="margin-left: 10px;">• 分 ${data.total_segments} 段分析</span>` : ''}
					${data.thinking_log && data.thinking_log.length > 0 ? '<span style="margin-left: 10px;">• 包含深度思考</span>' : ''}
				</div>
			</div>
		</div>
	`;
	
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

// 格式化分析內容
function formatAnalysisContent(content) {
	// 檢查 content 是否存在
	if (!content || typeof content !== 'string') {
		console.warn('formatAnalysisContent received invalid content:', content);
		return '<p>無分析內容</p>';
	}
	
	try {
		return content
			.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
			.replace(/`([^`]+)`/g, '<code>$1</code>')
			.replace(/^(\d+\.\s.*?)$/gm, '<li>$1</li>')
			.replace(/(<li>.*?<\/li>\s*)+/g, '<ol>$&</ol>')
			.replace(/\n\n/g, '</p><p>')
			.replace(/^/, '<p>')
			.replace(/$/, '</p>');
	} catch (error) {
		console.error('Error formatting analysis content:', error);
		return '<p>' + escapeHtml(content) + '</p>';
	}
}

// 在 DOMContentLoaded 時注入樣式
document.addEventListener('DOMContentLoaded', function() {

	// 替換原有的分析按鈕事件
	const analyzeBtn = document.getElementById('analyzeBtn');
	if (analyzeBtn) {
		analyzeBtn.onclick = analyzeCurrentFileImproved;
	}
});

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
    
    console.log('開始智能分析 - 模式:', mode, modeConfig.name);
    
    // 禁用按鈕
    btn.disabled = true;
    btn.classList.add('loading');
    btn.innerHTML = `<div class="ai-spinner"></div> ${modeConfig.icon} ${modeConfig.name}中...`;
    
    responseDiv.classList.add('active');
    
    try {
        // 統一使用 smart-analyze 端點
        const response = await fetch('/smart-analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                file_path: filePath,
                content: fileContent,
                mode: mode,  // 傳遞選中的模式
                file_type: filePath.toLowerCase().includes('tombstone') ? 'Tombstone' : 'ANR',
                enable_thinking: document.getElementById('enableDeepThinking')?.checked || false,
                include_recommendations: document.getElementById('includeRecommendations')?.checked || true
            })
        });
        
        const data = await response.json();
        
        if (response.ok && data.success) {
            // 顯示結果
            displaySmartAnalysisResult(data, modeConfig);
        } else {
            throw new Error(data.error || '分析失敗');
        }
        
    } catch (error) {
        console.error('Analysis error:', error);
        
        const errorDiv = document.createElement('div');
        errorDiv.className = 'ai-error';
        errorDiv.innerHTML = `
            <h3>❌ 分析失敗</h3>
            <p>${escapeHtml(error.message)}</p>
            <p style="margin-top: 10px;">
                <button class="retry-btn" onclick="startSmartAnalysis()">🔄 重試</button>
            </p>
        `;
        responseContent.appendChild(errorDiv);
        conversationHistory.push(errorDiv);
        
    } finally {
        isAnalyzing = false;
        btn.disabled = false;
        btn.classList.remove('loading');
        // 恢復按鈕原始狀態
        btn.innerHTML = `<span id="analyzeIcon">${modeConfig.icon}</span> <span id="analyzeText">${modeConfig.buttonText}</span>`;
    }
}

function selectAnalysisMode(mode) {
    if (!ANALYSIS_MODES[mode]) return;
    
    // 更新選中狀態
    document.querySelectorAll('.mode-card').forEach(card => {
        card.classList.remove('selected');
    });
    
    const selectedCard = document.querySelector(`.mode-card[data-mode="${mode}"]`);
    if (selectedCard) {
        selectedCard.classList.add('selected');
    }
    
    // 更新全局變量
    selectedAnalysisMode = mode;
    
    // 更新分析按鈕
    updateAnalyzeButton(mode);
    
    // 顯示選擇提示
    showModeSelectionToast(mode);
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
    console.log('Displaying result:', data);  // 調試日誌
    
    const responseContent = document.getElementById('aiResponseContent');
    
    if (!responseContent) {
        console.error('找不到 AI 回應區域');
        return;
    }
    
    // 創建對話項目
    const conversationItem = document.createElement('div');
    conversationItem.className = 'conversation-item smart-analysis-result';
    
    // 根據不同模式構建不同的顯示格式
    let resultHTML = `
        <div class="conversation-header">
            <span class="conversation-icon">${modeConfig.icon}</span>
            <span class="conversation-type">${modeConfig.name}</span>
            <span class="conversation-time">${new Date().toLocaleString('zh-TW')}</span>
        </div>
        <div class="result-header">
            <div class="mode-indicator">
                <span class="mode-icon">${modeConfig.icon}</span>
                <span class="mode-name">${modeConfig.name}</span>
                <span class="mode-badge ${modeConfig.badgeClass}">${modeConfig.badge}</span>
            </div>
            <div class="result-meta">
                <span>模型：${getModelDisplayName(data.model || selectedModel)}</span>
                <span>耗時：${data.elapsed_time || 'N/A'}</span>
            </div>
        </div>
    `;
    
    // 根據不同的分析模式顯示不同的內容
    if (data.analysis_mode === 'quick' || data.is_quick) {
        // 快速分析：簡潔顯示
        resultHTML += `
            <div class="quick-analysis-content">
                <div class="analysis-summary">
                    ${formatQuickAnalysis(data.analysis || data.result)}
                </div>
                ${data.analyzed_size ? `
                    <div class="analysis-info">
                        分析了 ${(data.analyzed_size/1024).toFixed(1)}KB / ${(data.original_size/1024).toFixed(1)}KB
                    </div>
                ` : ''}
            </div>
        `;
    } else if (data.is_segmented) {
        // 分段分析：顯示段落結果
        resultHTML += displaySegmentedResults(data);
    } else {
        // 標準分析：完整顯示
        resultHTML += `
            <div class="ai-response-item">
                <div class="ai-icon">🤖</div>
                <div class="ai-message">
                    ${data.truncated ? '<div class="ai-warning">⚠️ 由於檔案過大，只分析了部分內容</div>' : ''}
                    <div class="ai-analysis-content">
                        ${formatAnalysisContent(data.analysis || data.result || data.comprehensive_report)}
                    </div>
                    <div class="ai-footer">
                        <span>由 ${getModelDisplayName(data.model)} 提供分析</span>
                        ${data.thinking ? '<span style="margin-left: 10px;">• 包含深度思考</span>' : ''}
                    </div>
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

// 格式化快速分析結果
function formatQuickAnalysis(analysis) {
    if (!analysis) return '<p>無分析結果</p>';
    
    // 簡單的格式化
    return analysis
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/^/, '<p>')
        .replace(/$/, '</p>')
        .replace(/^\d+\.\s/gm, '<br>• ');
}

// 顯示分段結果
function displaySegmentedResults(data) {
    let html = '<div class="segmented-results">';
    
    if (data.segment_results) {
        html += '<div class="segment-summary">分析了 ' + data.total_segments + ' 個段落</div>';
        
        // 顯示每個段落的摘要
        data.segment_results.forEach(seg => {
            if (seg.success) {
                html += `
                    <details class="segment-detail">
                        <summary>段落 ${seg.segment || seg.segment_number} ✓</summary>
                        <div class="segment-content">
                            ${formatAnalysisContent(seg.analysis)}
                        </div>
                    </details>
                `;
            }
        });
    }
    
    // 顯示綜合報告
    if (data.comprehensive_report || data.full_analysis) {
        html += `
            <div class="final-report">
                <h3>📊 綜合分析報告</h3>
                ${formatAnalysisContent(data.comprehensive_report || data.full_analysis)}
            </div>
        `;
    }
    
    html += '</div>';
    return html;
}

// 格式化分析內容
function formatAnalysisContent(content) {
    if (!content || typeof content !== 'string') {
        return '<p>無分析內容</p>';
    }
    
    try {
        return content
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/^#+\s(.+)$/gm, '<h3>$1</h3>')
            .replace(/\n\n/g, '</p><p>')
            .replace(/^/, '<p>')
            .replace(/$/, '</p>');
    } catch (error) {
        return '<p>' + escapeHtml(content) + '</p>';
    }
}

// 判斷是否需要顯示分段對話框
function shouldShowSegmentDialog(mode, sizeInfo) {
    // 快速分析：永遠不顯示
    if (mode === 'quick') return false;
    
    // 最大分析：只在超過單次限制時顯示
    if (mode === 'max_tokens') {
        return sizeInfo.estimated_tokens > sizeInfo.max_tokens_per_request;
    }
    
    // 深度分析：建議分段數 > 2 時顯示
    if (mode === 'comprehensive') {
        return sizeInfo.suggested_segments > 2;
    }
    
    // 智能分析：根據 API 返回的策略決定
    if (mode === 'auto') {
        return sizeInfo.strategy === 'segmented' && sizeInfo.suggested_segments > 3;
    }
    
    return false;
}

// 快速分析（不分段）
async function performQuickAnalysis(responseContent) {
    // 顯示簡單進度
    const progressDiv = document.createElement('div');
    progressDiv.className = 'analysis-progress';
    progressDiv.innerHTML = `
        <div class="progress-header">
            <h4>⚡ 正在執行快速分析...</h4>
            <div class="progress-stats">
                <span>預計 30 秒內完成</span>
            </div>
        </div>
        <div class="ai-spinner"></div>
    `;
    responseContent.appendChild(progressDiv);
    
    try {
        const response = await fetch('/smart-analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                file_path: filePath,
                content: fileContent,
                mode: 'quick',  // 強制快速模式
                model: selectedModel,
                force_single_analysis: true  // 新增：強制單次分析
            })
        });
        
        const data = await response.json();
        
        progressDiv.remove();
        
        if (data.success) {
            displaySmartAnalysisResult(data);
        } else {
            throw new Error(data.error || '快速分析失敗');
        }
        
    } catch (error) {
        progressDiv.remove();
        throw error;
    }
}

// 執行一般分析
async function performAnalysis(responseContent, sizeInfo) {
    // 創建進度顯示
    const progressDiv = createAnalysisProgress();
    responseContent.appendChild(progressDiv);
    
    try {
        const response = await fetch('/smart-analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                file_path: filePath,
                content: fileContent,
                mode: selectedAnalysisMode,
                model: selectedModel,
                enable_thinking: document.getElementById('enableDeepThinking')?.checked,
                include_recommendations: document.getElementById('includeRecommendations')?.checked,
                expected_segments: sizeInfo.suggested_segments  // 傳遞預期的段數
            })
        });
        
        const data = await response.json();
        
        progressDiv.remove();
        
        if (data.success) {
            displaySmartAnalysisResult(data);
        } else {
            throw new Error(data.error || '分析失敗');
        }
        
    } catch (error) {
        progressDiv.remove();
        throw error;
    }
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

// 強化版修復代碼
(function enhancedFix() {
    console.log('=== 執行強化版修復 ===');
    
    // 1. 添加更明顯的選中樣式
    const style = document.createElement('style');
    style.innerHTML = `
        .mode-card.selected {
            border: 3px solid #667eea !important;
            background: #3a3a4a !important;
            box-shadow: 0 0 15px rgba(102, 126, 234, 0.8) !important;
            transform: scale(1.02) !important;
            position: relative;
        }
        .mode-card.selected::after {
            content: '✓ 已選擇';
            position: absolute;
            top: 5px;
            right: 5px;
            background: #667eea;
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }
        .mode-card {
            transition: all 0.3s ease !important;
        }
        .mode-card:hover {
            transform: translateY(-3px) !important;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3) !important;
        }
    `;
    document.head.appendChild(style);
    
    // 2. 重新綁定所有事件
    const modeCards = document.querySelectorAll('.mode-card');
    
    modeCards.forEach(card => {
        const mode = card.dataset.mode;
        
        // 移除所有舊事件
        const newCard = card.cloneNode(true);
        card.parentNode.replaceChild(newCard, card);
        
        // 添加新事件
        newCard.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            console.log(`✅ 點擊了 ${mode} 模式`);
            
            // 移除所有選中狀態
            document.querySelectorAll('.mode-card').forEach(c => {
                c.classList.remove('selected');
                c.style.transform = '';
            });
            
            // 添加選中狀態
            this.classList.add('selected');
            
            // 更新全局變量
            window.selectedAnalysisMode = mode;
            
            // 更新按鈕 - 包含顏色變化
            const btn = document.getElementById('analyzeBtn');
            const icon = document.getElementById('analyzeIcon');
            const text = document.getElementById('analyzeText');
            
            const modeInfo = {
                'auto': { 
                    icon: '🤖', 
                    text: '開始智能分析', 
                    color: 'linear-gradient(135deg, #667eea, #764ba2)'
                },
                'quick': { 
                    icon: '⚡', 
                    text: '快速分析 (30秒)', 
                    color: 'linear-gradient(135deg, #ffd700, #ffed4b)'
                },
                'comprehensive': { 
                    icon: '🔍', 
                    text: '深度分析 (2-5分鐘)', 
                    color: 'linear-gradient(135deg, #4ec9b0, #45d3b8)'
                },
                'max_tokens': { 
                    icon: '📊', 
                    text: '最大化分析', 
                    color: 'linear-gradient(135deg, #ff6b6b, #ff8787)'
                }
            };
            
            const info = modeInfo[mode];
            if (icon) icon.textContent = info.icon;
            if (text) text.textContent = info.text;
            if (btn) {
                btn.style.background = info.color;
                btn.style.transform = 'scale(1.05)';
                setTimeout(() => {
                    btn.style.transform = 'scale(1)';
                }, 200);
            }
            
            // 添加點擊動畫
            this.style.animation = 'none';
            setTimeout(() => {
                this.style.animation = 'pulse 0.5s ease';
            }, 10);
            
            // 顯示選擇提示
            showSelectionToast(mode);
        });
    });
    
    // 3. 設置默認選中（如果沒有）
    if (!document.querySelector('.mode-card.selected')) {
        const autoCard = document.querySelector('.mode-card[data-mode="auto"]');
        if (autoCard) {
            autoCard.click();
        }
    }
    
    // 4. 添加脈動動畫
    if (!document.querySelector('#enhanced-animations')) {
        const animStyle = document.createElement('style');
        animStyle.id = 'enhanced-animations';
        animStyle.innerHTML = `
            @keyframes pulse {
                0% { transform: scale(1); opacity: 1; }
                50% { transform: scale(1.05); opacity: 0.8; }
                100% { transform: scale(1); opacity: 1; }
            }
            
            .analyze-current-btn {
                transition: all 0.3s ease !important;
            }
        `;
        document.head.appendChild(animStyle);
    }
    
    console.log('=== 強化修復完成 ===');
})();

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
