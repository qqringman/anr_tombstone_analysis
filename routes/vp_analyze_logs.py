#!/usr/bin/env python3
"""
進階版 Android ANR/Tombstone 分析器 v4
支援所有 Android 版本的 ANR 和 Tombstone 格式
使用物件導向設計，基於大量真實案例的智能分析
"""

import os
import re
import sys
import html
import shutil
import time
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
from enum import Enum
import traceback


# ============= 工具函數 =============

def time_tracker(func_name: str):
    """時間追蹤裝飾器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            elapsed_time = time.time() - start_time
            print(f"⏱️  {func_name} 執行時間: {elapsed_time:.3f} 秒")
            return result
        return wrapper
    return decorator


# ============= 資料類別定義 =============

class ThreadState(Enum):
    """線程狀態枚舉"""
    RUNNABLE = "RUNNABLE"
    TIMED_WAIT = "TIMED_WAIT"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"
    SUSPENDED = "SUSPENDED"
    NATIVE = "NATIVE"
    MONITOR = "MONITOR"
    SLEEPING = "SLEEPING"
    ZOMBIE = "ZOMBIE"
    UNKNOWN = "UNKNOWN"


class ANRType(Enum):
    """ANR 類型枚舉"""
    INPUT_DISPATCHING = "Input ANR"
    SERVICE = "Service ANR"
    BROADCAST = "Broadcast ANR"
    CONTENT_PROVIDER = "Provider ANR"
    ACTIVITY = "Activity ANR"
    FOREGROUND_SERVICE = "Foreground Service ANR"
    UNKNOWN = "Unknown ANR"


class CrashSignal(Enum):
    """崩潰信號枚舉"""
    SIGSEGV = (11, "Segmentation fault")
    SIGABRT = (6, "Abort")
    SIGILL = (4, "Illegal instruction")
    SIGBUS = (7, "Bus error")
    SIGFPE = (8, "Floating point exception")
    SIGKILL = (9, "Kill signal")
    SIGTRAP = (5, "Trace trap")
    UNKNOWN = (0, "Unknown signal")


@dataclass
class ThreadInfo:
    """線程資訊"""
    name: str
    tid: str
    prio: str = "N/A"
    state: ThreadState = ThreadState.UNKNOWN
    sysTid: Optional[str] = None
    nice: Optional[str] = None
    schedstat: Optional[str] = None
    utm: Optional[str] = None
    stm: Optional[str] = None
    core: Optional[str] = None
    handle: Optional[str] = None
    backtrace: List[str] = field(default_factory=list)
    waiting_info: Optional[str] = None
    held_locks: List[str] = field(default_factory=list)
    waiting_locks: List[str] = field(default_factory=list)


@dataclass
class ANRInfo:
    """ANR 資訊"""
    anr_type: ANRType
    process_name: str
    pid: str
    timestamp: Optional[str] = None
    reason: Optional[str] = None
    main_thread: Optional[ThreadInfo] = None
    all_threads: List[ThreadInfo] = field(default_factory=list)
    cpu_usage: Optional[Dict] = None
    memory_info: Optional[Dict] = None


@dataclass
class TombstoneInfo:
    """Tombstone 資訊"""
    signal: CrashSignal
    signal_code: str
    fault_addr: str
    process_name: str
    pid: str
    tid: str
    thread_name: str
    abort_message: Optional[str] = None
    crash_backtrace: List[Dict] = field(default_factory=list)
    all_threads: List[ThreadInfo] = field(default_factory=list)
    memory_map: List[str] = field(default_factory=list)
    open_files: List[str] = field(default_factory=list)
    registers: Dict[str, str] = field(default_factory=dict)


# ============= 基礎分析器類別 =============

class BaseAnalyzer(ABC):
    """基礎分析器抽象類別"""
    
    def __init__(self):
        self.patterns = self._init_patterns()
    
    @abstractmethod
    def _init_patterns(self) -> Dict:
        """初始化分析模式"""
        pass
    
    @abstractmethod
    def analyze(self, file_path: str) -> str:
        """分析檔案"""
        pass


# ============= ANR 分析器 =============

class ANRAnalyzer(BaseAnalyzer):
    """ANR 分析器"""
    
    def _init_patterns(self) -> Dict:
        """初始化 ANR 分析模式"""
        return {
            'thread_patterns': [
                # 標準格式 (Android 4.x - 13)
                r'"([^"]+)"\s+(?:daemon\s+)?prio=(\d+)\s+tid=(\d+)\s+(\w+)',
                # 簡化格式
                r'"([^"]+)".*?tid=(\d+).*?(\w+)',
                # Thread dump 格式
                r'Thread-(\d+)\s+"([^"]+)".*?tid=(\d+).*?(\w+)',
                # ART 格式 (Android 5.0+)
                r'"([^"]+)".*?\|\s+group="([^"]+)".*?tid=(\d+).*?\|\s+state=(\w)',
                # 系統服務格式
                r'([a-zA-Z0-9._]+)\s+prio=(\d+)\s+tid=(\d+)\s+(\w+)',
                # Native thread 格式
                r'Thread\s+(\d+)\s+\(([^)]+)\).*?State:\s+(\w)',
            ],
            'anr_trigger_patterns': [
                r'Input event dispatching timed out.*?Waited\s+(\d+)ms\s+for\s+(.+)',
                r'Reason:\s*Input dispatching timed out.*?Waited\s+(\d+)ms',
                r'executing service\s+([^\s]+).*?timeout=(\d+)ms',
                r'Broadcast of Intent.*?timed out.*?receiver=([^\s]+)',
                r'ContentProvider.*?not responding.*?provider=([^\s]+)',
                r'ANR in\s+([^,\s]+).*?PID:\s*(\d+)',
                r'Subject:\s*ANR.*?Process:\s*([^\s]+)',
                r'Cmd line:\s*([^\s]+)',
            ],
            'lock_patterns': [
                r'waiting to lock\s+<([^>]+)>.*?held by thread\s+(\d+)',
                r'locked\s+<([^>]+)>',
                r'waiting on\s+<([^>]+)>',
                r'- locked\s+<0x([0-9a-f]+)>\s+\(a\s+([^)]+)\)',
                r'heldby=(\d+)',
            ],
            'binder_patterns': [
                r'BinderProxy\.transact',
                r'Binder\.transact',
                r'IPCThreadState::transact',
                r'android\.os\.BinderProxy\.transactNative',
            ],
        }
    
    @time_tracker("解析 ANR 檔案")
    def analyze(self, file_path: str) -> str:
        """分析 ANR 檔案"""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            # 解析 ANR 資訊
            anr_info = self._parse_anr_info(content)
            
            # 生成分析報告
            report = self._generate_report(anr_info, content)
            
            return report
            
        except Exception as e:
            return f"❌ 分析 ANR 檔案時發生錯誤: {str(e)}\n{traceback.format_exc()}"
    
    def _parse_anr_info(self, content: str) -> ANRInfo:
        """解析 ANR 資訊"""
        lines = content.splitlines()
        
        # 識別 ANR 類型和基本資訊
        anr_type = self._identify_anr_type(content)
        process_info = self._extract_process_info(content)
        
        # 解析所有線程資訊
        all_threads = self._extract_all_threads(lines, content)
        
        # 找出主線程
        main_thread = self._find_main_thread(all_threads)
        
        # 解析額外資訊
        cpu_usage = self._extract_cpu_usage(content)
        memory_info = self._extract_memory_info(content)
        
        return ANRInfo(
            anr_type=anr_type,
            process_name=process_info.get('process_name', 'Unknown'),
            pid=process_info.get('pid', 'Unknown'),
            timestamp=process_info.get('timestamp'),
            reason=process_info.get('reason'),
            main_thread=main_thread,
            all_threads=all_threads,
            cpu_usage=cpu_usage,
            memory_info=memory_info
        )
    
    def _identify_anr_type(self, content: str) -> ANRType:
        """識別 ANR 類型"""
        type_mappings = {
            "Input dispatching timed out": ANRType.INPUT_DISPATCHING,
            "Input event dispatching timed out": ANRType.INPUT_DISPATCHING,
            "executing service": ANRType.SERVICE,
            "Broadcast of Intent": ANRType.BROADCAST,
            "BroadcastReceiver": ANRType.BROADCAST,
            "ContentProvider": ANRType.CONTENT_PROVIDER,
            "Activity": ANRType.ACTIVITY,
            "Foreground service": ANRType.FOREGROUND_SERVICE,
        }
        
        for pattern, anr_type in type_mappings.items():
            if pattern in content:
                return anr_type
        
        return ANRType.UNKNOWN
    
    def _extract_process_info(self, content: str) -> Dict:
        """提取進程資訊"""
        info = {}
        
        # 嘗試多種模式提取進程名稱和 PID
        for pattern in self.patterns['anr_trigger_patterns']:
            match = re.search(pattern, content)
            if match:
                groups = match.groups()
                if len(groups) >= 1:
                    if 'Cmd line' in pattern:
                        info['process_name'] = groups[0]
                    elif 'ANR in' in pattern and len(groups) >= 2:
                        info['process_name'] = groups[0]
                        info['pid'] = groups[1]
                    elif len(groups) >= 2 and groups[0].isdigit():
                        info['timeout'] = groups[0]
                        info['reason'] = groups[1]
                    else:
                        info['process_name'] = groups[0]
                break
        
        # 提取時間戳
        timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)', content)
        if timestamp_match:
            info['timestamp'] = timestamp_match.group(1)
        
        return info
    
    def _extract_all_threads(self, lines: List[str], content: str) -> List[ThreadInfo]:
        """提取所有線程資訊"""
        threads = []
        
        for idx, line in enumerate(lines):
            thread_info = self._try_parse_thread(line, idx, lines)
            if thread_info:
                # 提取堆疊資訊
                thread_info.backtrace = self._extract_backtrace(lines, idx)
                
                # 提取鎖資訊
                self._extract_lock_info(thread_info, lines, idx)
                
                threads.append(thread_info)
        
        return threads
    
    def _try_parse_thread(self, line: str, idx: int, lines: List[str]) -> Optional[ThreadInfo]:
        """嘗試解析線程資訊"""
        for pattern in self.patterns['thread_patterns']:
            match = re.search(pattern, line)
            if match:
                groups = match.groups()
                
                # 根據不同模式解析
                if len(groups) == 4 and 'daemon' not in pattern:
                    name, prio, tid, state = groups
                    return ThreadInfo(
                        name=name,
                        tid=tid,
                        prio=prio,
                        state=self._parse_thread_state(state)
                    )
                elif len(groups) == 3:
                    name, tid, state = groups
                    return ThreadInfo(
                        name=name,
                        tid=tid,
                        state=self._parse_thread_state(state)
                    )
                
        return None
    
    def _parse_thread_state(self, state_str: str) -> ThreadState:
        """解析線程狀態"""
        state_mappings = {
            'R': ThreadState.RUNNABLE,
            'S': ThreadState.SLEEPING,
            'D': ThreadState.WAIT,
            'T': ThreadState.SUSPENDED,
            'Z': ThreadState.ZOMBIE,
            'RUNNABLE': ThreadState.RUNNABLE,
            'TIMED_WAIT': ThreadState.TIMED_WAIT,
            'TIMED_WAITING': ThreadState.TIMED_WAIT,
            'WAIT': ThreadState.WAIT,
            'WAITING': ThreadState.WAIT,
            'BLOCKED': ThreadState.BLOCKED,
            'SUSPENDED': ThreadState.SUSPENDED,
            'NATIVE': ThreadState.NATIVE,
            'MONITOR': ThreadState.MONITOR,
            'SLEEPING': ThreadState.SLEEPING,
            'ZOMBIE': ThreadState.ZOMBIE,
        }
        
        return state_mappings.get(state_str.upper(), ThreadState.UNKNOWN)
    
    def _extract_backtrace(self, lines: List[str], start_idx: int) -> List[str]:
        """提取堆疊追蹤"""
        backtrace = []
        
        for i in range(start_idx + 1, len(lines)):
            line = lines[i]
            
            # 檢測下一個線程或結束
            if self._is_thread_start(line):
                break
            
            # 提取堆疊行
            if self._is_stack_frame(line):
                frame = self._clean_stack_frame(line)
                if frame:
                    backtrace.append(frame)
        
        return backtrace
    
    def _is_thread_start(self, line: str) -> bool:
        """檢查是否為線程開始"""
        return any(re.search(pattern, line) for pattern in self.patterns['thread_patterns'][:3])
    
    def _is_stack_frame(self, line: str) -> bool:
        """檢查是否為堆疊框架"""
        patterns = [
            r'^\s*at\s+',
            r'^\s*#\d+\s+',
            r'\([^)]+\.java:\d+\)',
            r'\([^)]+\.kt:\d+\)',
            r'^\s*-\s+(locked|waiting)',
        ]
        return any(re.search(pattern, line) for pattern in patterns)
    
    def _clean_stack_frame(self, line: str) -> str:
        """清理堆疊框架"""
        # 移除前綴
        line = re.sub(r'^\s*at\s+', '', line)
        line = re.sub(r'^\s*#\d+\s+', '', line)
        return line.strip()
    
    def _extract_lock_info(self, thread: ThreadInfo, lines: List[str], start_idx: int) -> None:
        """提取鎖資訊"""
        for i in range(start_idx + 1, min(start_idx + 20, len(lines))):
            line = lines[i]
            
            # 檢查持有的鎖
            locked_match = re.search(r'- locked\s+<([^>]+)>', line)
            if locked_match:
                thread.held_locks.append(locked_match.group(1))
            
            # 檢查等待的鎖
            waiting_match = re.search(r'- waiting (?:on|to lock)\s+<([^>]+)>', line)
            if waiting_match:
                thread.waiting_locks.append(waiting_match.group(1))
                
                # 提取等待資訊
                held_by_match = re.search(r'held by (?:thread\s+)?(\d+)', line)
                if held_by_match:
                    thread.waiting_info = f"等待鎖 {waiting_match.group(1)}，被線程 {held_by_match.group(1)} 持有"
    
    def _find_main_thread(self, threads: List[ThreadInfo]) -> Optional[ThreadInfo]:
        """找出主線程"""
        # 優先查找名為 "main" 的線程
        for thread in threads:
            if thread.name.lower() == "main":
                return thread
        
        # 查找 tid=1 的線程
        for thread in threads:
            if thread.tid == "1":
                return thread
        
        return None
    
    def _extract_cpu_usage(self, content: str) -> Optional[Dict]:
        """提取 CPU 使用率資訊"""
        cpu_info = {}
        
        # 查找 CPU 使用率模式
        cpu_pattern = r'CPU:\s*([\d.]+)%\s*usr\s*\+\s*([\d.]+)%\s*sys'
        match = re.search(cpu_pattern, content)
        if match:
            cpu_info['user'] = float(match.group(1))
            cpu_info['system'] = float(match.group(2))
            cpu_info['total'] = cpu_info['user'] + cpu_info['system']
        
        return cpu_info if cpu_info else None
    
    def _extract_memory_info(self, content: str) -> Optional[Dict]:
        """提取記憶體資訊"""
        memory_info = {}
        
        # 查找記憶體資訊模式
        patterns = {
            'total': r'MemTotal:\s*(\d+)\s*kB',
            'free': r'MemFree:\s*(\d+)\s*kB',
            'available': r'MemAvailable:\s*(\d+)\s*kB',
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                memory_info[key] = int(match.group(1))
        
        return memory_info if memory_info else None
    
    def _generate_report(self, anr_info: ANRInfo, content: str) -> str:
        """生成分析報告"""
        analyzer = ANRReportGenerator(anr_info, content)
        return analyzer.generate()


class ANRReportGenerator:
    """ANR 報告生成器"""
    
    def __init__(self, anr_info: ANRInfo, content: str):
        self.anr_info = anr_info
        self.content = content
        self.report_lines = []
    
    def generate(self) -> str:
        """生成報告"""
        self._add_summary()
        self._add_basic_info()
        self._add_main_thread_analysis()
        self._add_root_cause_analysis()
        self._add_thread_analysis()
        self._add_deadlock_detection()
        self._add_performance_analysis()
        self._add_suggestions()
        
        return "\n".join(self.report_lines)
    
    def _add_summary(self):
        """添加摘要"""
        self.report_lines.extend([
            "🎯 ANR 分析報告",
            "=" * 60,
            f"📊 ANR 類型: {self.anr_info.anr_type.value}",
            f"📱 進程名稱: {self.anr_info.process_name}",
            f"🆔 進程 ID: {self.anr_info.pid}",
        ])
        
        if self.anr_info.timestamp:
            self.report_lines.append(f"🕐 發生時間: {self.anr_info.timestamp}")
        
        # 快速判斷嚴重程度
        severity = self._assess_severity()
        self.report_lines.append(f"🚨 嚴重程度: {severity}")
        
        # 根本原因快速定位
        root_cause = self._quick_root_cause()
        self.report_lines.append(f"🎯 可能原因: {root_cause}")
        
        self.report_lines.extend(["", "=" * 60, ""])
    
    def _assess_severity(self) -> str:
        """評估嚴重程度"""
        score = 0
        
        # 檢查死鎖
        if self._has_deadlock():
            score += 5
        
        # 檢查系統服務
        if "system_server" in self.anr_info.process_name:
            score += 3
        
        # 檢查阻塞線程數量
        blocked_count = sum(1 for t in self.anr_info.all_threads if t.state == ThreadState.BLOCKED)
        score += min(blocked_count // 3, 3)
        
        # 檢查 CPU 使用率
        if self.anr_info.cpu_usage and self.anr_info.cpu_usage.get('total', 0) > 90:
            score += 2
        
        # 返回評級
        if score >= 8:
            return "🔴 極其嚴重 (系統級問題/死鎖)"
        elif score >= 5:
            return "🟠 嚴重 (多線程阻塞/系統服務問題)"
        elif score >= 3:
            return "🟡 中等 (需要立即處理)"
        else:
            return "🟢 輕微 (應用層問題)"
    
    def _quick_root_cause(self) -> str:
        """快速定位根本原因"""
        causes = []
        
        if self.anr_info.main_thread:
            # 檢查主線程堆疊
            for frame in self.anr_info.main_thread.backtrace[:5]:
                if any(keyword in frame for keyword in ['BinderProxy', 'Binder.transact']):
                    causes.append("Binder IPC 阻塞")
                    break
                elif any(keyword in frame for keyword in ['synchronized', 'lock']):
                    causes.append("同步鎖等待")
                    break
                elif any(keyword in frame for keyword in ['Socket', 'Http', 'Network']):
                    causes.append("網路操作阻塞")
                    break
                elif any(keyword in frame for keyword in ['File', 'read', 'write', 'SQLite']):
                    causes.append("I/O 操作阻塞")
                    break
                elif 'sleep' in frame.lower():
                    causes.append("主線程休眠")
                    break
        
        # 檢查死鎖
        if self._has_deadlock():
            causes.append("可能存在死鎖")
        
        # 檢查 CPU
        if self.anr_info.cpu_usage and self.anr_info.cpu_usage.get('total', 0) > 90:
            causes.append("CPU 使用率過高")
        
        return " / ".join(causes) if causes else "需進一步分析"
    
    def _has_deadlock(self) -> bool:
        """檢查是否有死鎖"""
        # 簡單的死鎖檢測：檢查循環等待
        waiting_graph = {}
        
        for thread in self.anr_info.all_threads:
            if thread.waiting_info and 'held by' in thread.waiting_info:
                match = re.search(r'held by (?:thread\s+)?(\d+)', thread.waiting_info)
                if match:
                    waiting_graph[thread.tid] = match.group(1)
        
        # 檢查循環
        visited = set()
        for start_tid in waiting_graph:
            if start_tid in visited:
                continue
            
            current = start_tid
            path = [current]
            
            while current in waiting_graph:
                current = waiting_graph[current]
                if current in path:
                    return True  # 發現循環
                if current in visited:
                    break
                path.append(current)
            
            visited.update(path)
        
        return False
    
    def _add_basic_info(self):
        """添加基本資訊"""
        self.report_lines.append("📋 詳細分析")
        
        if self.anr_info.reason:
            self.report_lines.append(f"\n⚡ 觸發原因: {self.anr_info.reason}")
    
    def _add_main_thread_analysis(self):
        """添加主線程分析"""
        self.report_lines.append("\n🔍 主線程分析")
        
        if not self.anr_info.main_thread:
            self.report_lines.append("❌ 未找到主線程資訊")
            return
        
        main = self.anr_info.main_thread
        self.report_lines.extend([
            f"🧵 線程名稱: {main.name}",
            f"🔢 線程 ID: {main.tid}",
            f"📊 線程狀態: {main.state.value}",
            f"🎯 優先級: {main.prio}",
        ])
        
        # 分析線程狀態
        state_analysis = self._analyze_thread_state(main.state)
        self.report_lines.append(f"💡 狀態分析: {state_analysis}")
        
        # 分析堆疊
        if main.backtrace:
            # 深度分析堆疊
            stack_analysis = self._deep_analyze_stack(main.backtrace)
            
            self.report_lines.append(f"\n📚 堆疊分析 (共 {len(main.backtrace)} 層):")
            
            # 顯示分析結果
            if stack_analysis['root_cause']:
                self.report_lines.append(f"  🎯 根本原因: {stack_analysis['root_cause']}")
            
            if stack_analysis['blocking_operation']:
                self.report_lines.append(f"  ⏰ 阻塞操作: {stack_analysis['blocking_operation']}")
            
            if stack_analysis['target_service']:
                self.report_lines.append(f"  🔗 目標服務: {stack_analysis['target_service']}")
            
            if stack_analysis['key_findings']:
                for finding in stack_analysis['key_findings']:
                    self.report_lines.append(f"  • {finding}")
            
            # 顯示帶優先級標記的堆疊
            self.report_lines.append("\n🔍 關鍵堆疊 (標記重要幀):")
            
            # 分析每一幀的重要性
            frame_importances = self._analyze_frame_importance(main.backtrace)
            
            for i, (frame, importance) in enumerate(zip(main.backtrace[:20], frame_importances[:20])):
                priority_marker = importance['marker']
                explanation = importance['explanation']
                
                # 根據重要性顯示不同顏色的標記
                if importance['level'] == 'critical':
                    self.report_lines.append(f"  {priority_marker} #{i:02d} {frame}")
                    if explanation:
                        self.report_lines.append(f"        └─ {explanation}")
                elif importance['level'] == 'important':
                    self.report_lines.append(f"  {priority_marker} #{i:02d} {frame}")
                    if explanation:
                        self.report_lines.append(f"        └─ {explanation}")
                elif importance['level'] == 'normal' and i < 10:  # 只顯示前10個普通幀
                    self.report_lines.append(f"  {priority_marker} #{i:02d} {frame}")
        
        # 顯示鎖資訊
        if main.held_locks:
            self.report_lines.append(f"\n🔒 持有的鎖: {', '.join(main.held_locks)}")
        
        if main.waiting_locks:
            self.report_lines.append(f"⏰ 等待的鎖: {', '.join(main.waiting_locks)}")
        
        if main.waiting_info:
            self.report_lines.append(f"⏳ 等待資訊: {main.waiting_info}")
    
    def _analyze_thread_state(self, state: ThreadState) -> str:
        """分析線程狀態"""
        analyses = {
            ThreadState.BLOCKED: "線程被同步鎖阻塞 ⚠️ [可能是 ANR 主因]",
            ThreadState.WAIT: "線程在等待條件 ⏰ [需檢查等待原因]",
            ThreadState.TIMED_WAIT: "線程在定時等待 ⏰ [檢查等待時長]",
            ThreadState.SUSPENDED: "線程被暫停 ⚠️ [異常狀態]",
            ThreadState.RUNNABLE: "線程可運行 ✅ [正常狀態，但可能在執行耗時操作]",
            ThreadState.NATIVE: "執行原生代碼 📱 [檢查 JNI 調用]",
            ThreadState.SLEEPING: "線程休眠 😴 [不應在主線程]",
        }
        
        return analyses.get(state, "未知狀態")
    
    def _deep_analyze_stack(self, backtrace: List[str]) -> Dict:
        """深度分析堆疊"""
        analysis = {
            'root_cause': None,
            'blocking_operation': None,
            'target_service': None,
            'key_findings': []
        }
        
        if not backtrace:
            return analysis
        
        # 分析前10幀找出關鍵問題
        for i, frame in enumerate(backtrace[:10]):
            frame_lower = frame.lower()
            
            # Binder IPC 分析
            if any(keyword in frame for keyword in ['BinderProxy.transact', 'Binder.transact', 'IPCThreadState::transact']):
                if not analysis['root_cause']:
                    analysis['root_cause'] = "Binder IPC 調用阻塞"
                
                # 嘗試識別目標服務
                service = self._identify_binder_service(backtrace[i:i+5])
                if service:
                    analysis['target_service'] = service
                    
                # 識別具體的 Binder 方法
                method = self._identify_binder_method(backtrace[i:i+5])
                if method:
                    analysis['blocking_operation'] = f"Binder 方法: {method}"
                else:
                    analysis['blocking_operation'] = "Binder IPC 調用"
                    
                analysis['key_findings'].append(f"在第 {i} 層檢測到 Binder IPC 調用")
            
            # 同步鎖分析
            elif 'synchronized' in frame_lower or any(lock in frame_lower for lock in ['lock', 'monitor', 'mutex']):
                if not analysis['root_cause']:
                    analysis['root_cause'] = "同步鎖等待"
                
                lock_type = self._identify_lock_type([frame])
                if lock_type:
                    analysis['blocking_operation'] = lock_type
                    
                analysis['key_findings'].append(f"在第 {i} 層檢測到鎖操作")
            
            # I/O 操作分析
            elif any(io_op in frame for io_op in ['FileInputStream', 'FileOutputStream', 'RandomAccessFile', 'read', 'write']):
                if not analysis['root_cause']:
                    analysis['root_cause'] = "I/O 操作阻塞"
                    
                io_type = self._identify_io_type([frame])
                if io_type:
                    analysis['blocking_operation'] = io_type
                    
                analysis['key_findings'].append(f"在第 {i} 層檢測到 I/O 操作")
            
            # 資料庫操作
            elif any(db in frame for db in ['SQLite', 'database', 'Cursor', 'ContentProvider']):
                if not analysis['root_cause']:
                    analysis['root_cause'] = "資料庫操作阻塞"
                    
                analysis['blocking_operation'] = "資料庫操作"
                analysis['key_findings'].append(f"在第 {i} 層檢測到資料庫操作")
            
            # 網路操作
            elif any(net in frame for net in ['Socket', 'HttpURLConnection', 'URLConnection', 'OkHttp']):
                if not analysis['root_cause']:
                    analysis['root_cause'] = "網路請求阻塞"
                    
                network_type = self._identify_network_type([frame])
                if network_type:
                    analysis['blocking_operation'] = network_type
                    
                analysis['key_findings'].append(f"在第 {i} 層檢測到網路操作")
            
            # UI 渲染
            elif any(ui in frame for ui in ['onDraw', 'onMeasure', 'onLayout', 'inflate', 'measure']):
                if not analysis['root_cause']:
                    analysis['root_cause'] = "UI 渲染阻塞"
                    
                ui_operation = self._identify_ui_operation([frame])
                if ui_operation:
                    analysis['blocking_operation'] = ui_operation
                    
                analysis['key_findings'].append(f"在第 {i} 層檢測到 UI 操作")
            
            # 休眠操作
            elif 'sleep' in frame_lower:
                analysis['root_cause'] = "主線程休眠 (嚴重問題)"
                analysis['blocking_operation'] = "Thread.sleep()"
                analysis['key_findings'].append(f"⚠️ 在第 {i} 層檢測到 sleep 操作")
            
            # Native 方法
            elif 'native' in frame_lower or 'Native Method' in frame:
                if i < 3:  # 只有在頂層幾幀才認為是 Native 阻塞
                    if not analysis['root_cause']:
                        analysis['root_cause'] = "Native 方法阻塞"
                    analysis['key_findings'].append(f"在第 {i} 層進入 Native 方法")
        
        # 檢查特殊模式
        if len(backtrace) > 50:
            analysis['key_findings'].append(f"調用鏈過深 ({len(backtrace)} 層)，可能有遞迴")
        
        # 檢查是否有 Handler/Looper 模式
        if any('Handler' in frame or 'Looper' in frame for frame in backtrace[:5]):
            analysis['key_findings'].append("涉及 Handler/Looper 消息處理")
        
        # 如果沒有找到明確原因，進行更深入分析
        if not analysis['root_cause']:
            if any('wait' in frame.lower() or 'park' in frame.lower() for frame in backtrace[:5]):
                analysis['root_cause'] = "線程等待"
                analysis['blocking_operation'] = "等待條件或事件"
            else:
                analysis['root_cause'] = "未知阻塞原因"
        
        return analysis
    
    def _analyze_frame_importance(self, backtrace: List[str]) -> List[Dict]:
        """分析每一幀的重要性"""
        importances = []
        
        for i, frame in enumerate(backtrace):
            importance = {
                'level': 'normal',
                'marker': '⚪',
                'explanation': None
            }
            
            frame_lower = frame.lower()
            
            # 最高優先級 - 紅色標記
            if any(critical in frame for critical in [
                'BinderProxy.transact', 'Binder.transact', 'IPCThreadState::transact'
            ]):
                importance['level'] = 'critical'
                importance['marker'] = '🔴'
                importance['explanation'] = 'Binder IPC 調用阻塞'
            
            elif 'sleep' in frame_lower:
                importance['level'] = 'critical'
                importance['marker'] = '🔴'
                importance['explanation'] = '主線程休眠 - 嚴重問題！'
            
            elif 'synchronized' in frame_lower or 'lock' in frame_lower:
                importance['level'] = 'critical'
                importance['marker'] = '🔴'
                importance['explanation'] = '同步鎖等待'
            
            elif any(io in frame for io in ['Socket', 'Http', 'URLConnection']):
                importance['level'] = 'critical'
                importance['marker'] = '🔴'
                importance['explanation'] = '網路操作在主線程'
            
            # 中等優先級 - 黃色標記
            elif any(io in frame for io in ['FileInputStream', 'FileOutputStream', 'read', 'write']):
                importance['level'] = 'important'
                importance['marker'] = '🟡'
                importance['explanation'] = 'I/O 操作'
            
            elif any(db in frame for db in ['SQLite', 'database', 'Cursor']):
                importance['level'] = 'important'
                importance['marker'] = '🟡'
                importance['explanation'] = '資料庫操作'
            
            elif any(ui in frame for ui in ['onDraw', 'onMeasure', 'onLayout']):
                importance['level'] = 'important'
                importance['marker'] = '🟡'
                importance['explanation'] = 'UI 渲染操作'
            
            elif 'wait' in frame_lower or 'park' in frame_lower:
                importance['level'] = 'important'
                importance['marker'] = '🟡'
                importance['explanation'] = '等待操作'
            
            elif i == 0:  # 第一幀總是重要的
                importance['level'] = 'important'
                importance['marker'] = '🟡'
                importance['explanation'] = '頂層調用'
            
            # Native 方法
            elif 'native' in frame_lower or 'Native Method' in frame:
                if i < 3:
                    importance['level'] = 'important'
                    importance['marker'] = '🟡'
                    importance['explanation'] = 'Native 方法'
                else:
                    importance['marker'] = '⚪'
            
            importances.append(importance)
        
        return importances
    
    def _identify_binder_service(self, frames: List[str]) -> Optional[str]:
        """識別 Binder 目標服務"""
        # 擴展服務識別規則
        service_patterns = {
            'WindowManager': [
                'getWindowInsets', 'addWindow', 'removeWindow', 'updateViewLayout',
                'WindowManagerService', 'WindowManager$', 'IWindowManager'
            ],
            'ActivityManager': [
                'startActivity', 'bindService', 'getRunningTasks', 'getServices',
                'ActivityManagerService', 'ActivityManager$', 'IActivityManager'
            ],
            'PackageManager': [
                'getPackageInfo', 'queryIntentActivities', 'getApplicationInfo',
                'PackageManagerService', 'PackageManager$', 'IPackageManager'
            ],
            'PowerManager': [
                'isScreenOn', 'goToSleep', 'wakeUp', 'PowerManagerService',
                'PowerManager$', 'IPowerManager'
            ],
            'InputManager': [
                'injectInputEvent', 'getInputDevice', 'InputManagerService',
                'InputManager$', 'IInputManager'
            ],
            'NotificationManager': [
                'notify', 'cancel', 'NotificationManagerService',
                'NotificationManager$', 'INotificationManager'
            ],
            'AudioManager': [
                'setStreamVolume', 'AudioService', 'AudioManager$', 'IAudioService'
            ],
            'TelephonyManager': [
                'getDeviceId', 'getNetworkType', 'TelephonyRegistry',
                'TelephonyManager$', 'ITelephony'
            ],
            'LocationManager': [
                'getLastKnownLocation', 'requestLocationUpdates',
                'LocationManagerService', 'ILocationManager'
            ],
            'SensorManager': [
                'registerListener', 'SensorService', 'ISensorService'
            ],
        }
        
        for service, patterns in service_patterns.items():
            for frame in frames:
                if any(pattern in frame for pattern in patterns):
                    return service
        
        # 如果沒有找到具體服務，嘗試從 frame 中提取
        for frame in frames:
            if 'Service' in frame:
                match = re.search(r'(\w+Service)', frame)
                if match:
                    return match.group(1)
            elif 'Manager' in frame and 'Proxy' in frame:
                match = re.search(r'(\w+Manager)', frame)
                if match:
                    return match.group(1)
        
        return None
    
    def _identify_binder_method(self, frames: List[str]) -> Optional[str]:
        """識別 Binder 方法"""
        # 查找具體的方法調用
        for frame in frames:
            # 匹配標準 Java 方法格式
            match = re.search(r'\.(\w+)\([^)]*\)', frame)
            if match:
                method = match.group(1)
                # 過濾掉一些通用方法
                if method not in ['transact', 'onTransact', 'execTransact', 'invoke']:
                    return method
        
        return None
    
    def _identify_lock_type(self, frames: List[str]) -> Optional[str]:
        """識別鎖類型"""
        for frame in frames:
            if 'synchronized' in frame:
                # 嘗試提取同步的對象
                match = re.search(r'synchronized\s*\(([^)]+)\)', frame)
                if match:
                    return f"synchronized ({match.group(1)})"
                return "synchronized 同步鎖"
            elif 'ReentrantLock' in frame:
                return "ReentrantLock 可重入鎖"
            elif 'ReadWriteLock' in frame:
                return "ReadWriteLock 讀寫鎖"
            elif 'Semaphore' in frame:
                return "Semaphore 信號量"
            elif 'CountDownLatch' in frame:
                return "CountDownLatch 倒計時鎖"
            elif 'CyclicBarrier' in frame:
                return "CyclicBarrier 循環屏障"
            elif 'monitor' in frame.lower():
                return "Monitor 監視器鎖"
        
        return "未知類型的鎖"
    
    def _identify_io_type(self, frames: List[str]) -> Optional[str]:
        """識別 I/O 類型"""
        for frame in frames:
            if 'FileInputStream' in frame or 'FileReader' in frame:
                return "文件讀取"
            elif 'FileOutputStream' in frame or 'FileWriter' in frame:
                return "文件寫入"
            elif 'RandomAccessFile' in frame:
                return "隨機文件訪問"
            elif 'BufferedReader' in frame or 'BufferedWriter' in frame:
                return "緩衝 I/O"
            elif 'SharedPreferences' in frame:
                return "SharedPreferences 讀寫"
            elif 'SQLite' in frame or 'database' in frame:
                return "資料庫 I/O"
            elif 'ContentResolver' in frame:
                return "ContentProvider 訪問"
            elif 'AssetManager' in frame:
                return "Asset 資源讀取"
        
        return "文件 I/O"
    
    def _identify_network_type(self, frames: List[str]) -> Optional[str]:
        """識別網路類型"""
        for frame in frames:
            if 'HttpURLConnection' in frame:
                return "HttpURLConnection 請求"
            elif 'Socket' in frame:
                return "Socket 連接"
            elif 'OkHttp' in frame:
                return "OkHttp 請求"
            elif 'Volley' in frame:
                return "Volley 網路請求"
            elif 'Retrofit' in frame:
                return "Retrofit API 調用"
            elif 'AsyncHttpClient' in frame:
                return "AsyncHttpClient 請求"
            elif 'HttpClient' in frame:
                return "HttpClient 請求"
        
        return "網路請求"
    
    def _identify_ui_operation(self, frames: List[str]) -> Optional[str]:
        """識別 UI 操作"""
        for frame in frames:
            if 'inflate' in frame:
                return "View 布局填充"
            elif 'onMeasure' in frame:
                return "View 測量"
            elif 'onDraw' in frame:
                return "View 繪製"
            elif 'onLayout' in frame:
                return "View 布局"
            elif 'measure(' in frame:
                return "測量操作"
            elif 'layout(' in frame:
                return "布局操作"
            elif 'draw(' in frame:
                return "繪製操作"
            elif 'RecyclerView' in frame:
                return "RecyclerView 操作"
            elif 'ListView' in frame:
                return "ListView 操作"
            elif 'TextView' in frame and 'setText' in frame:
                return "TextView 更新"
        
        return "UI 操作"
    
    def _add_root_cause_analysis(self):
        """添加根本原因分析"""
        self.report_lines.append("\n🎯 根本原因分析")
        
        # Binder 分析
        binder_issues = self._analyze_binder_issues()
        if binder_issues:
            self.report_lines.append("\n🔗 Binder IPC 問題:")
            self.report_lines.extend(f"  • {issue}" for issue in binder_issues)
        
        # 鎖分析
        lock_issues = self._analyze_lock_issues()
        if lock_issues:
            self.report_lines.append("\n🔒 鎖競爭問題:")
            self.report_lines.extend(f"  • {issue}" for issue in lock_issues)
        
        # I/O 分析
        io_issues = self._analyze_io_issues()
        if io_issues:
            self.report_lines.append("\n💾 I/O 問題:")
            self.report_lines.extend(f"  • {issue}" for issue in io_issues)
        
        # 系統資源分析
        resource_issues = self._analyze_resource_issues()
        if resource_issues:
            self.report_lines.append("\n🖥️ 系統資源問題:")
            self.report_lines.extend(f"  • {issue}" for issue in resource_issues)
    
    def _analyze_binder_issues(self) -> List[str]:
        """分析 Binder 問題"""
        issues = []
        
        if not self.anr_info.main_thread:
            return issues
        
        # 檢查主線程是否在等待 Binder
        for frame in self.anr_info.main_thread.backtrace[:10]:
            if 'BinderProxy' in frame or 'Binder.transact' in frame:
                issues.append("主線程正在等待 Binder IPC 響應")
                
                # 檢查是否有 system_server 問題
                if 'system_server' in self.content:
                    issues.append("檢測到 system_server 相關資訊，可能是系統服務問題")
                
                break
        
        return issues
    
    def _analyze_lock_issues(self) -> List[str]:
        """分析鎖問題"""
        issues = []
        
        # 統計阻塞線程
        blocked_threads = [t for t in self.anr_info.all_threads if t.state == ThreadState.BLOCKED]
        if len(blocked_threads) > 3:
            issues.append(f"發現 {len(blocked_threads)} 個線程處於 BLOCKED 狀態")
            issues.append("可能存在嚴重的鎖競爭")
        
        # 檢查死鎖
        if self._has_deadlock():
            issues.append("⚠️ 檢測到可能的死鎖情況")
            
            # 找出死鎖線程
            deadlock_info = self._find_deadlock_threads()
            if deadlock_info:
                issues.extend(deadlock_info)
        
        return issues
    
    def _find_deadlock_threads(self) -> List[str]:
        """找出死鎖線程"""
        info = []
        
        # 建立等待圖
        waiting_graph = {}
        thread_map = {t.tid: t for t in self.anr_info.all_threads}
        
        for thread in self.anr_info.all_threads:
            if thread.waiting_info and 'held by' in thread.waiting_info:
                match = re.search(r'held by (?:thread\s+)?(\d+)', thread.waiting_info)
                if match:
                    waiting_graph[thread.tid] = match.group(1)
        
        # 找出循環
        for start_tid in waiting_graph:
            current = start_tid
            path = [current]
            
            while current in waiting_graph:
                current = waiting_graph[current]
                if current in path:
                    # 找到循環
                    cycle_start = path.index(current)
                    cycle = path[cycle_start:]
                    
                    cycle_info = []
                    for tid in cycle:
                        if tid in thread_map:
                            thread = thread_map[tid]
                            cycle_info.append(f"{thread.name} (tid={tid})")
                    
                    info.append(f"死鎖循環: {' -> '.join(cycle_info)}")
                    break
                    
                path.append(current)
        
        return info
    
    def _analyze_io_issues(self) -> List[str]:
        """分析 I/O 問題"""
        issues = []
        
        if not self.anr_info.main_thread:
            return issues
        
        io_keywords = ['File', 'read', 'write', 'SQLite', 'database', 'SharedPreferences']
        
        for frame in self.anr_info.main_thread.backtrace[:10]:
            for keyword in io_keywords:
                if keyword in frame:
                    issues.append(f"主線程正在執行 {keyword} 相關的 I/O 操作")
                    issues.append("建議將 I/O 操作移至背景線程")
                    return issues
        
        return issues
    
    def _analyze_resource_issues(self) -> List[str]:
        """分析系統資源問題"""
        issues = []
        
        # CPU 分析
        if self.anr_info.cpu_usage:
            total_cpu = self.anr_info.cpu_usage.get('total', 0)
            if total_cpu > 90:
                issues.append(f"CPU 使用率過高: {total_cpu:.1f}%")
            elif total_cpu > 70:
                issues.append(f"CPU 使用率較高: {total_cpu:.1f}%")
        
        # 記憶體分析
        if self.anr_info.memory_info:
            if 'available' in self.anr_info.memory_info:
                available_mb = self.anr_info.memory_info['available'] / 1024
                if available_mb < 100:
                    issues.append(f"可用記憶體不足: {available_mb:.1f} MB")
        
        # GC 分析
        gc_count = self.content.count('GC')
        if gc_count > 10:
            issues.append(f"頻繁的垃圾回收: {gc_count} 次")
        elif gc_count > 5:
            issues.append(f"垃圾回收較多: {gc_count} 次")
        
        # 檢查 OutOfMemoryError
        if "OutOfMemoryError" in self.content:
            issues.append("檢測到記憶體不足錯誤 (OutOfMemoryError)")
        
        # 檢查系統負載
        if "load average" in self.content:
            load_match = re.search(r'load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', self.content)
            if load_match:
                load1 = float(load_match.group(1))
                if load1 > 4.0:
                    issues.append(f"系統負載過高: {load1}")
        
        return issues
    
    def _add_thread_analysis(self):
        """添加線程分析"""
        if len(self.anr_info.all_threads) == 0:
            return
        
        self.report_lines.append(f"\n🧵 線程分析 (共 {len(self.anr_info.all_threads)} 個)")
        
        # 線程分類統計
        thread_stats = self._get_thread_statistics()
        
        self.report_lines.append("\n📊 線程狀態統計:")
        for state, count in thread_stats.items():
            if count > 0:
                self.report_lines.append(f"  • {state}: {count} 個")
        
        # 顯示重要線程
        important_threads = self._get_important_threads()
        if important_threads:
            self.report_lines.append("\n🔍 重要線程:")
            for thread in important_threads[:10]:
                summary = self._summarize_thread(thread)
                self.report_lines.append(f"  • {summary}")
    
    def _get_thread_statistics(self) -> Dict[str, int]:
        """獲取線程統計"""
        stats = {}
        
        for thread in self.anr_info.all_threads:
            state_name = thread.state.value
            stats[state_name] = stats.get(state_name, 0) + 1
        
        return stats
    
    def _get_important_threads(self) -> List[ThreadInfo]:
        """獲取重要線程"""
        important = []
        
        for thread in self.anr_info.all_threads:
            # 阻塞的線程
            if thread.state == ThreadState.BLOCKED:
                important.append(thread)
            # 等待鎖的線程
            elif thread.waiting_locks:
                important.append(thread)
            # 系統關鍵線程
            elif any(keyword in thread.name for keyword in ['Binder', 'main', 'UI', 'RenderThread']):
                important.append(thread)
        
        return important[:15]
    
    def _summarize_thread(self, thread: ThreadInfo) -> str:
        """總結線程資訊"""
        summary = f"{thread.name} (tid={thread.tid}, {thread.state.value})"
        
        if thread.waiting_info:
            summary += f" - {thread.waiting_info}"
        elif thread.waiting_locks:
            summary += f" - 等待鎖: {thread.waiting_locks[0]}"
        elif thread.held_locks:
            summary += f" - 持有鎖: {thread.held_locks[0]}"
        
        return summary
    
    def _add_deadlock_detection(self):
        """添加死鎖檢測"""
        if not self._has_deadlock():
            return
        
        self.report_lines.append("\n💀 死鎖檢測")
        
        deadlock_info = self._find_deadlock_threads()
        for info in deadlock_info:
            self.report_lines.append(f"  ⚠️ {info}")
    
    def _add_performance_analysis(self):
        """添加性能分析"""
        self.report_lines.append("\n⚡ 性能分析")
        
        perf_issues = []
        
        # 線程數量
        thread_count = len(self.anr_info.all_threads)
        if thread_count > 100:
            perf_issues.append(f"線程數量過多: {thread_count} 個")
        elif thread_count > 50:
            perf_issues.append(f"線程數量較多: {thread_count} 個")
        
        # 調用深度
        if self.anr_info.main_thread and len(self.anr_info.main_thread.backtrace) > 50:
            perf_issues.append(f"主線程調用鏈過深: {len(self.anr_info.main_thread.backtrace)} 層")
        
        if perf_issues:
            self.report_lines.extend(f"  • {issue}" for issue in perf_issues)
        else:
            self.report_lines.append("  ✅ 未發現明顯性能問題")
    
    def _add_suggestions(self):
        """添加解決建議"""
        self.report_lines.append("\n💡 解決建議")
        
        suggestions = self._generate_suggestions()
        
        # 立即行動項
        if suggestions['immediate']:
            self.report_lines.append("\n🚨 立即行動:")
            for i, suggestion in enumerate(suggestions['immediate'], 1):
                self.report_lines.append(f"  {i}. {suggestion}")
        
        # 優化建議
        if suggestions['optimization']:
            self.report_lines.append("\n🔧 優化建議:")
            for i, suggestion in enumerate(suggestions['optimization'], 1):
                self.report_lines.append(f"  {i}. {suggestion}")
        
        # 調查方向
        if suggestions['investigation']:
            self.report_lines.append("\n🔍 調查方向:")
            for i, suggestion in enumerate(suggestions['investigation'], 1):
                self.report_lines.append(f"  {i}. {suggestion}")
    
    def _generate_suggestions(self) -> Dict[str, List[str]]:
        """生成建議"""
        suggestions = {
            'immediate': [],
            'optimization': [],
            'investigation': []
        }
        
        # 基於主線程狀態
        if self.anr_info.main_thread:
            # 檢查堆疊
            for frame in self.anr_info.main_thread.backtrace[:5]:
                if 'sleep' in frame.lower():
                    suggestions['immediate'].append("立即移除主線程中的 sleep 操作")
                elif any(keyword in frame for keyword in ['File', 'SQLite', 'SharedPreferences']):
                    suggestions['immediate'].append("將 I/O 操作移至背景線程 (使用 AsyncTask/協程)")
                elif any(keyword in frame for keyword in ['Http', 'Socket', 'URL']):
                    suggestions['immediate'].append("將網路請求移至背景線程")
                elif 'synchronized' in frame:
                    suggestions['optimization'].append("檢查同步鎖的使用，考慮使用無鎖數據結構")
        
        # 基於 ANR 類型
        if self.anr_info.anr_type == ANRType.INPUT_DISPATCHING:
            suggestions['immediate'].append("檢查 UI 線程是否有耗時操作")
            suggestions['optimization'].append("使用 Systrace 分析 UI 性能")
        elif self.anr_info.anr_type == ANRType.SERVICE:
            suggestions['immediate'].append("Service 的 onStartCommand 應快速返回")
            suggestions['optimization'].append("考慮使用 IntentService 或 JobIntentService")
        elif self.anr_info.anr_type == ANRType.BROADCAST:
            suggestions['immediate'].append("BroadcastReceiver 的 onReceive 應在 10 秒內完成")
            suggestions['optimization'].append("使用 goAsync() 處理耗時操作")
        
        # 基於問題類型
        if self._has_deadlock():
            suggestions['immediate'].append("重新設計鎖的獲取順序，避免循環等待")
            suggestions['investigation'].append("使用 Android Studio 的 Thread Dump 分析工具")
        
        if any('Binder' in frame for frame in (self.anr_info.main_thread.backtrace[:5] if self.anr_info.main_thread else [])):
            suggestions['investigation'].append("檢查 system_server 的健康狀態")
            suggestions['investigation'].append("分析 /proc/binder 資訊")
            suggestions['optimization'].append("考慮使用異步 Binder 調用")
        
        # 通用建議
        suggestions['investigation'].extend([
            "收集更多 ANR traces 確認問題重現性",
            "使用 Profiler 分析 CPU 和記憶體使用",
            "檢查相關時間段的 logcat",
        ])
        
        suggestions['optimization'].extend([
            "啟用 StrictMode 檢測主線程違規",
            "使用 WorkManager 處理背景任務",
            "實施適當的線程池管理",
        ])
        
        return suggestions


# ============= Tombstone 分析器 =============

class TombstoneAnalyzer(BaseAnalyzer):
    """Tombstone 分析器"""
    
    def _init_patterns(self) -> Dict:
        """初始化 Tombstone 分析模式"""
        return {
            'signal_patterns': [
                r'signal\s+(\d+)\s+\((\w+)\)',
                r'si_signo=(\d+).*?si_code=(\d+)',
                r'Fatal signal\s+(\d+)\s+\((\w+)\)',
            ],
            'process_patterns': [
                r'pid:\s*(\d+),\s*tid:\s*(\d+),\s*name:\s*([^\s]+)',
                r'pid\s+(\d+)\s+tid\s+(\d+)\s+name\s+([^\s]+)',
                r'Process:\s*([^,\s]+).*?PID:\s*(\d+)',
            ],
            'abort_patterns': [
                r'Abort message:\s*["\'](.+?)["\']',
                r'Abort message:\s*(.+?)(?:\n|$)',
                r'abort_message:\s*"(.+?)"',
            ],
            'backtrace_patterns': [
                r'#(\d+)\s+pc\s+([0-9a-fA-F]+)\s+([^\s]+)(?:\s+\((.+?)\))?',
                r'#(\d+)\s+([0-9a-fA-F]+)\s+([^\s]+)(?:\s+\((.+?)\))?',
                r'backtrace:\s*#(\d+)\s+pc\s+([0-9a-fA-F]+)',
            ],
            'memory_patterns': [
                r'([0-9a-f]+)-([0-9a-f]+)\s+([rwxps-]+)\s+([0-9a-f]+)\s+([0-9a-f:]+)\s+(\d+)\s+(.*)',
            ],
        }
    
    @time_tracker("解析 Tombstone 檔案")
    def analyze(self, file_path: str) -> str:
        """分析 Tombstone 檔案"""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            # 解析 Tombstone 資訊
            tombstone_info = self._parse_tombstone_info(content)
            
            # 生成分析報告
            report = self._generate_report(tombstone_info, content)
            
            return report
            
        except Exception as e:
            return f"❌ 分析 Tombstone 檔案時發生錯誤: {str(e)}\n{traceback.format_exc()}"
    
    def _parse_tombstone_info(self, content: str) -> TombstoneInfo:
        """解析 Tombstone 資訊"""
        lines = content.splitlines()
        
        # 解析基本資訊
        signal_info = self._extract_signal_info(content)
        process_info = self._extract_process_info(content)
        abort_message = self._extract_abort_message(content)
        
        # 解析崩潰堆疊
        crash_backtrace = self._extract_backtrace(content)
        
        # 解析記憶體映射
        memory_map = self._extract_memory_map(content)
        
        # 解析打開的檔案
        open_files = self._extract_open_files(content)
        
        # 解析寄存器
        registers = self._extract_registers(content)
        
        # 解析所有線程
        all_threads = self._extract_all_threads_tombstone(lines, content)
        
        return TombstoneInfo(
            signal=signal_info.get('signal', CrashSignal.UNKNOWN),
            signal_code=signal_info.get('code', 'Unknown'),
            fault_addr=signal_info.get('fault_addr', 'Unknown'),
            process_name=process_info.get('process_name', 'Unknown'),
            pid=process_info.get('pid', 'Unknown'),
            tid=process_info.get('tid', 'Unknown'),
            thread_name=process_info.get('thread_name', 'Unknown'),
            abort_message=abort_message,
            crash_backtrace=crash_backtrace,
            all_threads=all_threads,
            memory_map=memory_map,
            open_files=open_files,
            registers=registers
        )
    
    def _extract_signal_info(self, content: str) -> Dict:
        """提取信號資訊"""
        info = {}
        
        # 提取信號
        for pattern in self.patterns['signal_patterns']:
            match = re.search(pattern, content)
            if match:
                signal_num = int(match.group(1))
                signal_name = match.group(2) if len(match.groups()) >= 2 else None
                
                # 匹配信號枚舉
                for signal in CrashSignal:
                    if signal.value[0] == signal_num:
                        info['signal'] = signal
                        break
                else:
                    info['signal'] = CrashSignal.UNKNOWN
                
                info['signal_num'] = signal_num
                info['signal_name'] = signal_name
                break
        
        # 提取信號碼
        code_match = re.search(r'(?:si_code|code)[=:\s]+([0-9-]+)', content)
        if code_match:
            info['code'] = code_match.group(1)
        
        # 提取故障地址
        fault_patterns = [
            r'fault addr\s+([0-9a-fxA-FX]+)',
            r'si_addr\s+([0-9a-fxA-FX]+)',
            r'Accessing address:\s*([0-9a-fxA-FX]+)',
        ]
        
        for pattern in fault_patterns:
            match = re.search(pattern, content)
            if match:
                info['fault_addr'] = match.group(1)
                break
        
        return info
    
    def _extract_process_info(self, content: str) -> Dict:
        """提取進程資訊"""
        info = {}
        
        for pattern in self.patterns['process_patterns']:
            match = re.search(pattern, content)
            if match:
                groups = match.groups()
                if len(groups) >= 3:
                    info['pid'] = groups[0]
                    info['tid'] = groups[1]
                    info['process_name'] = groups[2]
                elif len(groups) >= 2:
                    info['process_name'] = groups[0]
                    info['pid'] = groups[1]
                break
        
        # 提取線程名稱
        thread_match = re.search(r'Thread-\d+\s+"([^"]+)"', content)
        if thread_match:
            info['thread_name'] = thread_match.group(1)
        elif 'name' in info:
            info['thread_name'] = info.get('process_name', 'Unknown')
        else:
            info['thread_name'] = 'Unknown'
        
        return info
    
    def _extract_abort_message(self, content: str) -> Optional[str]:
        """提取 abort message"""
        for pattern in self.patterns['abort_patterns']:
            match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
            if match:
                return match.group(1).strip()
        return None
    
    def _extract_backtrace(self, content: str) -> List[Dict]:
        """提取崩潰堆疊"""
        backtrace = []
        
        # 查找 backtrace 區段
        backtrace_section = re.search(
            r'(?:backtrace:|stack:)\s*\n(.*?)(?:\n\n|memory map:|open files:)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        
        if not backtrace_section:
            # 嘗試直接匹配堆疊行
            backtrace_section = re.search(
                r'((?:#\d+\s+pc\s+[0-9a-fA-F]+.*\n)+)',
                content,
                re.MULTILINE
            )
        
        if backtrace_section:
            backtrace_text = backtrace_section.group(1)
            
            # 解析堆疊幀
            for pattern in self.patterns['backtrace_patterns']:
                frames = re.findall(pattern, backtrace_text, re.MULTILINE)
                
                for frame_match in frames:
                    if len(frame_match) >= 3:
                        frame_info = {
                            'num': int(frame_match[0]),
                            'pc': frame_match[1],
                            'location': frame_match[2],
                            'symbol': frame_match[3] if len(frame_match) > 3 else None
                        }
                        backtrace.append(frame_info)
                
                if backtrace:
                    break
        
        return backtrace
    
    def _extract_memory_map(self, content: str) -> List[str]:
        """提取記憶體映射"""
        memory_map = []
        
        # 查找 memory map 區段
        map_section = re.search(
            r'memory map.*?:\s*\n(.*?)(?:\n\n|open files:|$)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        
        if map_section:
            map_text = map_section.group(1)
            
            # 解析記憶體映射行
            for line in map_text.splitlines():
                if re.match(r'[0-9a-f]+-[0-9a-f]+\s+[rwxps-]+', line):
                    memory_map.append(line.strip())
        
        return memory_map[:50]  # 限制數量
    
    def _extract_open_files(self, content: str) -> List[str]:
        """提取打開的檔案"""
        open_files = []
        
        # 查找 open files 區段
        files_section = re.search(
            r'open files.*?:\s*\n(.*?)(?:\n\n|$)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        
        if files_section:
            files_text = files_section.group(1)
            
            for line in files_text.splitlines():
                line = line.strip()
                if line and not line.startswith('-'):
                    open_files.append(line)
        
        return open_files[:30]  # 限制數量
    
    def _extract_registers(self, content: str) -> Dict[str, str]:
        """提取寄存器資訊"""
        registers = {}
        
        # 查找寄存器區段
        reg_section = re.search(
            r'registers.*?:\s*\n(.*?)(?:\n\n|backtrace:|$)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        
        if reg_section:
            reg_text = reg_section.group(1)
            
            # 解析寄存器
            reg_pattern = r'([a-z0-9]+)\s+([0-9a-fA-F]+)'
            matches = re.findall(reg_pattern, reg_text)
            
            for reg_name, reg_value in matches:
                registers[reg_name] = reg_value
        
        return registers
    
    def _extract_all_threads_tombstone(self, lines: List[str], content: str) -> List[ThreadInfo]:
        """提取所有線程資訊 (Tombstone)"""
        threads = []
        
        # 查找線程區段
        thread_section = re.search(
            r'(?:threads|other threads).*?:\s*\n(.*?)(?:\n\n|memory map:|$)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        
        if thread_section:
            thread_text = thread_section.group(1)
            # 這裡可以實現更詳細的線程解析
            # 但 Tombstone 通常只包含崩潰線程的詳細資訊
        
        return threads
    
    def _generate_report(self, info: TombstoneInfo, content: str) -> str:
        """生成 Tombstone 報告"""
        generator = TombstoneReportGenerator(info, content)
        return generator.generate()


class TombstoneReportGenerator:
    """Tombstone 報告生成器"""
    
    def __init__(self, info: TombstoneInfo, content: str):
        self.info = info
        self.content = content
        self.report_lines = []
    
    def generate(self) -> str:
        """生成報告"""
        self._add_summary()
        self._add_basic_info()
        self._add_signal_analysis()
        self._add_abort_analysis()
        self._add_backtrace_analysis()
        self._add_memory_analysis()
        self._add_root_cause_analysis()
        self._add_suggestions()
        
        return "\n".join(self.report_lines)
    
    def _add_summary(self):
        """添加摘要"""
        self.report_lines.extend([
            "💥 Tombstone 崩潰分析報告",
            "=" * 60,
            f"📊 崩潰類型: {self._get_crash_type()}",
            f"🚨 信號: {self.info.signal.value[1]} (signal {self.info.signal.value[0]})",
            f"📱 進程: {self.info.process_name} (pid={self.info.pid})",
            f"🧵 線程: {self.info.thread_name} (tid={self.info.tid})",
        ])
        
        # 快速判斷
        severity = self._assess_severity()
        self.report_lines.append(f"⚠️ 嚴重程度: {severity}")
        
        root_cause = self._quick_root_cause()
        self.report_lines.append(f"🎯 可能原因: {root_cause}")
        
        fixability = self._assess_fixability()
        self.report_lines.append(f"🔧 可修復性: {fixability}")
        
        self.report_lines.extend(["", "=" * 60, ""])
    
    def _get_crash_type(self) -> str:
        """獲取崩潰類型"""
        if self.info.signal == CrashSignal.SIGSEGV:
            if self.info.fault_addr in ['0x0', '0', '00000000', '0000000000000000']:
                return "空指針解引用"
            else:
                return "記憶體訪問違規"
        elif self.info.signal == CrashSignal.SIGABRT:
            return "程序主動終止"
        elif self.info.signal == CrashSignal.SIGILL:
            return "非法指令"
        elif self.info.signal == CrashSignal.SIGBUS:
            return "匯流排錯誤"
        elif self.info.signal == CrashSignal.SIGFPE:
            return "浮點異常"
        else:
            return "未知崩潰類型"
    
    def _assess_severity(self) -> str:
        """評估嚴重程度"""
        # 檢查是否為系統進程
        if any(keyword in self.info.process_name for keyword in ['system_server', 'zygote', 'mediaserver']):
            return "🔴 極其嚴重 (系統進程崩潰)"
        
        # 檢查是否為框架庫
        if self.info.crash_backtrace:
            for frame in self.info.crash_backtrace[:3]:
                location = frame.get('location', '')
                if any(lib in location for lib in ['libc.so', 'libandroid_runtime.so', 'libbinder.so']):
                    return "🟠 嚴重 (框架層崩潰)"
        
        # 檢查是否為廠商庫
        if any('vendor' in frame.get('location', '') for frame in self.info.crash_backtrace[:5]):
            return "🟡 中等 (廠商庫問題)"
        
        return "🟢 輕微 (應用層崩潰)"
    
    def _quick_root_cause(self) -> str:
        """快速定位根本原因"""
        causes = []
        
        # 基於信號
        if self.info.signal == CrashSignal.SIGSEGV:
            if self.info.fault_addr in ['0x0', '0', '00000000']:
                causes.append("空指針解引用")
            else:
                causes.append("野指針或記憶體越界")
        elif self.info.signal == CrashSignal.SIGABRT:
            if self.info.abort_message:
                if 'assert' in self.info.abort_message.lower():
                    causes.append("斷言失敗")
                elif 'check failed' in self.info.abort_message.lower():
                    causes.append("檢查失敗")
                else:
                    causes.append("主動終止")
            else:
                causes.append("異常終止")
        
        # 基於堆疊
        if self.info.crash_backtrace:
            top_frame = self.info.crash_backtrace[0]
            symbol = top_frame.get('symbol', '')
            location = top_frame.get('location', '')
            
            if 'malloc' in symbol or 'free' in symbol:
                causes.append("記憶體管理錯誤")
            elif 'strlen' in symbol or 'strcpy' in symbol:
                causes.append("字串處理錯誤")
            elif 'JNI' in location:
                causes.append("JNI 調用錯誤")
        
        return " / ".join(causes) if causes else "需進一步分析"
    
    def _assess_fixability(self) -> str:
        """評估可修復性"""
        # 檢查是否在應用代碼
        if self.info.crash_backtrace:
            for frame in self.info.crash_backtrace[:5]:
                location = frame.get('location', '')
                if self.info.process_name in location:
                    return "🟢 容易 (應用層代碼)"
        
        # 檢查是否為廠商庫
        if any('vendor' in frame.get('location', '') for frame in self.info.crash_backtrace[:5]):
            return "🟡 中等 (需要廠商支援)"
        
        # 系統庫
        if any(lib in frame.get('location', '') for frame in self.info.crash_backtrace[:3] 
               for lib in ['libc.so', 'libandroid_runtime.so']):
            return "🔴 困難 (系統層問題)"
        
        return "🟡 中等"
    
    def _add_basic_info(self):
        """添加基本資訊"""
        self.report_lines.append("📋 詳細資訊")
        self.report_lines.append(f"\n📍 故障地址: {self.info.fault_addr}")
        
        # 分析故障地址
        addr_analysis = self._analyze_fault_address()
        if addr_analysis:
            self.report_lines.append(f"   分析: {addr_analysis}")
        
        self.report_lines.append(f"📟 信號碼: {self.info.signal_code}")
    
    def _analyze_fault_address(self) -> Optional[str]:
        """分析故障地址"""
        addr = self.info.fault_addr.lower()
        
        if addr in ['0x0', '0', '00000000', '0000000000000000']:
            return "空指針 - 嘗試訪問 NULL"
        elif addr == '0xdeadbaad':
            return "Bionic libc abort 標記"
        elif addr.startswith('0xdead'):
            return "可能是調試標記或損壞的指針"
        elif int(addr, 16) < 0x1000:
            return "低地址 - 可能是空指針加偏移"
        elif int(addr, 16) > 0x7fffffffffff:
            return "內核地址空間 - 可能是內核錯誤"
        
        # 檢查是否在記憶體映射中
        for mem_line in self.info.memory_map[:20]:
            if '-' in mem_line:
                parts = mem_line.split()
                if parts:
                    range_str = parts[0]
                    if '-' in range_str:
                        start, end = range_str.split('-')
                        try:
                            if int(start, 16) <= int(addr, 16) <= int(end, 16):
                                # 找到對應的記憶體區域
                                if len(parts) > 6:
                                    return f"位於 {parts[6]}"
                        except:
                            pass
        
        return None
    
    def _add_signal_analysis(self):
        """添加信號分析"""
        self.report_lines.append(f"\n🔍 信號分析")
        
        signal_analyses = {
            CrashSignal.SIGSEGV: [
                "記憶體訪問違規 - 程序嘗試訪問無效記憶體",
                "常見原因: 空指針、野指針、數組越界、使用已釋放的記憶體",
            ],
            CrashSignal.SIGABRT: [
                "程序主動終止 - 通常由 abort() 調用觸發",
                "常見原因: assert 失敗、檢測到嚴重錯誤、手動調用 abort",
            ],
            CrashSignal.SIGILL: [
                "非法指令 - CPU 無法執行的指令",
                "常見原因: 代碼損壞、函數指針錯誤、CPU 架構不匹配",
            ],
            CrashSignal.SIGBUS: [
                "匯流排錯誤 - 記憶體對齊或硬體問題",
                "常見原因: 未對齊的記憶體訪問、硬體故障",
            ],
            CrashSignal.SIGFPE: [
                "浮點異常 - 數學運算錯誤",
                "常見原因: 除零、整數溢出、無效的浮點運算",
            ],
        }
        
        analyses = signal_analyses.get(self.info.signal, ["未知信號類型"])
        for analysis in analyses:
            self.report_lines.append(f"  • {analysis}")
    
    def _add_abort_analysis(self):
        """添加 abort message 分析"""
        if not self.info.abort_message:
            return
        
        self.report_lines.append(f"\n🗨️ Abort Message 分析")
        self.report_lines.append(f"訊息: {self.info.abort_message}")
        
        # 分析 abort message
        analyses = []
        
        msg_lower = self.info.abort_message.lower()
        
        if 'assert' in msg_lower:
            analyses.append("檢測到斷言失敗")
            
            # 嘗試提取文件和行號
            file_match = re.search(r'(\w+\.\w+):(\d+)', self.info.abort_message)
            if file_match:
                analyses.append(f"位置: {file_match.group(1)}:{file_match.group(2)}")
        
        elif 'check failed' in msg_lower:
            analyses.append("執行時檢查失敗")
        
        elif 'fatal' in msg_lower:
            analyses.append("致命錯誤")
        
        elif 'out of memory' in msg_lower:
            analyses.append("記憶體不足")
        
        elif 'stack overflow' in msg_lower:
            analyses.append("堆疊溢出")
        
        if analyses:
            self.report_lines.append("分析:")
            for analysis in analyses:
                self.report_lines.append(f"  • {analysis}")
    
    def _add_backtrace_analysis(self):
        """添加堆疊分析"""
        if not self.info.crash_backtrace:
            self.report_lines.append("\n❌ 無崩潰堆疊資訊")
            return
        
        self.report_lines.append(f"\n📚 崩潰堆疊分析 (共 {len(self.info.crash_backtrace)} 層)")
        
        # 找出崩潰點
        crash_point = self._find_crash_point()
        if crash_point:
            self.report_lines.append(f"💥 崩潰點: {crash_point}")
        
        # 分析堆疊
        stack_analyses = self._analyze_crash_stack()
        if stack_analyses:
            self.report_lines.append("\n堆疊分析:")
            for analysis in stack_analyses:
                self.report_lines.append(f"  • {analysis}")
        
        # 顯示關鍵堆疊
        self.report_lines.append("\n關鍵堆疊:")
        for i, frame in enumerate(self.info.crash_backtrace[:15]):
            frame_str = self._format_frame(frame)
            marker = self._get_frame_marker_tombstone(frame)
            self.report_lines.append(f"  #{i:02d} {frame_str} {marker}")
    
    def _find_crash_point(self) -> Optional[str]:
        """找出崩潰點"""
        for frame in self.info.crash_backtrace[:5]:
            if frame.get('symbol'):
                return f"#{frame['num']} {frame['symbol']} @ {frame['location']}"
        
        # 如果沒有符號，返回第一個有效幀
        if self.info.crash_backtrace:
            frame = self.info.crash_backtrace[0]
            return f"#{frame['num']} pc {frame['pc']} @ {frame['location']}"
        
        return None
    
    def _analyze_crash_stack(self) -> List[str]:
        """分析崩潰堆疊"""
        analyses = []
        
        # 檢查記憶體管理問題
        memory_funcs = ['malloc', 'free', 'realloc', 'calloc', 'delete', 'new']
        for frame in self.info.crash_backtrace[:10]:
            symbol = frame.get('symbol', '')
            if any(func in symbol for func in memory_funcs):
                analyses.append("檢測到記憶體管理函數 - 可能是記憶體損壞或雙重釋放")
                break
        
        # 檢查字串操作
        string_funcs = ['strlen', 'strcpy', 'strcat', 'strcmp', 'memcpy', 'memmove']
        for frame in self.info.crash_backtrace[:10]:
            symbol = frame.get('symbol', '')
            if any(func in symbol for func in string_funcs):
                analyses.append("檢測到字串操作函數 - 可能是緩衝區溢出或無效指針")
                break
        
        # 檢查 JNI
        jni_found = False
        for frame in self.info.crash_backtrace[:10]:
            location = frame.get('location', '')
            symbol = frame.get('symbol', '')
            if 'JNI' in location or 'jni' in symbol.lower():
                analyses.append("檢測到 JNI 調用 - 檢查 Java/Native 介面")
                jni_found = True
                break
        
        # 檢查系統庫
        system_libs = ['libc.so', 'libandroid_runtime.so', 'libbinder.so', 'libutils.so']
        for frame in self.info.crash_backtrace[:5]:
            location = frame.get('location', '')
            for lib in system_libs:
                if lib in location:
                    if not jni_found:  # 避免重複
                        analyses.append(f"崩潰發生在系統庫 {lib}")
                    break
        
        # 檢查堆疊深度
        if len(self.info.crash_backtrace) > 50:
            analyses.append(f"堆疊過深 ({len(self.info.crash_backtrace)} 層) - 可能有遞迴或堆疊溢出")
        
        return analyses
    
    def _format_frame(self, frame: Dict) -> str:
        """格式化堆疊幀"""
        pc = frame.get('pc', 'Unknown')
        location = frame.get('location', 'Unknown')
        symbol = frame.get('symbol', '')
        
        if symbol:
            return f"pc {pc} {location} ({symbol})"
        else:
            return f"pc {pc} {location}"
    
    def _get_frame_marker_tombstone(self, frame: Dict) -> str:
        """獲取堆疊幀標記 (Tombstone)"""
        symbol = frame.get('symbol', '')
        location = frame.get('location', '')
        
        # 記憶體管理
        if any(func in symbol for func in ['malloc', 'free', 'new', 'delete']):
            return "💾 [記憶體]"
        
        # 字串操作
        elif any(func in symbol for func in ['strlen', 'strcpy', 'strcat']):
            return "📝 [字串]"
        
        # JNI
        elif 'JNI' in location or 'jni' in symbol.lower():
            return "☕ [JNI]"
        
        # 系統庫
        elif 'libc.so' in location:
            return "🔧 [libc]"
        elif 'libandroid_runtime.so' in location:
            return "🤖 [Runtime]"
        elif 'libbinder.so' in location:
            return "🔗 [Binder]"
        
        # 廠商庫
        elif 'vendor' in location:
            return "🏭 [廠商]"
        
        # 應用庫
        elif self.info.process_name in location:
            return "📱 [應用]"
        
        return ""
    
    def _add_memory_analysis(self):
        """添加記憶體分析"""
        if not self.info.memory_map:
            return
        
        self.report_lines.append(f"\n💾 記憶體映射分析 (顯示前 20 項)")
        
        # 分析故障地址所在區域
        fault_region = self._find_fault_memory_region()
        if fault_region:
            self.report_lines.append(f"\n故障地址所在區域:")
            self.report_lines.append(f"  {fault_region}")
        
        # 顯示關鍵記憶體區域
        self.report_lines.append("\n關鍵記憶體區域:")
        for i, mem_line in enumerate(self.info.memory_map[:20]):
            if any(keyword in mem_line for keyword in [
                self.info.process_name,
                'stack',
                'heap',
                '/system/lib',
                '/vendor/lib'
            ]):
                self.report_lines.append(f"  {mem_line}")
    
    def _find_fault_memory_region(self) -> Optional[str]:
        """找出故障地址所在的記憶體區域"""
        try:
            fault_addr_int = int(self.info.fault_addr, 16)
        except:
            return None
        
        for mem_line in self.info.memory_map:
            if '-' in mem_line:
                parts = mem_line.split()
                if parts:
                    range_str = parts[0]
                    if '-' in range_str:
                        start_str, end_str = range_str.split('-')
                        try:
                            start = int(start_str, 16)
                            end = int(end_str, 16)
                            if start <= fault_addr_int <= end:
                                return mem_line
                        except:
                            continue
        
        return None
    
    def _add_root_cause_analysis(self):
        """添加根本原因分析"""
        self.report_lines.append("\n🎯 根本原因分析")
        
        # 基於信號和堆疊的綜合分析
        root_causes = []
        
        # 空指針分析
        if self.info.signal == CrashSignal.SIGSEGV and self.info.fault_addr in ['0x0', '0', '00000000']:
            root_causes.append("空指針解引用:")
            root_causes.append("  • 檢查指針是否在使用前初始化")
            root_causes.append("  • 檢查函數返回值是否為 NULL")
            root_causes.append("  • 檢查是否有提前釋放的情況")
        
        # 記憶體損壞分析
        elif self.info.signal == CrashSignal.SIGSEGV:
            if self.info.crash_backtrace:
                top_symbol = self.info.crash_backtrace[0].get('symbol', '')
                if any(func in top_symbol for func in ['free', 'delete']):
                    root_causes.append("可能的雙重釋放或使用已釋放記憶體:")
                    root_causes.append("  • 檢查是否有重複 free/delete")
                    root_causes.append("  • 檢查是否在釋放後繼續使用指針")
                elif any(func in top_symbol for func in ['malloc', 'new']):
                    root_causes.append("記憶體分配失敗或堆損壞:")
                    root_causes.append("  • 檢查是否有記憶體洩漏")
                    root_causes.append("  • 檢查是否有緩衝區溢出")
            
            root_causes.append("記憶體訪問違規:")
            root_causes.append("  • 檢查數組邊界")
            root_causes.append("  • 檢查指針運算")
        
        # Abort 分析
        elif self.info.signal == CrashSignal.SIGABRT:
            if self.info.abort_message:
                if 'assert' in self.info.abort_message.lower():
                    root_causes.append("斷言失敗:")
                    root_causes.append("  • 程序狀態不符合預期")
                    root_causes.append("  • 檢查斷言條件")
                elif 'check failed' in self.info.abort_message.lower():
                    root_causes.append("運行時檢查失敗:")
                    root_causes.append("  • 檢查失敗的條件")
                    root_causes.append("  • 分析為何會達到這個狀態")
            else:
                root_causes.append("程序主動終止:")
                root_causes.append("  • 檢查是否有明確的 abort() 調用")
                root_causes.append("  • 檢查是否有未捕獲的異常")
        
        for cause in root_causes:
            self.report_lines.append(f"  {cause}")
    
    def _add_suggestions(self):
        """添加解決建議"""
        self.report_lines.append("\n💡 解決建議")
        
        suggestions = self._generate_suggestions()
        
        # 調試建議
        if suggestions['debugging']:
            self.report_lines.append("\n🔍 調試步驟:")
            for i, suggestion in enumerate(suggestions['debugging'], 1):
                self.report_lines.append(f"  {i}. {suggestion}")
        
        # 修復建議
        if suggestions['fixing']:
            self.report_lines.append("\n🔧 修復建議:")
            for i, suggestion in enumerate(suggestions['fixing'], 1):
                self.report_lines.append(f"  {i}. {suggestion}")
        
        # 預防建議
        if suggestions['prevention']:
            self.report_lines.append("\n🛡️ 預防措施:")
            for i, suggestion in enumerate(suggestions['prevention'], 1):
                self.report_lines.append(f"  {i}. {suggestion}")
    
    def _generate_suggestions(self) -> Dict[str, List[str]]:
        """生成建議"""
        suggestions = {
            'debugging': [],
            'fixing': [],
            'prevention': []
        }
        
        # 調試建議
        suggestions['debugging'].extend([
            "使用 addr2line 工具解析詳細的源碼位置",
            "在 Android Studio 中使用 Debug 模式重現問題",
            "開啟 Address Sanitizer (ASAN) 檢測記憶體錯誤",
        ])
        
        # 基於崩潰類型的建議
        if self.info.signal == CrashSignal.SIGSEGV:
            if self.info.fault_addr in ['0x0', '0', '00000000']:
                suggestions['fixing'].extend([
                    "檢查所有指針使用前是否為 NULL",
                    "為指針添加防禦性檢查",
                    "使用智能指針 (如 std::unique_ptr)",
                ])
            else:
                suggestions['fixing'].extend([
                    "檢查數組邊界訪問",
                    "使用 valgrind 或 ASAN 檢測記憶體問題",
                    "檢查多線程下的記憶體訪問",
                ])
        
        elif self.info.signal == CrashSignal.SIGABRT:
            suggestions['fixing'].extend([
                "檢查 assert 條件是否合理",
                "添加更多的錯誤處理",
                "使用 try-catch 捕獲異常",
            ])
        
        # JNI 相關
        if any('JNI' in frame.get('location', '') or 'jni' in frame.get('symbol', '').lower() 
               for frame in self.info.crash_backtrace[:10]):
            suggestions['fixing'].extend([
                "檢查 JNI 調用的參數有效性",
                "確保 JNI 局部引用正確管理",
                "檢查 Java 和 Native 之間的數據類型匹配",
            ])
        
        # 預防建議
        suggestions['prevention'].extend([
            "使用靜態分析工具 (如 Clang Static Analyzer)",
            "編寫單元測試覆蓋邊界情況",
            "使用 Code Review 檢查記憶體管理",
            "開啟編譯器的所有警告 (-Wall -Wextra)",
        ])
        
        # 系統庫崩潰
        if any(lib in frame.get('location', '') for frame in self.info.crash_backtrace[:3]
               for lib in ['libc.so', 'libandroid_runtime.so']):
            suggestions['debugging'].append("收集完整的 bugreport 分析系統狀態")
            suggestions['fixing'].append("檢查是否有系統資源耗盡")
        
        return suggestions


# ============= 分析器工廠 =============

class AnalyzerFactory:
    """分析器工廠"""
    
    @staticmethod
    def create_analyzer(file_type: str) -> BaseAnalyzer:
        """創建分析器"""
        if file_type.lower() == "anr":
            return ANRAnalyzer()
        elif file_type.lower() in ["tombstone", "tombstones"]:
            return TombstoneAnalyzer()
        else:
            raise ValueError(f"不支援的檔案類型: {file_type}")


# ============= 主程式 =============

class LogAnalyzerSystem:
    """日誌分析系統"""
    
    def __init__(self, input_folder: str, output_folder: str):
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.stats = {
            'anr_count': 0,
            'tombstone_count': 0,
            'error_count': 0,
            'total_time': 0,
        }
    
    def analyze(self):
        """執行分析"""
        start_time = time.time()
        
        print("🚀 啟動進階版 ANR/Tombstone 分析系統...")
        print(f"📂 輸入資料夾: {self.input_folder}")
        print(f"📂 輸出資料夾: {self.output_folder}")
        print("")
        
        # 創建輸出目錄
        os.makedirs(self.output_folder, exist_ok=True)
        
        # 掃描檔案
        files_to_analyze = self._scan_files()
        print(f"📊 找到 {len(files_to_analyze)} 個檔案需要分析")
        print("")
        
        # 分析檔案
        index_data = {}
        for file_info in files_to_analyze:
            try:
                self._analyze_file(file_info, index_data)
            except Exception as e:
                print(f"❌ 分析 {file_info['path']} 時發生錯誤: {str(e)}")
                self.stats['error_count'] += 1
        
        # 生成索引
        self._generate_index(index_data)
        
        # 顯示統計
        self.stats['total_time'] = time.time() - start_time
        self._show_statistics()
    
    def _scan_files(self) -> List[Dict]:
        """掃描檔案"""
        files = []
        
        for root, dirs, filenames in os.walk(self.input_folder):
            base_dir = os.path.basename(root).lower()
            
            if base_dir in ["anr", "tombstones", "tombstone"]:
                for filename in filenames:
                    # 跳過特定檔案
                    if filename.endswith('.pb') or filename.endswith('.txt.analyzed'):
                        continue
                    
                    file_path = os.path.join(root, filename)
                    file_type = "anr" if base_dir == "anr" else "tombstone"
                    
                    files.append({
                        'path': file_path,
                        'type': file_type,
                        'name': filename,
                        'rel_path': os.path.relpath(file_path, self.input_folder)
                    })
        
        return files
    
    def _analyze_file(self, file_info: Dict, index_data: Dict):
        """分析單個檔案"""
        print(f"🔍 分析 {file_info['type'].upper()}: {file_info['name']}")
        
        # 創建分析器
        analyzer = AnalyzerFactory.create_analyzer(file_info['type'])
        
        # 執行分析
        result = analyzer.analyze(file_info['path'])
        
        # 保存結果
        output_dir = os.path.join(self.output_folder, os.path.dirname(file_info['rel_path']))
        os.makedirs(output_dir, exist_ok=True)
        
        output_file = os.path.join(output_dir, file_info['name'] + '.analyzed.txt')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result)
        
        # 複製原始檔案
        original_copy = os.path.join(output_dir, file_info['name'])
        shutil.copy2(file_info['path'], original_copy)
        
        # 更新索引
        self._update_index(index_data, file_info['rel_path'], output_file, original_copy)
        
        # 更新統計
        if file_info['type'] == 'anr':
            self.stats['anr_count'] += 1
        else:
            self.stats['tombstone_count'] += 1
    
    def _update_index(self, index_data: Dict, rel_path: str, analyzed_file: str, original_file: str):
        """更新索引"""
        parts = rel_path.split(os.sep)
        current = index_data
        
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        
        filename = parts[-1]
        current[filename + '.analyzed.txt'] = {
            'analyzed_file': analyzed_file,
            'original_file': original_file
        }
    
    def _generate_index(self, index_data: Dict):
        """生成 HTML 索引"""
        html_content = self._generate_html_index(index_data)
        
        index_file = os.path.join(self.output_folder, 'index.html')
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"\n📝 已生成索引檔案: {index_file}")
    
    def _generate_html_index(self, index_data: Dict) -> str:
        """生成 HTML 索引內容"""
        def render_tree(data, prefix=""):
            html_str = "<ul>"
            for name, value in sorted(data.items()):
                if isinstance(value, dict) and 'analyzed_file' in value:
                    # 檔案項目
                    analyzed_rel = os.path.relpath(value['analyzed_file'], self.output_folder)
                    original_rel = os.path.relpath(value['original_file'], self.output_folder)
                    
                    html_str += f'<li>'
                    html_str += f'<a href="{html.escape(analyzed_rel)}">{html.escape(name)}</a>'
                    html_str += f' <span class="source-link">'
                    html_str += f'(<a href="{html.escape(original_rel)}">原始檔案</a>)'
                    html_str += f'</span>'
                    html_str += f'</li>'
                elif isinstance(value, dict):
                    # 目錄項目
                    html_str += f'<li class="folder">'
                    html_str += f'<strong>{html.escape(name)}</strong>'
                    html_str += render_tree(value, prefix + '/' + name)
                    html_str += f'</li>'
            html_str += "</ul>"
            return html_str
        
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>進階版 Android Log 分析報告 v4</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 0;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            margin: 0 0 20px 0;
            font-size: 2.5em;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        .stat-card {{
            background: #f9f9f9;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #4CAF50;
        }}
        .stat-card h3 {{
            margin: 0 0 5px 0;
            color: #666;
            font-size: 0.9em;
        }}
        .stat-card .value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #333;
        }}
        .content {{
            background: white;
            border-radius: 10px;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        ul {{
            list-style: none;
            padding-left: 20px;
        }}
        li {{
            margin: 8px 0;
            line-height: 1.6;
        }}
        li.folder > strong {{
            color: #666;
            font-size: 1.1em;
        }}
        a {{
            color: #2196F3;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .source-link {{
            color: #999;
            font-size: 0.9em;
            margin-left: 10px;
        }}
        .source-link a {{
            color: #999;
        }}
        .features {{
            background: #e3f2fd;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}
        .features h3 {{
            color: #1976d2;
            margin-top: 0;
        }}
        .features ul {{
            margin: 10px 0;
            padding-left: 20px;
        }}
        .features li {{
            list-style-type: disc;
            margin: 5px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 進階版 Android Log 分析報告 v4</h1>
            <p>基於物件導向設計的智能分析系統，支援所有 Android 版本的 ANR 和 Tombstone 格式</p>
            
            <div class="stats">
                <div class="stat-card">
                    <h3>ANR 檔案</h3>
                    <div class="value">{self.stats['anr_count']}</div>
                </div>
                <div class="stat-card">
                    <h3>Tombstone 檔案</h3>
                    <div class="value">{self.stats['tombstone_count']}</div>
                </div>
                <div class="stat-card">
                    <h3>總檔案數</h3>
                    <div class="value">{self.stats['anr_count'] + self.stats['tombstone_count']}</div>
                </div>
                <div class="stat-card">
                    <h3>分析時間</h3>
                    <div class="value">{self.stats['total_time']:.1f}s</div>
                </div>
            </div>
            
            <div class="features">
                <h3>🎯 分析特點</h3>
                <ul>
                    <li>支援所有 Android 版本 (4.x - 14) 的 ANR 格式</li>
                    <li>完整的 Tombstone 信號分析 (SIGSEGV, SIGABRT, SIGILL 等)</li>
                    <li>智能死鎖檢測和循環等待分析</li>
                    <li>Binder IPC 阻塞深度分析</li>
                    <li>記憶體管理錯誤定位</li>
                    <li>基於大量真實案例的模式識別</li>
                    <li>詳細的修復建議和調查方向</li>
                    <li>堆疊幀重要性標記 (🔴 關鍵 / 🟡 重要 / ⚪ 普通)</li>
                </ul>
            </div>
            
            <p><strong>生成時間:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="content">
            <h2>📁 分析結果</h2>
            {render_tree(index_data)}
        </div>
    </div>
</body>
</html>"""
    
    def _show_statistics(self):
        """顯示統計資訊"""
        print("\n" + "=" * 60)
        print("✅ 分析完成！")
        print("=" * 60)
        
        print(f"\n📊 分析統計:")
        print(f"  • ANR 檔案: {self.stats['anr_count']} 個")
        print(f"  • Tombstone 檔案: {self.stats['tombstone_count']} 個")
        print(f"  • 錯誤數量: {self.stats['error_count']} 個")
        print(f"  • 總執行時間: {self.stats['total_time']:.2f} 秒")
        
        if self.stats['anr_count'] + self.stats['tombstone_count'] > 0:
            avg_time = self.stats['total_time'] / (self.stats['anr_count'] + self.stats['tombstone_count'])
            print(f"  • 平均處理時間: {avg_time:.3f} 秒/檔案")
        
        print(f"\n🎯 輸出目錄: {self.output_folder}")
        print(f"🌐 請開啟 {os.path.join(self.output_folder, 'index.html')} 查看分析報告")


def main():
    """主函數"""
    if len(sys.argv) != 3:
        print("用法: python3 vp_analyze_logs.py <輸入資料夾> <輸出資料夾>")
        print("範例: python3 vp_analyze_logs.py logs/ output/")
        print("\n特點:")
        print("  • 使用物件導向設計，易於擴展和維護")
        print("  • 支援所有 Android 版本的 ANR 和 Tombstone 格式")
        print("  • 基於大量真實案例的智能分析")
        print("  • 提供詳細的根本原因分析和解決建議")
        sys.exit(1)
    
    input_folder = sys.argv[1]
    output_folder = sys.argv[2]
    
    # 創建分析系統並執行
    analyzer = LogAnalyzerSystem(input_folder, output_folder)
    analyzer.analyze()


if __name__ == "__main__":
    main()