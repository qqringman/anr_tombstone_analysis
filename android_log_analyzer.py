# android_log_analyzer.py
import re
import json
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

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
    
    def generate_smart_prompts(self, sections: Dict[str, str], log_type: LogType, 
                              analysis_mode: str = 'comprehensive') -> List[Dict[str, str]]:
        """生成智能分析提示詞"""
        prompts = []
        
        if analysis_mode == 'quick':
            # 快速分析：只分析最關鍵的部分
            if log_type == LogType.ANR:
                prompt = self._generate_anr_quick_prompt(sections)
            else:
                prompt = self._generate_tombstone_quick_prompt(sections)
            prompts.append(prompt)
            
        elif analysis_mode == 'comprehensive':
            # 全面分析：分段深入分析
            if log_type == LogType.ANR:
                prompts.extend(self._generate_anr_comprehensive_prompts(sections))
            else:
                prompts.extend(self._generate_tombstone_comprehensive_prompts(sections))
                
        elif analysis_mode == 'max_tokens':
            # 最大 token 分析：在 token 限制內盡可能分析
            prompt = self._generate_max_token_prompt(sections, log_type)
            prompts.append(prompt)
        
        return prompts
    
    def _generate_anr_quick_prompt(self, sections: Dict[str, str]) -> Dict[str, str]:
        """生成 ANR 快速分析提示詞"""
        critical_info = f"""
ANR 日誌快速分析：

{sections.get('header', '')}

主線程狀態：
{sections.get('main_thread', '')[:1000]}

CPU 使用情況：
{sections.get('cpu_info', '')[:500]}

死鎖檢測：
{sections.get('deadlocks', '')[:1000]}

請快速分析：
1. ANR 的直接原因
2. 是否存在死鎖
3. 主線程被什麼阻塞
4. 立即可採取的修復措施
"""
        
        return {
            'system': "你是 Android ANR 專家。請提供簡潔準確的分析。",
            'user': critical_info
        }
    
    def _generate_tombstone_quick_prompt(self, sections: Dict[str, str]) -> Dict[str, str]:
        """生成 Tombstone 快速分析提示詞"""
        critical_info = f"""
Tombstone 崩潰分析：

{sections.get('signal_info', '')}
{sections.get('abort_message', '')}

關鍵堆棧：
{sections.get('backtrace', '')[:1500]}

請快速分析：
1. 崩潰類型和原因
2. 崩潰發生在哪個函數
3. 是否是空指針/內存問題
4. 修復建議
"""
        
        return {
            'system': "你是 Android 崩潰分析專家。請提供精確的崩潰原因分析。",
            'user': critical_info
        }
    
    def _generate_anr_comprehensive_prompts(self, sections: Dict[str, str]) -> List[Dict[str, str]]:
        """生成 ANR 全面分析提示詞組"""
        prompts = []
        
        # 第一部分：線程狀態分析
        prompts.append({
            'system': "分析 Android ANR 的線程狀態和鎖定情況。",
            'user': f"""
分析以下線程信息，找出死鎖或阻塞原因：

{sections.get('main_thread', '')}

關鍵線程：
{sections.get('key_threads', '')}

請識別：
1. 哪些線程被阻塞
2. 鎖的持有和等待關係
3. 是否存在死鎖循環
"""
        })
        
        # 第二部分：系統資源分析
        prompts.append({
            'system': "分析 ANR 時的系統資源使用情況。",
            'user': f"""
分析系統資源：

{sections.get('cpu_info', '')}
{sections.get('memory_info', '')}

請分析：
1. CPU 使用是否異常
2. 內存壓力情況
3. 是否有資源耗盡
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
1. 崩潰信號的含義
2. 崩潰地址的意義
3. 可能的原因（空指針/越界/其他）
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
1. 崩潰發生在哪個函數
2. 調用鏈路
3. 是否涉及系統庫或應用代碼
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
1. 問題摘要（2-3句話）
2. 根本原因分析（詳細）
3. 影響範圍
4. 證據鏈（引用日誌內容）
5. 修復方案（短期和長期）
6. 預防措施

日誌內容：
{combined_content}
"""
        }