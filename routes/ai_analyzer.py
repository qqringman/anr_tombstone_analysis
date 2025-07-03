from flask import Blueprint, request, jsonify, Response, stream_with_context
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import os
import time
import json
import threading
from typing import Dict, List, Optional, Any
import anthropic
from config.config import AI_PROVIDERS, ANALYSIS_MODES, TOKEN_PRICING, RATE_LIMITS, MODEL_LIMITS, CLAUDE_API_KEY
from enum import Enum
from collections import deque

ai_analyzer_bp = Blueprint('ai_analyzer_bp', __name__)

# 全域變數用於管理進行中的分析
active_analyses: Dict[str, 'AnalysisSession'] = {}

class AnalysisMode(Enum):
    SMART = "smart"
    QUICK = "quick" 
    DEEP = "deep"

class MessageRole(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

@dataclass
class Message:
    role: MessageRole
    content: str
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class AnalysisContext:
    file_path: str
    file_content: str
    mode: AnalysisMode
    previous_messages: List[Message]
    metadata: Dict[str, Any]

class AIProvider(ABC):
    """AI Provider 的抽象基類"""
    
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._stop_flag = threading.Event()
        
    @abstractmethod
    def analyze_sync(self, context: AnalysisContext) -> str:
        """同步分析"""
        pass
    
    @abstractmethod
    def stream_analyze_sync(self, context: AnalysisContext):
        """同步流式分析"""
        pass
    
    def calculate_tokens(self, text: str) -> int:
        """計算 token 數量"""
        return len(text) // 4  # 簡單估算
    
    def get_cost(self, input_tokens: int, output_tokens: int) -> float:
        """計算成本"""
        return 0.0  # 簡化版本
    
    def stop(self):
        """停止當前的分析"""
        self._stop_flag.set()
    
    def reset_stop_flag(self):
        """重置停止標記"""
        self._stop_flag.clear()
    
    def should_stop(self) -> bool:
        """檢查是否應該停止"""
        return self._stop_flag.is_set()

class AnthropicProvider(AIProvider):
    """Anthropic Claude Provider"""
    
    def __init__(self, api_key: str, model: str):
        super().__init__(api_key, model)
        self.client = anthropic.Anthropic(api_key=api_key)
        
        # 從配置獲取模型限制
        self.model_config = MODEL_LIMITS.get(model, {})
        self.max_tokens = self.model_config.get('max_tokens', 200000)
        self.max_output_tokens = self.model_config.get('max_output_tokens', 4096)
        self.chars_per_token = self.model_config.get('chars_per_token', 4)

        # 獲取速率限制管理器
        self.rate_limiter = get_rate_limiter('anthropic')

    def calculate_tokens(self, text: str) -> int:
        """計算 token 數量"""
        if not text:
            return 0
        # 使用模型配置的 chars_per_token 或默認值 4
        return len(text) // self.chars_per_token
    
    def get_cost(self, input_tokens: int, output_tokens: int) -> float:
        """計算成本"""
        pricing = TOKEN_PRICING.get('anthropic', {}).get(self.model, {'input': 0, 'output': 0})
        input_cost = (input_tokens / 1000) * pricing.get('input', 0)
        output_cost = (output_tokens / 1000) * pricing.get('output', 0)
        return input_cost + output_cost
    
    def _truncate_content(self, content: str, mode: AnalysisMode) -> tuple[str, bool]:
        """根據 token 限制截取內容"""
        # 預留空間給系統提示和上下文
        reserved_tokens = 5000  # 預留給系統提示、歷史訊息等
        
        # 根據模式調整策略
        if mode == AnalysisMode.QUICK:
            # 快速分析：只取前後關鍵部分
            max_content_tokens = min(50000, self.max_tokens - reserved_tokens)
        elif mode == AnalysisMode.DEEP:
            # 深度分析：盡可能多的內容
            max_content_tokens = self.max_tokens - reserved_tokens
        else:  # SMART
            # 智能分析：平衡的內容量
            max_content_tokens = min(100000, self.max_tokens - reserved_tokens)
        
        # 估算當前內容的 tokens
        current_tokens = self.calculate_tokens(content)
        
        if current_tokens <= max_content_tokens:
            return content, False
        
        # 需要截取
        max_chars = max_content_tokens * self.chars_per_token
        
        if mode == AnalysisMode.QUICK:
            # 快速模式：取開頭和結尾
            head_chars = max_chars // 3
            tail_chars = max_chars // 3
            
            truncated = (
                content[:head_chars] + 
                f"\n\n... [省略中間內容，原始大小: {len(content)} 字元] ...\n\n" +
                content[-tail_chars:]
            )
        else:
            # 其他模式：優先保留開頭（通常包含重要信息）
            truncated = content[:max_chars] + f"\n\n... [內容已截取，原始大小: {len(content)} 字元]"
        
        return truncated, True
    
    def analyze_sync(self, context: AnalysisContext) -> str:
        """同步分析"""
        retry_count = 0
        max_retries = 3
        base_delay = 5  # 基礎延遲5秒
        
        while retry_count <= max_retries:
            try:
                messages = self._prepare_messages(context)
                response = self.client.messages.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self._get_max_tokens(context.mode),
                    temperature=self._get_temperature(context.mode)
                )
                return response.content[0].text
            except Exception as e:
                error_str = str(e)
                
                # 檢查是否是過載錯誤
                if "overloaded" in error_str.lower():
                    retry_count += 1
                    if retry_count <= max_retries:
                        # 指數退避策略
                        delay = base_delay * (2 ** (retry_count - 1))
                        print(f"API 過載，等待 {delay} 秒後重試... (第 {retry_count}/{max_retries} 次)")
                        time.sleep(delay)
                        continue
                    else:
                        raise Exception("API 持續過載，請稍後再試（建議等待 1-2 分鐘）")
                
                # 其他錯誤直接拋出
                raise Exception(f"Anthropic API 錯誤: {error_str}")
    
    def stream_analyze_sync(self, context: AnalysisContext):
        """同步流式分析"""
        self.reset_stop_flag()
        
        # 估算 token 使用量
        messages = self._prepare_messages(context)
        estimated_input_tokens = sum(self.calculate_tokens(str(msg)) for msg in messages)
        estimated_total_tokens = estimated_input_tokens + self.max_output_tokens
        
        # 獲取使用統計
        usage_stats = self.rate_limiter.get_usage_stats()
        
        # 發送速率限制信息
        yield json.dumps({
            'type': 'rate_limit_info',
            'usage': usage_stats,
            'estimated_tokens': estimated_total_tokens
        }) + '\n'
        
        # 檢查速率限制
        can_proceed, wait_time = self.rate_limiter.can_make_request(estimated_total_tokens)
        
        if not can_proceed:
            # 如果需要等待時間小於30秒，自動等待
            if wait_time <= 30:
                yield json.dumps({
                    'type': 'rate_limit_wait',
                    'wait_time': wait_time,
                    'reason': self._get_rate_limit_reason(usage_stats)
                }) + '\n'
                
                # 等待並重試
                if self._wait_for_rate_limit(estimated_total_tokens):
                    can_proceed = True
                else:
                    yield json.dumps({
                        'type': 'error',
                        'error': '速率限制：請稍後再試',
                        'usage_stats': usage_stats
                    }) + '\n'
                    return
            else:
                # 等待時間太長，直接返回錯誤
                yield json.dumps({
                    'type': 'error',
                    'error': f'已達到速率限制，請等待 {int(wait_time)} 秒後再試',
                    'usage_stats': usage_stats
                }) + '\n'
                return
        
        # 記錄請求開始
        request_start_time = time.time()
        actual_output_tokens = 0
        
        try:
            # 使用 stream
            with self.client.messages.stream(
                model=self.model,
                messages=messages,
                max_tokens=self._get_max_tokens(context.mode),
                temperature=self._get_temperature(context.mode)
            ) as stream:
                for text in stream.text_stream:
                    if self.should_stop():
                        break
                    actual_output_tokens += self.calculate_tokens(text)
                    yield json.dumps({
                        'type': 'content',
                        'content': text
                    }) + '\n'
                
                # 記錄實際使用的 tokens
                actual_total_tokens = estimated_input_tokens + actual_output_tokens
                self.rate_limiter.record_request(actual_total_tokens)
                
                # 發送完成信息，包含速率限制狀態
                final_usage = self.rate_limiter.get_usage_stats()
                yield json.dumps({
                    'type': 'complete',
                    'usage': {
                        'input': estimated_input_tokens,
                        'output': actual_output_tokens,
                        'total': actual_total_tokens
                    },
                    'rate_limit_status': final_usage
                }) + '\n'
                    
        except Exception as e:
            error_str = str(e)
            
            # 檢查是否是速率限制錯誤
            if any(keyword in error_str.lower() for keyword in ['rate', 'limit', 'overloaded', '429']):
                # 記錄失敗的請求（使用估算的 tokens）
                self.rate_limiter.record_request(estimated_total_tokens)
                
                current_usage = self.rate_limiter.get_usage_stats()
                yield json.dumps({
                    'type': 'error',
                    'error': '達到 API 速率限制',
                    'error_detail': error_str,
                    'usage_stats': current_usage,
                    'retry_after': 60  # 建議等待60秒
                }) + '\n'
            else:
                yield json.dumps({
                    'type': 'error',
                    'error': f'分析錯誤: {error_str}'
                }) + '\n'
    
    def _prepare_messages(self, context: AnalysisContext) -> List[Dict]:
        """準備訊息格式"""
        messages = []
        
        # 截取檔案內容
        truncated_content, was_truncated = self._truncate_content(
            context.file_content, 
            context.mode
        )
        
        # 添加系統提示
        system_prompt = self._get_system_prompt(context.mode)
        
        # 如果內容被截取，在系統提示中說明
        if was_truncated:
            system_prompt += "\n\n注意：由於檔案過大，只提供了部分內容進行分析。請基於可見的內容提供分析。"
        
        # 添加歷史訊息（限制數量）
        recent_messages = context.previous_messages[-3:]  # 只保留最近3條
        for msg in recent_messages:
            if msg.role == MessageRole.USER:
                # 限制歷史訊息長度
                content = msg.content[:1000] if len(msg.content) > 1000 else msg.content
                messages.append({"role": "user", "content": content})
            elif msg.role == MessageRole.ASSISTANT:
                content = msg.content[:2000] if len(msg.content) > 2000 else msg.content
                messages.append({"role": "assistant", "content": content})
        
        # 添加當前請求
        user_message = f"{system_prompt}\n\n檔案路徑: {context.file_path}\n\n檔案內容:\n{truncated_content}"
        messages.append({"role": "user", "content": user_message})
        
        # 將截取狀態保存到上下文
        context.metadata['was_truncated'] = was_truncated
        context.metadata['original_size'] = len(context.file_content)
        context.metadata['truncated_size'] = len(truncated_content)
        context.metadata['actual_input_tokens'] = self.calculate_tokens(user_message)
        
        return messages

    def _wait_for_rate_limit(self, estimated_tokens: int) -> bool:
        """等待速率限制"""
        max_wait = 60  # 最多等待60秒
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            can_proceed, wait_time = self.rate_limiter.can_make_request(estimated_tokens)
            
            if can_proceed:
                return True
            
            if wait_time > max_wait - (time.time() - start_time):
                # 等待時間太長
                return False
            
            # 智能等待
            actual_wait = min(wait_time + 1, 5)  # 最多等5秒後重新檢查
            print(f"速率限制，等待 {actual_wait:.1f} 秒...")
            time.sleep(actual_wait)
        
        return False

    def _get_rate_limit_reason(self, usage_stats: dict) -> str:
        """獲取速率限制原因"""
        reasons = []
        
        if usage_stats['rpm_current'] >= usage_stats['rpm_limit']:
            reasons.append(f"每分鐘請求數已達上限 ({usage_stats['rpm_current']}/{usage_stats['rpm_limit']})")
        
        if usage_stats['tpm_current'] >= usage_stats['tpm_limit']:
            reasons.append(f"每分鐘 Token 數已達上限 ({usage_stats['tpm_current']:,}/{usage_stats['tpm_limit']:,})")
        
        if usage_stats['tpd_current'] >= usage_stats['tpd_limit'] * 0.9:  # 接近每日限制
            reasons.append(f"接近每日 Token 限制 ({usage_stats['tpd_current']:,}/{usage_stats['tpd_limit']:,})")
        
        return " | ".join(reasons) if reasons else "API 繁忙"

    def _get_system_prompt(self, mode: AnalysisMode) -> str:
        """根據模式獲取系統提示"""
        prompts = {
            AnalysisMode.SMART: """你是一個專業的 Android 系統日誌分析專家。請分析提供的日誌內容：

1. 自動識別日誌類型：
   - 如果包含 "Subject: Input dispatching timed out" 或類似內容，這是 ANR (Application Not Responding) 日誌
   - 如果包含 "tombstone" 或崩潰堆疊，這是崩潰日誌
   - 其他類型請相應識別

2. 根據日誌類型提供分析：
   - **問題摘要**：簡潔描述發生了什麼問題
   - **根本原因**：深入分析導致問題的原因
   - **影響範圍**：哪些進程/組件受到影響
   - **解決方案**：提供具體的修復建議
   
3. 請使用清晰的標題和格式化輸出""",
            
            AnalysisMode.QUICK: """你是一個快速診斷助手。在 30 秒內分析這個 Android 日誌：

快速識別：
- 日誌類型（ANR/崩潰/其他）
- 主要問題
- 立即可執行的解決方案

請保持簡潔，只提供最關鍵的信息。""",
            
            AnalysisMode.DEEP: """你是一個細緻的 Android 系統分析專家。請對這個日誌進行深度分析：

1. **日誌解析**
   - 完整解讀每個關鍵信息
   - 分析記憶體地址、暫存器狀態
   - 追蹤完整的調用堆疊

2. **問題診斷**
   - 詳細的根因分析
   - 可能的觸發條件
   - 系統狀態評估

3. **解決方案**
   - 程式碼層面的修復建議
   - 系統配置優化
   - 預防措施

4. **相關知識**
   - 相關的 Android 系統知識
   - 類似問題的處理經驗"""
        }
        return prompts.get(mode, prompts[AnalysisMode.SMART])
    
    def _get_max_tokens(self, mode: AnalysisMode) -> int:
        """根據模式獲取最大輸出 token 數"""
        # 使用模型配置的最大輸出 tokens，但根據模式調整
        base_max = self.max_output_tokens
        
        tokens = {
            AnalysisMode.QUICK: min(1000, base_max),
            AnalysisMode.SMART: min(2000, base_max),
            AnalysisMode.DEEP: min(4000, base_max)
        }
        return tokens.get(mode, min(2000, base_max))
    
    def _get_temperature(self, mode: AnalysisMode) -> float:
        """根據模式獲取溫度參數"""
        temps = {
            AnalysisMode.QUICK: 0.3,
            AnalysisMode.SMART: 0.5,
            AnalysisMode.DEEP: 0.7
        }
        return temps.get(mode, 0.5)

class ProviderFactory:
    """AI Provider 工廠類"""
    
    @staticmethod
    def create_provider(provider_name: str, model: str) -> AIProvider:
        """創建 AI Provider 實例"""
        if provider_name not in AI_PROVIDERS:
            raise ValueError(f"不支援的 Provider: {provider_name}")
        
        config = AI_PROVIDERS[provider_name]
        api_key = config['api_key']
        
        if not api_key:
            raise ValueError(f"{provider_name} API Key 未設置")
        
        if provider_name == 'anthropic':
            return AnthropicProvider(api_key, model)
        else:
            raise ValueError(f"未實作的 Provider: {provider_name}")

class AnalysisSession:
    """分析會話管理"""
    
    def __init__(self, session_id: str, provider: AIProvider):
        self.session_id = session_id
        self.provider = provider
        self.messages: List[Message] = []
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.is_active = True
        self.total_cost = 0.0
        self.total_tokens = {'input': 0, 'output': 0}
        
    def add_message(self, role: MessageRole, content: str):
        """添加訊息到會話"""
        self.messages.append(Message(role, content))
        self.last_activity = datetime.now()
        
    def stop(self):
        """停止當前分析"""
        self.provider.stop()
        self.is_active = False
        
    def update_usage(self, input_tokens: int, output_tokens: int):
        """更新使用量統計"""
        self.total_tokens['input'] += input_tokens
        self.total_tokens['output'] += output_tokens
        self.total_cost += self.provider.get_cost(input_tokens, output_tokens)

class RateLimitManager:
    """速率限制管理器"""
    
    def __init__(self, provider: str = 'anthropic', tier: str = 'tier1'):
        self.provider = provider
        self.tier = tier
        self.limits = RATE_LIMITS.get(provider, {}).get(tier, {})
        
        # 請求歷史記錄
        self.request_history = deque()  # (timestamp, tokens)
        self.lock = threading.Lock()
        
        # 當前使用統計
        self.minute_requests = 0
        self.minute_tokens = 0
        self.day_tokens = 0
        self.last_reset_minute = time.time()
        self.last_reset_day = time.time()
        
    def can_make_request(self, estimated_tokens: int) -> tuple[bool, float]:
        """
        檢查是否可以發送請求
        返回: (是否可以, 需要等待的秒數)
        """
        with self.lock:
            current_time = time.time()
            
            # 清理過期的請求記錄
            self._cleanup_history(current_time)
            
            # 檢查每分鐘請求數 (RPM)
            rpm_limit = self.limits.get('rpm', 50)
            current_rpm = self._count_requests_in_window(60)
            if current_rpm >= rpm_limit:
                wait_time = 60 - (current_time - self.request_history[0][0])
                return False, wait_time
            
            # 檢查每分鐘 token 數 (TPM)
            tpm_limit = self.limits.get('tpm', 50000)
            current_tpm = self._count_tokens_in_window(60)
            if current_tpm + estimated_tokens > tpm_limit:
                wait_time = 60 - (current_time - self.request_history[0][0])
                return False, wait_time
            
            # 檢查每日 token 數 (TPD)
            tpd_limit = self.limits.get('tpd', 1000000)
            current_tpd = self._count_tokens_in_window(86400)  # 24小時
            if current_tpd + estimated_tokens > tpd_limit:
                # 建議等待到第二天
                return False, 3600  # 返回1小時作為建議等待時間
            
            return True, 0
    
    def record_request(self, tokens_used: int):
        """記錄一次請求"""
        with self.lock:
            self.request_history.append((time.time(), tokens_used))
    
    def _cleanup_history(self, current_time: float):
        """清理超過24小時的記錄"""
        cutoff_time = current_time - 86400  # 24小時前
        while self.request_history and self.request_history[0][0] < cutoff_time:
            self.request_history.popleft()
    
    def _count_requests_in_window(self, window_seconds: int) -> int:
        """計算時間窗口內的請求數"""
        cutoff_time = time.time() - window_seconds
        count = 0
        for timestamp, _ in self.request_history:
            if timestamp >= cutoff_time:
                count += 1
        return count
    
    def _count_tokens_in_window(self, window_seconds: int) -> int:
        """計算時間窗口內的 token 總數"""
        cutoff_time = time.time() - window_seconds
        total_tokens = 0
        for timestamp, tokens in self.request_history:
            if timestamp >= cutoff_time:
                total_tokens += tokens
        return total_tokens
    
    def get_usage_stats(self) -> dict:
        """獲取當前使用統計"""
        with self.lock:
            current_time = time.time()
            self._cleanup_history(current_time)
            
            return {
                'rpm_current': self._count_requests_in_window(60),
                'rpm_limit': self.limits.get('rpm', 50),
                'tpm_current': self._count_tokens_in_window(60),
                'tpm_limit': self.limits.get('tpm', 50000),
                'tpd_current': self._count_tokens_in_window(86400),
                'tpd_limit': self.limits.get('tpd', 1000000),
            }

# 全局速率限制管理器實例
rate_limiters = {}

def get_rate_limiter(provider: str, tier: str = None) -> RateLimitManager:
    """獲取或創建速率限制管理器"""
    if tier is None:
        # 根據 API key 或其他邏輯判斷 tier
        # 這裡預設使用 tier2
        tier = 'tier2'
    
    key = f"{provider}_{tier}"
    if key not in rate_limiters:
        rate_limiters[key] = RateLimitManager(provider, tier)
    return rate_limiters[key]

# API 路由
@ai_analyzer_bp.route('/api/ai/analyze', methods=['POST'])
def analyze_file():
    """執行 AI 分析"""
    try:
        data = request.json
        session_id = data.get('session_id', str(time.time()))
        provider_name = data.get('provider', 'anthropic')
        model = data.get('model', AI_PROVIDERS[provider_name]['default_model'])
        mode = AnalysisMode(data.get('mode', 'smart'))
        file_path = data.get('file_path', '')
        file_name = data.get('file_name', '')
        file_content = data.get('content', '')
        stream = data.get('stream', True)
        context_messages = data.get('context', [])
        
        # 創建或獲取會話
        if session_id in active_analyses:
            session = active_analyses[session_id]
        else:
            provider = ProviderFactory.create_provider(provider_name, model)
            session = AnalysisSession(session_id, provider)
            active_analyses[session_id] = session
        
        # 添加上下文訊息到會話
        for msg in context_messages:
            if 'role' in msg and 'content' in msg:
                try:
                    role = MessageRole(msg['role']) if msg['role'] in ['user', 'assistant', 'system'] else MessageRole.USER
                    session.add_message(role, msg['content'])
                except ValueError:
                    # 如果角色無效，默認為用戶
                    session.add_message(MessageRole.USER, msg['content'])
        
        # 準備分析上下文
        context = AnalysisContext(
            file_path=file_path,
            file_content=file_content,
            mode=mode,
            previous_messages=session.messages,
            metadata={
                'session_id': session_id,
                'file_name': file_name
            }
        )
        
        if stream:
            def generate():
                """生成 SSE 流"""
                try:
                    # 發送開始事件
                    yield f"data: {json.dumps({'type': 'start', 'mode': mode.value})}\n\n"
                    
                    # 檢查檔案大小
                    file_size = len(file_content)
                    estimated_tokens = session.provider.calculate_tokens(file_content)
                    
                    # 顯示檔案資訊
                    file_info = f"正在分析檔案: {file_path}"
                    if file_name:
                        file_info = f"正在分析檔案: {file_name}"
                    
                    # 識別檔案類型
                    if 'tombstone' in file_path.lower() or 'tombstone' in file_content[:1000].lower():
                        file_info += " (Tombstone 崩潰日誌)"
                    elif 'anr' in file_path.lower() or 'input dispatching timed out' in file_content[:5000].lower():
                        file_info += " (ANR 日誌)"
                    elif 'fatal' in file_content[:1000].lower() or 'crash' in file_content[:1000].lower():
                        file_info += " (崩潰日誌)"
                    
                    yield f"data: {json.dumps({'type': 'info', 'message': file_info})}\n\n"
                    
                    # 顯示檔案大小資訊
                    size_info = f"檔案大小: {file_size:,} 字元 (約 {estimated_tokens:,} tokens)"
                    yield f"data: {json.dumps({'type': 'info', 'message': size_info})}\n\n"
                    
                    # 如果檔案很大，發送警告
                    model_config = MODEL_LIMITS.get(model, {})
                    max_tokens = model_config.get('max_tokens', 200000)
                    
                    if estimated_tokens > max_tokens * 0.8:  # 超過 80% 限制
                        warning_msg = f"⚠️ 檔案較大（約 {estimated_tokens:,} tokens），將自動截取適當內容進行分析"
                        yield f"data: {json.dumps({'type': 'warning', 'message': warning_msg})}\n\n"
                    
                    # 根據模式顯示預期時間
                    if mode == AnalysisMode.QUICK:
                        yield f"data: {json.dumps({'type': 'info', 'message': '⚡ 快速分析模式：預計 30 秒內完成'})}\n\n"
                    elif mode == AnalysisMode.DEEP:
                        yield f"data: {json.dumps({'type': 'info', 'message': '🔍 深度分析模式：預計 2-3 分鐘完成'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'info', 'message': '🧠 智能分析模式：自動平衡速度與深度'})}\n\n"
                    
                    # 估算輸入 tokens（可能會被截取）
                    yield f"data: {json.dumps({'type': 'tokens', 'input': estimated_tokens})}\n\n"
                    
                    # 流式輸出
                    output_content = ""
                    chunk_count = 0
                    last_update_time = time.time()
                    
                    try:
                        for chunk in session.provider.stream_analyze_sync(context):
                            # 檢查是否被中斷
                            if not session.is_active:
                                yield f"data: {json.dumps({'type': 'stopped', 'message': '分析已被使用者中斷'})}\n\n"
                                break
                            
                            output_content += chunk
                            chunk_count += 1
                            
                            # 發送內容
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                            
                            # 定期更新 token 計數（每秒最多一次）
                            current_time = time.time()
                            if current_time - last_update_time > 1.0:
                                output_tokens = session.provider.calculate_tokens(output_content)
                                yield f"data: {json.dumps({'type': 'tokens', 'output': output_tokens})}\n\n"
                                last_update_time = current_time
                    
                    except Exception as stream_error:
                        # 處理流式輸出中的錯誤
                        error_msg = str(stream_error)
                        if "rate limit" in error_msg.lower():
                            error_msg = "超過 API 速率限制，請稍後再試（建議等待 30 秒）"
                        elif "prompt is too long" in error_msg.lower():
                            error_msg = "檔案內容過大，請嘗試使用快速分析模式或分段分析"
                        
                        yield f"data: {json.dumps({'type': 'error', 'error': error_msg})}\n\n"
                        return
                    
                    # 如果內容被截取，在完成時通知
                    if context.metadata.get('was_truncated', False):
                        original_size = context.metadata.get('original_size', 0)
                        truncated_size = context.metadata.get('truncated_size', 0)
                        truncate_percentage = (truncated_size / original_size * 100) if original_size > 0 else 0
                        
                        truncate_info = {
                            'type': 'info',
                            'message': f"✂️ 分析完成。由於檔案過大，實際分析了 {truncated_size:,} / {original_size:,} 字元 ({truncate_percentage:.1f}%)"
                        }
                        yield f"data: {json.dumps(truncate_info)}\n\n"
                    
                    # 完成分析
                    if session.is_active and output_content:
                        # 添加訊息到會話歷史
                        session.add_message(MessageRole.USER, f"分析 {mode.value} 模式: {file_name or file_path}")
                        session.add_message(MessageRole.ASSISTANT, output_content)
                        
                        # 計算最終的 token 使用量
                        final_output_tokens = session.provider.calculate_tokens(output_content)
                        actual_input_tokens = context.metadata.get('actual_input_tokens', estimated_tokens)
                        session.update_usage(actual_input_tokens, final_output_tokens)
                        
                        # 發送完成事件
                        yield f"data: {json.dumps({
                            'type': 'complete',
                            'usage': {
                                'input': session.total_tokens['input'],
                                'output': session.total_tokens['output'],
                                'total': session.total_tokens['input'] + session.total_tokens['output']
                            },
                            'cost': session.total_cost,
                            'was_truncated': context.metadata.get('was_truncated', False),
                            'duration': (datetime.now() - session.created_at).total_seconds()
                        })}\n\n"
                    
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    
                    error_msg = str(e)
                    # 提供更友好的錯誤訊息
                    if "prompt is too long" in error_msg:
                        error_msg = "檔案內容超過模型限制，請使用快速分析模式或減少檔案大小"
                    elif "rate limit" in error_msg.lower():
                        error_msg = "API 請求過於頻繁，請等待 30 秒後再試"
                    elif "api key" in error_msg.lower():
                        error_msg = "API Key 無效或未設置，請檢查配置"
                    
                    yield f"data: {json.dumps({'type': 'error', 'error': error_msg})}\n\n"
            
            return Response(
                stream_with_context(generate()),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                    'Connection': 'keep-alive',
                    'Content-Type': 'text/event-stream'
                }
            )
        else:
            # 非流式回應
            try:
                result = session.provider.analyze_sync(context)
                
                # 檢查是否被截取
                was_truncated = context.metadata.get('was_truncated', False)
                
                # 更新會話
                session.add_message(MessageRole.USER, f"分析檔案: {file_name or file_path}")
                session.add_message(MessageRole.ASSISTANT, result)
                
                # 計算 token 使用量
                input_tokens = session.provider.calculate_tokens(file_content)
                output_tokens = session.provider.calculate_tokens(result)
                session.update_usage(input_tokens, output_tokens)
                
                response_data = {
                    'success': True,
                    'result': result,
                    'session_id': session_id,
                    'usage': {
                        'input': session.total_tokens['input'],
                        'output': session.total_tokens['output'],
                        'total': session.total_tokens['input'] + session.total_tokens['output']
                    },
                    'cost': session.total_cost,
                    'was_truncated': was_truncated
                }
                
                if was_truncated:
                    response_data['truncation_info'] = {
                        'original_size': context.metadata.get('original_size', 0),
                        'truncated_size': context.metadata.get('truncated_size', 0)
                    }
                
                return jsonify(response_data)
                
            except Exception as e:
                import traceback
                traceback.print_exc()
                
                error_msg = str(e)
                if "prompt is too long" in error_msg:
                    error_msg = "檔案內容超過模型限制"
                elif "rate limit" in error_msg.lower():
                    error_msg = "API 請求限制"
                
                return jsonify({
                    'success': False,
                    'error': error_msg,
                    'details': str(e)
                }), 500
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': '處理請求時發生錯誤',
            'details': str(e)
        }), 500

@ai_analyzer_bp.route('/api/ai/stop/<session_id>', methods=['POST'])
def stop_analysis(session_id):
    """停止分析"""
    if session_id in active_analyses:
        session = active_analyses[session_id]
        session.stop()
        return jsonify({'success': True, 'message': '分析已停止'})
    return jsonify({'success': False, 'error': '會話不存在'}), 404

@ai_analyzer_bp.route('/api/ai/models/<provider>', methods=['GET'])
def get_models(provider):
    """獲取可用模型列表"""
    if provider not in AI_PROVIDERS:
        return jsonify({'error': '不支援的 Provider'}), 400
        
    models = AI_PROVIDERS[provider]['models']
    return jsonify({
        'models': [
            {
                'id': model_id,
                'name': info['name'],
                'description': info['description'],
                'max_tokens': info['max_tokens'],
                'pricing': TOKEN_PRICING.get(provider, {}).get(model_id, {})
            }
            for model_id, info in models.items()
        ]
    })

@ai_analyzer_bp.route('/api/ai/rate-limit-status', methods=['GET'])
def get_rate_limit_status():
    """獲取當前速率限制狀態"""
    provider = request.args.get('provider', 'anthropic')
    
    try:
        limiter = get_rate_limiter(provider)
        stats = limiter.get_usage_stats()
        
        # 計算剩餘配額百分比
        rpm_percentage = (stats['rpm_current'] / stats['rpm_limit'] * 100) if stats['rpm_limit'] > 0 else 0
        tpm_percentage = (stats['tpm_current'] / stats['tpm_limit'] * 100) if stats['tpm_limit'] > 0 else 0
        tpd_percentage = (stats['tpd_current'] / stats['tpd_limit'] * 100) if stats['tpd_limit'] > 0 else 0
        
        return jsonify({
            'success': True,
            'provider': provider,
            'usage': {
                'requests_per_minute': {
                    'current': stats['rpm_current'],
                    'limit': stats['rpm_limit'],
                    'percentage': round(rpm_percentage, 1)
                },
                'tokens_per_minute': {
                    'current': stats['tpm_current'],
                    'limit': stats['tpm_limit'],
                    'percentage': round(tpm_percentage, 1)
                },
                'tokens_per_day': {
                    'current': stats['tpd_current'],
                    'limit': stats['tpd_limit'],
                    'percentage': round(tpd_percentage, 1)
                }
            },
            'status': 'normal' if max(rpm_percentage, tpm_percentage) < 80 else 'warning'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

