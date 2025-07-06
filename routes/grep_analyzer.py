import subprocess
from collections import defaultdict
import os
import re
import threading
import time
from typing import Dict, List, Tuple
from enum import Enum
from datetime import datetime, timedelta
from collections import OrderedDict

class LogType(Enum):
    ANR = "ANR"
    TOMBSTONE = "Tombstone"
    UNKNOWN = "Unknown"

# 1. 使用有大小限制的 cache
class LimitedCache:
    def __init__(self, max_size=100, max_age_hours=24):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.max_age = timedelta(hours=max_age_hours)
        self.timestamps = {}
        self.lock = threading.Lock()
    
    def set(self, key, value):
        with self.lock:
            # 清理過期項目
            self.cleanup()
            
            # 如果超過大小限制，移除最舊的
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
                
            self.cache[key] = value
            self.timestamps[key] = datetime.now()
    
    def get(self, key):
        with self.lock:
            if key in self.cache:
                # 移到最後（LRU）
                self.cache.move_to_end(key)
                return self.cache[key]
            return None
    
    def cleanup(self):
        """清理過期的項目"""
        now = datetime.now()
        expired_keys = [
            k for k, timestamp in self.timestamps.items()
            if now - timestamp > self.max_age
        ]
        for key in expired_keys:
            self.cache.pop(key, None)
            self.timestamps.pop(key, None)

class AndroidLogAnalyzer:
    def __init__(self):
        # Support both "Cmd line:" and "Cmdline:" formats
        self.cmdline_pattern = re.compile(r'(?:Cmd line|Cmdline):\s+(.+)', re.IGNORECASE)
        self.subject_pattern = re.compile(r'Subject:\s+(.+)')
        self.timestamp_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})')
        self.use_grep = self.check_grep_availability()
        self.use_unzip = self.check_unzip_availability()
        
    def check_unzip_availability(self):
        """Check if unzip command is available"""
        try:
            result = subprocess.run(['unzip', '-v'], 
                                capture_output=True, 
                                text=True, 
                                timeout=2)
            available = result.returncode == 0
            print("✓ unzip is {}".format('available' if available else 'not available'))
            return available
        except Exception as e:
            print("✗ unzip not available: {}".format(e))
            return False

    def extract_and_process_zip_files(self, base_path: str) -> List[str]:
        """Find and extract all zip files in the given path"""
        extracted_paths = []
        
        if not self.use_unzip:
            print("✗ unzip not available, skipping zip file extraction")
            return extracted_paths
        
        print(f"\nSearching for zip files to extract...")
        
        # Find all zip files
        zip_files_found = []
        for root, dirs, files in os.walk(base_path):
            for file in files:
                if file.lower().endswith('.zip'):
                    zip_files_found.append(os.path.join(root, file))
        
        if not zip_files_found:
            print("  No zip files found")
            return extracted_paths
        
        print(f"  Found {len(zip_files_found)} zip files")
        
        for zip_path in zip_files_found:
            file = os.path.basename(zip_path)
            extract_dir = os.path.join(os.path.dirname(zip_path), f"{file}_extracted")
            
            # Skip if already extracted
            if os.path.exists(extract_dir):
                print(f"  ✓ Already extracted: {file}")
                extracted_paths.append(extract_dir)
                continue
            
            print(f"  Extracting: {file}")
            try:
                # Create extraction directory
                os.makedirs(extract_dir, exist_ok=True)
                
                # Extract using unzip command
                cmd = ['unzip', '-q', '-o', zip_path, '-d', extract_dir]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    print(f"    ✓ Successfully extracted to: {extract_dir}")
                    extracted_paths.append(extract_dir)
                else:
                    print(f"    ✗ Failed to extract: {result.stderr}")
                    # Clean up failed extraction
                    if os.path.exists(extract_dir) and not os.listdir(extract_dir):
                        os.rmdir(extract_dir)
            except subprocess.TimeoutExpired:
                print(f"    ✗ Extraction timeout")
            except Exception as e:
                print(f"    ✗ Extraction error: {e}")
        
        if extracted_paths:
            print(f"Successfully extracted/found {len(extracted_paths)} zip file contents")
        
        return extracted_paths
        
    def extract_process_name(self, cmdline: str) -> str:
        """Extract process name from command line"""
        if not cmdline:
            return None
        
        # 簡單地取第一個空格之前的內容
        # 這會保留完整路徑（如 /system/bin/vold）
        # 也會保留包名和進程後綴（如 com.google.android.apps.tv.launcherx:coreservices）
        parts = cmdline.strip().split()
        
        if parts:
            return parts[0]
        
        return None

    def extract_process_name_from_subject(self, subject_line: str) -> str:
        """從 ANR 的 Subject 行提取 process name"""
        if not subject_line:
            return None
        
        # 尋找包含 package name 的模式
        # 例如: "2511b15 com.google.android.apps.tv.launcherx/com.google.android.apps.tv.launcherx.home.HomeActivity"
        # 我們要提取斜線前面的 package name
        
        # 使用正則表達式來匹配 package name 模式
        # 匹配類似 "com.xxx.xxx" 的包名格式
        package_pattern = re.compile(r'\b([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)+)(?:/|\s)')
        match = package_pattern.search(subject_line)
        
        if match:
            return match.group(1)
        
        return None

    def debug_top_processes(self, logs: List[Dict]) -> None:
        """調試：打印實際的 Top 程序"""
        process_counts = defaultdict(int)
        
        for log in logs:
            if log.get('process'):
                process_counts[log['process']] += 1
        
        print("\n=== DEBUG: Actual Top 10 Processes ===")
        sorted_processes = sorted(process_counts.items(), key=lambda x: x[1], reverse=True)
        
        # 顯示前20個以便更好地調試
        for i, (proc, count) in enumerate(sorted_processes[:20], 1):
            print(f"{i}. {proc}: {count}")
            # 特別標記 launcherx 相關的
            if 'launcherx' in proc:
                print(f"   *** LAUNCHERX FOUND at position {i} ***")
        
        # 特別檢查 launcherx
        launcherx_entries = [(proc, count) for proc, count in process_counts.items() if 'launcherx' in proc]
        if launcherx_entries:
            print(f"\n=== All LauncherX entries ===")
            for proc, count in sorted(launcherx_entries, key=lambda x: x[1], reverse=True):
                print(f"  - {proc}: {count}")
        
        # 檢查是否有任何 log 包含 launcherx
        launcherx_logs = [log for log in logs if 'launcherx' in str(log.get('cmdline', ''))]
        print(f"\nDEBUG: Total logs with 'launcherx' in cmdline = {len(launcherx_logs)}")
        
        # 顯示總計
        print(f"\nTotal unique processes: {len(process_counts)}")
        print(f"Total log entries: {len(logs)}")
            
    def check_grep_availability(self):
        """Check if grep command is available"""
        try:
            result = subprocess.run(['grep', '--version'], 
                                capture_output=True, 
                                text=True, 
                                timeout=2)
            available = result.returncode == 0
            print(f"grep availability: {available}")
            return available
        except Exception as e:
            print(f"grep not available: {e}")
            return False
    
    def find_target_folders(self, base_path: str) -> Tuple[List[str], List[str]]:
        """Find ALL anr and tombstones folders recursively in the given path"""
        anr_folders = []
        tombstone_folders = []
        
        print(f"Searching for anr/ and tombstones/ folders in: {base_path}")
        
        # Walk through all directories recursively
        for root, dirs, files in os.walk(base_path):
            for dir_name in dirs:
                dir_lower = dir_name.lower()
                full_path = os.path.join(root, dir_name)
                
                if dir_lower == 'anr':
                    anr_folders.append(full_path)
                    print(f"  Found ANR folder: {full_path}")
                elif dir_lower in ['tombstones', 'tombstone']:
                    tombstone_folders.append(full_path)
                    print(f"  Found tombstone folder: {full_path}")
        
        # Also check if the base_path itself is anr or tombstones
        base_name = os.path.basename(base_path).lower()
        if base_name == 'anr' and base_path not in anr_folders:
            anr_folders.append(base_path)
            print(f"  Base path is ANR folder: {base_path}")
        elif base_name in ['tombstones', 'tombstone'] and base_path not in tombstone_folders:
            tombstone_folders.append(base_path)
            print(f"  Base path is tombstone folder: {base_path}")
        
        print(f"Total found: {len(anr_folders)} ANR folders, {len(tombstone_folders)} tombstone folders")
        return anr_folders, tombstone_folders
    
    def grep_cmdline_files(self, folder_path: str) -> List[Tuple[str, str, int]]:
        """Use grep to find files containing 'Cmd line:', 'Cmdline:', or 'Subject:' and extract the content with line number"""
        results = []
        
        try:
            # 判斷是否為 ANR 資料夾
            is_anr_folder = 'anr' in folder_path.lower()
            
            if is_anr_folder:
                # ANR 資料夾：搜尋 Subject:
                cmd = ['grep', '-H', '-n', '-i', '-r', 'Subject:', '.']
            else:
                # Tombstone 資料夾：搜尋 Cmd line 或 Cmdline
                cmd = ['grep', '-H', '-n', '-i', '-r', '-E', '(Cmd line|Cmdline):', '.']
            
            # Run grep in the target folder
            result = subprocess.run(cmd, 
                                cwd=folder_path,
                                capture_output=True, 
                                text=True,
                                timeout=30)
            
            if result.returncode == 0 and result.stdout.strip():
                # Parse grep output
                for line in result.stdout.strip().split('\n'):
                    if line and ':' in line:  # Ensure line is not empty and contains separator
                        # Format: filename:linenumber:content
                        parts = line.split(':', 3)  # Split into max 4 parts
                        if len(parts) >= 4:
                            filename = parts[0].lstrip('./')  # Remove ./ prefix if present
                            line_number = int(parts[1])
                            filepath = os.path.join(folder_path, filename)
                            content = parts[3] if len(parts) > 3 else parts[2]
                            
                            if is_anr_folder:
                                # 處理 ANR Subject
                                subject_match = self.subject_pattern.search(content)
                                if not subject_match:
                                    subject_match = self.subject_pattern.search(line)
                                if subject_match:
                                    subject_content = subject_match.group(1).strip()
                                    results.append((filepath, subject_content, line_number))
                            else:
                                # 處理 Tombstone Cmdline
                                cmdline_match = self.cmdline_pattern.search(content)
                                if not cmdline_match:
                                    cmdline_match = self.cmdline_pattern.search(line)
                                if cmdline_match:
                                    cmdline = cmdline_match.group(1).strip()
                                    results.append((filepath, cmdline, line_number))
                
            print(f"grep found {len(results)} files in {folder_path}")
            
        except subprocess.TimeoutExpired:
            print(f"grep timeout in {folder_path}, falling back to file reading")
        except Exception as e:
            print(f"grep error in {folder_path}: {e}")
        
        return results
    
    def extract_full_info_from_file(self, file_path: str, cmdline: str = None, line_number: int = None) -> Dict:
        """Extract full information from a file (timestamp, etc.)"""
        is_anr = 'anr' in file_path.lower()
        
        info = {
            'file': file_path,
            'filename': os.path.basename(file_path),
            'type': 'ANR' if is_anr else 'Tombstone',
            'cmdline': cmdline,
            'process': None,
            'timestamp': None,
            'filesize': 0,
            'line_number': line_number,
            'folder_path': self.shorten_folder_path(os.path.dirname(file_path))
        }
        
        # Get file size
        try:
            info['filesize'] = os.path.getsize(file_path)
        except:
            pass
        
        # Extract process name based on file type
        if cmdline:
            if is_anr:
                # ANR: 從 Subject 內容提取 process name
                info['process'] = self.extract_process_name_from_subject(cmdline)
            else:
                # Tombstone: 從 Cmdline 提取 process name
                info['process'] = self.extract_process_name(cmdline)
        
        try:
            # Read file to get timestamp and line number if not provided
            with open(file_path, 'r', errors='ignore') as f:
                lines = f.readlines()
                
                for line_no, line in enumerate(lines, 1):
                    # Extract timestamp
                    if not info['timestamp']:
                        timestamp_match = self.timestamp_pattern.search(line)
                        if timestamp_match:
                            info['timestamp'] = timestamp_match.group(1)
                    
                    # If cmdline wasn't provided by grep, extract it with line number
                    if not info['cmdline']:
                        if is_anr:
                            # ANR: 搜尋 Subject
                            subject_match = self.subject_pattern.search(line)
                            if subject_match:
                                info['cmdline'] = subject_match.group(1).strip()
                                info['line_number'] = line_no
                                info['process'] = self.extract_process_name_from_subject(info['cmdline'])
                        else:
                            # Tombstone: 搜尋 Cmdline
                            cmdline_match = self.cmdline_pattern.search(line)
                            if cmdline_match:
                                info['cmdline'] = cmdline_match.group(1).strip()
                                info['line_number'] = line_no
                                info['process'] = self.extract_process_name(info['cmdline'])
                    
                    # If we have cmdline but not line number, find it
                    elif not info['line_number'] and info['cmdline']:
                        if is_anr:
                            subject_match = self.subject_pattern.search(line)
                            if subject_match and subject_match.group(1).strip() == info['cmdline']:
                                info['line_number'] = line_no
                        else:
                            cmdline_match = self.cmdline_pattern.search(line)
                            if cmdline_match and cmdline_match.group(1).strip() == info['cmdline']:
                                info['line_number'] = line_no
            
            # Get file modification time if timestamp not found
            if not info['timestamp']:
                stat = os.stat(file_path)
                info['timestamp'] = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
        
        return info
    
    def extract_cmdline_from_file_fallback(self, file_path: str) -> Dict:
        """Fallback method: Extract cmdline by reading the entire file"""
        is_anr = 'anr' in file_path.lower()
        
        info = {
            'file': file_path,
            'filename': os.path.basename(file_path),
            'type': 'ANR' if is_anr else 'Tombstone',
            'cmdline': None,
            'process': None,
            'timestamp': None,
            'filesize': 0,
            'line_number': None,
            'folder_path': self.shorten_folder_path(os.path.dirname(file_path))
        }
        
        # Get file size
        try:
            info['filesize'] = os.path.getsize(file_path)
        except:
            pass
        
        try:
            with open(file_path, 'r', errors='ignore') as f:
                lines = f.readlines()
                
                for line_no, line in enumerate(lines, 1):
                    # Extract command line/subject with line number
                    if not info['cmdline']:
                        if is_anr:
                            # ANR: 搜尋 Subject
                            subject_match = self.subject_pattern.search(line)
                            if subject_match:
                                info['cmdline'] = subject_match.group(1).strip()
                                info['line_number'] = line_no
                                info['process'] = self.extract_process_name_from_subject(info['cmdline'])
                        else:
                            # Tombstone: 搜尋 Cmdline
                            cmdline_match = self.cmdline_pattern.search(line)
                            if cmdline_match:
                                info['cmdline'] = cmdline_match.group(1).strip()
                                info['line_number'] = line_no
                                info['process'] = self.extract_process_name(info['cmdline'])
                    
                    # Extract timestamp
                    if not info['timestamp']:
                        timestamp_match = self.timestamp_pattern.search(line)
                        if timestamp_match:
                            info['timestamp'] = timestamp_match.group(1)
                
                # Get file modification time if timestamp not found
                if not info['timestamp']:
                    stat = os.stat(file_path)
                    info['timestamp'] = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    
        except Exception as e:
            print(f"Error parsing file {file_path}: {e}")
        
        return info
    
    def analyze_logs(self, path: str) -> Dict:
        """Analyze all files in anr/ and tombstones/ folders"""
        start_time = time.time()
            
        # First, extract any zip files
        extracted_paths = self.extract_and_process_zip_files(path)
        
        # Search in original path and all extracted paths
        search_paths = [path] + extracted_paths
        all_anr_folders = []
        all_tombstone_folders = []
        
        for search_path in search_paths:
            anr_folders, tombstone_folders = self.find_target_folders(search_path)
            all_anr_folders.extend(anr_folders)
            all_tombstone_folders.extend(tombstone_folders)
        
        # Remove duplicates
        all_anr_folders = list(set(all_anr_folders))
        all_tombstone_folders = list(set(all_tombstone_folders))
        
        print(f"Total found: {len(all_anr_folders)} ANR folders, {len(all_tombstone_folders)} tombstone folders")
        print(f"Using grep: {self.use_grep}")
        
        all_logs = []
        files_with_cmdline = 0
        total_files_scanned = 0
        anr_subject_count = 0  # 新增：ANR Subject 計數器
                
        # Process ANR folders
        for anr_folder in all_anr_folders:
            if os.path.exists(anr_folder):
                folder_start = time.time()
                print(f"\nProcessing ANR folder: {anr_folder}")
                
                if self.use_grep:
                    # Use grep to quickly find files with Cmdline
                    grep_results = self.grep_cmdline_files(anr_folder)
                    
                    # Count total files in the directory
                    total_in_folder = len([f for f in os.listdir(anr_folder) 
                                        if os.path.isfile(os.path.join(anr_folder, f))])
                    total_files_scanned += total_in_folder
                    
                    if grep_results:
                        # Process grep results
                        for filepath, cmdline, line_number in grep_results:
                            log_info = self.extract_full_info_from_file(filepath, cmdline, line_number)
                            if log_info['cmdline']:
                                all_logs.append(log_info)
                                files_with_cmdline += 1
                                if log_info['type'] == 'ANR':  # 確保是 ANR 類型
                                    anr_subject_count += 1                                
                    else:
                        # Fallback to file reading if grep didn't find anything
                        print(f"  No grep results, falling back to file reading")
                        for file_name in os.listdir(anr_folder):
                            file_path = os.path.join(anr_folder, file_name)
                            if os.path.isfile(file_path):
                                log_info = self.extract_cmdline_from_file_fallback(file_path)
                                if log_info['cmdline']:
                                    all_logs.append(log_info)
                                    files_with_cmdline += 1
                                    if log_info['type'] == 'ANR':  # 確保是 ANR 類型
                                        anr_subject_count += 1
                else:
                    # No grep available, use traditional method
                    for file_name in os.listdir(anr_folder):
                        file_path = os.path.join(anr_folder, file_name)
                        if os.path.isfile(file_path):
                            total_files_scanned += 1
                            log_info = self.extract_cmdline_from_file_fallback(file_path)
                            if log_info['cmdline']:
                                all_logs.append(log_info)
                                files_with_cmdline += 1
                                if log_info['type'] == 'ANR':  # 確保是 ANR 類型
                                    anr_subject_count += 1                                
                
                print(f"  Processed in {time.time() - folder_start:.2f} seconds")
        
        # Process tombstone folders
        for tombstone_folder in all_tombstone_folders:
            if os.path.exists(tombstone_folder):
                folder_start = time.time()
                print(f"\nProcessing tombstone folder: {tombstone_folder}")
                
                if self.use_grep:
                    # Use grep to quickly find files with Cmdline
                    grep_results = self.grep_cmdline_files(tombstone_folder)
                    
                    # Count total files in the directory
                    total_in_folder = len([f for f in os.listdir(tombstone_folder) 
                                        if os.path.isfile(os.path.join(tombstone_folder, f))])
                    total_files_scanned += total_in_folder
                    
                    if grep_results:
                        # Process grep results
                        for filepath, cmdline, line_number in grep_results:
                            log_info = self.extract_full_info_from_file(filepath, cmdline, line_number)
                            if log_info['cmdline']:
                                all_logs.append(log_info)
                                files_with_cmdline += 1
                    else:
                        # Fallback to file reading
                        print(f"  No grep results, falling back to file reading")
                        for file_name in os.listdir(tombstone_folder):
                            file_path = os.path.join(tombstone_folder, file_name)
                            if os.path.isfile(file_path):
                                log_info = self.extract_cmdline_from_file_fallback(file_path)
                                if log_info['cmdline']:
                                    all_logs.append(log_info)
                                    files_with_cmdline += 1                                   
                else:
                    # No grep available, use traditional method
                    for file_name in os.listdir(tombstone_folder):
                        file_path = os.path.join(tombstone_folder, file_name)
                        if os.path.isfile(file_path):
                            total_files_scanned += 1
                            log_info = self.extract_cmdline_from_file_fallback(file_path)
                            if log_info['cmdline']:
                                all_logs.append(log_info)
                                files_with_cmdline += 1
                                if log_info['type'] == 'ANR':  # 確保是 ANR 類型
                                    anr_subject_count += 1
                
                print(f"  Processed in {time.time() - folder_start:.2f} seconds")

        total_time = time.time() - start_time
        print(f"\nTotal analysis time: {total_time:.2f} seconds")
        print(f"Total files scanned: {total_files_scanned}")
        print(f"Files with cmdline: {files_with_cmdline}")
        
        # 🔍 在這裡調用調試函數
        self.debug_top_processes(all_logs)
    
        # Generate statistics
        stats = self.generate_statistics(all_logs)
        
        # Generate file statistics
        file_stats = self.generate_file_statistics(all_logs)
        
        return {
            'logs': all_logs,
            'statistics': stats,
            'file_statistics': file_stats,
            'total_files': total_files_scanned,
            'files_with_cmdline': files_with_cmdline,
            'anr_folders': len(all_anr_folders),
            'tombstone_folders': len(all_tombstone_folders),
            'analysis_time': round(total_time, 2),
            'used_grep': self.use_grep,
            'zip_files_extracted': len(extracted_paths),
            'anr_subject_count': anr_subject_count
        }
    
    def generate_file_statistics(self, logs: List[Dict]) -> List[Dict]:
        """Generate statistics by file"""
        # 使用檔案路徑作為唯一識別，而不只是檔案名稱
        file_stats = defaultdict(lambda: {
            'type': '',
            'filesize': 0,
            'processes_count': defaultdict(int),  # 改為記錄每個程序的次數
            'timestamps': [],
            'folder_path': '',
            'filepath': ''  # 新增完整路徑
        })
        
        for log in logs:
            filepath = log['file']  # 使用完整路徑作為 key
            file_stats[filepath]['type'] = log['type']
            file_stats[filepath]['filesize'] = log['filesize']
            file_stats[filepath]['folder_path'] = log.get('folder_path', '')
            file_stats[filepath]['filepath'] = filepath
            
            # 統計每個程序在此檔案中的出現次數
            if log['process']:
                file_stats[filepath]['processes_count'][log['process']] += 1
            
            if log['timestamp']:
                file_stats[filepath]['timestamps'].append(log['timestamp'])
        
        # Convert to list
        result = []
        for filepath, stats in file_stats.items():
            # 格式化程序列表：程序名稱 (次數)
            process_list = []
            for process, count in sorted(stats['processes_count'].items()):
                process_list.append(f"{process} ({count})")
            
            # Get the earliest timestamp for this file
            timestamps = sorted(stats['timestamps']) if stats['timestamps'] else []
            
            result.append({
                'filename': os.path.basename(filepath),
                'filepath': filepath,
                'type': stats['type'],
                'count': sum(stats['processes_count'].values()),  # 總次數
                'filesize': stats['filesize'],
                'processes': process_list,  # 改為格式化的列表
                'timestamp': timestamps[0] if timestamps else '-',
                'folder_path': stats['folder_path']
            })
        
        # Sort by count descending
        result.sort(key=lambda x: x['count'], reverse=True)
        
        return result
    
    def generate_statistics(self, logs: List[Dict]) -> Dict:
        """Generate statistics from parsed logs"""
        process_count = defaultdict(int)
        cmdline_count = defaultdict(int)
        type_count = defaultdict(int)
        daily_count = defaultdict(int)
        hourly_count = defaultdict(int)
        folder_count = defaultdict(int)
            
        # 新增：按類型分開統計
        process_by_type = {
            'ANR': defaultdict(int),
            'Tombstone': defaultdict(int)
        }
        daily_by_type = {
            'ANR': defaultdict(int),
            'Tombstone': defaultdict(int)
        }
        hourly_by_type = {
            'ANR': defaultdict(int),
            'Tombstone': defaultdict(int)
        }
        
        # Summary by type and process
        type_process_count = defaultdict(int)
        
        for log in logs:
            # Ensure folder_path is set for each log
            if 'folder_path' not in log or not log['folder_path']:
                log['folder_path'] = self.shorten_folder_path(os.path.dirname(log['file']))
            
            log_type = log['type']  # ANR or Tombstone
            
            # Count by process
            if log['process']:
                process_count[log['process']] += 1
                # 按類型分開統計
                process_by_type[log_type][log['process']] += 1
            
            # Count by full cmdline
            if log['cmdline']:
                cmdline_count[log['cmdline']] += 1
            
            # Count by type
            type_count[log_type] += 1
            
            # Count by type + process combination
            if log['process']:
                key = f"{log_type}|{log['process']}"
                type_process_count[key] += 1
            
            # Count by folder
            folder_path = os.path.dirname(log['file'])
            folder_name = os.path.basename(folder_path)
            folder_count[folder_name] += 1
            
            # Count by date and hour
            if log['timestamp']:
                date = log['timestamp'].split()[0]
                hour = log['timestamp'].split()[1].split(':')[0]
                
                # 總計
                daily_count[date] += 1
                hourly_count[f"{hour}:00"] += 1
                
                # 按類型分開統計
                daily_by_type[log_type][date] += 1
                hourly_by_type[log_type][f"{hour}:00"] += 1
        
        # Get unique process names
        unique_processes = sorted(list(process_count.keys()))
        print(f"\nFound {len(unique_processes)} unique process names:")
        for proc in unique_processes[:20]:  # Show first 20
            print(f"  - {proc}: {process_count[proc]} occurrences")
        if len(unique_processes) > 20:
            print(f"  ... and {len(unique_processes) - 20} more")
        # Debug: Check if by_process and type_process_summary are consistent
        print("\n=== DEBUG: Checking data consistency ===")
        # Sum up counts from type_process_summary by process
        process_sum_from_type = defaultdict(int)
        for key, count in type_process_count.items():
            type_name, process_name = key.split('|')
            process_sum_from_type[process_name] += count

        # Compare top 10 from both sources
        print("\nTop 10 from by_process:")
        for i, (proc, count) in enumerate(sorted(process_count.items(), key=lambda x: x[1], reverse=True)[:10], 1):
            print(f"  {i}. {proc}: {count}")

        print("\nTop 10 from type_process_summary (summed):")
        for i, (proc, count) in enumerate(sorted(process_sum_from_type.items(), key=lambda x: x[1], reverse=True)[:10], 1):
            print(f"  {i}. {proc}: {count}")            
            
        # Format type_process_count for display
        type_process_summary = []
        for key, count in sorted(type_process_count.items(), key=lambda x: x[1], reverse=True):
            type_name, process_name = key.split('|')
            type_process_summary.append({
                'type': type_name,
                'process': process_name,
                'count': count
            })
        
        return {
            'by_process': dict(sorted(process_count.items(), key=lambda x: x[1], reverse=True)),
            'by_process_type': {
                'ANR': dict(sorted(process_by_type['ANR'].items(), key=lambda x: x[1], reverse=True)),
                'Tombstone': dict(sorted(process_by_type['Tombstone'].items(), key=lambda x: x[1], reverse=True))
            },
            'by_cmdline': dict(sorted(cmdline_count.items(), key=lambda x: x[1], reverse=True)[:20]),
            'by_type': dict(type_count),
            'by_date': dict(sorted(daily_count.items())),
            'by_date_type': {
                'ANR': dict(sorted(daily_by_type['ANR'].items())),
                'Tombstone': dict(sorted(daily_by_type['Tombstone'].items()))
            },
            'by_hour': dict(sorted(hourly_count.items())),
            'by_hour_type': {
                'ANR': dict(sorted(hourly_by_type['ANR'].items())),
                'Tombstone': dict(sorted(hourly_by_type['Tombstone'].items()))
            },
            'by_folder': dict(sorted(folder_count.items(), key=lambda x: x[1], reverse=True)),
            'unique_processes': unique_processes,
            'total_unique_processes': len(unique_processes),
            'type_process_summary': type_process_summary
        }
    
    def shorten_folder_path(self, path: str) -> str:
        """Shorten folder path for display"""
        # Find common patterns in the path
        parts = path.split(os.sep)
        
        # Look for key folders like anr, tombstones
        for i, part in enumerate(parts):
            if part.lower() in ['anr', 'tombstone', 'tombstones']:
                # Show last 3-4 parts before the key folder
                start_idx = max(0, i - 3)
                relevant_parts = parts[start_idx:i+1]
                if start_idx > 0:
                    return ".../" + "/".join(relevant_parts)
                else:
                    return "/".join(relevant_parts)
        
        # If no key folder found, show last 4 parts
        if len(parts) > 4:
            return ".../" + "/".join(parts[-4:])
        else:
            return path

    def search_in_file_with_grep(self, file_path: str, search_text: str, use_regex: bool = False) -> List[Dict]:
        """Use grep to search in a file and return match information"""
        if not self.use_grep:
            return None
            
        results = []
        
        try:
            # Prepare grep command
            cmd = ['grep', '-n', '-o', '-b']  # -n: line number, -o: only matching, -b: byte offset
            
            if not use_regex:
                cmd.append('-F')  # Fixed string (literal)
                search_pattern = search_text
            else:
                cmd.append('-E')  # Extended regex
                search_pattern = search_text
            
            if not use_regex:  # Case insensitive for literal search
                cmd.append('-i')
                
            cmd.extend([search_pattern, file_path])
            
            # Run grep
            result = subprocess.run(cmd, 
                                capture_output=True, 
                                text=True,
                                timeout=5)
            
            if result.returncode == 0 and result.stdout.strip():
                # Parse grep output
                # Format: line:byte-offset:matched-text
                for line in result.stdout.strip().split('\n'):
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        line_number = int(parts[0])
                        byte_offset = int(parts[1])
                        matched_text = parts[2]
                        
                        results.append({
                            'line': line_number,
                            'offset': byte_offset,
                            'text': matched_text,
                            'length': len(matched_text)
                        })
                
                return results
            
        except subprocess.TimeoutExpired:
            print("Grep timeout for file search")
        except Exception as e:
            print(f"Grep error in file search: {e}")
        
        return None

    def search_in_file_with_grep_optimized(self, file_path: str, search_text: str, use_regex: bool = False, max_results: int = 500) -> List[Dict]:
        """優化的 grep 搜尋，限制結果數量並提供行內容"""
        if not self.use_grep:
            return None
            
        results = []
        
        try:
            # 使用 grep 獲取匹配的行
            cmd = ['grep', '-n']
            
            if not use_regex:
                cmd.extend(['-F', '-i'])  # 固定字串，不區分大小寫
            else:
                cmd.append('-E')  # 延伸正則表達式
            
            # 限制結果數量以提升效能
            cmd.extend(['-m', str(max_results * 2)])  # 多抓一些以確保有足夠結果
            cmd.extend([search_text, file_path])
            
            # 執行 grep
            result = subprocess.run(cmd, 
                                capture_output=True, 
                                text=True,
                                timeout=20)  # 縮短 timeout
            
            if result.returncode == 0 and result.stdout.strip():
                # 編譯搜尋模式
                if use_regex:
                    pattern = re.compile(search_text, re.IGNORECASE if not use_regex else 0)
                else:
                    pattern = re.compile(re.escape(search_text), re.IGNORECASE)
                
                # 解析 grep 輸出
                for line in result.stdout.strip().split('\n')[:max_results]:
                    if ':' in line:
                        parts = line.split(':', 1)
                        if len(parts) >= 2:
                            line_number = int(parts[0])
                            line_content = parts[1]
                            
                            # 在行內找到所有匹配位置
                            for match in pattern.finditer(line_content):
                                results.append({
                                    'line': line_number,
                                    'offset': match.start(),
                                    'text': match.group(0),
                                    'length': len(match.group(0)),
                                    'line_content': line_content  # 包含整行內容
                                })
                                
                                if len(results) >= max_results:
                                    break
                    
                    if len(results) >= max_results:
                        break
                
                return results
                
        except subprocess.TimeoutExpired:
            print("Grep timeout - file might be too large")
        except Exception as e:
            print(f"Grep error: {e}")
        
        return None
    