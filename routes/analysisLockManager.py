import os
import threading
from typing import Dict, Optional
from datetime import datetime, timedelta

class AnalysisLockManager:
    """管理分析路徑的鎖機制"""
    
    def __init__(self):
        self._locks: Dict[str, Dict] = {}  # 路徑 -> {lock: threading.Lock, owner: str, start_time: datetime}
        self._manager_lock = threading.Lock()  # 用於保護 _locks 字典的鎖
        self._lock_timeout = 360  # 鎖的超時時間（秒）
    
    def acquire_lock(self, path: str, owner_id: str = None) -> tuple[bool, Optional[str]]:
        """
        嘗試獲取路徑的鎖
        
        Args:
            path: 要分析的路徑
            owner_id: 鎖的擁有者ID（可以是 session ID 或用戶 ID）
            
        Returns:
            (成功與否, 錯誤訊息或None)
        """
        normalized_path = os.path.normpath(path)
        
        with self._manager_lock:
            # 清理過期的鎖
            self._cleanup_expired_locks()
            
            # 檢查是否已有鎖
            if normalized_path in self._locks:
                lock_info = self._locks[normalized_path]
                elapsed_time = (datetime.now() - lock_info['start_time']).total_seconds()
                
                # 檢查鎖是否過期
                if elapsed_time > self._lock_timeout:
                    # 過期的鎖，可以移除
                    del self._locks[normalized_path]
                else:
                    # 鎖還有效，返回等待訊息
                    remaining_time = self._lock_timeout - elapsed_time
                    return False, f"此路徑正在被其他使用者分析中，預計還需要 {int(remaining_time)} 秒。請稍後再試。"
            
            # 創建新的鎖
            self._locks[normalized_path] = {
                'lock': threading.Lock(),
                'owner': owner_id or 'unknown',
                'start_time': datetime.now()
            }
            
            return True, None
    
    def release_lock(self, path: str, owner_id: str = None):
        """釋放路徑的鎖"""
        normalized_path = os.path.normpath(path)
        
        with self._manager_lock:
            if normalized_path in self._locks:
                # 可以加入擁有者檢查，確保只有擁有者能釋放鎖
                del self._locks[normalized_path]
    
    def is_locked(self, path: str) -> bool:
        """檢查路徑是否被鎖定"""
        normalized_path = os.path.normpath(path)
        
        with self._manager_lock:
            self._cleanup_expired_locks()
            return normalized_path in self._locks
    
    def get_lock_info(self, path: str) -> Optional[Dict]:
        """獲取鎖的資訊"""
        normalized_path = os.path.normpath(path)
        
        with self._manager_lock:
            return self._locks.get(normalized_path)
    
    def _cleanup_expired_locks(self):
        """清理過期的鎖"""
        current_time = datetime.now()
        expired_paths = []
        
        for path, lock_info in self._locks.items():
            elapsed_time = (current_time - lock_info['start_time']).total_seconds()
            if elapsed_time > self._lock_timeout:
                expired_paths.append(path)
        
        for path in expired_paths:
            del self._locks[path]
