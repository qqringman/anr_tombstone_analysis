# android_log_analyzer.py
import re
import json
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
from config.config import MODEL_LIMITS
import threading
from typing import Dict, List, Tuple
import time
import asyncio
import queue
from collections import deque

class LogType(Enum):
    ANR = "ANR"
    TOMBSTONE = "Tombstone"
    UNKNOWN = "Unknown"

@dataclass
class AnalysisResult:
    log_type: LogType
    summary: str
    root_cause: str
    affected_processes: List[str]
    key_evidence: List[str]
    recommendations: List[str]
    severity: str  # Critical, High, Medium, Low
    confidence: float  # 0.0 - 1.0

class AndroidLogAnalyzer:
    """Android ANR/Tombstone 日誌智能分析器"""
    
    def __init__(self):
        # ANR 關鍵模式
        self.anr_patterns = {
            'main_thread_blocked': r'main.*?(?:BLOCKED|WAITING|TIMED_WAITING)',
            'lock_wait': r'waiting to lock <(0x[0-9a-f]+)>',
            'held_by': r'held by thread (\d+)',
            'cpu_usage': r'CPU usage.*?(\d+)%.*?user.*?(\d+)%.*?kernel',
            'anr_header': r'ANR in (.*?) \((.*?)\)',
            'reason': r'Reason: (.*?)(?:\n|$)',
            'deadlock': r'Found one Java-level deadlock',
            'binder_timeout': r'Binder.*?timeout',
            'input_dispatching': r'Input dispatching timed out'
        }
        
        # Tombstone 關鍵模式
        self.tombstone_patterns = {
            'signal': r'signal (\d+) \((.*?)\)',
            'fault_addr': r'fault addr (0x[0-9a-f]+)',
            'abort_message': r'Abort message: (.*?)(?:\n|$)',
            'crash_type': r'(?:SIGSEGV|SIGABRT|SIGBUS|SIGFPE|SIGILL)',
            'backtrace': r'backtrace:',
            'pc_address': r'pc ([0-9a-f]+)',
            'process_name': r'pid: \d+, tid: \d+, name: (.*?)>>>',
            'native_crash': r'Native crash',
            'java_crash': r'JavaCrashReport'
        }
        
        # 常見問題模式庫
        self.known_issues = {
            'null_pointer': {
                'pattern': r'(?:null pointer|0x0000000000000000|segmentation fault)',
                'severity': 'Critical',
                'recommendation': '檢查空指針引用，確保對象初始化'
            },
            'oom': {
                'pattern': r'(?:OutOfMemoryError|OOM|low memory)',
                'severity': 'High',
                'recommendation': '優化內存使用，檢查內存洩漏'
            },
            'stack_overflow': {
                'pattern': r'(?:StackOverflowError|stack overflow)',
                'severity': 'High',
                'recommendation': '檢查遞歸調用，優化算法'
            },
            'deadlock': {
                'pattern': r'(?:deadlock|circular dependency)',
                'severity': 'Critical',
                'recommendation': '重新設計鎖定順序，避免循環依賴'
            },
            'binder_exhausted': {
                'pattern': r'(?:binder.*exhausted|too many binder threads)',
                'severity': 'High',
                'recommendation': '減少 Binder 調用頻率，優化 IPC'
            }
        }
    
    def detect_log_type(self, content: str) -> LogType:
        """檢測日誌類型"""
        content_lower = content.lower()
        
        # 檢查 ANR 特徵
        anr_indicators = [
            'anr in',
            'application not responding',
            'input dispatching timed out',
            'broadcast timeout',
            'service timeout'
        ]
        
        # 檢查 Tombstone 特徵
        tombstone_indicators = [
            '*** *** *** *** *** *** *** ***',
            'build fingerprint:',
            'tombstone',
            'signal',
            'fault addr',
            'abort message'
        ]
        
        anr_score = sum(1 for indicator in anr_indicators if indicator in content_lower)
        tombstone_score = sum(1 for indicator in tombstone_indicators if indicator in content_lower)
        
        if tombstone_score > anr_score:
            return LogType.TOMBSTONE
        elif anr_score > 0:
            return LogType.ANR
        else:
            return LogType.UNKNOWN
    
    def extract_key_sections(self, content: str, log_type: LogType) -> Dict[str, str]:
        """提取關鍵部分以減少 token 使用"""
        sections = {}
        
        if log_type == LogType.ANR:
            # 提取 ANR 關鍵部分
            sections['header'] = self._extract_section(content, r'ANR in.*?(?=\n\n)', 500)
            sections['main_thread'] = self._extract_thread_info(content, 'main')
            sections['cpu_info'] = self._extract_section(content, r'CPU usage.*?(?=\n\n)', 1000)
            sections['memory_info'] = self._extract_section(content, r'Total memory.*?(?=\n\n)', 500)
            sections['deadlocks'] = self._extract_section(content, r'Found.*?deadlock.*?(?=\n\n)', 2000)
            sections['key_threads'] = self._extract_important_threads(content)
            
        elif log_type == LogType.TOMBSTONE:
            # 提取 Tombstone 關鍵部分
            sections['header'] = self._extract_section(content, r'\*\*\*.*?Revision.*?(?=\n)', 1000)
            sections['signal_info'] = self._extract_section(content, r'signal.*?fault addr.*?(?=\n)', 500)
            sections['abort_message'] = self._extract_section(content, r'Abort message:.*?(?=\n)', 500)
            sections['backtrace'] = self._extract_backtrace(content)
            sections['registers'] = self._extract_section(content, r'registers:.*?(?=backtrace:)', 1000)
            sections['memory_map'] = self._extract_memory_map(content)
        
        return sections
    
    def _extract_section(self, content: str, pattern: str, max_chars: int) -> str:
        """提取指定模式的部分"""
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            section = match.group(0)
            return section[:max_chars] if len(section) > max_chars else section
        return ""
    
    def _extract_thread_info(self, content: str, thread_name: str) -> str:
        """提取特定線程信息"""
        pattern = rf'".*?{thread_name}.*?".*?(?:\n.*?){{0,50}}'
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        return match.group(0) if match else ""
    
    def _extract_important_threads(self, content: str) -> str:
        """提取重要線程（主線程、Binder線程、被阻塞的線程）"""
        important_threads = []
        thread_pattern = r'"(.*?)".*?tid=\d+.*?(?:BLOCKED|WAITING|RUNNABLE).*?(?:\n.*?){0,10}'
        
        for match in re.finditer(thread_pattern, content):
            thread_info = match.group(0)
            if any(keyword in thread_info for keyword in ['main', 'Binder', 'BLOCKED', 'waiting to lock']):
                important_threads.append(thread_info)
                if len(important_threads) >= 5:  # 限制數量
                    break
        
        return '\n\n'.join(important_threads)
    
    def _extract_backtrace(self, content: str) -> str:
        """提取關鍵的堆棧追蹤"""
        backtrace_start = content.find('backtrace:')
        if backtrace_start == -1:
            return ""
        
        # 提取前 30 行堆棧
        lines = content[backtrace_start:].split('\n')[:30]
        return '\n'.join(lines)
    
    def _extract_memory_map(self, content: str) -> str:
        """提取崩潰地址附近的內存映射"""
        # 先找到 fault address
        fault_match = re.search(r'fault addr (0x[0-9a-f]+)', content)
        if not fault_match:
            return ""
        
        fault_addr = int(fault_match.group(1), 16)
        
        # 提取相關的內存映射
        memory_maps = []
        map_pattern = r'([0-9a-f]+)-([0-9a-f]+).*?(/.*?)(?:\n|$)'
        
        for match in re.finditer(map_pattern, content):
            start_addr = int(match.group(1), 16)
            end_addr = int(match.group(2), 16)
            
            if start_addr <= fault_addr <= end_addr:
                memory_maps.append(match.group(0))
                # 也包含前後幾行
                context = content[max(0, match.start()-200):match.end()+200]
                memory_maps.append(context)
                break
        
        return '\n'.join(memory_maps[:500])  # 限制長度
    
    def _combine_sections_smart(self, sections: Dict[str, str], max_size: int = 50000) -> str:
        """智能組合各個部分的內容"""
        if not sections:
            return ""
        
        combined_parts = []
        total_size = 0
        
        # 按優先級排序的 keys
        priority_order = [
            'header', 'signal_info', 'abort_message', 'main_thread', 
            'backtrace', 'deadlocks', 'cpu_info', 'memory_info', 
            'registers', 'memory_map', 'key_threads'
        ]
        
        # 先添加優先級高的部分
        for key in priority_order:
            if key in sections and sections[key]:
                content = sections[key].strip()
                if content and total_size + len(content) < max_size:
                    combined_parts.append(f"=== {key.upper()} ===\n{content}")
                    total_size += len(content)
        
        # 如果還有空間，添加其他部分
        for key, content in sections.items():
            if key not in priority_order and content:
                content = content.strip()
                if content and total_size + len(content) < max_size:
                    combined_parts.append(f"=== {key.upper()} ===\n{content}")
                    total_size += len(content)
        
        result = '\n\n'.join(combined_parts)
        
        # 確保返回非空內容
        if not result:
            result = "無法提取有效內容"
        
        return result

    def generate_smart_prompts(self, sections: Dict[str, str], log_type: LogType, 
                          analysis_mode: str = 'comprehensive') -> List[Dict[str, str]]:
        """生成智能分析提示詞"""
        prompts = []
        
        if analysis_mode == 'auto':
            # 智能模式：平衡且實用
            prompt = {
                'system': f"""你是 Android {log_type.value} 分析專家。請提供智能、實用的分析。

    重點關注：
    1. 快速定位問題根源
    2. 提供可執行的解決方案
    3. 預測潛在風險

    格式要求：
    - 使用簡潔的要點
    - 突出關鍵信息
    - 提供優先級建議""",
                'user': f"""
    分析此 {log_type.value} 日誌並提供：

    1. **問題診斷**（最重要的3個發現）
    2. **根本原因**（1-2句話說明）
    3. **立即行動**（按優先級排序）
    4. **風險評估**（如果不處理會怎樣）

    重點查找：
    - 發生問題的 Process 名稱
    - Main thread 的 backtrace
    - 卡住或崩潰的具體原因

    日誌內容：
    {self._combine_sections_smart(sections)}
    """
            }
            prompts.append(prompt)
        
        return prompts
    
    def _generate_anr_quick_prompt(self, sections: Dict[str, str]) -> Dict[str, str]:
        """生成 ANR 快速分析提示詞"""
        # 收集所有非空的部分
        content_parts = []
        
        if sections.get('header') and sections['header'].strip():
            content_parts.append(f"=== ANR 標題信息 ===\n{sections['header']}")
        
        if sections.get('main_thread') and sections['main_thread'].strip():
            content_parts.append(f"=== 主線程狀態 ===\n{sections['main_thread'][:1000]}")
        
        if sections.get('cpu_info') and sections['cpu_info'].strip():
            content_parts.append(f"=== CPU 使用情況 ===\n{sections['cpu_info'][:500]}")
        
        if sections.get('deadlocks') and sections['deadlocks'].strip():
            content_parts.append(f"=== 死鎖檢測 ===\n{sections['deadlocks'][:1000]}")
        
        # 如果沒有任何內容，返回一個基本的提示
        if not content_parts:
            critical_info = "無法提取關鍵信息，請基於您的專業知識提供一般性的 ANR 分析指導。"
        else:
            critical_info = '\n\n'.join(content_parts)
        
        # 確保 critical_info 不為空
        if not critical_info.strip():
            critical_info = "ANR 日誌內容為空或無法解析。"
        
        user_content = f"""ANR 日誌快速分析：

    {critical_info}

    請快速分析：
    1. ANR 的直接原因
    2. 是否存在死鎖
    3. 主線程被什麼阻塞
    4. 立即可採取的修復措施

    如果能識別到具體的 Process 和 backtrace，請指出。"""
        
        return {
            'system': "你是 Android ANR 專家。請提供簡潔準確的分析。",
            'user': user_content
        }
    
    def _generate_tombstone_quick_prompt(self, sections: Dict[str, str]) -> Dict[str, str]:
        """生成 Tombstone 快速分析提示詞"""
        # 收集所有非空的部分
        content_parts = []
        
        if sections.get('signal_info') and sections['signal_info'].strip():
            content_parts.append(f"=== 信號信息 ===\n{sections['signal_info']}")
        
        if sections.get('abort_message') and sections['abort_message'].strip():
            content_parts.append(f"=== 中止消息 ===\n{sections['abort_message']}")
        
        if sections.get('backtrace') and sections['backtrace'].strip():
            content_parts.append(f"=== 關鍵堆棧 ===\n{sections['backtrace'][:1500]}")
        
        # 如果沒有任何內容，返回一個基本的提示
        if not content_parts:
            critical_info = "無法提取關鍵信息，請基於您的專業知識提供一般性的崩潰分析指導。"
        else:
            critical_info = '\n\n'.join(content_parts)
        
        # 確保 critical_info 不為空
        if not critical_info.strip():
            critical_info = "Tombstone 日誌內容為空或無法解析。"
        
        user_content = f"""Tombstone 崩潰分析：

    {critical_info}

    請快速分析：
    1. 崩潰類型和原因
    2. 崩潰發生在哪個函數
    3. 是否是空指針/內存問題
    4. 修復建議

    如果能識別到具體的 Process 和 backtrace，請指出。"""
        
        return {
            'system': "你是 Android 崩潰分析專家。請提供精確的崩潰原因分析。",
            'user': user_content
        }
    
    def _generate_anr_comprehensive_prompts(self, sections: Dict[str, str]) -> List[Dict[str, str]]:
        """生成 ANR 全面分析提示詞組"""
        prompts = []
        
        # 深度分析專用提示
        prompts.append({
            'system': """你是 Android ANR 深度分析專家。請提供極其詳細的技術分析。
    使用以下格式：

    ## 執行摘要
    [2-3段的問題概述]

    ## 技術分析

    ### 1. 問題識別
    [詳細列出所有發現的問題]

    ### 2. 根本原因分析
    [深入分析每個問題的根源]
    - 指出發生 ANR 的 Process
    - 列出該 Process main thread 的完整 backtrace
    - 分析 main thread 卡住的具體原因

    ### 3. 影響評估
    [評估問題的嚴重性和影響範圍]

    ### 4. 技術細節
    [堆棧分析、內存狀態、線程狀態等]

    ## 解決方案

    ### 立即措施
    1. [具體步驟1]
    2. [具體步驟2]

    ### 短期改進
    - [1-2週內的改進計劃]

    ### 長期優化
    - [架構級別的改進建議]

    ## 預防措施
    [如何避免類似問題]
    """,
            'user': f"""
    分析以下 ANR 日誌：

    {sections.get('header', '')}
    {sections.get('main_thread', '')}
    {sections.get('key_threads', '')}
    {sections.get('deadlocks', '')}
    {sections.get('cpu_info', '')}

    請提供深度技術分析。
    """
        })
        
        return prompts
    
    def _generate_tombstone_comprehensive_prompts(self, sections: Dict[str, str]) -> List[Dict[str, str]]:
        """生成 Tombstone 全面分析提示詞組"""
        prompts = []
        
        # 第一部分：崩潰原因分析
        prompts.append({
            'system': "分析 Android Native 崩潰的根本原因。",
            'user': f"""
崩潰信息：
{sections.get('signal_info', '')}
{sections.get('abort_message', '')}

寄存器狀態：
{sections.get('registers', '')[:1000]}

請分析：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 崩潰信號的含義
5. 崩潰地址的意義
6. 可能的原因（空指針/越界/其他）
"""
        })
        
        # 第二部分：堆棧追蹤分析
        prompts.append({
            'system': "分析崩潰的調用堆棧，定位問題代碼。",
            'user': f"""
堆棧追蹤：
{sections.get('backtrace', '')}

內存映射：
{sections.get('memory_map', '')}

請分析：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 崩潰發生在哪個函數
5. 調用鏈路
6. 是否涉及系統庫或應用代碼
"""
        })
        
        return prompts
    
    def _generate_max_token_prompt(self, sections: Dict[str, str], log_type: LogType) -> Dict[str, str]:
        """生成最大 token 限制內的分析提示詞"""
        # 根據優先級組合內容，直到接近 token 限制
        max_chars = 350000  # 約 175K tokens
        
        content_parts = []
        current_chars = 0
        
        if log_type == LogType.ANR:
            priority_sections = [
                ('header', sections.get('header', '')),
                ('main_thread', sections.get('main_thread', '')),
                ('deadlocks', sections.get('deadlocks', '')),
                ('key_threads', sections.get('key_threads', '')),
                ('cpu_info', sections.get('cpu_info', '')),
                ('memory_info', sections.get('memory_info', ''))
            ]
        else:
            priority_sections = [
                ('signal_info', sections.get('signal_info', '')),
                ('abort_message', sections.get('abort_message', '')),
                ('backtrace', sections.get('backtrace', '')),
                ('registers', sections.get('registers', '')),
                ('memory_map', sections.get('memory_map', ''))
            ]
        
        for name, content in priority_sections:
            if current_chars + len(content) < max_chars:
                content_parts.append(f"=== {name.upper()} ===\n{content}")
                current_chars += len(content)
            else:
                # 添加部分內容
                remaining = max_chars - current_chars
                if remaining > 1000:
                    content_parts.append(f"=== {name.upper()} (TRUNCATED) ===\n{content[:remaining]}")
                break
        
        combined_content = '\n\n'.join(content_parts)
        
        return {
            'system': f"你是 Android {log_type.value} 分析專家。請提供全面深入的分析。",
            'user': f"""
請分析以下 {log_type.value} 日誌，提供：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 問題摘要（2-3句話）
5. 根本原因分析（詳細）
6. 影響範圍
7. 證據鏈（引用日誌內容）
8. 修復方案（短期和長期）
9. 預防措施

日誌內容：
{combined_content}
"""
        }