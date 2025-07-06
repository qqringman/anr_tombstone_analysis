import json
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import numpy as np
from typing import List, Dict, Optional, Tuple, Set
import hashlib
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

# ============================================================================
@dataclass
class SourceLink:
    """源碼連結資訊"""
    text: str
    file_path: str
    line_number: int
    context: str = ""
    
class SourceLinker:
    """源碼連結器 - 用於生成可跳轉的連結"""
    
    def __init__(self, original_file_path: str, output_folder: str):
        self.original_file_path = original_file_path
        self.output_folder = output_folder
        self.line_cache = {}
        self._load_file_lines()
    
    def _load_file_lines(self):
        """載入原始檔案的所有行"""
        try:
            with open(self.original_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                self.file_lines = f.readlines()
        except:
            self.file_lines = []
    
    def find_line_number(self, text: str, start_line: int = 0) -> Optional[int]:
        """查找文字在檔案中的行號"""
        if text in self.line_cache:
            return self.line_cache[text]
        
        # 清理文字
        clean_text = text.strip()
        if not clean_text:
            return None
        
        # 從 start_line 開始搜尋
        for i in range(start_line, len(self.file_lines)):
            if clean_text in self.file_lines[i]:
                self.line_cache[text] = i + 1  # 行號從 1 開始
                return i + 1
        
        # 如果沒找到，從頭搜尋
        for i in range(0, min(start_line, len(self.file_lines))):
            if clean_text in self.file_lines[i]:
                self.line_cache[text] = i + 1
                return i + 1
        
        return None
    
    def create_link(self, text: str, line_number: Optional[int] = None) -> str:
        """創建可點擊的連結"""
        if line_number is None:
            line_number = self.find_line_number(text)
        
        if line_number:
            # 生成相對路徑
            rel_path = os.path.relpath(self.original_file_path, self.output_folder)
            # 創建連結，使用 # 號傳遞行號
            link_url = f"{rel_path}#L{line_number}"
            
            # 返回 HTML 連結
            return (f'<a href="{html.escape(link_url)}" '
                   f'class="source-link" '
                   f'data-line="{line_number}" '
                   f'title="跳轉到第 {line_number} 行">'
                   f'{html.escape(text)}</a>')
        else:
            # 如果找不到行號，返回純文字
            return html.escape(text)
    
    def create_backtrace_link(self, frame: str, frame_index: int) -> str:
        """為堆疊幀創建連結"""
        line_number = self.find_line_number(frame)
        
        if line_number:
            rel_path = os.path.relpath(self.original_file_path, self.output_folder)
            link_url = f"{rel_path}#L{line_number}"
            
            # 為堆疊幀創建特殊樣式的連結
            return (f'<div class="stack-frame" data-frame-index="{frame_index}">'
                   f'<span class="frame-number">#{frame_index:02d}</span> '
                   f'<a href="{link_url}" class="frame-link" data-line="{line_number}">'
                   f'{html.escape(frame)}</a>'
                   f'</div>')
        else:
            return (f'<div class="stack-frame" data-frame-index="{frame_index}">'
                   f'<span class="frame-number">#{frame_index:02d}</span> '
                   f'<span class="frame-text">{html.escape(frame)}</span>'
                   f'</div>')

class ANRTimeouts:
    """ANR 超時時間定義"""
    INPUT_DISPATCHING = 5000  # 5秒
    SERVICE_TIMEOUT = 20000   # 20秒 (前台服務)
    SERVICE_BACKGROUND_TIMEOUT = 200000  # 200秒 (背景服務)
    BROADCAST_TIMEOUT = 10000  # 10秒 (前台廣播)
    BROADCAST_BACKGROUND_TIMEOUT = 60000  # 60秒 (背景廣播)
    CONTENT_PROVIDER_TIMEOUT = 10000  # 10秒
    JOB_SCHEDULER_TIMEOUT = 10000  # 10秒

# 擴展信號類型
class CrashSignal(Enum):
    SIGSEGV = (11, "Segmentation fault")
    SIGABRT = (6, "Abort")
    SIGILL = (4, "Illegal instruction")
    SIGBUS = (7, "Bus error")
    SIGFPE = (8, "Floating point exception")
    SIGKILL = (9, "Kill signal")
    SIGTRAP = (5, "Trace trap")
    SIGSYS = (31, "Bad system call")  # seccomp 違規
    SIGPIPE = (13, "Broken pipe")
    UNKNOWN = (0, "Unknown signal")

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

@dataclass
class ThreadInfo:
    """線程資訊"""
    name: str
    tid: str
    prio: str = "N/A"
    state: ThreadState = ThreadState.UNKNOWN
    nice: Optional[str] = None
    core: Optional[str] = None
    handle: Optional[str] = None
    backtrace: List[str] = field(default_factory=list)
    waiting_info: Optional[str] = None
    held_locks: List[str] = field(default_factory=list)
    waiting_locks: List[str] = field(default_factory=list)
    utm: Optional[str] = None  # 用戶態時間
    stm: Optional[str] = None  # 系統態時間
    schedstat: Optional[str] = None  # 調度統計
    sysTid: Optional[str] = None  # 系統線程ID
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
    timeout_info: Optional[Dict] = None  # 新增欄位

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

# ============================================================================
