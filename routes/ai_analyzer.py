from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import anthropic
from config.config import CLAUDE_API_KEY, MODEL_LIMITS

@dataclass
class AnalysisRequest:
    """分析請求的資料結構"""
    file_path: str
    content: str
    file_type: str
    mode: str
    original_question: Optional[str] = None
    enable_thinking: bool = True

@dataclass
class AnalysisResult:
    """分析結果的資料結構"""
    success: bool
    analysis: str
    model: str
    mode: str
    elapsed_time: float
    is_segmented: bool = False
    segments: List[Dict] = None
    error: Optional[str] = None

class AnalysisStrategy(ABC):
    """分析策略的抽象基類"""
    
    def __init__(self, client: anthropic.Anthropic):
        self.client = client
        self.model = self.get_default_model()
    
    @abstractmethod
    def get_default_model(self) -> str:
        """獲取預設模型"""
        pass
    
    @abstractmethod
    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        """執行分析"""
        pass
    
    def estimate_tokens(self, text: str) -> int:
        """估算 token 數量"""
        english_chars = len([c for c in text if c.isascii() and c.isalnum()])
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
        other_chars = len(text) - english_chars - chinese_chars
        
        estimated = (
            english_chars / 4 +
            chinese_chars / 2.5 +
            other_chars / 3
        )
        
        return int(estimated * 1.1)

class QuickAnalysisStrategy(AnalysisStrategy):
    """快速分析策略 - 30秒內完成"""
    
    def get_default_model(self) -> str:
        return 'claude-3-5-haiku-20241022'
    
    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        import time
        start_time = time.time()
        
        try:
            # 提取關鍵部分（最多 25KB）
            key_content = self._extract_key_sections(request.content, request.file_type)
            
            # 構建精簡的提示
            system_prompt = """你是 Android 系統專家。快速分析日誌，只提供最關鍵的發現。
限制回答在 1000 字以內，包含：
1. 主要問題（1-2句）
2. 根本原因（1-2句）
3. 立即可行的解決方案（2-3點）"""
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0,
                system=system_prompt,
                messages=[{"role": "user", "content": key_content}]
            )
            
            elapsed_time = time.time() - start_time
            
            return AnalysisResult(
                success=True,
                analysis=response.content[0].text,
                model=self.model,
                mode='quick',
                elapsed_time=elapsed_time,
                is_segmented=False
            )
            
        except Exception as e:
            return AnalysisResult(
                success=False,
                analysis='',
                model=self.model,
                mode='quick',
                elapsed_time=time.time() - start_time,
                error=str(e)
            )
    
    def _extract_key_sections(self, content: str, file_type: str) -> str:
        """提取關鍵部分"""
        max_size = 25000
        
        if file_type == 'ANR':
            # ANR 的關鍵部分
            keywords = ['main', 'BLOCKED', 'held by', 'waiting', 'CPU usage']
        else:
            # Tombstone 的關鍵部分
            keywords = ['signal', 'fault addr', 'backtrace', 'abort message']
        
        # 簡單實現：提取包含關鍵字的行
        lines = content.split('\n')
        key_lines = []
        current_size = 0
        
        for i, line in enumerate(lines):
            if any(keyword in line for keyword in keywords):
                # 包含前後文
                start = max(0, i - 5)
                end = min(len(lines), i + 10)
                for j in range(start, end):
                    if current_size + len(lines[j]) < max_size:
                        key_lines.append(lines[j])
                        current_size += len(lines[j])
        
        return '\n'.join(key_lines)

class ComprehensiveAnalysisStrategy(AnalysisStrategy):
    """深度分析策略 - 詳細分析"""
    
    def get_default_model(self) -> str:
        return 'claude-opus-4-20250514'
    
    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        import time
        start_time = time.time()
        
        try:
            # 檢查是否需要分段
            if self._needs_segmentation(request.content):
                return self._analyze_in_segments(request)
            else:
                return self._analyze_single(request)
                
        except Exception as e:
            return AnalysisResult(
                success=False,
                analysis='',
                model=self.model,
                mode='comprehensive',
                elapsed_time=time.time() - start_time,
                error=str(e)
            )
    
    def _needs_segmentation(self, content: str) -> bool:
        """判斷是否需要分段"""
        estimated_tokens = self.estimate_tokens(content)
        model_config = MODEL_LIMITS.get(self.model, MODEL_LIMITS['claude-3-5-sonnet-20241022'])
        max_tokens = int(model_config['max_tokens'] * 0.8)
        return estimated_tokens > max_tokens
    
    def _analyze_single(self, request: AnalysisRequest) -> AnalysisResult:
        """單次深度分析"""
        import time
        start_time = time.time()
        
        system_prompt = """你是資深的 Android 系統專家，請提供極其詳細的分析報告。

分析格式：
# 執行摘要
[2-3段的問題概述]

# 技術分析
## 1. 問題識別
[詳細列出所有發現的問題]

## 2. 根本原因分析
[深入分析每個問題的根源]

## 3. 影響評估
[評估問題的嚴重性和影響範圍]

# 解決方案
## 立即措施
## 短期改進
## 長期優化

# 預防措施"""
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": request.content}]
        )
        
        return AnalysisResult(
            success=True,
            analysis=response.content[0].text,
            model=self.model,
            mode='comprehensive',
            elapsed_time=time.time() - start_time,
            is_segmented=False
        )
    
    def _analyze_in_segments(self, request: AnalysisRequest) -> AnalysisResult:
        """分段深度分析"""
        # 這裡實現分段邏輯
        # 為了簡化，這裡只是示意
        segments = self._create_segments(request.content)
        segment_results = []
        
        for i, segment in enumerate(segments):
            # 分析每個段落
            result = self._analyze_segment(segment, i, len(segments))
            segment_results.append(result)
        
        # 綜合所有段落
        final_analysis = self._synthesize_segments(segment_results)
        
        return AnalysisResult(
            success=True,
            analysis=final_analysis,
            model=self.model,
            mode='comprehensive',
            elapsed_time=0,  # 計算總時間
            is_segmented=True,
            segments=segment_results
        )
    
    def _create_segments(self, content: str) -> List[str]:
        """創建智能分段"""
        # 簡化實現
        max_size = 100000
        segments = []
        
        for i in range(0, len(content), max_size):
            segments.append(content[i:i+max_size])
        
        return segments
    
    def _analyze_segment(self, segment: str, index: int, total: int) -> Dict:
        """分析單個段落"""
        # 簡化實現
        return {
            'segment_number': index + 1,
            'analysis': f'段落 {index + 1} 的分析結果',
            'success': True
        }
    
    def _synthesize_segments(self, segments: List[Dict]) -> str:
        """綜合所有段落的分析"""
        return "綜合分析結果"

class SmartAnalysisStrategy(AnalysisStrategy):
    """智能分析策略 - 自動選擇最佳方法"""
    
    def __init__(self, client: anthropic.Anthropic):
        super().__init__(client)
        self.quick_strategy = QuickAnalysisStrategy(client)
        self.comprehensive_strategy = ComprehensiveAnalysisStrategy(client)
    
    def get_default_model(self) -> str:
        return 'claude-sonnet-4-20250514'
    
    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        # 根據內容大小自動選擇策略
        content_size = len(request.content)
        estimated_tokens = self.estimate_tokens(request.content)
        
        if estimated_tokens < 20000:  # 小檔案
            # 使用標準分析
            return self._standard_analysis(request)
        elif estimated_tokens < 100000:  # 中等檔案
            # 使用優化分析
            return self._optimized_analysis(request)
        else:  # 大檔案
            # 使用深度策略的分段分析
            return self.comprehensive_strategy.analyze(request)
    
    def _standard_analysis(self, request: AnalysisRequest) -> AnalysisResult:
        """標準分析"""
        import time
        start_time = time.time()
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            temperature=0,
            system="智能分析 Android 日誌，提供平衡的分析結果",
            messages=[{"role": "user", "content": request.content}]
        )
        
        return AnalysisResult(
            success=True,
            analysis=response.content[0].text,
            model=self.model,
            mode='auto',
            elapsed_time=time.time() - start_time,
            is_segmented=False
        )
    
    def _optimized_analysis(self, request: AnalysisRequest) -> AnalysisResult:
        """優化分析"""
        # 實現優化邏輯
        return self._standard_analysis(request)

class AIAnalyzer:
    """AI 分析器的主類"""
    
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        self.strategies = {
            'quick': QuickAnalysisStrategy(self.client),
            'comprehensive': ComprehensiveAnalysisStrategy(self.client),
            'auto': SmartAnalysisStrategy(self.client)
        }
    
    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        """執行分析"""
        strategy = self.strategies.get(request.mode, self.strategies['auto'])
        return strategy.analyze(request)