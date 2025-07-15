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
import base64

# 導入基礎類別
from vp_analyze_logs_base import (
    SourceLink, SourceLinker, ANRTimeouts, ThreadInfo, ANRType, CrashSignal, ThreadState, ANRInfo, TombstoneInfo
)

from vp_analyze_logs_ext import PerformanceBottleneckDetector, BinderCallChainAnalyzer, ThreadDependencyAnalyzer, TimelineAnalyzer,CrossProcessAnalyzer,MLAnomalyDetector,RootCausePredictor,RiskAssessmentEngine,TrendAnalyzer,SystemMetricsIntegrator,SourceCodeAnalyzer,CodeFixGenerator,ConfigurationOptimizer,ComparativeAnalyzer,ParallelAnalyzer,IncrementalAnalyzer,VisualizationGenerator,ExecutiveSummaryGenerator

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
                # 新增的模式
                r'JobScheduler.*?timed out.*?job=([^\s]+)',
                r'Foreground service.*?timed out.*?service=([^\s]+)',
                r'JobService.*?did not return.*?from.*?(\w+)',
            ],
            'lock_patterns': [
                r'waiting to lock\s+<([^>]+)>.*?held by thread\s+(\d+)',
                r'locked\s+<([^>]+)>',
                r'waiting on\s+<([^>]+)>',
                r'- locked\s+<0x([0-9a-f]+)>\s+\(a\s+([^)]+)\)',
                r'heldby=(\d+)',
                # 新增跨進程鎖模式
                r'held by tid=(\d+) in process (\d+)',
                r'waiting for monitor entry',
                r'waiting for ownable synchronizer',
            ],
            'binder_patterns': [
                r'BinderProxy\.transact',
                r'Binder\.transact',
                r'IPCThreadState::transact',
                r'android\.os\.BinderProxy\.transactNative',
                r'android\.os\.Binder\.execTransact',
                r'oneway\s+transaction',
            ],
            'watchdog_patterns': [
                r'Watchdog.*detected.*deadlock',
                r'WATCHDOG.*TIMEOUT',
                r'system_server.*anr.*Trace\.txt',
                r'com\.android\.server\.Watchdog',
                r'watchdog.*kill.*system_server',
            ],
            'gc_patterns': [
                r'GC_FOR_ALLOC.*?freed.*?paused\s+(\d+)ms',
                r'GC_CONCURRENT.*?freed.*?paused\s+(\d+)ms\+(\d+)ms',
                r'GC_EXPLICIT.*?freed.*?paused\s+(\d+)ms',
                r'Clamp target GC heap',
                r'Alloc.*?concurrent.*?GC',
                r'Starting a blocking GC',
            ],
            'strictmode_patterns': [
                r'StrictMode.*?violation',
                r'DiskReadViolation',
                r'DiskWriteViolation',
                r'NetworkViolation',
                r'CustomSlowCallViolation',
                r'ResourceMismatchViolation',
            ],
        }
    
    @time_tracker("解析 ANR 檔案")
    def analyze(self, file_path: str) -> str:
        """分析 ANR 檔案"""
        try:
            print(f"開始分析檔案: {file_path}")
            
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            print(f"檔案大小: {len(content)} 字符")
            
            # 解析 ANR 資訊
            anr_info = self._parse_anr_info(content)
            
            print(f"解析結果 - 進程名: {anr_info.process_name}, PID: {anr_info.pid}")
            print(f"ANR 類型: {anr_info.anr_type.value}")
            print(f"線程數量: {len(anr_info.all_threads)}")
            
            # 創建智能分析引擎 - 修正這裡
            try:
                from vp_analyze_logs_ext import (
                    TimelineAnalyzer, CrossProcessAnalyzer, MLAnomalyDetector,
                    RootCausePredictor, RiskAssessmentEngine, TrendAnalyzer,
                    SystemMetricsIntegrator, SourceCodeAnalyzer, CodeFixGenerator,
                    ConfigurationOptimizer, ComparativeAnalyzer, ParallelAnalyzer,
                    IncrementalAnalyzer, VisualizationGenerator, ExecutiveSummaryGenerator
                )
                
                intelligent_engine = IntelligentAnalysisEngine()
            except Exception as e:
                print(f"創建智能分析引擎失敗: {e}")
                intelligent_engine = None
            
            # 生成分析報告
            report = self._generate_report(anr_info, content, intelligent_engine)
            
            return report
            
        except Exception as e:
            error_msg = f"❌ 分析 ANR 檔案時發生錯誤: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            return error_msg
    
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
        
        # 新增：解析 ANR 超時時間
        timeout_info = self._extract_timeout_info(content)
        
        anr_info = ANRInfo(
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
        
        # 新增：將超時資訊加入 ANRInfo
        anr_info.timeout_info = timeout_info
        
        return anr_info
    
    def _identify_anr_type(self, content: str) -> ANRType:
        """識別 ANR 類型 - 增強版"""
        type_mappings = {
            # 原有的映射
            "Input dispatching timed out": ANRType.INPUT_DISPATCHING,
            "Input event dispatching timed out": ANRType.INPUT_DISPATCHING,
            "executing service": ANRType.SERVICE,
            "Broadcast of Intent": ANRType.BROADCAST,
            "BroadcastReceiver": ANRType.BROADCAST,
            "ContentProvider": ANRType.CONTENT_PROVIDER,
            "Activity": ANRType.ACTIVITY,
            "Foreground service": ANRType.FOREGROUND_SERVICE,
            # 新增的類型檢測
            "JobScheduler": ANRType.SERVICE,
            "JobService": ANRType.SERVICE,
            "startForeground": ANRType.FOREGROUND_SERVICE,
        }
        
        # 檢查是否有 Watchdog 超時
        if any(re.search(pattern, content) for pattern in self.patterns['watchdog_patterns']):
            # Watchdog 通常是系統服務問題
            return ANRType.SERVICE
        
        for pattern, anr_type in type_mappings.items():
            if pattern in content:
                return anr_type
        
        return ANRType.UNKNOWN
    
    def _extract_process_info(self, content: str) -> Dict:
        """提取進程資訊"""
        info = {}
        
        # 特別處理您的日誌格式
        # 1. 提取 PID 和時間戳
        pid_patterns = [
            r'----- pid (\d+) at ([\d-]+\s+[\d:.]+[\+\-]\d+)',  # 完整格式
            r'----- dumping pid:\s*(\d+)',  # dumping 格式
        ]
        
        for pattern in pid_patterns:
            match = re.search(pattern, content)
            if match:
                info['pid'] = match.group(1)
                if len(match.groups()) > 1:  # 如果有時間戳
                    timestamp = match.group(2)
                    # 移除時區，保留主要時間
                    info['timestamp'] = re.sub(r'[\+\-]\d+$', '', timestamp).strip()
                break
        
        # 2. 提取進程名（從 Cmd line）
        cmdline_match = re.search(r'Cmd line:\s*([^\s\n]+)', content)
        if cmdline_match:
            info['process_name'] = cmdline_match.group(1)
        
        # 3. 提取 Build fingerprint
        fingerprint_match = re.search(r"Build fingerprint:\s*'([^']+)'", content)
        if fingerprint_match:
            info['build_fingerprint'] = fingerprint_match.group(1)
        
        # 4. 提取 ABI
        abi_match = re.search(r"ABI:\s*'([^']+)'", content)
        if abi_match:
            info['abi'] = abi_match.group(1)
        
        # 如果上面的特殊處理已經找到了基本資訊，可以返回
        if 'pid' in info and 'process_name' in info:
            print(f"提取的進程資訊: {info}")
            return info
        
        # 否則嘗試其他標準格式
        patterns = [
            # 標準 ANR 格式
            r'ANR in\s+([^\s,]+).*?(?:PID:\s*(\d+))?',
            r'Process:\s*([^\s,]+).*?(?:PID:\s*(\d+))?',
            r'ProcessRecord\{[^}]+\s+(\d+):([^/]+)',
            # Subject 行格式
            r'Subject:\s*ANR.*?Process:\s*([^\s]+)',
            # 新格式
            r'pid:\s*(\d+),.*?name:\s*([^\s]+)',
            # Executing service
            r'executing service\s+([^/]+)/([^\s]+)',
            # Input dispatching
            r'Input event dispatching timed out.*?([^\s]+)\s+\(server\)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.MULTILINE)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    # 根據模式處理不同的匹配結果
                    if pattern.startswith(r'pid:'):
                        info['pid'] = groups[0]
                        info['process_name'] = groups[1]
                    elif pattern.startswith(r'ProcessRecord'):
                        info['pid'] = groups[0]
                        info['process_name'] = groups[1]
                    elif pattern.startswith(r'executing service'):
                        info['process_name'] = groups[0]
                    else:
                        info['process_name'] = groups[0]
                        if len(groups) > 1 and groups[1]:
                            info['pid'] = groups[1]
                elif len(groups) == 1:
                    info['process_name'] = groups[0]
                
                # 如果找到進程名，就跳出循環
                if 'process_name' in info:
                    break
        
        # 如果還是沒有找到，嘗試從內容中提取
        if 'process_name' not in info:
            # 嘗試找包名格式 (com.example.app)
            package_match = re.search(r'(com\.[a-zA-Z0-9._]+)', content)
            if package_match:
                info['process_name'] = package_match.group(1)
        
        # 提取時間戳（如果還沒有）
        if 'timestamp' not in info:
            timestamp_patterns = [
                r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)',
                r'(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)',
                r'Time:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
            ]
            
            for pattern in timestamp_patterns:
                timestamp_match = re.search(pattern, content)
                if timestamp_match:
                    info['timestamp'] = timestamp_match.group(1)
                    break
        
        # 提取原因
        reason_patterns = [
            r'Reason:\s*(.+?)(?:\n|$)',
            r'Input event dispatching timed out.*?\.\s*(.+?)(?:\n|$)',
            r'executing service\s+(.+?)(?:\n|$)',
        ]
        
        for pattern in reason_patterns:
            reason_match = re.search(pattern, content)
            if reason_match:
                info['reason'] = reason_match.group(1).strip()
                break
        
        print(f"提取的進程資訊: {info}")
        return info
    
    def _extract_timeout_info(self, content: str) -> Dict:
        """提取 ANR 超時資訊"""
        timeout_info = {
            'wait_time': None,
            'timeout_threshold': None,
            'is_foreground': True
        }
        
        # 提取等待時間
        wait_match = re.search(r'Waited\s+(\d+)ms', content)
        if wait_match:
            timeout_info['wait_time'] = int(wait_match.group(1))
        
        # 判斷是否為前台/背景
        if 'background' in content.lower() or 'bg anr' in content.lower():
            timeout_info['is_foreground'] = False
        
        # 根據 ANR 類型設定閾值
        if 'Input' in content:
            timeout_info['timeout_threshold'] = ANRTimeouts.INPUT_DISPATCHING
        elif 'Service' in content:
            if timeout_info['is_foreground']:
                timeout_info['timeout_threshold'] = ANRTimeouts.SERVICE_TIMEOUT
            else:
                timeout_info['timeout_threshold'] = ANRTimeouts.SERVICE_BACKGROUND_TIMEOUT
        elif 'Broadcast' in content:
            if timeout_info['is_foreground']:
                timeout_info['timeout_threshold'] = ANRTimeouts.BROADCAST_TIMEOUT
            else:
                timeout_info['timeout_threshold'] = ANRTimeouts.BROADCAST_BACKGROUND_TIMEOUT
        elif 'JobScheduler' in content or 'JobService' in content:
            timeout_info['timeout_threshold'] = ANRTimeouts.JOB_SCHEDULER_TIMEOUT
        elif 'ContentProvider' in content:
            timeout_info['timeout_threshold'] = ANRTimeouts.CONTENT_PROVIDER_TIMEOUT
        
        return timeout_info
    
    def _extract_all_threads(self, lines: List[str], content: str) -> List[ThreadInfo]:
        """提取所有線程資訊 - 增強版"""
        threads = []
        
        for idx, line in enumerate(lines):
            thread_info = self._try_parse_thread(line, idx, lines)
            if thread_info:
                # 提取堆疊資訊
                thread_info.backtrace = self._extract_backtrace(lines, idx)
                
                # 提取鎖資訊
                self._extract_lock_info(thread_info, lines, idx)
                
                # 新增：檢測跨進程鎖
                self._extract_cross_process_lock_info(thread_info, lines, idx)
                
                # 新增：提取線程 CPU 時間
                self._extract_thread_cpu_time(thread_info, lines, idx)
                
                threads.append(thread_info)
        
        return threads
    
    def _try_parse_thread(self, line: str, idx: int, lines: List[str]) -> Optional[ThreadInfo]:
        """嘗試解析線程資訊"""
        # 您的日誌格式: "GmsDynamite" prio=5 tid=46 Waiting
        thread_match = re.match(r'"([^"]+)"\s+prio=(\d+)\s+tid=(\d+)\s+(\w+)', line)
        if thread_match:
            name = thread_match.group(1)
            prio = thread_match.group(2)
            tid = thread_match.group(3)
            state_str = thread_match.group(4)
            
            thread_info = ThreadInfo(
                name=name,
                tid=tid,
                prio=prio,
                state=self._parse_thread_state(state_str)
            )
            
            # 從後續行提取 sysTid 和其他資訊
            for i in range(idx + 1, min(idx + 5, len(lines))):
                next_line = lines[i]
                
                # 提取 sysTid
                systid_match = re.search(r'sysTid=(\d+)', next_line)
                if systid_match:
                    thread_info.sysTid = systid_match.group(1)
                
                # 提取 state (更詳細的狀態)
                state_match = re.search(r'\|\s+state=([A-Z])', next_line)
                if state_match:
                    # 如果有更詳細的狀態，更新它
                    detailed_state = self._parse_thread_state(state_match.group(1))
                    if detailed_state != ThreadState.UNKNOWN:
                        thread_info.state = detailed_state
                
                # 提取 utm 和 stm
                utm_match = re.search(r'utm=(\d+)', next_line)
                stm_match = re.search(r'stm=(\d+)', next_line)
                if utm_match:
                    thread_info.utm = utm_match.group(1)
                if stm_match:
                    thread_info.stm = stm_match.group(1)
                
                # 提取 schedstat
                schedstat_match = re.search(r'schedstat=\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)', next_line)
                if schedstat_match:
                    runtime = int(schedstat_match.group(1)) / 1000000  # 轉換為毫秒
                    waittime = int(schedstat_match.group(2)) / 1000000
                    thread_info.schedstat = f"運行:{runtime:.1f}ms 等待:{waittime:.1f}ms"
                
                # 如果遇到下一個線程，停止
                if re.match(r'"[^"]+".*tid=\d+', next_line):
                    break
            
            return thread_info
        
        # 嘗試其他格式
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
            r'Native Method',
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
            
            # 檢查 parking 狀態
            if 'parking to wait for' in line:
                park_match = re.search(r'parking to wait for\s+<([^>]+)>', line)
                if park_match:
                    thread.waiting_info = f"Parking 等待: {park_match.group(1)}"
    
    def _extract_cross_process_lock_info(self, thread: ThreadInfo, lines: List[str], start_idx: int) -> None:
        """提取跨進程鎖資訊"""
        for i in range(start_idx + 1, min(start_idx + 20, len(lines))):
            line = lines[i]
            
            # 檢查跨進程等待
            cross_process_match = re.search(r'held by tid=(\d+) in process (\d+)', line)
            if cross_process_match:
                thread.waiting_info = f"等待跨進程鎖，被進程 {cross_process_match.group(2)} 的線程 {cross_process_match.group(1)} 持有"
                break
    
    def _extract_thread_cpu_time(self, thread: ThreadInfo, lines: List[str], start_idx: int) -> None:
        """提取線程 CPU 時間"""
        # 查找 schedstat 資訊
        for i in range(start_idx, min(start_idx + 5, len(lines))):
            line = lines[i]
            
            # schedstat 格式: schedstat=( 運行時間 等待時間 時間片次數 )
            schedstat_match = re.search(r'schedstat=\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)', line)
            if schedstat_match:
                thread.schedstat = f"運行:{int(schedstat_match.group(1))/1000000:.1f}ms " \
                                  f"等待:{int(schedstat_match.group(2))/1000000:.1f}ms"
            
            # utm/stm 格式
            utm_match = re.search(r'utm=(\d+)', line)
            stm_match = re.search(r'stm=(\d+)', line)
            if utm_match:
                thread.utm = utm_match.group(1)
            if stm_match:
                thread.stm = stm_match.group(1)
    
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
        
        # 查找包含 ActivityThread 的線程
        for thread in threads:
            if any('ActivityThread' in frame for frame in thread.backtrace):
                return thread
        
        return None
    
    def _extract_cpu_usage(self, content: str) -> Optional[Dict]:
        """提取 CPU 使用率資訊"""
        cpu_info = {}
        
        # 查找 CPU 使用率模式
        cpu_patterns = [
            r'CPU:\s*([\d.]+)%\s*usr\s*\+\s*([\d.]+)%\s*sys',
            r'Load:\s*([\d.]+)\s*/\s*([\d.]+)\s*/\s*([\d.]+)',
            r'cpu\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)',
        ]
        
        for pattern in cpu_patterns:
            match = re.search(pattern, content)
            if match:
                if 'usr' in pattern:
                    cpu_info['user'] = float(match.group(1))
                    cpu_info['system'] = float(match.group(2))
                    cpu_info['total'] = cpu_info['user'] + cpu_info['system']
                elif 'Load' in pattern:
                    cpu_info['load_1min'] = float(match.group(1))
                    cpu_info['load_5min'] = float(match.group(2))
                    cpu_info['load_15min'] = float(match.group(3))
                break
        
        return cpu_info if cpu_info else None
    
    def _extract_memory_info(self, content: str) -> Optional[Dict]:
        """提取記憶體資訊"""
        memory_info = {}
        
        # 查找記憶體資訊模式
        patterns = {
            'total': r'MemTotal:\s*(\d+)\s*kB',
            'free': r'MemFree:\s*(\d+)\s*kB',
            'available': r'MemAvailable:\s*(\d+)\s*kB',
            'buffers': r'Buffers:\s*(\d+)\s*kB',
            'cached': r'Cached:\s*(\d+)\s*kB',
            'swap_total': r'SwapTotal:\s*(\d+)\s*kB',
            'swap_free': r'SwapFree:\s*(\d+)\s*kB',
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                memory_info[key] = int(match.group(1))
        
        # 計算使用率
        if 'total' in memory_info and 'available' in memory_info:
            used = memory_info['total'] - memory_info['available']
            memory_info['used_percent'] = (used / memory_info['total']) * 100
        
        return memory_info if memory_info else None
    
    def _generate_report(self, anr_info: ANRInfo, content: str, intelligent_engine=None) -> str:
        """生成分析報告"""
        try:
            analyzer = ANRReportGenerator(anr_info, content, intelligent_engine)
            return analyzer.generate()
        except Exception as e:
            # 如果報告生成失敗，返回基本信息
            import traceback
            error_trace = traceback.format_exc()
            
            basic_report = [
                "🎯 ANR 分析報告",
                "=" * 60,
                f"📊 ANR 類型: {anr_info.anr_type.value}",
                f"📱 進程名稱: {anr_info.process_name}",
                f"🆔 進程 ID: {anr_info.pid}",
                "",
                "❌ 詳細分析生成失敗",
                f"錯誤信息: {str(e)}",
                "",
                "錯誤詳情:",
                error_trace,
                "",
                "基本信息:",
                f"- 線程總數: {len(anr_info.all_threads)}",
                f"- 主線程狀態: {anr_info.main_thread.state.value if anr_info.main_thread else 'Unknown'}",
            ]
            
            if anr_info.cpu_usage:
                basic_report.append(f"- CPU 使用率: {anr_info.cpu_usage.get('total', 'N/A')}%")
            
            if anr_info.memory_info:
                available_mb = anr_info.memory_info.get('available', 0) / 1024
                basic_report.append(f"- 可用記憶體: {available_mb:.1f} MB")
            
            return "\n".join(basic_report)

class ANRReportGenerator:
    """ANR 報告生成器"""
    
    def __init__(self, anr_info: ANRInfo, content: str, intelligent_engine=None, 
                 output_format: str = 'text', source_linker: Optional[SourceLinker] = None):
        self.anr_info = anr_info
        self.content = content
        self.report_lines = []
        self.intelligent_engine = intelligent_engine or IntelligentAnalysisEngine()
        self.output_format = output_format
        self.source_linker = source_linker
        
        # 如果是 HTML 格式，創建 HTML 生成器
        if output_format == 'html' and source_linker:
            self.html_generator = HTMLReportGenerator(source_linker)
    
    def generate(self) -> str:
        """生成報告"""
        try:
            if self.output_format == 'html':
                return self._generate_html_report()
            else:
                return self._generate_text_report()
        except Exception as e:
            # 確保總是返回一些內容
            error_msg = f"報告生成失敗: {str(e)}\n"
            error_msg += f"ANR 類型: {self.anr_info.anr_type.value}\n"
            error_msg += f"進程: {self.anr_info.process_name}\n"
            error_msg += f"線程數: {len(self.anr_info.all_threads)}\n"
            
            # 嘗試至少生成基本的文字報告
            try:
                self.report_lines = [error_msg]
                self._add_summary()
                self._add_basic_info()
                return "\n".join(self.report_lines)
            except:
                return error_msg

    def _generate_text_report(self) -> str:
        self._add_summary()
        self._add_basic_info()
        self._add_main_thread_analysis()
        self._add_root_cause_analysis()
        self._add_intelligent_analysis()
        self._add_thread_analysis()
        self._add_deadlock_detection()
        self._add_binder_chain_analysis()      # 新增
        self._add_thread_dependency_graph()    # 新增
        self._add_performance_bottleneck()     # 新增        
        self._add_watchdog_analysis()      # 新增
        self._add_strictmode_analysis()    # 新增
        self._add_gc_analysis()            # 新增
        self._add_performance_analysis()
        self._add_system_health_score()    # 新增
        self._add_suggestions()
        
        return "\n".join(self.report_lines)

    def _generate_html_report(self) -> str:
        """生成 HTML 報告"""
        # 生成 HTML 頭部
        html_content = f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ANR 分析報告 - {self.anr_info.process_name}</title>
    <style>
        {self._get_report_css()}
    </style>
</head>
<body>
    <div class="container">
        <header class="report-header">
            <h1>🎯 ANR 分析報告</h1>
            <div class="report-meta">
                <span class="process-name">{html.escape(self.anr_info.process_name)}</span>
                <span class="pid">PID: {self.anr_info.pid}</span>
                <span class="anr-type">{self.anr_info.anr_type.value}</span>
            </div>
        </header>
        
        <div class="report-content">
        '''

        # 添加時間線分析
        self._add_html_timeline_analysis()
        
        # 添加 AI 異常檢測
        self._add_html_anomaly_detection()
        
        # 添加風險評估
        self._add_html_risk_assessment()
        
        # 添加代碼修復建議
        self._add_html_code_fix_suggestions()
        
        # 添加執行摘要（放在最前面）
        executive_summary = self._generate_executive_summary()

        # 添加摘要
        self._add_html_summary()
        
        # 添加主線程分析
        self._add_html_main_thread_analysis()
        
        # 添加 Binder 分析
        self._add_html_binder_analysis()
        
        # 添加線程依賴圖
        self._add_html_thread_dependency()
        
        # 添加性能瓶頸
        self._add_html_performance_bottleneck()
        
        # 添加建議
        self._add_html_suggestions()
        
        html_content += self.html_generator.generate_html()
        
        html_content += '''
        </div>
        
        <footer class="report-footer">
            <p>生成時間: ''' + time.strftime('%Y-%m-%d %H:%M:%S') + '''</p>
        </footer>
    </div>
    
    <script>
        ''' + self._get_report_javascript() + '''
    </script>
</body>
</html>'''
        
        return html_content
    
    def _get_report_css(self) -> str:
        """獲取報告的 CSS 樣式"""
        return '''
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        :root {
            --primary-color: #10a37f;
            --primary-hover: #0d8f6f;
            --background: #ffffff;
            --surface: #f7f7f8;
            --border: #e5e5e5;
            --text-primary: #2d2d2d;
            --text-secondary: #666666;
            --text-muted: #999999;
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
            --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.07);
            --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
            --radius: 8px;
            --transition: all 0.2s ease;
            --anr-color: #dc3545;
            --anr-bg: #fff5f5;
            --anr-bg-hover: #fee0e0;
            --anr-border: #feb2b2;
            --tombstone-color: #6f42c1;
            --tombstone-bg: #f7f3ff;
            --tombstone-bg-hover: #ebe0ff;
            --tombstone-border: #d6bcfa;
        }
        
        @media (prefers-color-scheme: dark) {
            :root {
                --background: #1a1a1a;
                --surface: #2a2a2a;
                --border: #404040;
                --text-primary: #ffffff;
                --text-secondary: #c5c5c5;
                --text-muted: #8e8e8e;
                --anr-bg: #3a1f23;
                --anr-bg-hover: #4a2833;
                --anr-border: #9b2c2c;
                --tombstone-bg: #2d2440;
                --tombstone-bg-hover: #3d3050;
                --tombstone-border: #553c9a;
            }
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            background: var(--background);
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }
        
        /* Header */
        .header {
            padding: 40px 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 32px;
        }
        
        .header h1 {
            font-size: 32px;
            font-weight: 600;
            margin-bottom: 8px;
            color: var(--text-primary);
        }
        
        .header .subtitle {
            font-size: 16px;
            color: var(--text-secondary);
            margin-bottom: 24px;
        }
        
        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 16px;
            margin-bottom: 40px;
        }
        
        .stat-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            transition: var(--transition);
        }
        
        .stat-card:hover {
            box-shadow: var(--shadow-md);
            border-color: var(--primary-color);
        }
        
        .stat-card .label {
            font-size: 14px;
            color: var(--text-secondary);
            margin-bottom: 4px;
        }
        
        .stat-card .value {
            font-size: 28px;
            font-weight: 600;
            color: var(--primary-color);
        }
        
        /* Main Content */
        .main-content {
            margin-bottom: 40px;
        }
        
        .section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
        }
        
        .section-header h2 {
            font-size: 24px;
            font-weight: 600;
            color: var(--text-primary);
        }
        
        /* File Browser */
        .file-browser {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
        }
        
        .file-item, .folder-item {
            border-bottom: 1px solid var(--border);
            transition: var(--transition);
        }
        
        .file-item:last-child, .folder-item:last-child {
            border-bottom: none;
        }
        
        .file-item:hover {
            box-shadow: inset 0 0 0 1px var(--border);
        }
        
        /* ANR 和 Tombstone 檔案的不同顏色 - 增強版 */
        .anr-item {
            background-color: var(--anr-bg);
            border-left: 4px solid var(--anr-color);
            position: relative;
        }
        
        .anr-item::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(90deg, 
                rgba(220, 53, 69, 0.1) 0%, 
                transparent 100%);
            opacity: 0;
            transition: opacity 0.2s ease;
        }
        
        .anr-item:hover {
            background-color: var(--anr-bg-hover);
            border-left-width: 6px;
        }
        
        .anr-item:hover::before {
            opacity: 1;
        }
        
        .tombstone-item {
            background-color: var(--tombstone-bg);
            border-left: 4px solid var(--tombstone-color);
            position: relative;
        }
        
        .tombstone-item::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(90deg, 
                rgba(111, 66, 193, 0.1) 0%, 
                transparent 100%);
            opacity: 0;
            transition: opacity 0.2s ease;
        }
        
        .tombstone-item:hover {
            background-color: var(--tombstone-bg-hover);
            border-left-width: 6px;
        }
        
        .tombstone-item:hover::before {
            opacity: 1;
        }
        
        .file-content {
            padding: 16px 20px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .file-icon {
            font-size: 24px;
            flex-shrink: 0;
            filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.1));
        }
        
        .anr-item .file-icon {
            color: var(--anr-color);
        }
        
        .tombstone-item .file-icon {
            color: var(--tombstone-color);
        }
        
        .file-info {
            flex: 1;
            min-width: 0;
        }
        
        .file-name {
            font-size: 15px;
            font-weight: 500;
            color: var(--text-primary);
            text-decoration: none;
            display: block;
            margin-bottom: 4px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            transition: var(--transition);
        }
        
        .file-name:hover {
            color: var(--primary-color);
        }
        
        .file-meta {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 13px;
        }
        
        .file-type {
            padding: 3px 10px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: white;
        }
        
        .file-type-anr {
            background: var(--anr-color);
            box-shadow: 0 2px 4px rgba(220, 53, 69, 0.2);
        }
        
        .file-type-tombstone {
            background: var(--tombstone-color);
            box-shadow: 0 2px 4px rgba(111, 66, 193, 0.2);
        }
        
        .source-link {
            color: var(--text-secondary);
            text-decoration: none;
            transition: var(--transition);
        }
        
        .source-link:hover {
            color: var(--primary-color);
            text-decoration: underline;
        }
        
        /* Folder */
        .folder-header {
            padding: 16px 20px;
            display: flex;
            align-items: center;
            gap: 12px;
            cursor: pointer;
            user-select: none;
            transition: var(--transition);
        }
        
        .folder-header:hover {
            background: var(--background);
        }
        
        .folder-arrow {
            color: var(--text-secondary);
            transition: transform 0.2s ease;
            flex-shrink: 0;
        }
        
        .folder-arrow.open {
            transform: rotate(180deg);
        }
        
        .folder-icon {
            font-size: 20px;
            flex-shrink: 0;
        }
        
        .folder-name {
            font-size: 15px;
            font-weight: 500;
            color: var(--text-primary);
            flex: 1;
        }
        
        .folder-count {
            font-size: 13px;
            color: var(--text-muted);
        }
        
        .folder-content {
            background: var(--background);
            border-top: 1px solid var(--border);
            padding-left: 20px;
        }
        
        /* Features */
        .features {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 24px;
            margin-bottom: 32px;
        }
        
        .features h3 {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            color: var(--text-primary);
        }
        
        .features ul {
            list-style: none;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 12px;
        }
        
        .features li {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            font-size: 14px;
            color: var(--text-secondary);
        }
        
        .features li::before {
            content: "✓";
            color: var(--primary-color);
            font-weight: bold;
            flex-shrink: 0;
        }
        
        /* Footer */
        .footer {
            padding: 32px 0;
            border-top: 1px solid var(--border);
            text-align: center;
            color: var(--text-secondary);
            font-size: 14px;
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            .header h1 {
                font-size: 24px;
            }
            
            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            
            .features ul {
                grid-template-columns: 1fr;
            }
            
            .file-meta {
                flex-wrap: wrap;
                gap: 8px;
            }
        }
        '''

    def _get_report_javascript(self) -> str:
        """獲取報告的 JavaScript"""
        return '''
        // 處理連結點擊
        document.addEventListener('click', function(e) {
            if (e.target.classList.contains('source-link') || 
                e.target.classList.contains('frame-link')) {
                e.preventDefault();
                
                const href = e.target.getAttribute('href');
                const lineNumber = e.target.getAttribute('data-line');
                
                // 創建並顯示浮動視窗
                showSourceViewer(href, lineNumber);
            }
        });
        
        // 顯示源碼查看器
        function showSourceViewer(filePath, lineNumber) {
            // 如果已存在查看器，先移除
            const existingViewer = document.getElementById('source-viewer');
            if (existingViewer) {
                existingViewer.remove();
            }
            
            // 創建查看器
            const viewer = document.createElement('div');
            viewer.id = 'source-viewer';
            viewer.className = 'source-viewer';
            viewer.innerHTML = `
                <div class="viewer-header">
                    <span class="viewer-title">${filePath} - Line ${lineNumber}</span>
                    <button class="viewer-close" onclick="closeSourceViewer()">✕</button>
                </div>
                <div class="viewer-content">
                    <iframe src="${filePath}#L${lineNumber}" 
                            onload="scrollToLine(this, ${lineNumber})"></iframe>
                </div>
            `;
            
            document.body.appendChild(viewer);
            
            // 添加樣式
            addViewerStyles();
        }
        
        function closeSourceViewer() {
            const viewer = document.getElementById('source-viewer');
            if (viewer) {
                viewer.remove();
            }
        }
        
        function scrollToLine(iframe, lineNumber) {
            try {
                const doc = iframe.contentDocument || iframe.contentWindow.document;
                const lineElement = doc.getElementById('L' + lineNumber);
                if (lineElement) {
                    lineElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    lineElement.style.backgroundColor = '#ffffcc';
                }
            } catch (e) {
                console.error('Unable to scroll to line:', e);
            }
        }
        
        function addViewerStyles() {
            if (document.getElementById('viewer-styles')) return;
            
            const style = document.createElement('style');
            style.id = 'viewer-styles';
            style.textContent = `
                .source-viewer {
                    position: fixed;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    width: 80%;
                    height: 80%;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                    z-index: 10000;
                    display: flex;
                    flex-direction: column;
                }
                
                .viewer-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 15px 20px;
                    background: #f5f5f5;
                    border-bottom: 1px solid #ddd;
                    border-radius: 8px 8px 0 0;
                }
                
                .viewer-title {
                    font-weight: bold;
                    font-size: 16px;
                }
                
                .viewer-close {
                    background: none;
                    border: none;
                    font-size: 24px;
                    cursor: pointer;
                    color: #666;
                    padding: 0 5px;
                }
                
                .viewer-close:hover {
                    color: #333;
                }
                
                .viewer-content {
                    flex: 1;
                    overflow: hidden;
                }
                
                .viewer-content iframe {
                    width: 100%;
                    height: 100%;
                    border: none;
                }
            `;
            document.head.appendChild(style);
        }
        
        // 添加行號提示
        let tooltip = null;
        
        document.addEventListener('mouseover', function(e) {
            if (e.target.classList.contains('source-link') || 
                e.target.classList.contains('frame-link')) {
                const lineNumber = e.target.getAttribute('data-line');
                if (lineNumber) {
                    showLineTooltip(e.target, lineNumber);
                }
            }
        });
        
        document.addEventListener('mouseout', function(e) {
            if (e.target.classList.contains('source-link') || 
                e.target.classList.contains('frame-link')) {
                hideLineTooltip();
            }
        });
        
        function showLineTooltip(element, lineNumber) {
            if (!tooltip) {
                tooltip = document.createElement('div');
                tooltip.className = 'line-tooltip';
                document.body.appendChild(tooltip);
            }
            
            tooltip.textContent = `Line ${lineNumber}`;
            
            const rect = element.getBoundingClientRect();
            tooltip.style.left = rect.left + 'px';
            tooltip.style.top = (rect.top - 30) + 'px';
            
            setTimeout(() => {
                tooltip.classList.add('show');
            }, 10);
        }
        
        function hideLineTooltip() {
            if (tooltip) {
                tooltip.classList.remove('show');
            }
        }
        '''
    
    def _add_html_summary(self):
        """添加 HTML 格式的摘要"""
        severity = self._assess_severity()
        root_cause = self._quick_root_cause()
        
        severity_class = 'critical' if '極其嚴重' in severity else 'warning' if '嚴重' in severity else 'info'
        
        content = f'''
        <div class="summary-grid">
            <div class="summary-item {severity_class}">
                <h3>嚴重程度</h3>
                <p>{severity}</p>
            </div>
            <div class="summary-item">
                <h3>可能原因</h3>
                <p>{root_cause}</p>
            </div>
            <div class="summary-item">
                <h3>發生時間</h3>
                <p>{self.anr_info.timestamp or 'Unknown'}</p>
            </div>
        </div>
        '''
        
        self.html_generator.add_section('摘要', content, 'summary-section')
    
    def _add_html_main_thread_analysis(self):
        """添加 HTML 格式的主線程分析"""
        if not self.anr_info.main_thread:
            self.html_generator.add_section('主線程分析', '<p>未找到主線程資訊</p>')
            return
        
        # 添加主線程堆疊
        self.html_generator.add_backtrace(
            '主線程堆疊追蹤',
            self.anr_info.main_thread.backtrace
        )

    def _add_binder_chain_analysis(self):
        """添加 Binder 調用鏈分析"""
        self.report_lines.append("\n🔗 Binder 調用鏈詳細分析")
        
        # 創建分析器
        binder_analyzer = BinderCallChainAnalyzer()
        
        if self.anr_info.main_thread:
            chain_analysis = binder_analyzer.analyze_binder_chain(
                self.anr_info.main_thread.backtrace
            )
            
            if chain_analysis['call_sequence']:
                self.report_lines.append(f"\n📊 Binder 調用序列 (共 {len(chain_analysis['call_sequence'])} 次跨進程調用):")
                
                for i, call in enumerate(chain_analysis['call_sequence'], 1):
                    self.report_lines.append(
                        f"  {i}. {call['service']}.{call['method']} "
                        f"(預估延遲: {call['estimated_latency']}ms)"
                    )
                    if call.get('transaction_code'):
                        self.report_lines.append(f"      事務碼: {call['transaction_code']}")
                
                self.report_lines.append(f"\n⏱️ 總延遲: {chain_analysis['total_latency']}ms")
                
                if chain_analysis['bottlenecks']:
                    self.report_lines.append("\n🚫 識別的瓶頸:")
                    for bottleneck in chain_analysis['bottlenecks']:
                        self.report_lines.append(
                            f"  • {bottleneck['service']}.{bottleneck['method']} "
                            f"({bottleneck['latency']}ms)"
                        )
                        self.report_lines.append(f"    原因: {bottleneck['reason']}")
                
                if chain_analysis['recommendation']:
                    self.report_lines.append(f"\n💡 優化建議: {chain_analysis['recommendation']}")
            else:
                self.report_lines.append("  ✅ 未檢測到 Binder 調用")

    def _add_thread_dependency_graph(self):
        """添加線程依賴關係圖"""
        self.report_lines.append("\n🕸️ 線程依賴關係分析")
        
        # 創建分析器
        dependency_analyzer = ThreadDependencyAnalyzer()
        
        dep_analysis = dependency_analyzer.analyze_thread_dependencies(
            self.anr_info.all_threads
        )
        
        # 顯示 ASCII 圖
        if dep_analysis.get('visualization'):
            viz = dep_analysis['visualization']
            # 檢查是否真的包含圖形元素（如 → 或其他圖形字符）
            if any(char in viz for char in ['→', '←', '↔', '─', '│', '┌', '└', '├', '┤']):
                self.report_lines.append("\n\n線程依賴關係圖:")
                self.report_lines.append(viz)
            else:
                # 如果只是文本，直接顯示
                self.report_lines.append(viz)
                self.report_lines.append("\n\n  ℹ️ 未生成依賴關係視覺化圖表")
        else:
            # 如果沒有視覺化，顯示基本信息
            self.report_lines.append("  ℹ️ 未生成依賴關係圖")
        
        # 顯示死鎖詳情（如果有的話）- 這部分保持不變
        if dep_analysis.get('deadlock_cycles'):
            self.report_lines.append("\n🔴 死鎖詳細分析:")
            for i, cycle in enumerate(dep_analysis['deadlock_cycles'], 1):
                self.report_lines.append(f"  死鎖循環 {i}:")
                for thread_info in cycle:
                    self.report_lines.append(
                        f"    • 線程 {thread_info['tid']} ({thread_info['name']}) "
                        f"- {thread_info['state']}"
                    )
                    if thread_info.get('waiting_on'):
                        self.report_lines.append(f"      等待: {thread_info['waiting_on']}")
        else:
            self.report_lines.append("  ✅ 未檢測到死鎖")
        
        # 確保顯示阻塞鏈
        if dep_analysis.get('blocking_chains'):
            self.report_lines.append("\n🟡 主要阻塞鏈:")
            for chain in dep_analysis['blocking_chains'][:3]:
                self.report_lines.append(
                    f"  • {chain['blocker_name']} (tid={chain['blocker']}) "
                    f"阻塞了 {chain['impact']} 個線程"
                )
                self.report_lines.append(f"    嚴重性: {chain['severity']}")
        else:
            self.report_lines.append("\n  ℹ️ 未發現明顯的阻塞鏈")
        
        # 確保顯示關鍵路徑
        if dep_analysis.get('critical_paths'):
            self.report_lines.append("\n🔵 關鍵阻塞路徑:")
            for path_info in dep_analysis['critical_paths'][:3]:
                path_str = " → ".join(path_info['path'][:5])
                if len(path_info['path']) > 5:
                    path_str += f" → ... ({len(path_info['path'])-5} more)"
                self.report_lines.append(
                    f"  • {path_info['type']}: {path_str}"
                )
                self.report_lines.append(f"    嚴重性: {path_info['severity']}")
        else:
            self.report_lines.append("\n  ℹ️ 未發現關鍵阻塞路徑")

    def _add_performance_bottleneck(self):
        """添加性能瓶頸自動識別"""
        self.report_lines.append("\n🎯 性能瓶頸自動識別")
        
        # 創建檢測器
        bottleneck_detector = PerformanceBottleneckDetector()
        
        bottleneck_analysis = bottleneck_detector.detect_bottlenecks(
            self.anr_info,
            self.content
        )
        
        # 顯示整體評分
        score = bottleneck_analysis['overall_score']
        score_emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "🟠" if score >= 40 else "🔴"
        self.report_lines.append(f"\n{score_emoji} 性能評分: {score}/100")
        
        # 顯示主要問題
        if bottleneck_analysis['top_issues']:
            self.report_lines.append("\n🚨 識別的主要瓶頸:")
            for i, issue in enumerate(bottleneck_analysis['top_issues'], 1):
                severity_emoji = {
                    'critical': '🔴',
                    'high': '🟠',
                    'medium': '🟡',
                    'low': '🟢'
                }.get(issue['severity'], '⚪')
                
                self.report_lines.append(
                    f"\n  {i}. {severity_emoji} {issue['description']}"
                )
                self.report_lines.append(f"     影響: {issue['impact']}")
                
                # 顯示詳細數據
                if issue.get('gc_stats'):
                    stats = issue['gc_stats']
                    self.report_lines.append(
                        f"     GC 統計: {stats['count']} 次, "
                        f"平均 {stats['avg_pause']}ms, 最大 {stats['max_pause']}ms"
                    )
                elif issue.get('lock_analysis'):
                    analysis = issue['lock_analysis']
                    self.report_lines.append(
                        f"     鎖分析: {analysis['total_waiting']} 個等待, "
                        f"{analysis['unique_locks']} 個獨特鎖"
                    )
                
                # 顯示解決方案
                if issue.get('solutions'):
                    self.report_lines.append("     解決方案:")
                    for solution in issue['solutions'][:3]:
                        self.report_lines.append(f"       • {solution}")
        
        # 顯示總體建議
        if bottleneck_analysis['recommendations']:
            self.report_lines.append("\n📋 優化建議優先級:")
            for i, rec in enumerate(bottleneck_analysis['recommendations'], 1):
                self.report_lines.append(f"  {i}. {rec}")
                
    def _add_performance_analysis(self):
        """添加性能分析"""
        self.report_lines.append("\n⚡ 性能分析")
        
        perf_issues = []
        
        # 初始化變數
        available_mb = float('inf')  # 預設為無限大
        total_cpu = 0
        
        # 1. 線程數量分析
        thread_count = len(self.anr_info.all_threads)
        if thread_count > 200:
            perf_issues.append(f"線程數量過多: {thread_count} 個 (建議: < 100)")
            perf_issues.append("  可能原因: 線程洩漏、過度使用線程池")
        elif thread_count > 100:
            perf_issues.append(f"線程數量較多: {thread_count} 個")
        
        # 2. 調用深度分析
        if self.anr_info.main_thread and len(self.anr_info.main_thread.backtrace) > 50:
            depth = len(self.anr_info.main_thread.backtrace)
            perf_issues.append(f"主線程調用鏈過深: {depth} 層")
            perf_issues.append("  可能原因: 遞迴調用、過度的方法嵌套")
        
        # 3. Binder 線程分析
        binder_threads = [t for t in self.anr_info.all_threads if 'Binder' in t.name]
        if len(binder_threads) > 0:
            binder_busy = sum(1 for t in binder_threads if t.state != ThreadState.WAIT)
            if binder_busy == len(binder_threads):
                perf_issues.append(f"所有 Binder 線程都在忙碌 ({binder_busy}/{len(binder_threads)})")
                perf_issues.append("  可能導致 IPC 請求排隊")
        
        # 4. 鎖競爭分析
        blocked_on_locks = sum(1 for t in self.anr_info.all_threads 
                              if t.state == ThreadState.BLOCKED or t.waiting_locks)
        if blocked_on_locks > 5:
            perf_issues.append(f"大量線程在等待鎖: {blocked_on_locks} 個")
            perf_issues.append("  建議: 優化鎖的粒度，使用無鎖數據結構")
        
        # 5. 記憶體壓力對性能的影響
        if self.anr_info.memory_info:
            available_mb = self.anr_info.memory_info.get('available', float('inf')) / 1024
            if available_mb < 100:
                perf_issues.append(f"低記憶體可能影響性能: {available_mb:.1f} MB")
                perf_issues.append("  影響: 頻繁 GC、頁面交換")
        
        # 6. CPU 分析
        if self.anr_info.cpu_usage:
            total_cpu = self.anr_info.cpu_usage.get('total', 0)
            if total_cpu > 80:
                perf_issues.append(f"CPU 使用率高: {total_cpu:.1f}%")
                
                # 分析 load average
                load_1 = self.anr_info.cpu_usage.get('load_1min', 0)
                if load_1 > 4.0:
                    perf_issues.append(f"  系統負載過高: {load_1}")
        
        # 7. GC 影響分析
        gc_pause_pattern = r'paused\s+(\d+)ms'
        gc_pauses = re.findall(gc_pause_pattern, self.content)
        if gc_pauses:
            total_pause = sum(int(pause) for pause in gc_pauses)
            max_pause = max(int(pause) for pause in gc_pauses)
            if total_pause > 500:
                perf_issues.append(f"GC 暫停時間過長: 總計 {total_pause}ms, 最大 {max_pause}ms")
        
        # 8. 線程優先級分析
        high_prio_blocked = 0
        for thread in self.anr_info.all_threads:
            if thread.prio and thread.prio.isdigit() and int(thread.prio) <= 5:
                if thread.state == ThreadState.BLOCKED or thread.waiting_locks:
                    high_prio_blocked += 1
        
        if high_prio_blocked > 0:
            perf_issues.append(f"高優先級線程被阻塞: {high_prio_blocked} 個")
            perf_issues.append("  可能存在優先級反轉問題")
        
        # 顯示結果
        if perf_issues:
            self.report_lines.extend(f"  • {issue}" for issue in perf_issues)
        else:
            self.report_lines.append("  ✅ 未發現明顯性能問題")
        
        # 性能評分
        perf_score = 100
        perf_score -= min(thread_count // 50, 20)  # 線程數扣分
        perf_score -= min(blocked_on_locks * 2, 20)  # 鎖競爭扣分
        if available_mb < 100:
            perf_score -= 20  # 記憶體扣分
        if total_cpu > 90:
            perf_score -= 20  # CPU 扣分
        
        perf_score = max(perf_score, 0)
        
        self.report_lines.append(f"\n  性能評分: {perf_score}/100")
        if perf_score < 60:
            self.report_lines.append("  ⚠️ 性能問題需要立即處理")
    
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
        
        # 預防措施
        self.report_lines.append("\n🛡️ 預防措施:")
        prevention_suggestions = [
            "定期使用 Android Studio Profiler 監控應用性能",
            "在開發階段啟用 StrictMode 檢測違規操作",
            "實施 CI/CD 中的性能測試",
            "監控生產環境的 ANR 率 (目標 < 0.47%)",
            "建立 ANR 預警機制和自動化分析",
        ]
        
        for i, suggestion in enumerate(prevention_suggestions, 1):
            self.report_lines.append(f"  {i}. {suggestion}")
        
        # 工具推薦
        self.report_lines.append("\n🔨 推薦工具:")
        tools = [
            "Systrace - 系統級性能分析",
            "Method Tracing - 方法級性能分析",
            "Android Studio Profiler - CPU、記憶體、網路分析",
            "Firebase Performance Monitoring - 生產環境監控",
            "Perfetto - 新一代追蹤工具",
        ]
        
        for tool in tools:
            self.report_lines.append(f"  • {tool}")
        
        # 相關文檔
        self.report_lines.append("\n📚 相關文檔:")
        docs = [
            "Android 官方 ANR 文檔: https://developer.android.com/topic/performance/vitals/anr",
            "Thread 和 Process 指南: https://developer.android.com/guide/components/processes-and-threads",
            "性能優化最佳實踐: https://developer.android.com/topic/performance/",
        ]
        
        for doc in docs:
            self.report_lines.append(f"  • {doc}")

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
        
        # 顯示超時資訊
        if hasattr(self.anr_info, 'timeout_info') and self.anr_info.timeout_info:
            timeout_info = self.anr_info.timeout_info
            if timeout_info.get('wait_time'):
                self.report_lines.append(
                    f"⏱️ 等待時間: {timeout_info['wait_time']}ms "
                    f"(閾值: {timeout_info.get('timeout_threshold', 'N/A')}ms)"
                )
        
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
        elif any(svc in self.anr_info.process_name for svc in 
                ['launcher', 'systemui', 'phone', 'bluetooth']):
            score += 2
        
        # 檢查阻塞線程數量
        blocked_count = sum(1 for t in self.anr_info.all_threads if t.state == ThreadState.BLOCKED)
        score += min(blocked_count // 3, 3)
        
        # 檢查 CPU 使用率
        if self.anr_info.cpu_usage and self.anr_info.cpu_usage.get('total', 0) > 90:
            score += 2
        
        # 檢查記憶體壓力
        if self.anr_info.memory_info:
            available = self.anr_info.memory_info.get('available', float('inf'))
            if available < 50 * 1024:  # 小於 50MB
                score += 3
            elif available < 100 * 1024:  # 小於 100MB
                score += 2
        
        # 檢查主線程狀態
        if self.anr_info.main_thread:
            if self.anr_info.main_thread.state == ThreadState.BLOCKED:
                score += 2
            elif self.anr_info.main_thread.waiting_locks:
                score += 1
        
        # 檢查是否有 Watchdog
        if any(re.search(pattern, self.content) for pattern in 
               ['Watchdog', 'WATCHDOG', 'watchdog']):
            score += 3
        
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
            # 檢查主線程堆疊前5幀
            for i, frame in enumerate(self.anr_info.main_thread.backtrace[:5]):
                frame_lower = frame.lower()
                
                # Binder IPC
                if any(keyword in frame for keyword in ['BinderProxy', 'Binder.transact']):
                    service = self._identify_binder_service(self.anr_info.main_thread.backtrace[i:i+5])
                    if service:
                        causes.append(f"Binder IPC 阻塞 ({service})")
                    else:
                        causes.append("Binder IPC 阻塞")
                    break
                    
                # 同步鎖
                elif any(keyword in frame_lower for keyword in ['synchronized', 'lock', 'monitor']):
                    causes.append("同步鎖等待")
                    break
                    
                # 網路操作
                elif any(keyword in frame for keyword in ['Socket', 'Http', 'Network', 'URL']):
                    causes.append("網路操作阻塞")
                    break
                    
                # I/O 操作
                elif any(keyword in frame for keyword in ['File', 'read', 'write', 'SQLite']):
                    causes.append("I/O 操作阻塞")
                    break
                    
                # 休眠
                elif 'sleep' in frame_lower:
                    causes.append("主線程休眠")
                    break
                    
                # SharedPreferences
                elif 'SharedPreferences' in frame and 'commit' in frame:
                    causes.append("SharedPreferences.commit() 阻塞")
                    break
                    
                # ContentProvider
                elif 'ContentResolver' in frame or 'ContentProvider' in frame:
                    causes.append("ContentProvider 操作阻塞")
                    break
        
        # 檢查死鎖
        if self._has_deadlock():
            causes.append("可能存在死鎖")
        
        # 檢查 CPU
        if self.anr_info.cpu_usage and self.anr_info.cpu_usage.get('total', 0) > 90:
            causes.append("CPU 使用率過高")
        
        # 檢查記憶體
        if self.anr_info.memory_info:
            available = self.anr_info.memory_info.get('available', float('inf'))
            if available < 100 * 1024:
                causes.append("記憶體嚴重不足")
        
        # 檢查線程數
        if len(self.anr_info.all_threads) > 150:
            causes.append("線程數過多")
        
        # 基於 ANR 類型
        if self.anr_info.anr_type == ANRType.INPUT_DISPATCHING:
            if not causes:
                causes.append("主線程無響應")
        elif self.anr_info.anr_type == ANRType.SERVICE:
            if not causes:
                causes.append("Service 生命週期方法超時")
        elif self.anr_info.anr_type == ANRType.BROADCAST:
            if not causes:
                causes.append("BroadcastReceiver.onReceive 超時")
        
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
        
        # 添加超時詳情
        if hasattr(self.anr_info, 'timeout_info') and self.anr_info.timeout_info:
            timeout_info = self.anr_info.timeout_info
            if timeout_info.get('wait_time') and timeout_info.get('timeout_threshold'):
                ratio = timeout_info['wait_time'] / timeout_info['timeout_threshold']
                self.report_lines.append(
                    f"⏱️ 超時詳情: 等待了 {timeout_info['wait_time']}ms "
                    f"(超過閾值 {ratio:.1f} 倍)"
                )
        
        # 添加進程詳情
        self.report_lines.append(f"\n📱 進程詳情:")
        self.report_lines.append(f"  • 進程名: {self.anr_info.process_name}")
        self.report_lines.append(f"  • PID: {self.anr_info.pid}")
        if self.anr_info.timestamp:
            self.report_lines.append(f"  • 時間: {self.anr_info.timestamp}")
    
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
        
 
    def _add_intelligent_analysis(self):
        """添加智能分析 - 問題來龍去脈"""
        self.report_lines.append("\n🧠 智能分析 - 問題來龍去脈")
        
        # 分析調用鏈
        if self.anr_info.main_thread:
            call_chain = self.intelligent_engine.analyze_call_chain(
                self.anr_info.main_thread.backtrace
            )
            
            # 顯示調用流程
            if call_chain['call_flow']:
                self.report_lines.append("\n📊 調用流程分析:")
                for i, flow in enumerate(call_chain['call_flow']):
                    indent = "  " * (i + 1)
                    marker = "→" if i < len(call_chain['call_flow']) - 1 else "✘"
                    self.report_lines.append(
                        f"{indent}{marker} {flow['type']}: {flow['detail']}"
                    )
                    if 'target' in flow:
                        self.report_lines.append(f"{indent}  目標: {flow['target']}")
                    if 'method' in flow:
                        self.report_lines.append(f"{indent}  方法: {flow['method']}")
            
            # 顯示阻塞點
            if call_chain['blocking_points']:
                self.report_lines.append("\n🚫 識別的阻塞點:")
                for point in call_chain['blocking_points']:
                    self.report_lines.append(
                        f"  • 第 {point['level']} 層: {point['description']} "
                        f"[{point['type']}]"
                    )
            
            # 顯示服務交互
            if call_chain['service_interactions']:
                self.report_lines.append("\n🔄 服務交互鏈:")
                for interaction in call_chain['service_interactions']:
                    self.report_lines.append(
                        f"  • {interaction['from']} → {interaction['to']} "
                        f"({interaction['type']})"
                    )
        
        # 匹配已知模式
        known_patterns = self.intelligent_engine.match_known_patterns(self.anr_info)
        if known_patterns:
            self.report_lines.append("\n🎯 匹配的已知問題模式:")
            for pattern in known_patterns[:3]:
                # 處理兩種不同的模式格式
                if 'root_cause' in pattern:
                    # analysis_patterns 格式
                    self.report_lines.append(
                        f"\n  📌 {pattern['root_cause']} "
                        f"(信心度: {pattern['confidence']*100:.0f}%)"
                    )
                    self.report_lines.append(f"     嚴重性: {pattern.get('severity', '未知')}")
                    self.report_lines.append("     解決方案:")
                    solutions = pattern.get('solutions', [])
                    for solution in solutions:
                        self.report_lines.append(f"       • {solution}")
                else:
                    # known_issues_db 格式
                    self.report_lines.append(
                        f"\n  📌 {pattern.get('description', '已知問題')} "
                        f"(信心度: {pattern['confidence']*100:.0f}%)"
                    )
                    if 'workarounds' in pattern:
                        self.report_lines.append("     處理方法:")
                        for workaround in pattern['workarounds']:
                            self.report_lines.append(f"       • {workaround}")
        
        # 時序分析
        self._add_timeline_analysis()
    
    def _add_timeline_analysis(self):
        """添加通用的時序分析"""
        self.report_lines.append("\n⏱️ 事件時序分析:")
        
        events = []
        
        # 基於 ANR 類型構建時序
        if self.anr_info.anr_type == ANRType.INPUT_DISPATCHING:
            events.append("1. 用戶觸發輸入事件（觸摸/按鍵）")
            events.append("2. InputDispatcher 嘗試分發事件到應用")
            events.append("3. 應用主線程無響應")
            events.append("4. 等待超過 5 秒")
            events.append("5. 系統觸發 ANR")
        elif self.anr_info.anr_type == ANRType.SERVICE:
            events.append("1. Service 接收到啟動/綁定請求")
            events.append("2. onCreate/onStartCommand 開始執行")
            events.append("3. 主線程被阻塞")
            timeout = ANRTimeouts.SERVICE_TIMEOUT if hasattr(self.anr_info, 'timeout_info') and self.anr_info.timeout_info.get('is_foreground') else ANRTimeouts.SERVICE_BACKGROUND_TIMEOUT
            events.append(f"4. 超過 {timeout/1000} 秒未完成")
            events.append("5. 系統觸發 ANR")
        elif self.anr_info.anr_type == ANRType.BROADCAST:
            events.append("1. 系統/應用發送廣播")
            events.append("2. BroadcastReceiver.onReceive 開始執行")
            events.append("3. 處理時間過長")
            timeout = ANRTimeouts.BROADCAST_TIMEOUT if hasattr(self.anr_info, 'timeout_info') and self.anr_info.timeout_info.get('is_foreground') else ANRTimeouts.BROADCAST_BACKGROUND_TIMEOUT
            events.append(f"4. 超過 {timeout/1000} 秒未完成")
            events.append("5. 系統觸發 ANR")
        
        # 基於堆疊分析補充事件
        if self.anr_info.main_thread:
            for i, frame in enumerate(self.anr_info.main_thread.backtrace[:5]):
                if 'Binder' in frame:
                    events.insert(3, f"  → 第 {i} 層: 進行 Binder IPC 調用")
                elif 'wait' in frame.lower() or 'lock' in frame.lower():
                    events.insert(3, f"  → 第 {i} 層: 線程等待/鎖競爭")
                elif any(io in frame for io in ['File', 'SQLite', 'Socket']):
                    events.insert(3, f"  → 第 {i} 層: I/O 操作")
        
        for event in events:
            self.report_lines.append(f"  {event}")
    
    def _add_watchdog_analysis(self):
        """添加 Watchdog 分析"""
        watchdog_info = self.intelligent_engine._detect_watchdog_timeout(self.content)
        if watchdog_info:
            self.report_lines.append("\n⚠️ Watchdog 檢測")
            self.report_lines.append(f"  類型: {watchdog_info['type']}")
            self.report_lines.append(f"  嚴重性: {watchdog_info['severity']}")
            self.report_lines.append(f"  說明: {watchdog_info['description']}")
            self.report_lines.append("  建議:")
            self.report_lines.append("    • 檢查 system_server 是否有死鎖")
            self.report_lines.append("    • 分析系統服務的 CPU 和記憶體使用")
            self.report_lines.append("    • 查看 /data/anr/traces.txt 獲取完整資訊")
    
    def _add_strictmode_analysis(self):
        """添加 StrictMode 違規分析"""
        violations = self.intelligent_engine._detect_strictmode_violations(self.content)
        if violations:
            self.report_lines.append("\n🚫 StrictMode 違規檢測")
            for violation in violations:
                self.report_lines.append(f"  • {violation['type']}: {violation['description']}")
                self.report_lines.append(f"    建議: {violation['suggestion']}")
    
    def _add_gc_analysis(self):
        """添加 GC 分析"""
        gc_info = self.intelligent_engine._analyze_gc_impact(self.content)
        if gc_info['gc_count'] > 0:
            self.report_lines.append("\n♻️ 垃圾回收分析")
            self.report_lines.append(f"  • GC 次數: {gc_info['gc_count']}")
            self.report_lines.append(f"  • 總暫停時間: {gc_info['total_pause_time']}ms")
            self.report_lines.append(f"  • 影響評估: {gc_info['impact']}")
            
            if gc_info['impact'] in ['high', 'medium']:
                self.report_lines.append("  建議:")
                self.report_lines.append("    • 優化記憶體分配策略")
                self.report_lines.append("    • 避免創建大量臨時對象")
                self.report_lines.append("    • 使用對象池重用對象")
    
    def _add_system_health_score(self):
        """添加系統健康度評分"""
        health_score = self.intelligent_engine._calculate_system_health_score(self.anr_info)
        
        # 儲存健康分數供其他方法使用
        self._last_health_score = health_score['score']
        
        self.report_lines.append("\n🏥 系統健康度評估")
        
        # 使用圖形化顯示分數
        score = health_score['score']
        if score >= 80:
            score_display = f"🟢 {score}/100 (健康)"
        elif score >= 60:
            score_display = f"🟡 {score}/100 (一般)"
        elif score >= 40:
            score_display = f"🟠 {score}/100 (較差)"
        else:
            score_display = f"🔴 {score}/100 (嚴重)"
        
        self.report_lines.append(f"  總分: {score_display}")
        
        if health_score['factors']:
            self.report_lines.append("  扣分因素:")
            for factor in health_score['factors']:
                self.report_lines.append(f"    • {factor}")
        
        if 'recommendation' in health_score:
            self.report_lines.append(f"  建議: {health_score['recommendation']}")
    
    def _add_thread_analysis(self):
        """添加線程分析 - 增強版"""
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
                
                # 新增：顯示 Crashlytics 風格標籤
                tags = self.intelligent_engine._identify_crashlytics_tags(thread)
                if tags:
                    self.report_lines.append(f"    標籤: {', '.join(tags)}")

    def _summarize_thread(self, thread: ThreadInfo) -> str:
        """總結線程資訊"""
        summary_parts = [f"{thread.name} (tid={thread.tid}"]
        
        # 添加系統線程 ID
        if thread.sysTid:
            summary_parts.append(f"sysTid={thread.sysTid}")
        
        # 添加優先級
        if thread.prio and thread.prio != "N/A":
            summary_parts.append(f"prio={thread.prio}")
        
        # 添加狀態
        summary_parts.append(f"{thread.state.value})")
        
        summary = ", ".join(summary_parts)
        
        # 添加額外資訊
        extra_info = []
        
        if thread.waiting_info:
            extra_info.append(thread.waiting_info)
        elif thread.waiting_locks:
            if len(thread.waiting_locks) == 1:
                extra_info.append(f"等待鎖: {thread.waiting_locks[0]}")
            else:
                extra_info.append(f"等待 {len(thread.waiting_locks)} 個鎖")
        elif thread.held_locks:
            if len(thread.held_locks) == 1:
                extra_info.append(f"持有鎖: {thread.held_locks[0]}")
            else:
                extra_info.append(f"持有 {len(thread.held_locks)} 個鎖")
        
        # 添加 CPU 時間資訊
        if thread.schedstat:
            extra_info.append(thread.schedstat)
        elif thread.utm and thread.stm:
            utm_ms = int(thread.utm) * 10  # jiffies to ms (假設 HZ=100)
            stm_ms = int(thread.stm) * 10
            extra_info.append(f"CPU: usr={utm_ms}ms sys={stm_ms}ms")
        
        # 檢查是否在執行特定操作
        if thread.backtrace:
            for frame in thread.backtrace[:3]:
                if 'sleep' in frame.lower():
                    extra_info.append("🛌 休眠中")
                    break
                elif 'wait' in frame.lower() or 'park' in frame.lower():
                    extra_info.append("⏰ 等待中")
                    break
                elif any(io in frame for io in ['File', 'SQLite', 'Socket']):
                    extra_info.append("💾 I/O 操作")
                    break
                elif 'Binder' in frame:
                    extra_info.append("🔗 Binder IPC")
                    break
        
        if extra_info:
            summary += " - " + ", ".join(extra_info)
        
        return summary
        
    def _get_important_threads(self) -> List[ThreadInfo]:
            """獲取重要線程"""
            important = []
            seen_threads = set()
            
            # 1. 主線程總是重要的
            if self.anr_info.main_thread:
                important.append(self.anr_info.main_thread)
                seen_threads.add(self.anr_info.main_thread.tid)
            
            # 2. 阻塞的線程
            blocked_threads = []
            for thread in self.anr_info.all_threads:
                if thread.tid not in seen_threads and thread.state == ThreadState.BLOCKED:
                    blocked_threads.append(thread)
            
            # 按優先級排序阻塞的線程
            blocked_threads.sort(key=lambda t: int(t.prio) if t.prio.isdigit() else 999)
            important.extend(blocked_threads[:5])
            seen_threads.update(t.tid for t in blocked_threads[:5])
            
            # 3. 等待鎖的線程
            waiting_threads = []
            for thread in self.anr_info.all_threads:
                if thread.tid not in seen_threads and thread.waiting_locks:
                    waiting_threads.append(thread)
            
            important.extend(waiting_threads[:5])
            seen_threads.update(t.tid for t in waiting_threads[:5])
            
            # 4. 系統關鍵線程
            critical_thread_names = [
                'Binder:', 'FinalizerDaemon', 'FinalizerWatchdogDaemon',
                'ReferenceQueueDaemon', 'HeapTaskDaemon', 'RenderThread',
                'UI Thread', 'AsyncTask', 'OkHttp', 'grpc', 'Retrofit'
            ]
            
            for thread in self.anr_info.all_threads:
                if thread.tid not in seen_threads:
                    for critical_name in critical_thread_names:
                        if critical_name in thread.name:
                            important.append(thread)
                            seen_threads.add(thread.tid)
                            break
            
            # 5. 執行 Binder 調用的線程
            binder_threads = []
            for thread in self.anr_info.all_threads:
                if thread.tid not in seen_threads:
                    if any('Binder' in frame for frame in thread.backtrace[:3]):
                        binder_threads.append(thread)
            
            important.extend(binder_threads[:3])
            seen_threads.update(t.tid for t in binder_threads[:3])
            
            # 6. Native 狀態的線程（可能在執行 JNI）
            native_threads = []
            for thread in self.anr_info.all_threads:
                if thread.tid not in seen_threads and thread.state == ThreadState.NATIVE:
                    native_threads.append(thread)
            
            important.extend(native_threads[:3])
            
            return important[:20]  # 最多返回20個重要線程
    
    def _get_thread_statistics(self) -> Dict[str, int]:
        """獲取線程統計"""
        stats = {}
        
        for thread in self.anr_info.all_threads:
            state_name = thread.state.value
            stats[state_name] = stats.get(state_name, 0) + 1
        
        # 按數量排序
        sorted_stats = dict(sorted(stats.items(), key=lambda x: x[1], reverse=True))
        
        return sorted_stats
        
    def _add_deadlock_detection(self):
        """添加死鎖檢測 - 增強版"""
        # 使用增強的死鎖檢測
        deadlock_info = self.intelligent_engine._detect_complex_deadlock(self.anr_info.all_threads)
        
        if deadlock_info['has_deadlock']:
            self.report_lines.append("\n💀 死鎖檢測")
            
            if deadlock_info['cross_process']:
                self.report_lines.append("  ⚠️ 檢測到跨進程死鎖!")
            
            if deadlock_info['cycles']:
                for i, cycle in enumerate(deadlock_info['cycles'], 1):
                    self.report_lines.append(f"  死鎖循環 {i}:")
                    for thread_info in cycle:
                        self.report_lines.append(f"    • {thread_info}")
    
    def _generate_suggestions(self) -> Dict[str, List[str]]:
        """生成建議 - 增強版"""
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
                    suggestions['immediate'].append("將 I/O 操作移至背景線程 (使用 Kotlin 協程或 ExecutorService)")
                elif any(keyword in frame for keyword in ['Http', 'Socket', 'URL']):
                    suggestions['immediate'].append("將網路請求移至背景線程")
                elif 'synchronized' in frame:
                    suggestions['optimization'].append("檢查同步鎖的使用，考慮使用無鎖數據結構或 ReadWriteLock")
        
        # 基於 ANR 類型
        if self.anr_info.anr_type == ANRType.INPUT_DISPATCHING:
            suggestions['immediate'].append("檢查 UI 線程是否有耗時操作")
            suggestions['optimization'].append("使用 Systrace 分析 UI 性能")
            suggestions['optimization'].append("考慮使用 Choreographer 監控幀率")
        elif self.anr_info.anr_type == ANRType.SERVICE:
            suggestions['immediate'].append("Service 的 onStartCommand 應快速返回")
            suggestions['optimization'].append("考慮使用 JobIntentService 或 WorkManager")
            suggestions['investigation'].append("檢查是否需要前台服務")
        elif self.anr_info.anr_type == ANRType.BROADCAST:
            suggestions['immediate'].append("BroadcastReceiver 的 onReceive 應在 10 秒內完成")
            suggestions['optimization'].append("使用 goAsync() 處理耗時操作")
            suggestions['optimization'].append("考慮使用 LocalBroadcastManager 減少開銷")
        
        # 基於問題類型
        if self._has_deadlock():
            suggestions['immediate'].append("重新設計鎖的獲取順序，避免循環等待")
            suggestions['investigation'].append("使用 Android Studio 的 CPU Profiler 分析死鎖")
            suggestions['optimization'].append("考慮使用 java.util.concurrent 包中的高級同步工具")
        
        if any('Binder' in frame for frame in (self.anr_info.main_thread.backtrace[:5] if self.anr_info.main_thread else [])):
            suggestions['investigation'].append("檢查 system_server 的健康狀態")
            suggestions['investigation'].append("使用 'dumpsys activity' 查看系統狀態")
            suggestions['optimization'].append("考慮使用異步 Binder 調用 (oneway)")
        
        # 基於系統健康度
        if hasattr(self, '_last_health_score') and self._last_health_score < 60:
            suggestions['immediate'].append("系統資源緊張，考慮優化應用記憶體使用")
            suggestions['optimization'].append("實施記憶體快取策略")
        
        # 通用建議
        suggestions['investigation'].extend([
            "收集更多 ANR traces 確認問題重現性",
            "使用 Android Studio Profiler 分析 CPU 和記憶體使用",
            "檢查相關時間段的 logcat (特別是 system_server)",
            "開啟 StrictMode 檢測潛在問題",
        ])
        
        suggestions['optimization'].extend([
            "使用 Kotlin Coroutines 或 RxJava 處理異步操作",
            "實施適當的線程池管理 (避免創建過多線程)",
            "考慮使用 Android Jetpack 的 WorkManager",
            "定期 review 主線程的所有操作",
        ])
        
        return suggestions

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
                    
                    # 嘗試識別目標服務
                    service = self._identify_binder_service(self.anr_info.main_thread.backtrace[:10])
                    if service:
                        issues.append(f"目標服務: {service}")
                    
                    break
            
            # 檢查其他線程的 Binder 狀態
            binder_waiting_threads = 0
            for thread in self.anr_info.all_threads:
                if thread != self.anr_info.main_thread:
                    for frame in thread.backtrace[:5]:
                        if 'Binder' in frame:
                            binder_waiting_threads += 1
                            break
            
            if binder_waiting_threads > 3:
                issues.append(f"發現 {binder_waiting_threads} 個線程在等待 Binder 調用")
                issues.append("可能存在 Binder 線程池耗盡問題")
            
            return issues
        
    def _analyze_lock_issues(self) -> List[str]:
        """分析鎖問題"""
        issues = []
        
        # 統計阻塞線程
        blocked_threads = [t for t in self.anr_info.all_threads if t.state == ThreadState.BLOCKED]
        if len(blocked_threads) > 3:
            issues.append(f"發現 {len(blocked_threads)} 個線程處於 BLOCKED 狀態")
            issues.append("可能存在嚴重的鎖競爭")
            
            # 列出前3個阻塞的線程
            for thread in blocked_threads[:3]:
                if thread.waiting_info:
                    issues.append(f"  - {thread.name}: {thread.waiting_info}")
        
        # 檢查死鎖
        if self._has_deadlock():
            issues.append("⚠️ 檢測到可能的死鎖情況")
            
            # 找出死鎖線程
            deadlock_info = self._find_deadlock_threads()
            if deadlock_info:
                issues.extend(deadlock_info)
        
        # 檢查主線程是否持有鎖
        if self.anr_info.main_thread and self.anr_info.main_thread.held_locks:
            issues.append(f"主線程持有 {len(self.anr_info.main_thread.held_locks)} 個鎖")
            for lock in self.anr_info.main_thread.held_locks[:3]:
                issues.append(f"  - {lock}")
        
        return issues
    
    def _analyze_io_issues(self) -> List[str]:
        """分析 I/O 問題"""
        issues = []
        
        if not self.anr_info.main_thread:
            return issues
        
        io_keywords = [
            ('File', '文件'),
            ('read', '讀取'),
            ('write', '寫入'),
            ('SQLite', '資料庫'),
            ('database', '資料庫'),
            ('SharedPreferences', '偏好設定'),
            ('ContentResolver', 'ContentProvider'),
            ('AssetManager', 'Asset 資源'),
        ]
        
        for frame in self.anr_info.main_thread.backtrace[:10]:
            for keyword, desc in io_keywords:
                if keyword in frame:
                    issues.append(f"主線程正在執行 {desc} 相關的 I/O 操作")
                    issues.append("建議將 I/O 操作移至背景線程")
                    
                    # 特定建議
                    if 'SharedPreferences' in frame:
                        issues.append("考慮使用 apply() 而非 commit()")
                    elif 'SQLite' in frame or 'database' in frame:
                        issues.append("使用 AsyncQueryHandler 或 Room 的異步 API")
                    
                    return issues
        
        # 檢查網路 I/O
        network_keywords = ['Socket', 'Http', 'URL', 'Network', 'Download', 'Upload']
        for frame in self.anr_info.main_thread.backtrace[:10]:
            for keyword in network_keywords:
                if keyword in frame:
                    issues.append("主線程正在執行網路操作")
                    issues.append("嚴重違反 Android 最佳實踐")
                    issues.append("使用 Retrofit、OkHttp 或 Volley 的異步 API")
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
                issues.append("可能原因: 無限循環、過度計算、頻繁 GC")
            elif total_cpu > 70:
                issues.append(f"CPU 使用率較高: {total_cpu:.1f}%")
            
            # 檢查負載
            load_1min = self.anr_info.cpu_usage.get('load_1min', 0)
            if load_1min > 4.0:
                issues.append(f"系統負載過高: {load_1min}")
        
        # 記憶體分析
        if self.anr_info.memory_info:
            if 'available' in self.anr_info.memory_info:
                available_mb = self.anr_info.memory_info['available'] / 1024
                if available_mb < 100:
                    issues.append(f"可用記憶體嚴重不足: {available_mb:.1f} MB")
                    issues.append("可能觸發頻繁的 GC 和記憶體壓縮")
                elif available_mb < 200:
                    issues.append(f"可用記憶體較低: {available_mb:.1f} MB")
            
            # 檢查記憶體使用率
            if 'used_percent' in self.anr_info.memory_info:
                used_percent = self.anr_info.memory_info['used_percent']
                if used_percent > 90:
                    issues.append(f"記憶體使用率過高: {used_percent:.1f}%")
        
        # GC 分析
        gc_count = self.content.count('GC_')
        if gc_count > 10:
            issues.append(f"頻繁的垃圾回收: {gc_count} 次")
            issues.append("建議優化記憶體分配策略")
        elif gc_count > 5:
            issues.append(f"垃圾回收較多: {gc_count} 次")
        
        # 檢查 OutOfMemoryError
        if "OutOfMemoryError" in self.content:
            issues.append("檢測到記憶體不足錯誤 (OutOfMemoryError)")
            issues.append("應用可能存在記憶體洩漏")
        
        # 檢查系統負載
        if "load average" in self.content:
            load_match = re.search(r'load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', self.content)
            if load_match:
                load1 = float(load_match.group(1))
                load5 = float(load_match.group(2))
                load15 = float(load_match.group(3))
                if load1 > 8.0:
                    issues.append(f"系統負載極高: 1分鐘平均 {load1}")
                elif load1 > 4.0:
                    issues.append(f"系統負載過高: 1分鐘平均 {load1}")
        
        # 線程數分析
        thread_count = len(self.anr_info.all_threads)
        if thread_count > 200:
            issues.append(f"線程數量過多: {thread_count} 個")
            issues.append("可能存在線程洩漏")
        elif thread_count > 100:
            issues.append(f"線程數量較多: {thread_count} 個")
        
        return issues
    
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
        visited = set()
        cycles_found = set()
        
        for start_tid in waiting_graph:
            if start_tid in visited:
                continue
            
            current = start_tid
            path = [current]
            
            while current in waiting_graph:
                current = waiting_graph[current]
                if current in path:
                    # 找到循環
                    cycle_start = path.index(current)
                    cycle = path[cycle_start:]
                    cycle_key = tuple(sorted(cycle))
                    
                    if cycle_key not in cycles_found:
                        cycles_found.add(cycle_key)
                        
                        cycle_info = []
                        for tid in cycle:
                            if tid in thread_map:
                                thread = thread_map[tid]
                                cycle_info.append(f"{thread.name} (tid={tid})")
                        
                        info.append(f"死鎖循環: {' -> '.join(cycle_info)} -> {cycle_info[0]}")
                    break
                    
                path.append(current)
            
            visited.update(path)
        
        return info
    
    def _identify_binder_service(self, frames: List[str]) -> Optional[str]:
        """識別 Binder 目標服務"""
        # 擴展服務識別規則
        service_patterns = {
            'WindowManager': [
                'getWindowInsets', 'addWindow', 'removeWindow', 'updateViewLayout',
                'WindowManagerService', 'WindowManager$', 'IWindowManager',
                'ViewRootImpl', 'relayoutWindow', 'WindowSession'
            ],
            'ActivityManager': [
                'startActivity', 'bindService', 'getRunningTasks', 'getServices',
                'ActivityManagerService', 'ActivityManager$', 'IActivityManager',
                'broadcastIntent', 'startService', 'stopService'
            ],
            'PackageManager': [
                'getPackageInfo', 'queryIntentActivities', 'getApplicationInfo',
                'PackageManagerService', 'PackageManager$', 'IPackageManager',
                'getInstalledPackages', 'resolveActivity'
            ],
            'PowerManager': [
                'isScreenOn', 'goToSleep', 'wakeUp', 'PowerManagerService',
                'PowerManager$', 'IPowerManager', 'acquire', 'release'
            ],
            'InputManager': [
                'injectInputEvent', 'getInputDevice', 'InputManagerService',
                'InputManager$', 'IInputManager', 'InputMethodManager'
            ],
            'NotificationManager': [
                'notify', 'cancel', 'NotificationManagerService',
                'NotificationManager$', 'INotificationManager', 'enqueueNotification'
            ],
            'AudioManager': [
                'setStreamVolume', 'AudioService', 'AudioManager$', 'IAudioService',
                'playSoundEffect', 'setRingerMode'
            ],
            'TelephonyManager': [
                'getDeviceId', 'getNetworkType', 'TelephonyRegistry',
                'TelephonyManager$', 'ITelephony', 'getPhoneType'
            ],
            'LocationManager': [
                'getLastKnownLocation', 'requestLocationUpdates',
                'LocationManagerService', 'ILocationManager', 'removeUpdates'
            ],
            'SensorManager': [
                'registerListener', 'SensorService', 'ISensorService',
                'unregisterListener', 'getDefaultSensor'
            ],
            'ConnectivityManager': [
                'getActiveNetworkInfo', 'ConnectivityService', 'IConnectivityManager',
                'requestNetwork', 'getNetworkCapabilities'
            ],
            'WifiManager': [
                'getWifiState', 'WifiService', 'IWifiManager',
                'startScan', 'getConnectionInfo'
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

    def _add_html_timeline_analysis(self):
        """添加 HTML 格式的時間線分析"""
        # 延遲導入避免循環引入
        from vp_analyze_logs_ext import TimelineAnalyzer, VisualizationGenerator
        
        timeline_analyzer = TimelineAnalyzer()
        timeline_data = timeline_analyzer.analyze_timeline(self.content, self.anr_info)
        
        # 生成時間線視覺化
        viz_generator = VisualizationGenerator()
        timeline_viz = viz_generator.generate_timeline_visualization(timeline_data)
        
        content = f'''
        <div class="timeline-analysis">
            <h3>事件時間線分析</h3>
            {timeline_viz}
            
            <div class="timeline-findings">
                <h4>關鍵發現</h4>
                <ul>
                    {''.join(f"<li>{rec}</li>" for rec in timeline_data.get('recommendations', []))}
                </ul>
            </div>
            
            <div class="critical-period">
                <h4>關鍵時期</h4>
                {self._format_critical_period(timeline_data.get('critical_period'))}
            </div>
        </div>
        '''
        
        self.html_generator.add_section('時間線分析', content, 'timeline-section')

    def _add_html_anomaly_detection(self):
        """添加 HTML 格式的異常檢測"""
        from vp_analyze_logs_ext import MLAnomalyDetector
        
        detector = MLAnomalyDetector()
        anomalies = detector.detect_anomalies(self.anr_info)
        
        if anomalies:
            anomaly_html = '''
            <div class="anomaly-list">
            '''
            
            for anomaly in anomalies:
                severity_class = 'high' if anomaly['score'] > 0.8 else 'medium'
                anomaly_html += f'''
                <div class="anomaly-item {severity_class}">
                    <h4>{anomaly['type'].replace('_', ' ').title()}</h4>
                    <div class="anomaly-score">異常分數: {anomaly['score']:.2f}</div>
                    <div class="anomaly-explanation">{anomaly['explanation']}</div>
                </div>
                '''
            
            anomaly_html += '</div>'
            
            self.html_generator.add_section('AI 異常檢測', anomaly_html, 'anomaly-section')

    def _add_html_risk_assessment(self):
        """添加 HTML 格式的風險評估"""
        from vp_analyze_logs_ext import RiskAssessmentEngine
        
        risk_engine = RiskAssessmentEngine()
        
        # 準備系統狀態數據
        system_state = {
            'thread_count': len(self.anr_info.all_threads),
            'blocked_threads': sum(1 for t in self.anr_info.all_threads if t.state == ThreadState.BLOCKED),
            'cpu_usage': self.anr_info.cpu_usage.get('total', 0) if self.anr_info.cpu_usage else 0,
            'memory_available_mb': self.anr_info.memory_info.get('available', 0) / 1024 if self.anr_info.memory_info else 0
        }
        
        risk_assessment = risk_engine.assess_anr_risk(system_state)
        
        risk_html = f'''
        <div class="risk-assessment">
            <div class="overall-risk risk-{risk_assessment['risk_level']}">
                <h3>整體風險等級: {risk_assessment['risk_level'].upper()}</h3>
                <div class="risk-score">風險分數: {risk_assessment['overall_risk']:.2f}</div>
                <div class="anr-probability">預測 ANR 概率: {risk_assessment['predicted_anr_probability']:.1%}</div>
            </div>
            
            <div class="risk-factors">
                <h4>風險因素分析</h4>
                {self._format_risk_factors(risk_assessment['factors'])}
            </div>
            
            <div class="preventive-actions">
                <h4>預防措施</h4>
                {self._format_preventive_actions(risk_assessment['recommendations'])}
            </div>
        </div>
        '''
        
        self.html_generator.add_section('風險評估', risk_html, 'risk-section')

    def _add_html_code_fix_suggestions(self):
        """添加 HTML 格式的代碼修復建議"""
        from vp_analyze_logs_ext import CodeFixGenerator
        
        fix_generator = CodeFixGenerator()
        
        # 基於分析結果生成修復建議
        fix_suggestions = []
        
        if self.anr_info.main_thread:
            for frame in self.anr_info.main_thread.backtrace[:5]:
                if 'File' in frame or 'SQLite' in frame:
                    fix_suggestions.extend(
                        fix_generator.generate_fix_suggestions('main_thread_io', {'stack_frame': frame})
                    )
                    break
                elif 'SharedPreferences' in frame and 'commit' in frame:
                    fix_suggestions.extend(
                        fix_generator.generate_fix_suggestions('shared_preferences_commit', {})
                    )
                    break
        
        if fix_suggestions:
            fix_html = '<div class="code-fixes">'
            
            for i, suggestion in enumerate(fix_suggestions[:3]):  # 最多顯示3個
                fix_html += f'''
                <div class="fix-suggestion">
                    <h4>{suggestion['title']}</h4>
                    <div class="difficulty-{suggestion['difficulty']}">
                        難度: {suggestion['difficulty']} | 影響: {suggestion['impact']}
                    </div>
                    
                    <div class="code-comparison">
                        <div class="code-before">
                            <h5>修改前:</h5>
                            <pre><code>{html.escape(suggestion['before'])}</code></pre>
                        </div>
                        <div class="code-after">
                            <h5>修改後:</h5>
                            <pre><code>{html.escape(suggestion['after'])}</code></pre>
                        </div>
                    </div>
                    
                    <div class="fix-explanation">
                        <p>{suggestion['explanation']}</p>
                    </div>
                </div>
                '''
            
            fix_html += '</div>'
            
            self.html_generator.add_section('代碼修復建議', fix_html, 'fix-section')

    def _generate_executive_summary(self) -> str:
        """生成執行摘要"""
        from vp_analyze_logs_ext import ExecutiveSummaryGenerator
        
        summary_generator = ExecutiveSummaryGenerator()
        
        # 準備分析結果
        analysis_results = {
            'anr_type': self.anr_info.anr_type.value,
            'severity': self._assess_severity(),
            'root_cause': self._quick_root_cause(),
            'frequency': 1,  # 實際應從歷史數據獲取
            'fix_complexity': 'medium'  # 實際應根據問題類型評估
        }
        
        return summary_generator.generate_summary(analysis_results)

    def _format_critical_period(self, critical_period: Optional[Dict]) -> str:
        """格式化關鍵時期"""
        if not critical_period:
            return '<p>未識別到明顯的關鍵時期</p>'
        
        return f'''
        <div class="critical-period-details">
            <p>時間範圍: {critical_period['start']} - {critical_period['end']}</p>
            <p>事件數量: {critical_period['event_count']}</p>
            <p>平均嚴重性: {critical_period['avg_severity']:.1f}/10</p>
        </div>
        '''

    def _format_risk_factors(self, factors: Dict) -> str:
        """格式化風險因素"""
        html = '<div class="factor-grid">'
        
        for factor_name, factor_data in factors.items():
            if isinstance(factor_data, dict) and 'score' in factor_data:
                risk_class = factor_data['risk_level']
                html += f'''
                <div class="factor-item risk-{risk_class}">
                    <h5>{factor_name.replace('_', ' ').title()}</h5>
                    <div class="factor-score">{factor_data['score']:.2f}</div>
                    <div class="factor-details">{factor_data.get('details', '')}</div>
                </div>
                '''
        
        html += '</div>'
        return html

    def _format_preventive_actions(self, actions: List[Dict]) -> str:
        """格式化預防措施"""
        if not actions:
            return '<p>暫無特定預防措施建議</p>'
        
        html = '<ul class="action-list">'
        
        for action in actions:
            priority_class = f"priority-{action['priority']}"
            html += f'''
            <li class="{priority_class}">
                <strong>{action['action']}</strong>
                <p>{action['description']}</p>
            </li>
            '''
        
        html += '</ul>'
        return html
        
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
                r'terminating with uncaught exception',
                r'Abort message',
            ],
            'process_patterns': [
                r'pid:\s*(\d+),\s*tid:\s*(\d+),\s*name:\s*([^\s]+)',
                r'pid\s+(\d+)\s+tid\s+(\d+)\s+name\s+([^\s]+)',
                r'Process:\s*([^,\s]+).*?PID:\s*(\d+)',
                r'Cmdline:\s*(.+)',
                r'>>> ([^\s]+) <<<',
            ],
            'abort_patterns': [
                r'Abort message:\s*["\'](.+?)["\']',
                r'Abort message:\s*(.+?)(?:\n|$)',
                r'abort_message:\s*"(.+?)"',
                r'CHECK\s+failed:\s*(.+)',
                r'Fatal Exception:\s*(.+)',
            ],
            'backtrace_patterns': [
                r'#(\d+)\s+pc\s+([0-9a-fA-F]+)\s+([^\s]+)(?:\s+\((.+?)\))?',
                r'#(\d+)\s+([0-9a-fA-F]+)\s+([^\s]+)(?:\s+\((.+?)\))?',
                r'backtrace:\s*#(\d+)\s+pc\s+([0-9a-fA-F]+)',
                r'at\s+([^\(]+)\(([^\)]+)\)',
            ],
            'memory_patterns': [
                r'([0-9a-f]+)-([0-9a-f]+)\s+([rwxps-]+)\s+([0-9a-f]+)\s+([0-9a-f:]+)\s+(\d+)\s+(.*)',
                r'memory near',
                r'code around',
            ],
            'register_patterns': [
                r'(r\d+|x\d+|pc|sp|lr|fp)\s+([0-9a-fA-F]+)',
                r'(eax|ebx|ecx|edx|esi|edi|ebp|esp|eip)\s+([0-9a-fA-F]+)',
            ],
            'fortify_patterns': [
                r'FORTIFY:\s*(.+)',
                r'fortify_fatal:\s*(.+)',
                r'detected source and destination buffer overlap',
                r'buffer overflow detected',
            ],
            'seccomp_patterns': [
                r'seccomp prevented call to disallowed.*?system call\s+(\d+)',
                r'signal\s+31\s+\(SIGSYS\)',
                r'SYS_SECCOMP',
            ],
            'java_patterns': [
                r'java:\s*(.+)',
                r'at\s+([a-zA-Z0-9._$]+)\(([^)]+)\)',
                r'Caused by:\s*(.+)',
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
        
        # 新增：解析 Java 堆疊（如果有）
        java_stack = self._extract_java_stack(content)
        
        tombstone_info = TombstoneInfo(
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
        
        # 新增：加入 Java 堆疊
        if hasattr(tombstone_info, 'java_stack'):
            tombstone_info.java_stack = java_stack
        
        return tombstone_info
    
    def _extract_signal_info(self, content: str) -> Dict:
        """提取信號資訊"""
        info = {}
        
        # 提取信號
        for pattern in self.patterns['signal_patterns']:
            match = re.search(pattern, content)
            if match:
                if 'signal' in pattern and len(match.groups()) >= 2:
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
        
        # 特殊處理 SIGSYS (seccomp)
        if any(re.search(pattern, content) for pattern in self.patterns['seccomp_patterns']):
            info['signal'] = CrashSignal.SIGSYS
            info['signal_num'] = 31
            info['signal_name'] = 'SIGSYS'
            
            # 提取被阻止的系統調用號
            syscall_match = re.search(r'system call\s+(\d+)', content)
            if syscall_match:
                info['blocked_syscall'] = syscall_match.group(1)
        
        # 提取信號碼
        code_match = re.search(r'(?:si_code|code)[=:\s]+([0-9-]+)', content)
        if code_match:
            info['code'] = code_match.group(1)
            
            # 解析信號碼含義
            info['code_meaning'] = self._interpret_signal_code(
                info.get('signal', CrashSignal.UNKNOWN),
                info['code']
            )
        
        # 提取故障地址
        fault_patterns = [
            r'fault addr\s+([0-9a-fxA-FX]+)',
            r'si_addr\s+([0-9a-fxA-FX]+)',
            r'Accessing address:\s*([0-9a-fxA-FX]+)',
            r'Cause:\s*null pointer dereference',
        ]
        
        for pattern in fault_patterns:
            match = re.search(pattern, content)
            if match:
                if 'null pointer' in pattern:
                    info['fault_addr'] = '0x0'
                else:
                    info['fault_addr'] = match.group(1)
                break
        else:
            # 如果沒有找到故障地址，設為 Unknown
            info['fault_addr'] = 'Unknown'
        
        # 檢查特殊故障地址
        if info.get('fault_addr'):
            addr = info['fault_addr'].lower()
            if addr in ['0x0', '0', '00000000', '0000000000000000']:
                info['fault_type'] = 'null_pointer'
            elif addr == '0xdeadbaad':
                info['fault_type'] = 'abort_marker'
            elif addr.startswith('0xdead'):
                info['fault_type'] = 'debug_marker'
            elif addr == '0xdeadbeef':
                info['fault_type'] = 'uninitialized'
        
        return info
    
    def _interpret_signal_code(self, signal: CrashSignal, code: str) -> str:
        """解釋信號碼的含義"""
        try:
            code_num = int(code)
        except:
            return "Unknown"
        
        if signal == CrashSignal.SIGSEGV:
            segv_codes = {
                1: "SEGV_MAPERR - 地址未映射",
                2: "SEGV_ACCERR - 無訪問權限",
                3: "SEGV_BNDERR - 邊界檢查失敗",
                4: "SEGV_PKUERR - 保護鍵錯誤",
            }
            return segv_codes.get(code_num, f"Unknown SIGSEGV code {code_num}")
        elif signal == CrashSignal.SIGBUS:
            bus_codes = {
                1: "BUS_ADRALN - 地址對齊錯誤",
                2: "BUS_ADRERR - 不存在的物理地址",
                3: "BUS_OBJERR - 對象特定硬體錯誤",
            }
            return bus_codes.get(code_num, f"Unknown SIGBUS code {code_num}")
        elif signal == CrashSignal.SIGILL:
            ill_codes = {
                1: "ILL_ILLOPC - 非法操作碼",
                2: "ILL_ILLOPN - 非法操作數",
                3: "ILL_ILLADR - 非法尋址模式",
                4: "ILL_ILLTRP - 非法陷阱",
                5: "ILL_PRVOPC - 特權操作碼",
                6: "ILL_PRVREG - 特權寄存器",
                7: "ILL_COPROC - 協處理器錯誤",
                8: "ILL_BADSTK - 內部堆疊錯誤",
            }
            return ill_codes.get(code_num, f"Unknown SIGILL code {code_num}")
        
        return f"Signal code {code_num}"
    
    def _extract_process_info(self, content: str) -> Dict:
        """提取進程資訊"""
        info = {}
        
        for pattern in self.patterns['process_patterns']:
            match = re.search(pattern, content)
            if match:
                groups = match.groups()
                if 'pid:' in pattern and len(groups) >= 3:
                    info['pid'] = groups[0]
                    info['tid'] = groups[1]
                    info['process_name'] = groups[2]
                elif 'Process:' in pattern and len(groups) >= 2:
                    info['process_name'] = groups[0]
                    info['pid'] = groups[1]
                elif '>>>' in pattern and len(groups) >= 1:
                    info['process_name'] = groups[0]
                elif 'Cmdline:' in pattern and len(groups) >= 1:
                    info['cmdline'] = groups[0]
                    # 從 cmdline 提取進程名
                    if '/' in groups[0]:
                        info['process_name'] = groups[0].split('/')[-1]
                    else:
                        info['process_name'] = groups[0]
                
                if 'pid' in info and 'tid' in info:
                    break
        
        # 提取線程名稱
        thread_patterns = [
            r'Thread-\d+\s+"([^"]+)"',
            r'name:\s*([^\s]+)\s+>>>',
            r'thread_name:\s*([^\s]+)',
        ]
        
        for pattern in thread_patterns:
            thread_match = re.search(pattern, content)
            if thread_match:
                info['thread_name'] = thread_match.group(1)
                break
        
        if 'thread_name' not in info:
            info['thread_name'] = info.get('process_name', 'Unknown')
        
        # 提取 ABI 和構建指紋
        abi_match = re.search(r"ABI:\s*'([^']+)'", content)
        if abi_match:
            info['abi'] = abi_match.group(1)
        
        fingerprint_match = re.search(r"Build fingerprint:\s*'([^']+)'", content)
        if fingerprint_match:
            info['build_fingerprint'] = fingerprint_match.group(1)
        
        return info
    
    def _extract_abort_message(self, content: str) -> Optional[str]:
        """提取 abort message"""
        for pattern in self.patterns['abort_patterns']:
            match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
            if match:
                message = match.group(1).strip()
                # 清理訊息
                message = message.replace('\\n', '\n')
                message = message.replace('\\t', '\t')
                return message
        
        # 檢查 FORTIFY 訊息
        for pattern in self.patterns['fortify_patterns']:
            match = re.search(pattern, content)
            if match:
                return f"FORTIFY: {match.group(1)}"
        
        return None
    
    def _extract_backtrace(self, content: str) -> List[Dict]:
        """提取崩潰堆疊"""
        backtrace = []
        
        # 查找 backtrace 區段
        backtrace_patterns = [
            r'(?:backtrace:|stack:)\s*\n(.*?)(?:\n\n|memory map:|open files:)',
            r'((?:#\d+\s+pc\s+[0-9a-fA-F]+.*\n)+)',
            r'Stack Trace:\s*\n(.*?)(?:\n\n|$)',
        ]
        
        backtrace_text = None
        for pattern in backtrace_patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                backtrace_text = match.group(1)
                break
        
        if backtrace_text:
            # 解析堆疊幀
            for pattern in self.patterns['backtrace_patterns']:
                frames = re.findall(pattern, backtrace_text, re.MULTILINE)
                
                for frame_match in frames:
                    if len(frame_match) >= 3:
                        frame_info = {
                            'num': int(frame_match[0]) if frame_match[0].isdigit() else 0,
                            'pc': frame_match[1],
                            'location': frame_match[2],
                            'symbol': frame_match[3] if len(frame_match) > 3 else None
                        }
                        
                        # 解析符號資訊
                        if frame_info['symbol']:
                            frame_info['demangled'] = self._demangle_symbol(frame_info['symbol'])
                        
                        backtrace.append(frame_info)
                
                if backtrace:
                    break
        
        return backtrace
    
    def _demangle_symbol(self, symbol: str) -> str:
        """嘗試 demangle C++ 符號"""
        # 這是簡化版本，實際應該調用 c++filt
        if symbol.startswith('_Z'):
            # C++ mangled symbol
            return f"{symbol} (C++ mangled)"
        return symbol
    
    def _extract_memory_map(self, content: str) -> List[str]:
        """提取記憶體映射"""
        memory_map = []
        
        # 查找 memory map 區段
        map_patterns = [
            r'memory map.*?:\s*\n(.*?)(?:\n\n|open files:|$)',
            r'maps:\s*\n(.*?)(?:\n\n|$)',
            r'memory near.*?:\s*\n(.*?)(?:\n\n|$)',
        ]
        
        for pattern in map_patterns:
            map_section = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if map_section:
                map_text = map_section.group(1)
                
                # 解析記憶體映射行
                for line in map_text.splitlines():
                    if re.match(r'[0-9a-f]+-[0-9a-f]+\s+[rwxps-]+', line):
                        memory_map.append(line.strip())
                
                if memory_map:
                    break
        
        return memory_map[:100]  # 限制數量
    
    def _extract_open_files(self, content: str) -> List[str]:
        """提取打開的檔案"""
        open_files = []
        
        # 查找 open files 區段
        files_patterns = [
            r'open files.*?:\s*\n(.*?)(?:\n\n|$)',
            r'fd table:\s*\n(.*?)(?:\n\n|$)',
        ]
        
        for pattern in files_patterns:
            files_section = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if files_section:
                files_text = files_section.group(1)
                
                for line in files_text.splitlines():
                    line = line.strip()
                    if line and not line.startswith('-'):
                        # 解析文件描述符資訊
                        fd_match = re.match(r'(\d+):\s+(.+)', line)
                        if fd_match:
                            open_files.append(f"fd {fd_match.group(1)}: {fd_match.group(2)}")
                        else:
                            open_files.append(line)
                
                if open_files:
                    break
        
        return open_files[:50]  # 限制數量
    
    def _extract_registers(self, content: str) -> Dict[str, str]:
        """提取寄存器資訊"""
        registers = {}
        
        # 查找寄存器區段
        reg_patterns = [
            r'registers.*?:\s*\n(.*?)(?:\n\n|backtrace:|$)',
            r'((?:[rx]\d+|pc|sp|lr|fp)\s+[0-9a-fA-F]+.*\n)+',
        ]
        
        for pattern in reg_patterns:
            reg_section = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if reg_section:
                reg_text = reg_section.group(1)
                
                # 解析寄存器
                for reg_pattern in self.patterns['register_patterns']:
                    matches = re.findall(reg_pattern, reg_text)
                    
                    for reg_name, reg_value in matches:
                        registers[reg_name] = reg_value
                
                if registers:
                    break
        
        # 特殊處理某些架構的寄存器顯示
        if not registers:
            # ARM64 格式
            arm64_match = re.search(
                r'x0\s+([0-9a-f]+)\s+x1\s+([0-9a-f]+)\s+x2\s+([0-9a-f]+)\s+x3\s+([0-9a-f]+)',
                content
            )
            if arm64_match:
                for i in range(4):
                    registers[f'x{i}'] = arm64_match.group(i + 1)
        
        return registers
    
    def _extract_all_threads_tombstone(self, lines: List[str], content: str) -> List[ThreadInfo]:
        """提取所有線程資訊 (Tombstone)"""
        threads = []
        
        # 查找線程區段
        thread_patterns = [
            r'(?:threads|other threads).*?:\s*\n(.*?)(?:\n\n|memory map:|$)',
            r'--- --- --- --- --- --- --- ---\s*\n(.*?)(?:\n\n|$)',
        ]
        
        for pattern in thread_patterns:
            thread_section = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if thread_section:
                thread_text = thread_section.group(1)
                
                # 解析每個線程
                thread_blocks = re.split(r'\n(?=tid=|Thread \d+)', thread_text)
                
                for block in thread_blocks:
                    if 'tid=' in block or 'Thread' in block:
                        thread_info = self._parse_thread_block(block)
                        if thread_info:
                            threads.append(thread_info)
                
                break
        
        return threads
    
    def _parse_thread_block(self, block: str) -> Optional[ThreadInfo]:
        """解析線程區塊"""
        # 提取線程資訊
        tid_match = re.search(r'tid=(\d+)', block)
        name_match = re.search(r'name=([^\s]+)', block)
        
        if tid_match:
            thread = ThreadInfo(
                name=name_match.group(1) if name_match else 'Unknown',
                tid=tid_match.group(1),
                state=ThreadState.UNKNOWN
            )
            
            # 提取堆疊
            stack_lines = []
            for line in block.splitlines():
                if re.match(r'\s*#\d+\s+pc', line):
                    stack_lines.append(line.strip())
            
            thread.backtrace = stack_lines
            return thread
        
        return None
    
    def _extract_java_stack(self, content: str) -> List[str]:
        """提取 Java 堆疊（如果有）"""
        java_stack = []
        
        # 查找 Java 堆疊區段
        java_patterns = [
            r'java stack trace.*?:\s*\n(.*?)(?:\n\n|$)',
            r'(at\s+[a-zA-Z0-9._$]+\([^)]+\).*\n)+',
        ]
        
        for pattern in java_patterns:
            java_match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if java_match:
                java_text = java_match.group(1)
                
                # 解析 Java 堆疊行
                for line in java_text.splitlines():
                    if line.strip().startswith('at '):
                        java_stack.append(line.strip())
                    elif line.strip().startswith('Caused by:'):
                        java_stack.append(line.strip())
                
                break
        
        return java_stack
    
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
        self.intelligent_engine = IntelligentAnalysisEngine()
    
    def generate(self) -> str:
        """生成報告"""
        self._add_summary()
        self._add_basic_info()
        self._add_signal_analysis()
        self._add_abort_analysis()
        self._add_backtrace_analysis()
        self._add_memory_analysis()
        self._add_root_cause_analysis()
        self._add_intelligent_crash_analysis()  # 新增
        self._add_fortify_analysis()           # 新增
        self._add_symbol_resolution_guide()    # 新增
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

    def _add_suggestions(self):
        """添加解決建議"""
        self.report_lines.append("\n💡 解決建議")
        
        suggestions = self._generate_suggestions()
        
        # 調試建議
        if suggestions['debugging']:
            self.report_lines.append("\n🔍 調試建議:")
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
        
        # 推薦工具
        self.report_lines.append("\n🔨 推薦工具:")
        tools = [
            "addr2line - 符號解析",
            "ndk-stack - 堆疊符號化",
            "AddressSanitizer (ASAN) - 記憶體錯誤檢測",
            "ThreadSanitizer (TSAN) - 線程競爭檢測",
            "UndefinedBehaviorSanitizer (UBSAN) - 未定義行為檢測",
            "Valgrind - 記憶體洩漏檢測",
            "GDB/LLDB - 調試器",
            "Android Studio Native Debugger - IDE 調試"
        ]
        
        for tool in tools:
            self.report_lines.append(f"  • {tool}")
        
        # 相關文檔
        self.report_lines.append("\n📚 相關文檔:")
        docs = [
            "Android NDK 調試指南: https://developer.android.com/ndk/guides/debug",
            "AddressSanitizer 使用: https://source.android.com/docs/security/test/asan",
            "Native Crash 分析: https://source.android.com/docs/core/architecture/debugging/native-crash",
            "Tombstone 分析指南: https://source.android.com/docs/core/architecture/debugging"
        ]
        
        for doc in docs:
            self.report_lines.append(f"  • {doc}")
            
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
        
        # 檢查是否為 Unknown 或無效地址
        if addr in ['unknown', 'n/a', 'none', '']:
            return None
        
        if addr in ['0x0', '0', '00000000', '0000000000000000']:
            return "空指針 - 嘗試訪問 NULL"
        elif addr == '0xdeadbaad':
            return "Bionic libc abort 標記"
        elif addr.startswith('0xdead'):
            return "可能是調試標記或損壞的指針"
        
        # 安全地嘗試轉換為整數
        try:
            addr_int = int(addr, 16)
            if addr_int < 0x1000:
                return "低地址 - 可能是空指針加偏移"
            elif addr_int > 0x7fffffffffff:
                return "內核地址空間 - 可能是內核錯誤"
        except ValueError:
            # 如果無法解析為十六進制，返回 None
            return None
        
        # 檢查是否在記憶體映射中
        for mem_line in self.info.memory_map[:20]:
            if '-' in mem_line:
                parts = mem_line.split()
                if parts:
                    range_str = parts[0]
                    if '-' in range_str:
                        start_str, end_str = range_str.split('-')
                        try:
                            start = int(start_str, 16)
                            end = int(end_str, 16)
                            addr_int = int(addr, 16)
                            if start <= addr_int <= end:
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
        
        self._add_intelligent_crash_analysis()  # 新增這行
    
    def _add_intelligent_crash_analysis(self):
        """添加智能崩潰分析"""
        self.report_lines.append("\n🧠 智能崩潰分析")
        
        # 分析崩潰模式
        crash_analysis = self.intelligent_engine.analyze_crash_pattern(self.info)
        
        # 顯示崩潰流程
        if crash_analysis['crash_flow']:
            self.report_lines.append("\n📊 崩潰調用流程:")
            for i, flow in enumerate(crash_analysis['crash_flow']):
                marker = "→" if i < len(crash_analysis['crash_flow']) - 1 else "💥"
                self.report_lines.append(
                    f"  {marker} #{i} pc {flow['pc']} @ {flow['location']}"
                )
                if flow['symbol']:
                    self.report_lines.append(f"      {flow['symbol']}")
                if flow['analysis'] != '未知':
                    self.report_lines.append(f"      分析: {flow['analysis']}")
        
        # 顯示記憶體上下文
        if crash_analysis['memory_context']:
            ctx = crash_analysis['memory_context']
            self.report_lines.append("\n💾 記憶體上下文分析:")
            
            if ctx['analysis']:
                self.report_lines.append(f"  • {ctx['analysis']}")
            
            if ctx['fault_location']:
                self.report_lines.append(f"  • 崩潰位置: {ctx['fault_location']}")
            
            if ctx['nearby_regions']:
                self.report_lines.append("  • 附近區域:")
                for region in ctx['nearby_regions'][:3]:
                    self.report_lines.append(f"    - {region}")
        
        # 崩潰簽名
        if crash_analysis['crash_signature']:
            self.report_lines.append(f"\n🔑 崩潰簽名: {crash_analysis['crash_signature']}")
            self.report_lines.append("  (可用於搜尋相似崩潰)")
        
        # 匹配已知模式
        known_patterns = self.intelligent_engine.match_tombstone_patterns(self.info)
        if known_patterns:
            self.report_lines.append("\n🎯 匹配的已知崩潰模式:")
            for pattern in known_patterns[:3]:
                self.report_lines.append(
                    f"\n  📌 {pattern['root_cause']} "
                    f"(信心度: {pattern['confidence']*100:.0f}%)"
                )
                self.report_lines.append(f"     嚴重性: {pattern['severity']}")
                self.report_lines.append("     解決方案:")
                for solution in pattern['solutions']:
                    self.report_lines.append(f"       • {solution}")
        
        # 相似崩潰建議
        self._add_similar_crash_suggestions()
    
    def _add_similar_crash_suggestions(self):
        """添加相似崩潰建議"""
        self.report_lines.append("\n🔍 相似崩潰分析:")
        
        # 基於崩潰特徵給出建議
        if self.info.signal == CrashSignal.SIGSEGV:
            if self.info.fault_addr in ['0x0', '0', '00000000', '0000000000000000']:
                self.report_lines.extend([
                    "  • 這是典型的空指針崩潰",
                    "  • 建議搜尋類似的空指針崩潰案例",
                    "  • 使用防禦性編程檢查所有指針",
                ])
            elif int(self.info.fault_addr, 16) < 0x1000:
                self.report_lines.extend([
                    "  • 低地址訪問，可能是空指針加偏移",
                    "  • 檢查數組或結構體成員訪問",
                ])
            else:
                self.report_lines.extend([
                    "  • 記憶體訪問違規，可能是野指針或緩衝區溢出",
                    "  • 建議開啟 AddressSanitizer (ASAN) 進行調試",
                    "  • 檢查是否有 use-after-free 情況",
                ])
        elif self.info.signal == CrashSignal.SIGABRT:
            self.report_lines.extend([
                "  • 主動終止通常由 assert 或檢查失敗引起",
                "  • 查看 abort_message 獲取更多資訊",
                "  • 檢查是否有未捕獲的異常",
            ])
        elif self.info.signal == CrashSignal.SIGSYS:
            self.report_lines.extend([
                "  • Seccomp 違規 - 嘗試調用被禁止的系統調用",
                "  • 檢查應用的 seccomp 策略",
                "  • 避免使用受限的系統調用",
            ])
    
    def _add_fortify_analysis(self):
        """添加 FORTIFY 分析"""
        fortify_info = self.intelligent_engine._analyze_fortify_failure(self.content)
        if fortify_info:
            self.report_lines.append("\n🛡️ FORTIFY 保護檢測")
            self.report_lines.append(f"  類型: {fortify_info['type']}")
            self.report_lines.append(f"  訊息: {fortify_info['message']}")
            self.report_lines.append(f"  嚴重性: {fortify_info['severity']}")
            self.report_lines.append(f"  建議: {fortify_info['suggestion']}")
            self.report_lines.append("  常見原因:")
            self.report_lines.append("    • 緩衝區溢出")
            self.report_lines.append("    • 字串操作越界")
            self.report_lines.append("    • 格式化字串漏洞")
    
    def _add_symbol_resolution_guide(self):
        """添加符號解析指南"""
        self.report_lines.append("\n🔧 符號解析指南")
        
        # 生成 addr2line 命令
        addr2line_cmds = self._generate_addr2line_commands(self.info)
        if addr2line_cmds:
            self.report_lines.append("\n📝 使用以下命令解析詳細符號:")
            for i, cmd in enumerate(addr2line_cmds[:5], 1):
                self.report_lines.append(f"  {i}. {cmd}")
            
            if len(addr2line_cmds) > 5:
                self.report_lines.append(f"  ... 還有 {len(addr2line_cmds) - 5} 個命令")
        
        # 提供 ndk-stack 使用建議
        self.report_lines.append("\n💡 或使用 ndk-stack 工具:")
        self.report_lines.append("  $ ndk-stack -sym <path-to-symbols> -dump <tombstone-file>")
        
        # 符號文件位置提示
        self.report_lines.append("\n📂 符號文件通常位於:")
        self.report_lines.append("  • 本地編譯: out/target/product/*/symbols/")
        self.report_lines.append("  • NDK 應用: app/build/intermediates/cmake/*/obj/")
        self.report_lines.append("  • 系統庫: 需要對應版本的 symbols.zip")
    
    def _generate_addr2line_commands(self, tombstone_info: TombstoneInfo) -> List[str]:
        """生成 addr2line 命令供開發者使用"""
        commands = []
        seen_libs = set()
        
        for frame in tombstone_info.crash_backtrace:
            location = frame.get('location', '')
            pc = frame.get('pc', '')
            
            # 只為 .so 文件生成命令
            if '.so' in location and location not in seen_libs:
                seen_libs.add(location)
                
                # 判斷架構
                if 'arm64' in self.content or 'aarch64' in self.content:
                    prefix = "aarch64-linux-android-"
                elif 'arm' in self.content:
                    prefix = "arm-linux-androideabi-"
                elif 'x86_64' in self.content:
                    prefix = "x86_64-linux-android-"
                else:
                    prefix = "i686-linux-android-"
                
                cmd = f"{prefix}addr2line -C -f -e {location} {pc}"
                commands.append(cmd)
        
        return commands
    
    def _add_backtrace_analysis(self):
        """添加堆疊分析 - 增強版"""
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
            
            # 對關鍵幀添加額外分析
            if i < 5 and not frame.get('symbol'):
                self.report_lines.append(f"      💡 提示: 使用 addr2line 解析符號")
    
    def _generate_suggestions(self) -> Dict[str, List[str]]:
        """生成建議 - 增強版"""
        suggestions = {
            'debugging': [],
            'fixing': [],
            'prevention': []
        }
        
        # 調試建議
        suggestions['debugging'].extend([
            "使用 addr2line 工具解析詳細的源碼位置",
            "在 Android Studio 中使用 LLDB 調試器重現問題",
            "開啟 AddressSanitizer (ASAN) 檢測記憶體錯誤",
            "收集 coredump 進行離線分析",
        ])
        
        # 基於崩潰類型的建議
        if self.info.signal == CrashSignal.SIGSEGV:
            if self.info.fault_addr in ['0x0', '0', '00000000']:
                suggestions['fixing'].extend([
                    "檢查所有指針使用前是否為 NULL",
                    "為指針添加防禦性檢查",
                    "使用智能指針 (如 std::unique_ptr, std::shared_ptr)",
                    "啟用編譯器的 -Wnull-dereference 警告",
                ])
            else:
                suggestions['fixing'].extend([
                    "檢查數組邊界訪問",
                    "使用 valgrind 或 ASAN 檢測記憶體問題",
                    "檢查多線程下的記憶體訪問競爭",
                    "確認記憶體對齊要求",
                ])
        
        elif self.info.signal == CrashSignal.SIGABRT:
            suggestions['fixing'].extend([
                "檢查 assert 條件是否合理",
                "添加更多的錯誤處理和恢復機制",
                "使用 try-catch 捕獲 C++ 異常",
                "檢查是否有資源耗盡（如記憶體、文件句柄）",
            ])
        
        elif self.info.signal == CrashSignal.SIGSYS:
            suggestions['fixing'].extend([
                "檢查 seccomp 策略配置",
                "避免使用被限制的系統調用",
                "更新到支援的 API 調用方式",
            ])
        
        # JNI 相關
        if any('JNI' in frame.get('location', '') or 'jni' in frame.get('symbol', '').lower() 
               for frame in self.info.crash_backtrace[:10]):
            suggestions['fixing'].extend([
                "檢查 JNI 調用的參數有效性",
                "確保 JNI 局部引用正確管理 (使用 NewLocalRef/DeleteLocalRef)",
                "檢查 Java 和 Native 之間的數據類型匹配",
                "驗證 JNI 方法簽名正確性",
                "使用 CheckJNI 模式調試 (-Xcheck:jni)",
            ])
        
        # 預防建議
        suggestions['prevention'].extend([
            "使用靜態分析工具 (如 Clang Static Analyzer, PVS-Studio)",
            "編寫單元測試覆蓋邊界情況",
            "使用 Code Review 檢查記憶體管理",
            "開啟編譯器的所有警告 (-Wall -Wextra -Werror)",
            "使用 Sanitizers 進行持續測試 (ASAN, TSAN, UBSAN)",
            "實施 FORTIFY_SOURCE 保護",
            "定期進行 Fuzzing 測試",
        ])
        
        # 系統庫崩潰
        if any(lib in frame.get('location', '') for frame in self.info.crash_backtrace[:3]
               for lib in ['libc.so', 'libandroid_runtime.so']):
            suggestions['debugging'].append("收集完整的 bugreport 分析系統狀態")
            suggestions['fixing'].append("檢查是否有系統資源耗盡")
            suggestions['fixing'].append("驗證 API 調用參數的有效性")
        
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

    def _extract_report_info(self, html_content: str, file_path: str) -> Optional[Dict]:
        """從 HTML 報告中提取關鍵信息"""

        info = {
            'path': file_path,  # 保留絕對路徑供後續讀取
            'filename': os.path.basename(file_path),
            'type': 'anr' if 'anr' in file_path.lower() else 'tombstone',
            'root_cause': '',
            'severity': '',
            'process_name': '',
            'features': [],
            'content': html_content  # 直接保存內容
        }
        
        # 使用正則表達式提取關鍵信息
        # 提取可能原因
        cause_match = re.search(r'可能原因[：:]\s*([^<\n]+)', html_content)
        if cause_match:
            info['root_cause'] = cause_match.group(1).strip()
        
        # 提取嚴重程度
        severity_match = re.search(r'嚴重程度[：:]\s*([^<\n]+)', html_content)
        if severity_match:
            info['severity'] = severity_match.group(1).strip()
        
        # 提取進程名稱
        process_match = re.search(r'進程名稱[：:]\s*([^<\n]+)', html_content)
        if process_match:
            info['process_name'] = process_match.group(1).strip()
        
        # 提取特徵（用於相似度計算）
        if 'Binder IPC' in html_content:
            info['features'].append('binder_ipc')
        if 'WindowManager' in html_content:
            info['features'].append('window_manager')
        if '線程數過多' in html_content or '線程數量過多' in html_content:
            info['features'].append('too_many_threads')
        if '死鎖' in html_content:
            info['features'].append('deadlock')
        if '記憶體不足' in html_content:
            info['features'].append('memory_low')
        if 'WebView' in html_content:
            info['features'].append('webview')
        if '空指針' in html_content or 'null pointer' in html_content.lower():
            info['features'].append('null_pointer')
        if 'SIGSEGV' in html_content:
            info['features'].append('sigsegv')
        if 'SIGABRT' in html_content:
            info['features'].append('sigabrt')
        
        return info if info['root_cause'] else None

    def _analyze_similarity(self, reports: List[Dict]) -> List[Dict]:
        """分析報告的相似度並分組"""
        if not reports:
            return []
        
        # 按 root_cause 初步分組
        groups = {}
        for report in reports:
            root_cause = report['root_cause']
            if root_cause not in groups:
                groups[root_cause] = []
            groups[root_cause].append(report)
        
        # 計算每組的相似度並簡化標題
        similarity_groups = []
        for root_cause, group_reports in groups.items():
            if len(group_reports) > 1:
                # 計算組內相似度
                avg_similarity = self._calculate_group_similarity(group_reports)
                
                # 提取最關鍵的共同特徵作為標題
                key_feature = self._extract_key_feature(group_reports)
                
                similarity_groups.append({
                    'title': key_feature,  # 使用簡化的標題
                    'full_title': root_cause,  # 保留完整標題以備用
                    'reports': group_reports,
                    'count': len(group_reports),
                    'similarity': avg_similarity,
                    'group_id': f"group_{len(similarity_groups)}"
                })
        
        # 按相似度排序
        similarity_groups.sort(key=lambda x: x['similarity'], reverse=True)
        
        return similarity_groups

    def _extract_key_feature(self, reports: List[Dict]) -> str:
        """提取最關鍵的共同特徵作為簡化標題"""
        # 統計所有報告中的關鍵詞頻率
        keyword_count = {}
        
        # 定義關鍵詞優先級
        priority_keywords = {
            'Binder IPC 阻塞': ['Binder IPC', 'BinderProxy', 'transact'],
            '線程數過多': ['線程數過多', '線程數量過多', 'too many threads'],
            '死鎖': ['死鎖', 'deadlock', '循環等待'],
            '記憶體不足': ['記憶體不足', '記憶體嚴重不足', 'OutOfMemoryError'],
            '主線程阻塞': ['主線程', 'main thread', 'UI thread'],
            'WindowManager 服務阻塞': ['WindowManager', 'window service'],
            'WebView 問題': ['WebView', 'chromium'],
            '空指針': ['空指針', 'null pointer', 'NullPointerException'],
            'I/O 操作阻塞': ['I/O', 'File', 'SQLite', 'SharedPreferences'],
            '網路請求阻塞': ['Http', 'Socket', 'Network'],
        }
        
        # 檢查每個優先關鍵詞在所有報告中的出現情況
        for key_feature, keywords in priority_keywords.items():
            found_in_all = True
            for report in reports:
                found = False
                # 檢查這個特徵的任何關鍵詞是否在報告中
                for keyword in keywords:
                    if (keyword in report['root_cause'] or 
                        keyword in ' '.join(report['features'])):
                        found = True
                        break
                if not found:
                    found_in_all = False
                    break
            
            if found_in_all:
                return key_feature
        
        # 如果沒有找到共同的優先關鍵詞，使用最常見的特徵
        all_features = []
        for report in reports:
            all_features.extend(report['features'])
        
        if all_features:
            from collections import Counter
            feature_counter = Counter(all_features)
            most_common = feature_counter.most_common(1)[0][0]
            
            # 轉換特徵名稱為更友好的顯示
            feature_map = {
                'binder_ipc': 'Binder IPC 問題',
                'window_manager': 'WindowManager 問題',
                'too_many_threads': '線程數過多',
                'deadlock': '死鎖問題',
                'memory_low': '記憶體不足',
                'webview': 'WebView 問題',
                'null_pointer': '空指針錯誤',
                'sigsegv': '記憶體訪問違規',
                'sigabrt': '程序異常終止'
            }
            
            return feature_map.get(most_common, '相似問題')
        
        # 最後的fallback
        return '相似問題'

    def _calculate_group_similarity(self, reports: List[Dict]) -> float:
        """計算組內平均相似度"""
        if len(reports) < 2:
            return 100.0
        
        similarities = []
        for i in range(len(reports)):
            for j in range(i + 1, len(reports)):
                sim = self._calculate_report_similarity(reports[i], reports[j])
                similarities.append(sim)
        
        return sum(similarities) / len(similarities) if similarities else 0

    def _calculate_report_similarity(self, report1: Dict, report2: Dict) -> float:
        """計算兩個報告的相似度"""
        score = 0.0
        
        # 相同的 root_cause
        if report1['root_cause'] == report2['root_cause']:
            score += 40
        
        # 相同的嚴重程度
        if report1['severity'] == report2['severity']:
            score += 10
        
        # 相同的類型
        if report1['type'] == report2['type']:
            score += 10
        
        # 特徵相似度
        features1 = set(report1['features'])
        features2 = set(report2['features'])
        if features1 and features2:
            intersection = features1.intersection(features2)
            union = features1.union(features2)
            jaccard = len(intersection) / len(union)
            score += jaccard * 40
        
        return min(score, 100)
                    
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
            # 過濾掉隱藏資料夾（以 . 開頭的資料夾）
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            base_dir = os.path.basename(root).lower()
            
            if base_dir in ["anr", "tombstones", "tombstone"]:
                for filename in filenames:
                    # 跳過特定檔案
                    if filename.endswith('.pb') or filename.endswith('.txt.analyzed'):
                        continue
                    if base_dir == "anr" and not filename.lower().startswith('anr'):
                        continue

                    file_path = os.path.join(root, filename)

                    # 檢查檔案大小，排除 0KB 的檔案
                    try:
                        file_size = os.path.getsize(file_path)
                        if file_size == 0:
                            print(f"  跳過空檔案 (0KB): {filename}")
                            continue
                    except OSError as e:
                        print(f"  無法讀取檔案大小: {filename} - {str(e)}")
                        continue

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
        
        # 保存文字版本
        output_file_txt = os.path.join(output_dir, file_info['name'] + '.analyzed.txt')
        with open(output_file_txt, 'w', encoding='utf-8') as f:
            f.write(result)
        
        # 生成並保存 HTML 版本
        output_file_html = os.path.join(output_dir, file_info['name'] + '.analyzed.html')
        try:
            html_content = self._generate_html_report(result, file_info)
            with open(output_file_html, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"✅ HTML 報告已生成: {output_file_html}")
            
            # 如果 HTML 生成成功，使用 HTML 版本
            output_file = output_file_html
        except Exception as e:
            print(f"❌ 生成 HTML 報告失敗: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # 如果 HTML 生成失敗，使用文字版本
            output_file = output_file_txt
        
        # 複製原始檔案
        original_copy = os.path.join(output_dir, file_info['name'])
        shutil.copy2(file_info['path'], original_copy)
        
        # 更新索引（保持原有結構）
        self._update_index(index_data, file_info['rel_path'], output_file, original_copy)
        
        # 更新統計
        if file_info['type'] == 'anr':
            self.stats['anr_count'] += 1
        else:
            self.stats['tombstone_count'] += 1
    
    def _generate_html_report(self, text_content: str, file_info: Dict) -> str:
        """生成 HTML 格式的分析報告（支援分割視窗）"""
        import json
        
        # 原始檔案的相對路徑
        original_file = file_info['name']
        
        # 將內容分行並進行 JSON 編碼（最安全的方式）
        lines = text_content.split('\n')
        json_lines = json.dumps(lines, ensure_ascii=False)
        
        return f"""<!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{html.escape(file_info['name'])} - 分析報告</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                background: #1a1a1a;
                color: #d4d4d4;
                overflow: hidden;
                height: 100vh;
            }}
            
            /* 分割視窗容器 */
            .split-container {{
                display: flex;
                height: 100vh;
                position: relative;
            }}
            
            /* 左側面板 - 分析報告 */
            .left-panel {{
                flex: 1;
                overflow-y: auto;
                background: #1e1e1e;
                position: relative;
            }}
            
            /* 右側面板 - 原始檔案 */
            .right-panel {{
                flex: 0;
                width: 0;
                overflow-y: auto;
                background: #252526;
                position: relative;
                transition: width 0.3s ease;
            }}
            
            .right-panel.open {{
                flex: 1;
                width: 50%;
            }}
            
            /* 分割條 */
            .splitter {{
                width: 5px;
                background: #333;
                cursor: col-resize;
                position: relative;
                display: none;
            }}
            
            .splitter.visible {{
                display: block;
            }}
            
            .splitter:hover {{
                background: #007acc;
            }}
            
            /* 面板內容 */
            .panel-content {{
                padding: 20px;
                font-size: 14px;
                line-height: 1.6;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            }}
            
            /* 標題欄 */
            .panel-header {{
                position: sticky;
                top: 0;
                background: #2d2d30;
                padding: 10px 20px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid #3e3e42;
                z-index: 10;
            }}
            
            .panel-title {{
                font-weight: bold;
                color: #cccccc;
            }}
            
            /* 控制按鈕 */
            .panel-controls {{
                display: flex;
                gap: 10px;
            }}
            
            .control-btn {{
                background: transparent;
                border: none;
                color: #cccccc;
                cursor: pointer;
                padding: 5px 10px;
                border-radius: 3px;
                font-size: 14px;
                transition: all 0.2s;
            }}
            
            .control-btn:hover {{
                background: #3e3e42;
                color: #ffffff;
            }}
            
            /* 查看原始檔案連結 */
            .view-original {{
                color: #4ec9b0;
                text-decoration: underline;
                cursor: pointer;
            }}
            
            .view-original:hover {{
                color: #6edcb8;
            }}
            
            /* 全屏模式 */
            .fullscreen {{
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                width: 100% !important;
                height: 100% !important;
                z-index: 9999;
                max-width: 100% !important;
            }}
            
            /* Loading */
            .loading {{
                text-align: center;
                padding: 50px;
                color: #666;
            }}
            
            /* 報告行樣式 */
            .report-line {{
                white-space: pre-wrap;
                word-wrap: break-word;
                margin: 0;
                padding: 2px 0;
            }}
            
            /* 高亮樣式 */
            .anr-type {{
                color: #ff9800;
                font-weight: bold;
            }}
            
            .process-name {{
                color: #4ec9b0;
                font-weight: bold;
            }}
            
            .timestamp {{
                color: #608b4e;
            }}
            
            .separator {{
                color: #565656;
            }}
            
            .emoji {{
                font-size: 1.1em;
            }}
            
            /* 原始檔案內容 */
            .original-content {{
                white-space: pre;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            }}
        </style>
    </head>
    <body>
        <div class="split-container">
            <!-- 左側面板 - 分析報告 -->
            <div class="left-panel" id="leftPanel">
                <div class="panel-content" id="reportContent">載入中...</div>
            </div>
            
            <!-- 分割條 -->
            <div class="splitter" id="splitter"></div>
            
            <!-- 右側面板 - 原始檔案 -->
            <div class="right-panel" id="rightPanel">
                <div class="panel-header">
                    <span class="panel-title">📄 原始檔案: {html.escape(original_file)}</span>
                    <div class="panel-controls">
                        <button class="control-btn" onclick="toggleFullscreen('rightPanel')" title="全屏">⛶</button>
                        <button class="control-btn" onclick="closeRightPanel()" title="關閉">✕</button>
                    </div>
                </div>
                <div class="panel-content" id="originalContent">
                    <div class="loading">載入中...</div>
                </div>
            </div>
        </div>
        
        <script>
            // 報告內容（使用 JSON 格式最安全）
            const reportLines = {json_lines};
            
            // 初始化
            document.addEventListener('DOMContentLoaded', function() {{
                processReportContent();
            }});
            
            // 處理報告內容
            function processReportContent() {{
                const container = document.getElementById('reportContent');
                container.innerHTML = '';
                
                reportLines.forEach(function(line) {{
                    const div = document.createElement('div');
                    div.className = 'report-line';
                    
                    // 處理特殊格式
                    let processedLine = line;
                    
                    // 將 "查看原始檔案" 轉換為連結
                    if (line.includes('🔗 查看原始檔案:')) {{
                        processedLine = line.replace(
                            /🔗 查看原始檔案: (.+)/,
                            '🔗 <a class="view-original" onclick="openOriginalFile()">查看原始檔案: $1</a>'
                        );
                    }}
                    
                    // 高亮關鍵字
                    processedLine = processedLine.replace(/ANR 類型: (.+)/, 'ANR 類型: <span class="anr-type">$1</span>');
                    processedLine = processedLine.replace(/進程名稱: (.+)/, '進程名稱: <span class="process-name">$1</span>');
                    processedLine = processedLine.replace(/發生時間: (.+)/, '發生時間: <span class="timestamp">$1</span>');
                    
                    // 處理分隔線
                    if (/^=+$/.test(processedLine)) {{
                        processedLine = '<span class="separator">' + processedLine + '</span>';
                    }}
                    
                    div.innerHTML = processedLine;
                    container.appendChild(div);
                }});
            }}
            
            // 開啟原始檔案
            function openOriginalFile() {{
                const rightPanel = document.getElementById('rightPanel');
                const splitter = document.getElementById('splitter');
                
                rightPanel.classList.add('open');
                splitter.classList.add('visible');
                
                loadOriginalFile();
            }}
            
            // 載入原始檔案
            async function loadOriginalFile() {{
                try {{
                    const response = await fetch('{original_file}');
                    const text = await response.text();
                    
                    const contentDiv = document.getElementById('originalContent');
                    contentDiv.innerHTML = '';
                    
                    const pre = document.createElement('pre');
                    pre.className = 'original-content';
                    pre.textContent = text;
                    
                    contentDiv.appendChild(pre);
                }} catch (error) {{
                    document.getElementById('originalContent').innerHTML = 
                        '<div class="loading">載入失敗: ' + error.message + '</div>';
                }}
            }}
            
            // 關閉右側面板
            function closeRightPanel() {{
                const rightPanel = document.getElementById('rightPanel');
                const splitter = document.getElementById('splitter');
                
                rightPanel.classList.remove('open');
                splitter.classList.remove('visible');
            }}
            
            // 全屏切換
            function toggleFullscreen(panelId) {{
                const panel = document.getElementById(panelId);
                panel.classList.toggle('fullscreen');
            }}
            
            // 分割條拖動
            let isResizing = false;
            
            document.getElementById('splitter').addEventListener('mousedown', function(e) {{
                isResizing = true;
                document.body.style.cursor = 'col-resize';
                e.preventDefault();
            }});
            
            document.addEventListener('mousemove', function(e) {{
                if (!isResizing) return;
                
                const container = document.querySelector('.split-container');
                const leftPanel = document.getElementById('leftPanel');
                const rightPanel = document.getElementById('rightPanel');
                
                const containerWidth = container.offsetWidth;
                const leftWidth = e.clientX;
                const leftPercent = (leftWidth / containerWidth) * 100;
                
                if (leftPercent > 20 && leftPercent < 80) {{
                    leftPanel.style.flex = '0 0 ' + leftPercent + '%';
                    rightPanel.style.flex = '0 0 ' + (100 - leftPercent) + '%';
                }}
            }});
            
            document.addEventListener('mouseup', function() {{
                isResizing = false;
                document.body.style.cursor = 'default';
            }});
            
            // ESC 退出全屏
            document.addEventListener('keydown', function(e) {{
                if (e.key === 'Escape') {{
                    document.querySelectorAll('.fullscreen').forEach(function(el) {{
                        el.classList.remove('fullscreen');
                    }});
                }}
            }});
        </script>
    </body>
    </html>"""

    def _update_index(self, index_data: Dict, rel_path: str, analyzed_file: str, original_file: str):
        """更新索引 - 使用絕對路徑"""
        parts = rel_path.split(os.sep)
        current = index_data
        
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        
        filename = parts[-1]
        
        # 根據分析檔案的實際格式建立索引鍵
        if analyzed_file.endswith('.html'):
            index_key = filename + '.analyzed.html'
        else:
            index_key = filename + '.analyzed.txt'
        
        # 儲存絕對路徑而不是相對路徑
        current[index_key] = {
            'analyzed_file': os.path.abspath(analyzed_file),  # 使用絕對路徑
            'original_file': os.path.abspath(original_file)   # 使用絕對路徑
        }
    
    def _generate_index(self, index_data: Dict):
        """生成 HTML 索引"""
        print(f"\n📊 最終索引數據結構:")
        print(json.dumps(index_data, indent=2, ensure_ascii=False)[:1000])
        print("...")
        
        # 統計實際的 HTML 檔案
        anr_html_count = 0
        tombstone_html_count = 0
        
        # 收集所有分析報告用於相似度分析
        analyzed_reports = []
        
        for root, dirs, files in os.walk(self.output_folder):
            for file in files:
                if file.endswith('.analyzed.html'):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(root, self.output_folder).lower()
                    
                    # 讀取分析報告內容
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            # 提取分析報告的關鍵信息
                            report_info = self._extract_report_info(content, full_path)
                            if report_info:
                                analyzed_reports.append(report_info)
                    except Exception as e:
                        print(f"讀取報告失敗: {full_path} - {e}")
                    
                    if 'anr' in rel_path:
                        anr_html_count += 1
                    elif 'tombstone' in rel_path:
                        tombstone_html_count += 1
        
        # 更新統計數據
        self.stats['anr_count'] = anr_html_count
        self.stats['tombstone_count'] = tombstone_html_count
        
        # 進行相似度分析
        similarity_groups = self._analyze_similarity(analyzed_reports)
        
        html_content = self._generate_html_index(index_data, similarity_groups)
        
        index_file = os.path.join(self.output_folder, 'index.html')
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"\n📝 已生成索引檔案: {index_file}")
    
    def _get_original_styles(self) -> str:
        """獲取原始樣式（保持不變）"""
        return """
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            :root {
                --bg-primary: #212121;
                --bg-secondary: #2a2a2a;
                --bg-hover: #343434;
                --text-primary: #ececec;
                --text-secondary: #a0a0a0;
                --text-muted: #6e6e6e;
                --border: #424242;
                --accent: #10a37f;
                --accent-hover: #0e8e6f;
                --anr-color: #ff9800;
                --tombstone-color: #ab47bc;
                --shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
                --radius: 8px;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
                background: var(--bg-primary);
                color: var(--text-primary);
                line-height: 1.6;
                min-height: 100vh;
            }
            
            .container {
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
            }
            
            /* Header */
            .header {
                text-align: center;
                padding: 60px 0 40px;
                border-bottom: 1px solid var(--border);
                margin-bottom: 40px;
            }
            
            .header h1 {
                font-size: 32px;
                font-weight: 600;
                margin-bottom: 12px;
                color: var(--text-primary);
            }
            
            .header .subtitle {
                font-size: 16px;
                color: var(--text-secondary);
            }
            
            /* Stats */
            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 16px;
                margin: 40px 0;
            }
            
            .stat-card {
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                padding: 20px;
                text-align: center;
                transition: all 0.2s ease;
            }
            
            .stat-card:hover {
                border-color: var(--accent);
                transform: translateY(-2px);
            }
            
            .stat-value {
                font-size: 28px;
                font-weight: 600;
                color: var(--accent);
            }
            
            .stat-label {
                font-size: 14px;
                color: var(--text-secondary);
                margin-top: 4px;
            }
            
            /* File Browser */
            .file-browser {
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                overflow: hidden;
            }
            
            /* File Item */
            .file-item {
                border-bottom: 1px solid var(--border);
                position: relative;
                transition: background 0.2s ease;
            }
            
            .file-item:last-child {
                border-bottom: none;
            }
            
            .file-item:hover {
                background: var(--bg-hover);
            }
            
            .file-link {
                display: block;
                text-decoration: none;
                color: inherit;
            }
            
            .file-content {
                padding: 16px 20px;
                display: flex;
                align-items: center;
                gap: 12px;
            }
            
            .file-icon {
                font-size: 24px;
                flex-shrink: 0;
            }
            
            .file-info {
                flex: 1;
                min-width: 0;
            }
            
            .file-name {
                font-size: 14px;
                color: var(--text-primary);
                margin-bottom: 4px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            
            .file-meta {
                display: flex;
                align-items: center;
                gap: 12px;
                font-size: 12px;
                color: var(--text-secondary);
            }
            
            .file-type {
                padding: 2px 8px;
                border-radius: 4px;
                font-weight: 500;
                text-transform: uppercase;
                font-size: 11px;
            }
            
            .file-type-anr {
                background: rgba(255, 152, 0, 0.15);
                color: var(--anr-color);
            }
            
            .file-type-tombstone {
                background: rgba(171, 71, 188, 0.2);
                color: var(--tombstone-color);
            }
            
            .source-link {
                position: absolute;
                right: 20px;
                top: 50%;
                transform: translateY(-50%);
                color: var(--text-secondary);
                padding: 8px;
                border-radius: 4px;
                transition: all 0.2s ease;
                opacity: 0;
            }
            
            .file-item:hover .source-link {
                opacity: 1;
            }
            
            .source-link:hover {
                color: var(--text-primary);
                background: var(--bg-hover);
            }
            
            /* Folder */
            .folder-item {
                border-bottom: 1px solid var(--border);
            }
            
            .folder-header {
                padding: 16px 20px;
                display: flex;
                align-items: center;
                gap: 12px;
                cursor: pointer;
                user-select: none;
                transition: background 0.2s ease;
            }
            
            .folder-header:hover {
                background: var(--bg-hover);
            }
            
            .folder-arrow {
                color: var(--text-secondary);
                transition: transform 0.2s ease;
                flex-shrink: 0;
            }
            
            .folder-arrow.open {
                transform: rotate(90deg);
            }
            
            .folder-icon {
                font-size: 20px;
                flex-shrink: 0;
            }
            
            .folder-name {
                font-size: 14px;
                color: var(--text-primary);
                flex: 1;
            }
            
            .folder-count {
                font-size: 12px;
                color: var(--text-muted);
                background: var(--bg-primary);
                padding: 2px 8px;
                border-radius: 12px;
            }
            
            .folder-content {
                background: rgba(0, 0, 0, 0.2);
            }
            
            .folder-content .file-item {
                margin-left: 32px;
            }
            
            /* Footer */
            .footer {
                text-align: center;
                padding: 40px 0;
                color: var(--text-secondary);
                font-size: 14px;
            }
            
            /* Responsive */
            @media (max-width: 768px) {
                .container {
                    padding: 16px;
                }
                
                .header {
                    padding: 40px 0 30px;
                }
                
                .header h1 {
                    font-size: 24px;
                }
                
                .stats {
                    grid-template-columns: repeat(2, 1fr);
                    gap: 12px;
                }
                
                .file-content {
                    padding: 14px 16px;
                }
                
                .source-link {
                    opacity: 1;
                    right: 16px;
                }
            }

            /* Controls */
            .controls {
                display: flex;
                gap: 12px;
                margin-bottom: 20px;
            }

            .control-btn {
                display: flex;
                align-items: center;
                gap: 6px;
                padding: 8px 16px;
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                color: var(--text-primary);
                font-size: 14px;
                cursor: pointer;
                transition: all 0.2s ease;
            }

            .control-btn:hover {
                background: var(--bg-hover);
                border-color: var(--accent);
            }

            .control-btn:active {
                transform: scale(0.98);
            }

            .control-btn svg {
                flex-shrink: 0;
            }

            .file-formats {
                display: inline-flex;
                gap: 8px;
            }

            .file-formats a {
                text-decoration: none;
                opacity: 0.7;
                transition: opacity 0.2s;
            }

            .file-formats a:hover {
                opacity: 1;
            }
        """
            
    def _generate_html_index(self, index_data: Dict, similarity_groups: List[Dict] = None) -> str:
        """生成 HTML 索引內容 - Dark ChatGPT 風格"""
        def render_tree(data, prefix=""):
            html_str = ""
            for name, value in sorted(data.items()):
                if isinstance(value, dict) and 'analyzed_file' in value:
                    # 檔案項目
                    # 現在 value['analyzed_file'] 和 value['original_file'] 已經是絕對路徑
                    analyzed_path = value['analyzed_file']
                    original_path = value['original_file']
                    
                    # 檢查是否有 HTML 版本
                    is_html = analyzed_path.endswith('.html')
                    file_type = 'anr' if 'anr' in name.lower() else 'tombstone'
                    icon = '⚠️' if file_type == 'anr' else '💥'
                    
                    # 使用新的查看器，傳遞絕對路徑
                    html_str += f'''
                    <div class="file-item {file_type}-item">
                        <a href="/view-analysis?path={html.escape(analyzed_path)}" class="file-link">
                            <div class="file-content">
                                <span class="file-icon">{icon}</span>
                                <div class="file-info">
                                    <div class="file-name">
                                        {html.escape(name)}
                                    </div>
                                    <div class="file-meta">
                                        <span class="file-type file-type-{file_type}">{file_type.upper()}</span>
                                        <span class="file-size">點擊查看分析</span>
                                    </div>
                                </div>
                            </div>
                        </a>
                        <a href="/view-analysis?path={html.escape(original_path)}.analyzed.html" target="_blank" class="source-link" title="查看原始檔案">
                            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                                <path d="M6.22 8.72a.75.75 0 001.06 1.06l5.22-5.22v1.69a.75.75 0 001.5 0v-3.5a.75.75 0 00-.75-.75h-3.5a.75.75 0 000 1.5h1.69L6.22 8.72z" fill="currentColor"/>
                                <path d="M3.5 6.75v7.5c0 .414.336.75.75.75h7.5a.75.75 0 00.75-.75v-7.5a.75.75 0 00-1.5 0v6.75h-6v-6.75a.75.75 0 00-1.5 0z" fill="currentColor"/>
                            </svg>
                        </a>
                    </div>
                    '''
                elif isinstance(value, dict):
                    # 目錄項目（保持不變）
                    folder_id = f"folder-{prefix}-{name}".replace('/', '-').replace(' ', '-')
                    file_count = _count_files(value)
                    html_str += f'''
                    <div class="folder-item">
                        <div class="folder-header" onclick="toggleFolder('{folder_id}')">
                            <svg class="folder-arrow" id="arrow-{folder_id}" width="16" height="16" viewBox="0 0 16 16">
                                <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" fill="none"/>
                            </svg>
                            <span class="folder-icon">📁</span>
                            <span class="folder-name">{html.escape(name)}</span>
                            <span class="folder-count">{file_count}</span>
                        </div>
                        <div class="folder-content" id="{folder_id}">
                            {render_tree(value, prefix + '/' + name)}
                        </div>
                    </div>
                    '''
            return html_str

        def render_similarity_groups(groups):
            if not groups:
                return '<p>沒有發現相似問題</p>'
            
            html_str = ''
            for group in groups:
                html_str += f'''
                <div class="similarity-group" id="{group['group_id']}">
                    <div class="group-header" onclick="toggleGroup('{group['group_id']}')">
                        <svg class="group-arrow open" id="arrow-{group['group_id']}" width="16" height="16" viewBox="0 0 16 16">
                            <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" fill="none"/>
                        </svg>
                        <span class="group-icon">📋</span>
                        <span class="group-title">{html.escape(group['title'])}</span>
                        <span class="group-info">
                            {group['count']} 個相似檔案 (信心度: {group['similarity']:.0f}%)
                        </span>
                    </div>
                    <div class="group-content" id="content-{group['group_id']}" style="display: block;">
                '''
                
                # 渲染組內的報告
                for report in group['reports']:
                    report_id = f"report_{group['group_id']}_{report['filename'].replace('.', '_')}"
                    escaped_filename = html.escape(report['filename'])
                    
                    # 讀取檔案內容並轉換為 data URL
                    try:
                        # 如果已經有內容，直接使用
                        if 'content' in report and report['content']:
                            report_content = report['content']
                        else:
                            # 否則從檔案讀取
                            with open(report['path'], 'r', encoding='utf-8') as f:
                                report_content = f.read()
                        
                        # Base64 編碼
                        import base64
                        encoded_content = base64.b64encode(report_content.encode('utf-8')).decode('utf-8')
                        iframe_src = f"data:text/html;charset=utf-8;base64,{encoded_content}"
                    except Exception as e:
                        print(f"無法讀取檔案 {report['path']}: {e}")
                        # 顯示錯誤訊息
                        error_html = f'<html><body><p style="color: red;">無法載入檔案: {escaped_filename}</p></body></html>'
                        encoded_error = base64.b64encode(error_html.encode('utf-8')).decode('utf-8')
                        iframe_src = f"data:text/html;charset=utf-8;base64,{encoded_error}"
                    
                    html_str += f'''
                    <div class="similarity-item">
                        <div class="report-header" onclick="toggleReport('{report_id}')">
                            <svg class="report-arrow open" id="arrow-{report_id}" width="16" height="16" viewBox="0 0 16 16">
                                <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" fill="none"/>
                            </svg>
                            <span class="report-icon">📄</span>
                            <span class="report-name">{escaped_filename}</span>
                        </div>
                        <div class="report-content" id="content-{report_id}" style="display: block;">
                            <iframe src="{iframe_src}" 
                                    class="report-iframe"
                                    style="width: 100%; min-height: 600px; border: 1px solid #ddd; background: white;"
                                    onload="adjustIframeHeight(this)">
                            </iframe>
                        </div>
                    </div>
                    '''
                
                html_str += '''
                    </div>
                </div>
                '''
            
            return html_str
                        
        # 計算統計數據
        def _count_files(data):
            count = 0
            for value in data.values():
                if isinstance(value, dict):
                    if 'analyzed_file' in value:
                        count += 1
                    else:
                        count += _count_files(value)
            return count
        
        # 主 HTML 模板
        return f"""<!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Android Log 分析報告</title>
        <style>
            /* 保留原有的樣式 */
            {self._get_original_styles()}
            
            /* 新增相似問題視圖的樣式 */
            .view-mode {{
                display: none;
            }}
            
            .view-mode.active {{
                display: block;
            }}
            
            .similarity-group {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                margin-bottom: 16px;
                overflow: hidden;
            }}
            
            .group-header {{
                padding: 16px 20px;
                display: flex;
                align-items: center;
                gap: 12px;
                cursor: pointer;
                user-select: none;
                transition: background 0.2s ease;
                background: rgba(255, 152, 0, 0.1);
            }}
            
            .group-header:hover {{
                background: rgba(255, 152, 0, 0.2);
            }}
            
            .group-arrow {{
                color: var(--text-secondary);
                transition: transform 0.2s ease;
                flex-shrink: 0;
            }}
            
            .group-arrow.open {{
                transform: rotate(90deg);
            }}
            
            .group-icon {{
                font-size: 20px;
                flex-shrink: 0;
            }}
            
            .group-title {{
                font-size: 16px;
                font-weight: 600;
                color: var(--text-primary);
                flex: 1;
            }}
            
            .group-info {{
                font-size: 13px;
                color: var(--text-secondary);
                background: var(--bg-primary);
                padding: 4px 12px;
                border-radius: 16px;
            }}
            
            .group-content {{
                background: rgba(0, 0, 0, 0.2);
            }}
            
            .similarity-item {{
                border-bottom: 1px solid var(--border);
            }}
            
            .similarity-item:last-child {{
                border-bottom: none;
            }}
            
            .report-header {{
                padding: 12px 20px 12px 40px;
                display: flex;
                align-items: center;
                gap: 8px;
                cursor: pointer;
                transition: background 0.2s ease;
            }}
            
            .report-header:hover {{
                background: var(--bg-hover);
            }}
            
            .report-arrow {{
                color: var(--text-secondary);
                transition: transform 0.2s ease;
                flex-shrink: 0;
            }}
            
            .report-arrow.open {{
                transform: rotate(90deg);
            }}
            
            .report-icon {{
                font-size: 16px;
            }}
            
            .report-name {{
                font-size: 14px;
                color: var(--text-primary);
            }}
            
            .report-content {{
                padding: 0;
                background: var(--bg-primary);
            }}
            
            .report-iframe {{
                width: 100%;
                height: 600px;
                border: none;
                display: block;
            }}
            
            .view-toggle {{
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 8px 16px;
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                color: var(--text-primary);
                font-size: 14px;
                cursor: pointer;
                transition: all 0.2s ease;
            }}
            
            .view-toggle:hover {{
                background: var(--bg-hover);
                border-color: var(--accent);
            }}
            
            .view-toggle.active {{
                background: var(--accent);
                color: white;
                border-color: var(--accent);
            }}

            .iframe-error {{
                padding: 40px;
                text-align: center;
                color: var(--text-secondary);
                background: rgba(255, 0, 0, 0.1);
                border-radius: var(--radius);
                margin: 20px;
            }}

            .iframe-error p {{
                margin: 10px 0;
            }}

            .report-iframe {{
                width: 100%;
                min-height: 600px;
                max-height: 1000px;
                border: none;
                display: block;
                background: var(--bg-primary);
            }}

        </style>
    </head>
    <body>
        <div class="container">
            <header class="header">
                <h1>Android Log 分析報告</h1>
                <p class="subtitle">智能分析系統 • 深度解析 ANR 和 Tombstone 問題</p>
            </header>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{self.stats['anr_count']}</div>
                    <div class="stat-label">ANR 檔案</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{self.stats['tombstone_count']}</div>
                    <div class="stat-label">Tombstone 檔案</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{self.stats['anr_count'] + self.stats['tombstone_count']}</div>
                    <div class="stat-label">總檔案數</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{self.stats['total_time']:.1f}s</div>
                    <div class="stat-label">分析時間</div>
                </div>
            </div>
            
            <div class="controls">
                <button onclick="expandAll()" class="control-btn">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                        <path d="M3 6l5 5 5-5" stroke="currentColor" stroke-width="1.5"/>
                    </svg>
                    全部展開
                </button>
                <button onclick="collapseAll()" class="control-btn">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                        <path d="M3 10l5-5 5 5" stroke="currentColor" stroke-width="1.5"/>
                    </svg>
                    全部收合
                </button>
                <button onclick="toggleView('similarity')" class="view-toggle" id="similarityBtn">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                        <path d="M8 2v6m0 0l3-3m-3 3L5 5m7 6v2a1 1 0 01-1 1H5a1 1 0 01-1-1v-2" stroke="currentColor" stroke-width="1.5"/>
                    </svg>
                    相似問題
                </button>
            </div>
            
            <!-- 檔案瀏覽視圖 -->
            <main class="file-browser view-mode active" id="fileView">
                {render_tree(index_data)}
            </main>
            
            <!-- 相似問題視圖 -->
            <main class="similarity-view view-mode" id="similarityView">
                {render_similarity_groups(similarity_groups)}
            </main>
            
            <footer class="footer">
                <p>生成時間: {time.strftime('%Y-%m-%d %H:%M:%S')} • Android Log Analyzer v5</p>
            </footer>
        </div>
        
        <script>
            let currentView = 'file';
            
            function toggleView(view) {{
                const fileView = document.getElementById('fileView');
                const similarityView = document.getElementById('similarityView');
                const similarityBtn = document.getElementById('similarityBtn');
                
                if (view === 'similarity') {{
                    if (currentView === 'similarity') {{
                        // 切換回檔案視圖
                        fileView.classList.add('active');
                        similarityView.classList.remove('active');
                        similarityBtn.classList.remove('active');
                        currentView = 'file';
                    }} else {{
                        // 切換到相似問題視圖
                        fileView.classList.remove('active');
                        similarityView.classList.add('active');
                        similarityBtn.classList.add('active');
                        currentView = 'similarity';
                    }}
                }}
            }}
            
            function toggleFolder(folderId) {{
                const folder = document.getElementById(folderId);
                const arrow = document.getElementById('arrow-' + folderId);
                
                if (folder.style.display === 'none' || folder.style.display === '') {{
                    folder.style.display = 'block';
                    arrow.classList.add('open');
                }} else {{
                    folder.style.display = 'none';
                    arrow.classList.remove('open');
                }}
            }}
            
            function toggleGroup(groupId) {{
                const content = document.getElementById('content-' + groupId);
                const arrow = document.getElementById('arrow-' + groupId);
                
                if (content.style.display === 'none') {{
                    content.style.display = 'block';
                    arrow.classList.add('open');
                }} else {{
                    content.style.display = 'none';
                    arrow.classList.remove('open');
                }}
            }}
            
            function toggleReport(reportId) {{
                const content = document.getElementById('content-' + reportId);
                const arrow = document.getElementById('arrow-' + reportId);
                
                if (content.style.display === 'none') {{
                    content.style.display = 'block';
                    arrow.classList.add('open');
                }} else {{
                    content.style.display = 'none';
                    arrow.classList.remove('open');
                }}
            }}
            
            function expandAll() {{
                if (currentView === 'file') {{
                    // 檔案視圖的展開
                    const folders = document.querySelectorAll('.folder-content');
                    const arrows = document.querySelectorAll('.folder-arrow');
                    
                    folders.forEach(folder => {{
                        folder.style.display = 'block';
                    }});
                    
                    arrows.forEach(arrow => {{
                        arrow.classList.add('open');
                    }});
                }} else {{
                    // 相似問題視圖的展開
                    const groupContents = document.querySelectorAll('.group-content');
                    const groupArrows = document.querySelectorAll('.group-arrow');
                    const reportContents = document.querySelectorAll('.report-content');
                    const reportArrows = document.querySelectorAll('.report-arrow');
                    
                    groupContents.forEach(content => {{
                        content.style.display = 'block';
                    }});
                    
                    groupArrows.forEach(arrow => {{
                        arrow.classList.add('open');
                    }});
                    
                    reportContents.forEach(content => {{
                        content.style.display = 'block';
                    }});
                    
                    reportArrows.forEach(arrow => {{
                        arrow.classList.add('open');
                    }});
                }}
            }}
            
            function collapseAll() {{
                if (currentView === 'file') {{
                    // 檔案視圖的收合
                    const folders = document.querySelectorAll('.folder-content');
                    const arrows = document.querySelectorAll('.folder-arrow');
                    
                    folders.forEach(folder => {{
                        folder.style.display = 'none';
                    }});
                    
                    arrows.forEach(arrow => {{
                        arrow.classList.remove('open');
                    }});
                }} else {{
                    // 相似問題視圖的收合
                    const groupContents = document.querySelectorAll('.group-content');
                    const groupArrows = document.querySelectorAll('.group-arrow');
                    const reportContents = document.querySelectorAll('.report-content');
                    const reportArrows = document.querySelectorAll('.report-arrow');
                    
                    groupContents.forEach(content => {{
                        content.style.display = 'none';
                    }});
                    
                    groupArrows.forEach(arrow => {{
                        arrow.classList.remove('open');
                    }});
                    
                    reportContents.forEach(content => {{
                        content.style.display = 'none';
                    }});
                    
                    reportArrows.forEach(arrow => {{
                        arrow.classList.remove('open');
                    }});
                }}
            }}
            
            function adjustIframeHeight(iframe) {{
                try {{
                    // 嘗試自動調整 iframe 高度
                    const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
                    const height = Math.max(
                        iframeDoc.body.scrollHeight,
                        iframeDoc.documentElement.scrollHeight
                    );
                    iframe.style.height = Math.min(height + 20, 800) + 'px';
                }} catch (e) {{
                    // 跨域限制，使用固定高度
                    iframe.style.height = '600px';
                }}
            }}

            function handleIframeError(iframe, filename, path) {{
                console.error('Failed to load iframe:', filename, 'Path:', path);
                iframe.style.display = 'none';
                const errorDiv = document.createElement('div');
                errorDiv.className = 'iframe-error';
                errorDiv.innerHTML = '<p>無法載入分析報告: ' + filename + '</p>' +
                                    '<p>嘗試路徑: ' + path + '</p>' +
                                    '<p>請確認檔案是否存在</p>';
                errorDiv.style.padding = '20px';
                errorDiv.style.textAlign = 'center';
                errorDiv.style.color = '#999';
                errorDiv.style.backgroundColor = 'rgba(255,0,0,0.1)';
                errorDiv.style.borderRadius = '8px';
                errorDiv.style.margin = '20px';
                iframe.parentNode.appendChild(errorDiv);
            }}

            function adjustIframeHeight(iframe) {{
                try {{
                    // 重置高度以獲得正確的內容高度
                    iframe.style.height = '100px';
                    
                    // 等待內容載入
                    setTimeout(() => {{
                        try {{
                            const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
                            const height = Math.max(
                                iframeDoc.body.scrollHeight,
                                iframeDoc.documentElement.scrollHeight,
                                600 // 最小高度
                            );
                            iframe.style.height = Math.min(height + 50, 1000) + 'px';
                        }} catch (e) {{
                            // 跨域或其他錯誤，使用預設高度
                            iframe.style.height = '700px';
                        }}
                    }}, 100);
                }} catch (e) {{
                    iframe.style.height = '700px';
                }}
            }}

            // 預設展開檔案視圖
            document.addEventListener('DOMContentLoaded', function() {{
                expandAll();
            }});
        </script>
    </body>
    </html>"""

    def _show_statistics(self):
        """顯示統計資訊"""
        print("\n" + "=" * 60)
        print("✅ 分析完成！")
        print("=" * 60)
        
        # 統計實際生成的 HTML 檔案
        anr_html_count = 0
        tombstone_html_count = 0
        
        for root, dirs, files in os.walk(self.output_folder):
            for file in files:
                if file.endswith('.analyzed.html'):
                    # 根據路徑判斷是 ANR 還是 Tombstone
                    rel_path = os.path.relpath(root, self.output_folder).lower()
                    if 'anr' in rel_path:
                        anr_html_count += 1
                    elif 'tombstone' in rel_path:
                        tombstone_html_count += 1
        
        print(f"\n📊 分析統計:")
        print(f"  • ANR HTML 報告: {anr_html_count} 個")
        print(f"  • Tombstone HTML 報告: {tombstone_html_count} 個")
        print(f"  • 總 HTML 報告: {anr_html_count + tombstone_html_count} 個")
        print(f"  • 錯誤數量: {self.stats['error_count']} 個")
        print(f"  • 總執行時間: {self.stats['total_time']:.2f} 秒")
        
        total_html = anr_html_count + tombstone_html_count
        if total_html > 0:
            avg_time = self.stats['total_time'] / total_html
            print(f"  • 平均處理時間: {avg_time:.3f} 秒/檔案")
        
        print(f"\n🎯 輸出目錄: {self.output_folder}")
        print(f"🌐 請開啟 {os.path.join(self.output_folder, 'index.html')} 查看分析報告")

# ============= 智能分析引擎 =============
class IntelligentAnalysisEngine:
    """智能分析引擎 - 整合所有分析功能"""
    
    def __init__(self):
        self.analysis_patterns = self._init_analysis_patterns()
        self.known_issues_db = self._init_known_issues()
        
        # 延遲初始化分析器，避免循環引用
        self._analyzers_initialized = False
        self._init_analyzers_lazy()
            
    def _get_health_recommendation(self, score: int) -> str:
        """根據健康分數提供建議"""
        if score >= 80:
            return "系統運行正常，繼續保持"
        elif score >= 60:
            return "系統有輕微壓力，建議優化記憶體使用"
        elif score >= 40:
            return "系統壓力較大，需要立即優化"
        else:
            return "系統嚴重異常，需要緊急處理"
            
    def _init_analysis_patterns(self) -> Dict:
        """初始化分析模式庫"""
        return {
            'binder_deadlock_patterns': {
                'windowmanager_timeout': {
                    'signatures': [
                        'BinderProxy.transactNative',
                        'WindowManager.*getWindowInsets',
                        'system_server.*block'
                    ],
                    'root_cause': 'WindowManager 服務阻塞',
                    'severity': 'critical',
                    'solutions': [
                        '檢查 system_server 負載和 GC 狀況',
                        '分析 WindowManager 服務是否有死鎖',
                        '查看同時間的其他 Binder 調用'
                    ]
                },
                'webview_anr': {
                    'signatures': [
                        'chromium.*WebView',
                        'onDisplayChanged',
                        'WindowMetricsController'
                    ],
                    'root_cause': 'WebView 渲染引擎阻塞',
                    'severity': 'high',
                    'solutions': [
                        '檢查 WebView 版本和相容性',
                        '分析 WebView 渲染線程狀態',
                        '考慮延遲或異步載入 WebView'
                    ]
                }
            },
            'system_service_patterns': {
                'input_timeout': {
                    'signatures': [
                        'Input dispatching timed out',
                        'Waited.*ms for',
                        'FocusEvent.*hasFocus'
                    ],
                    'root_cause': 'Input 事件分發超時',
                    'severity': 'critical',
                    'solutions': [
                        '檢查主線程是否有耗時操作',
                        '分析 InputDispatcher 狀態',
                        '查看是否有 Window focus 切換問題'
                    ]
                }
            },
            'tombstone_crash_patterns': {
                'null_pointer': {
                    'signatures': ['fault addr 0x0', 'signal 11', 'SIGSEGV'],
                    'root_cause': '空指針解引用',
                    'severity': 'high',
                    'solutions': [
                        '檢查指針初始化',
                        '添加空指針檢查',
                        '使用智能指針'
                    ]
                },
                'memory_corruption': {
                    'signatures': ['malloc', 'free', 'heap corruption'],
                    'root_cause': '記憶體損壞',
                    'severity': 'critical',
                    'solutions': [
                        '使用 AddressSanitizer',
                        '檢查緩衝區溢出',
                        '避免 use-after-free'
                    ]
                }
            }
        }
    
    def _init_known_issues(self) -> Dict:
        """初始化已知問題資料庫"""
        return {
            # 通用的已知問題模式，而非特定設備
            'webview_display_change_anr': {
                'patterns': [
                    'WebView.*onDisplayChanged',
                    'WindowManager.*getWindowInsets',
                    'chromium.*TrichroneWebView'
                ],
                'description': 'WebView 在顯示配置變更時的 ANR',
                'affected_versions': ['Android 10+', 'WebView 83+'],
                'workarounds': [
                    '延遲 WebView 初始化',
                    '使用異步載入',
                    '避免在 onDisplayChanged 中進行同步操作'
                ]
            },
            'system_server_overload': {
                'patterns': [
                    'system_server.*block',
                    'InputDispatcher.*timed out',
                    'Waited.*ms for.*system_server'
                ],
                'description': 'system_server 過載導致的 ANR',
                'affected_versions': ['所有 Android 版本'],
                'workarounds': [
                    '減少同時進行的系統服務調用',
                    '使用批量操作',
                    '實施重試機制'
                ]
            },
            'binder_transaction_limit': {
                'patterns': [
                    'TransactionTooLargeException',
                    'Binder transaction.*too large',
                    'data parcel size.*bytes'
                ],
                'description': 'Binder 事務大小超限',
                'affected_versions': ['所有 Android 版本'],
                'workarounds': [
                    '減少單次傳輸的數據量',
                    '分批傳輸大數據',
                    '使用 ContentProvider 或文件傳輸'
                ]
            }
        }
    
    def _init_analyzers_lazy(self):
        """延遲初始化分析器"""
        if self._analyzers_initialized:
            return
            
        try:
            # 延遲導入
            from vp_analyze_logs_ext import (
                BinderCallChainAnalyzer, ThreadDependencyAnalyzer,
                PerformanceBottleneckDetector, TimelineAnalyzer,
                CrossProcessAnalyzer, MLAnomalyDetector, RootCausePredictor,
                RiskAssessmentEngine, TrendAnalyzer, SystemMetricsIntegrator,
                SourceCodeAnalyzer, CodeFixGenerator, ConfigurationOptimizer,
                ComparativeAnalyzer, ParallelAnalyzer, IncrementalAnalyzer,
                VisualizationGenerator, ExecutiveSummaryGenerator
            )
            
            # 初始化所有分析器
            self.binder_analyzer = BinderCallChainAnalyzer()
            self.dependency_analyzer = ThreadDependencyAnalyzer()
            self.bottleneck_detector = PerformanceBottleneckDetector()
            self.timeline_analyzer = TimelineAnalyzer()
            self.cross_process_analyzer = CrossProcessAnalyzer()
            self.anomaly_detector = MLAnomalyDetector()
            self.root_cause_predictor = RootCausePredictor()
            self.risk_engine = RiskAssessmentEngine()
            self.trend_analyzer = TrendAnalyzer()
            self.system_metrics_integrator = SystemMetricsIntegrator()
            self.source_analyzer = SourceCodeAnalyzer()
            self.fix_generator = CodeFixGenerator()
            self.config_optimizer = ConfigurationOptimizer()
            self.comparative_analyzer = ComparativeAnalyzer()
            self.parallel_analyzer = ParallelAnalyzer()
            self.incremental_analyzer = IncrementalAnalyzer()
            self.viz_generator = VisualizationGenerator()
            self.summary_generator = ExecutiveSummaryGenerator()
            
            self._analyzers_initialized = True
        except Exception as e:
            print(f"警告: 無法初始化所有分析器 - {e}")
            # 設置空的分析器以避免錯誤
            self.binder_analyzer = None
            self.dependency_analyzer = None
            self.bottleneck_detector = None
            self.timeline_analyzer = None
            self.cross_process_analyzer = None
            self.anomaly_detector = None
            self.root_cause_predictor = None
            self.risk_engine = None
            self.trend_analyzer = None
            self.system_metrics_integrator = None
            self.source_analyzer = None
            self.fix_generator = None
            self.config_optimizer = None
            self.comparative_analyzer = None
            self.parallel_analyzer = None
            self.incremental_analyzer = None
            self.viz_generator = None
            self.summary_generator = None
    
    def analyze_call_chain(self, backtrace: List[str]) -> Dict:
        """分析調用鏈，找出問題的完整脈絡"""
        analysis = {
            'call_flow': [],
            'blocking_points': [],
            'service_interactions': [],
            'potential_causes': []
        }
        
        # 建立調用流程圖
        for i, frame in enumerate(backtrace):
            # 提取關鍵資訊
            if 'BinderProxy' in frame:
                analysis['call_flow'].append({
                    'level': i,
                    'type': 'IPC',
                    'detail': 'Binder IPC 調用',
                    'target': self._extract_binder_target(frame, backtrace[i:i+3])
                })
            elif 'WindowManager' in frame:
                analysis['call_flow'].append({
                    'level': i,
                    'type': 'System Service',
                    'detail': 'WindowManager 服務調用',
                    'method': self._extract_method_name(frame)
                })
            elif 'WebView' in frame or 'chromium' in frame.lower():
                analysis['call_flow'].append({
                    'level': i,
                    'type': 'WebView',
                    'detail': 'WebView 元件',
                    'action': self._extract_webview_action(frame)
                })
        
        # 識別阻塞點
        analysis['blocking_points'] = self._identify_blocking_points(backtrace)
        
        # 分析服務交互
        analysis['service_interactions'] = self._analyze_service_interactions(backtrace)
        
        return analysis
    
    def _extract_binder_target(self, frame: str, context_frames: List[str]) -> str:
        """提取 Binder 調用的目標服務"""
        # 從後續幀中找出目標服務
        for ctx_frame in context_frames[1:]:
            if 'WindowManager' in ctx_frame:
                return 'WindowManagerService'
            elif 'ActivityManager' in ctx_frame:
                return 'ActivityManagerService'
            elif 'PackageManager' in ctx_frame:
                return 'PackageManagerService'
        return 'Unknown Service'
    
    def _extract_method_name(self, frame: str) -> str:
        """提取方法名稱"""
        match = re.search(r'\.(\w+)\(', frame)
        return match.group(1) if match else 'Unknown'
    
    def _extract_webview_action(self, frame: str) -> str:
        """提取 WebView 相關動作"""
        if 'onDisplayChanged' in frame:
            return '顯示配置變更'
        elif 'loadUrl' in frame:
            return '載入 URL'
        elif 'onDraw' in frame:
            return '渲染繪製'
        return '其他操作'
    
    def _identify_blocking_points(self, backtrace: List[str]) -> List[Dict]:
        """識別阻塞點"""
        blocking_points = []
        
        for i, frame in enumerate(backtrace[:10]):
            if 'Native method' in frame or 'transactNative' in frame:
                blocking_points.append({
                    'level': i,
                    'type': 'Native 阻塞',
                    'description': '在 Native 層等待',
                    'severity': 'high'
                })
            elif 'wait' in frame.lower() or 'park' in frame.lower():
                blocking_points.append({
                    'level': i,
                    'type': '線程等待',
                    'description': '線程被掛起等待',
                    'severity': 'medium'
                })
        
        return blocking_points
    
    def _analyze_service_interactions(self, backtrace: List[str]) -> List[Dict]:
        """分析服務交互"""
        interactions = []
        
        # 分析 Binder 調用鏈
        service_chain = []
        for frame in backtrace:
            if 'Service' in frame or 'Manager' in frame:
                service = re.search(r'(\w+(?:Service|Manager))', frame)
                if service and service.group(1) not in service_chain:
                    service_chain.append(service.group(1))
        
        # 建立交互關係
        for i in range(len(service_chain) - 1):
            interactions.append({
                'from': service_chain[i],
                'to': service_chain[i + 1],
                'type': 'Binder IPC'
            })
        
        return interactions
    
    def match_known_patterns(self, anr_info: ANRInfo) -> List[Dict]:
        """匹配已知問題模式"""
        matches = []
        
        if not anr_info.main_thread:
            return matches
        
        # 將堆疊轉為字串便於匹配
        stack_str = '\n'.join(anr_info.main_thread.backtrace)
        
        # 檢查分析模式
        for category, patterns in self.analysis_patterns.items():
            for pattern_name, pattern_info in patterns.items():
                match_count = sum(1 for sig in pattern_info['signatures']
                                if re.search(sig, stack_str, re.IGNORECASE))
                
                if match_count > 0:
                    confidence = match_count / len(pattern_info['signatures'])
                    matches.append({
                        'pattern': pattern_name,
                        'confidence': confidence,
                        'root_cause': pattern_info['root_cause'],
                        'severity': pattern_info['severity'],
                        'solutions': pattern_info['solutions']
                    })
        
        # 檢查已知問題
        for issue_name, issue_info in self.known_issues_db.items():
            if 'patterns' in issue_info:
                match_count = sum(1 for pattern in issue_info['patterns']
                                if re.search(pattern, stack_str, re.IGNORECASE))
                
                if match_count > 0:
                    confidence = match_count / len(issue_info['patterns'])
                    matches.append({
                        'pattern': issue_name,
                        'confidence': confidence,
                        'description': issue_info.get('description', ''),
                        'workarounds': issue_info.get('workarounds', [])
                    })
        
        return sorted(matches, key=lambda x: x['confidence'], reverse=True)

    def analyze_crash_pattern(self, tombstone_info: TombstoneInfo) -> Dict:
        """分析崩潰模式 - 專門為 Tombstone"""
        analysis = {
            'crash_flow': [],
            'memory_context': {},
            'crash_signature': '',
            'similar_crashes': []
        }
        
        # 分析崩潰流程
        if tombstone_info.crash_backtrace:
            for i, frame in enumerate(tombstone_info.crash_backtrace[:10]):
                frame_analysis = {
                    'level': i,
                    'pc': frame.get('pc', 'Unknown'),
                    'location': frame.get('location', 'Unknown'),
                    'symbol': frame.get('symbol'),
                    'analysis': self._analyze_crash_frame(frame)
                }
                analysis['crash_flow'].append(frame_analysis)
        
        # 分析記憶體上下文
        if tombstone_info.fault_addr:
            analysis['memory_context'] = self._analyze_memory_context(
                tombstone_info.fault_addr,
                tombstone_info.memory_map
            )
        
        # 生成崩潰簽名（用於相似崩潰匹配）
        analysis['crash_signature'] = self._generate_crash_signature(tombstone_info)
        
        return analysis

    def _analyze_crash_frame(self, frame: Dict) -> str:
        """分析崩潰幀"""
        location = frame.get('location', '')
        symbol = frame.get('symbol', '')
        
        if 'libc.so' in location:
            if 'malloc' in symbol or 'free' in symbol:
                return '記憶體管理操作'
            elif 'strlen' in symbol or 'strcpy' in symbol:
                return '字串操作'
            else:
                return '系統 C 庫調用'
        elif 'libandroid_runtime.so' in location:
            return 'Android Runtime 層'
        elif 'art::' in symbol:
            return 'ART 虛擬機'
        elif '.so' in location and 'vendor' in location:
            return '廠商庫'
        elif '.apk' in location or '.dex' in location:
            return '應用層代碼'
        
        return '未知'

    def _analyze_memory_context(self, fault_addr: str, memory_map: List[str]) -> Dict:
        """分析記憶體上下文"""
        context = {
            'fault_location': None,
            'nearby_regions': [],
            'analysis': None
        }
        
        # 檢查是否為無效地址
        if fault_addr.lower() in ['unknown', 'n/a', 'none', '']:
            context['analysis'] = '無法確定故障地址'
            return context
        
        try:
            fault_int = int(fault_addr, 16)
            
            # 特殊地址分析
            if fault_int == 0:
                context['analysis'] = '空指針訪問'
            elif fault_int < 0x1000:
                context['analysis'] = '低地址訪問，可能是空指針加偏移'
            elif fault_int == 0xdeadbaad:
                context['analysis'] = 'Android libc abort 標記'
            elif fault_int == 0xdeadbeef:
                context['analysis'] = '調試標記地址'
            
            # 查找所在記憶體區域
            for mem_line in memory_map[:50]:
                if '-' in mem_line:
                    parts = mem_line.split()
                    if parts:
                        addr_range = parts[0]
                        if '-' in addr_range:
                            start_str, end_str = addr_range.split('-')
                            try:
                                start = int(start_str, 16)
                                end = int(end_str, 16)
                                
                                if start <= fault_int <= end:
                                    context['fault_location'] = mem_line
                                    context['analysis'] = self._analyze_memory_region(parts)
                                elif abs(fault_int - start) < 0x1000 or abs(fault_int - end) < 0x1000:
                                    context['nearby_regions'].append(mem_line)
                            except:
                                pass
        except:
            pass
        
        return context

    def _analyze_memory_region(self, parts: List[str]) -> str:
        """分析記憶體區域類型"""
        if len(parts) > 6:
            region_name = parts[6]
            if '[stack]' in region_name:
                return '堆疊區域 - 可能是堆疊溢出'
            elif '[heap]' in region_name:
                return '堆區域 - 可能是堆損壞'
            elif '.so' in region_name:
                return f'共享庫區域: {region_name}'
            elif '.apk' in region_name:
                return 'APK 代碼區域'
        
        permissions = parts[1] if len(parts) > 1 else ''
        if 'r-x' in permissions:
            return '代碼段'
        elif 'rw-' in permissions:
            return '數據段'
        
        return '未知區域'

    def _generate_crash_signature(self, tombstone_info: TombstoneInfo) -> str:
        """生成崩潰簽名用於相似崩潰匹配"""
        signature_parts = []
        
        # 信號類型
        signature_parts.append(f"sig_{tombstone_info.signal.name}")
        
        # 故障地址特徵
        if tombstone_info.fault_addr in ['0x0', '0']:
            signature_parts.append("null_ptr")
        elif tombstone_info.fault_addr.startswith('0xdead'):
            signature_parts.append("debug_marker")
        
        # 頂層堆疊特徵
        if tombstone_info.crash_backtrace:
            for frame in tombstone_info.crash_backtrace[:3]:
                if frame.get('symbol'):
                    # 提取函數名
                    func_name = frame['symbol'].split('(')[0].split()[-1]
                    signature_parts.append(func_name)
        
        return "_".join(signature_parts[:5])  # 限制長度

    def match_tombstone_patterns(self, tombstone_info: TombstoneInfo) -> List[Dict]:
        """匹配 Tombstone 已知模式"""
        matches = []
        
        # 準備匹配數據
        crash_str = f"{tombstone_info.signal.name} {tombstone_info.fault_addr}"
        if tombstone_info.crash_backtrace:
            for frame in tombstone_info.crash_backtrace[:5]:
                crash_str += f" {frame.get('location', '')} {frame.get('symbol', '')}"
        
        # 檢查崩潰模式
        for pattern_name, pattern_info in self.analysis_patterns.get('tombstone_crash_patterns', {}).items():
            match_count = sum(1 for sig in pattern_info['signatures'] 
                            if sig.lower() in crash_str.lower())
            
            if match_count > 0:
                confidence = match_count / len(pattern_info['signatures'])
                if confidence >= 0.5:  # 50% 匹配度
                    matches.append({
                        'pattern': pattern_name,
                        'confidence': confidence,
                        'root_cause': pattern_info['root_cause'],
                        'severity': pattern_info['severity'],
                        'solutions': pattern_info['solutions']
                    })
        
        return sorted(matches, key=lambda x: x['confidence'], reverse=True)

    def _detect_complex_deadlock(self, all_threads: List[ThreadInfo]) -> Dict:
        """複雜死鎖檢測 - 包括跨進程死鎖"""
        deadlock_info = {
            'has_deadlock': False,
            'type': None,
            'cycles': [],
            'cross_process': False
        }
        
        # 建立等待圖
        wait_graph = {}
        lock_holders = {}
        thread_map = {t.tid: t for t in all_threads}
        
        for thread in all_threads:
            if thread.waiting_info and 'held by' in thread.waiting_info:
                # 解析等待資訊
                match = re.search(r'held by (?:thread\s+)?(\d+)', thread.waiting_info)
                if match:
                    wait_graph[thread.tid] = match.group(1)
                
                # 檢查是否在等待其他進程
                cross_match = re.search(r'held by tid=(\d+) in process (\d+)', thread.waiting_info)
                if cross_match:
                    deadlock_info['cross_process'] = True
            
            # 記錄鎖持有者
            for lock in thread.held_locks:
                lock_holders[lock] = thread.tid
        
        # 使用 Tarjan 算法檢測強連通分量（循環）
        cycles = self._tarjan_scc(wait_graph)
        
        if cycles:
            deadlock_info['has_deadlock'] = True
            deadlock_info['type'] = 'circular_wait'
            
            # 轉換循環為線程資訊
            for cycle in cycles:
                cycle_info = []
                for tid in cycle:
                    if tid in thread_map:
                        thread = thread_map[tid]
                        cycle_info.append({
                            'tid': tid,
                            'name': thread.name,
                            'state': thread.state.value,
                            'waiting_on': thread.waiting_locks[0] if thread.waiting_locks else None
                        })
                
                if cycle_info:
                    deadlock_info['cycles'].append(cycle_info)
        
        # 檢查其他類型的死鎖
        # 1. 優先級反轉
        high_prio_waiting = []
        low_prio_holding = []
        
        for thread in all_threads:
            if thread.prio and thread.prio.isdigit():
                prio = int(thread.prio)
                if prio <= 5 and thread.waiting_locks:  # 高優先級等待
                    high_prio_waiting.append(thread)
                elif prio >= 8 and thread.held_locks:  # 低優先級持有
                    low_prio_holding.append(thread)
        
        # 檢查是否有優先級反轉
        for high_thread in high_prio_waiting:
            for low_thread in low_prio_holding:
                if any(lock in low_thread.held_locks for lock in high_thread.waiting_locks):
                    if not deadlock_info['has_deadlock']:
                        deadlock_info['has_deadlock'] = True
                        deadlock_info['type'] = 'priority_inversion'
                    break
        
        # 儲存結果供後續使用
        self._last_deadlock_cycles = deadlock_info.get('cycles', [])
        
        return deadlock_info

    def _tarjan_scc(self, graph: Dict[str, str]) -> List[List[str]]:
        """使用 Tarjan 算法尋找強連通分量（用於死鎖檢測）"""
        index_counter = [0]
        stack = []
        lowlinks = {}
        index = {}
        on_stack = {}
        sccs = []
        
        def strongconnect(node):
            index[node] = index_counter[0]
            lowlinks[node] = index_counter[0]
            index_counter[0] += 1
            stack.append(node)
            on_stack[node] = True
            
            # 考慮後繼節點
            if node in graph:
                successor = graph[node]
                if successor not in index:
                    strongconnect(successor)
                    lowlinks[node] = min(lowlinks[node], lowlinks[successor])
                elif on_stack.get(successor, False):
                    lowlinks[node] = min(lowlinks[node], index[successor])
            
            # 如果節點是根節點，則彈出堆疊並生成 SCC
            if lowlinks[node] == index[node]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    scc.append(w)
                    if w == node:
                        break
                # 只返回包含多個節點的 SCC（這些是循環）
                if len(scc) > 1:
                    sccs.append(scc)
        
        # 對圖中的每個節點調用算法
        for node in graph:
            if node not in index:
                strongconnect(node)
        
        return sccs
    
    def _detect_watchdog_timeout(self, content: str) -> Optional[Dict]:
        """檢測 Watchdog 超時"""
        watchdog_patterns = [
            r'Watchdog.*detected.*deadlock',
            r'WATCHDOG.*TIMEOUT',
            r'system_server.*anr.*Trace\.txt'
        ]
        
        for pattern in watchdog_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return {
                    'type': 'Watchdog Timeout',
                    'severity': 'critical',
                    'description': 'System server 可能發生死鎖或嚴重阻塞'
                }
        
        return None

    def _identify_crashlytics_tags(self, thread_info: ThreadInfo) -> List[str]:
        """識別 Firebase Crashlytics 風格的標籤"""
        tags = []
        
        # Triggered ANR
        if thread_info.state == ThreadState.BLOCKED and thread_info.tid == "1":
            tags.append("Triggered ANR")
        
        # Root blocking
        if thread_info.held_locks and not thread_info.waiting_locks:
            tags.append("Root blocking")
        
        # IO Root blocking
        for frame in thread_info.backtrace[:5]:
            if any(io in frame for io in ['FileInputStream', 'FileOutputStream', 'fdatasync']):
                tags.append("IO Root blocking")
                break
        
        # Deadlocked
        if self._is_in_deadlock(thread_info):
            tags.append("Deadlocked")
        
        return tags

    def _is_in_deadlock(self, thread_info: ThreadInfo) -> bool:
        """檢查線程是否在死鎖中"""
        # 如果線程在等待鎖，且該鎖被其他線程持有
        if thread_info.waiting_info and 'held by' in thread_info.waiting_info:
            # 簡單檢查：如果等待資訊中包含死鎖相關關鍵字
            deadlock_keywords = ['deadlock', 'circular', 'cycle']
            if any(keyword in thread_info.waiting_info.lower() for keyword in deadlock_keywords):
                return True
            
            # 如果有等待鎖且狀態是 BLOCKED
            if thread_info.state == ThreadState.BLOCKED and thread_info.waiting_locks:
                return True
        
        return False
    
    def _detect_strictmode_violations(self, content: str) -> List[Dict]:
        """檢測 StrictMode 違規"""
        violations = []
        
        strictmode_patterns = {
            'DiskReadViolation': '主線程磁碟讀取',
            'DiskWriteViolation': '主線程磁碟寫入',
            'NetworkViolation': '主線程網路操作',
            'CustomSlowCallViolation': '自定義慢調用',
            'ResourceMismatchViolation': '資源不匹配'
        }
        
        for violation_type, description in strictmode_patterns.items():
            if violation_type in content:
                violations.append({
                    'type': violation_type,
                    'description': description,
                    'suggestion': '將操作移至背景線程'
                })
        
        return violations

    def _analyze_gc_impact(self, content: str) -> Dict:
        """分析垃圾回收的影響"""
        gc_info = {
            'gc_count': 0,
            'total_pause_time': 0,
            'concurrent_gc': 0,
            'explicit_gc': 0,
            'alloc_gc': 0,
            'impact': 'low'
        }
        
        # 解析 GC 日誌
        gc_patterns = [
            r'GC_FOR_ALLOC.*?paused\s+(\d+)ms',
            r'GC_CONCURRENT.*?paused\s+(\d+)ms\+(\d+)ms',
            r'GC_EXPLICIT.*?paused\s+(\d+)ms',
            r'Clamp target GC heap'
        ]
        
        for pattern in gc_patterns:
            matches = re.findall(pattern, content)
            gc_info['gc_count'] += len(matches)
            
            # 計算總暫停時間
            for match in matches:
                if isinstance(match, tuple):
                    gc_info['total_pause_time'] += sum(int(x) for x in match)
                else:
                    gc_info['total_pause_time'] += int(match)
        
        # 評估影響
        if gc_info['total_pause_time'] > 1000:  # 超過1秒
            gc_info['impact'] = 'high'
        elif gc_info['total_pause_time'] > 500:  # 超過500ms
            gc_info['impact'] = 'medium'
        
        return gc_info

    def _calculate_system_health_score(self, anr_info: ANRInfo) -> Dict:
        """計算系統健康度評分"""
        score = 100
        factors = []
        
        # CPU 使用率
        if anr_info.cpu_usage:
            cpu_total = anr_info.cpu_usage.get('total', 0)
            if cpu_total > 90:
                score -= 30
                factors.append(f"CPU 過載 ({cpu_total}%)")
            elif cpu_total > 70:
                score -= 15
                factors.append(f"CPU 偏高 ({cpu_total}%)")
        
        # 記憶體壓力
        if anr_info.memory_info:
            available = anr_info.memory_info.get('available', 0)
            if available < 100 * 1024:  # 小於 100MB
                score -= 25
                factors.append("記憶體嚴重不足")
        
        # 線程數量
        thread_count = len(anr_info.all_threads)
        if thread_count > 200:
            score -= 20
            factors.append(f"線程過多 ({thread_count})")
        
        # 阻塞線程
        blocked_count = sum(1 for t in anr_info.all_threads if t.state == ThreadState.BLOCKED)
        if blocked_count > 10:
            score -= 20
            factors.append(f"大量阻塞線程 ({blocked_count})")
        
        return {
            'score': max(0, score),
            'factors': factors,
            'recommendation': self._get_health_recommendation(score)
        }

    def _analyze_fortify_failure(self, content: str) -> Optional[Dict]:
        """分析 FORTIFY 失敗"""
        fortify_match = re.search(r'FORTIFY:\s*(.+)', content)
        if fortify_match:
            return {
                'type': 'FORTIFY Protection',
                'message': fortify_match.group(1),
                'severity': 'security',
                'suggestion': '檢查緩衝區大小和字串操作安全性'
            }
        return None
    
class HTMLReportGenerator:
    """HTML 報告生成器基類"""
    
    def __init__(self, source_linker: SourceLinker):
        self.source_linker = source_linker
        self.html_parts = []
    
    def add_section(self, title: str, content: str, section_class: str = ""):
        """添加一個區段"""
        self.html_parts.append(f'''
        <div class="section {section_class}">
            <h2>{title}</h2>
            <div class="section-content">
                {content}
            </div>
        </div>
        ''')
    
    def add_backtrace(self, title: str, backtrace: List[str], limit: int = 20):
        """添加可點擊的堆疊追蹤"""
        if not backtrace:
            self.add_section(title, "<p>無堆疊資訊</p>", "backtrace-section")
            return
        
        html_frames = []
        for i, frame in enumerate(backtrace[:limit]):
            html_frames.append(self.source_linker.create_backtrace_link(frame, i))
        
        if len(backtrace) > limit:
            html_frames.append(f'<div class="more-frames">... 還有 {len(backtrace) - limit} 幀</div>')
        
        content = f'''
        <div class="backtrace">
            {''.join(html_frames)}
        </div>
        '''
        
        self.add_section(title, content, "backtrace-section")
    
    def add_code_block(self, title: str, code: str, language: str = ""):
        """添加代碼塊，其中的內容可點擊"""
        lines = code.split('\n')
        linked_lines = []
        
        for line in lines:
            if line.strip():
                linked_line = self.source_linker.create_link(line)
                linked_lines.append(linked_line)
            else:
                linked_lines.append('')
        
        content = f'''
        <pre class="code-block {language}">
{'<br>'.join(linked_lines)}
        </pre>
        '''
        
        self.add_section(title, content, "code-section")
    
    def generate_html(self) -> str:
        """生成完整的 HTML"""
        return ''.join(self.html_parts)
                            
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