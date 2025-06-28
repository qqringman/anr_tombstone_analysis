import anthropic
from flask import Flask, render_template_string, request, jsonify, send_file, Response
import os
import re
import json
import csv
import io
import subprocess
import string
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
import threading
from typing import Dict, List, Tuple
import time
from urllib.parse import quote
import html
from collections import OrderedDict
import uuid

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



app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.config['JSON_AS_ASCII'] = False

# Claude API 配置 - 請設置環境變數或直接填入
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')  # 從環境變數讀取

# Global storage for analysis results
analysis_cache = LimitedCache(max_size=100, max_age_hours=24)
analysis_lock = threading.Lock()

class AndroidLogAnalyzer:
    def __init__(self):
        # Support both "Cmd line:" and "Cmdline:" formats
        self.cmdline_pattern = re.compile(r'(?:Cmd line|Cmdline):\s+(.+)', re.IGNORECASE)
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
            print(f"✓ unzip is {'available' if available else 'not available'}")
            return available
        except Exception as e:
            print(f"✗ unzip not available: {e}")
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
        """Use grep to find files containing 'Cmd line:' or 'Cmdline:' and extract the content with line number"""
        results = []
        
        try:
            # Use grep to find files with both "Cmd line" and "Cmdline" patterns
            # -H: print filename, -n: line number, -i: case insensitive, -r: recursive, -E: extended regex
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
                        # Format: filename:linenumber:Cmd line: content
                        parts = line.split(':', 3)  # Split into max 4 parts
                        if len(parts) >= 4:
                            filename = parts[0].lstrip('./')  # Remove ./ prefix if present
                            line_number = int(parts[1])
                            filepath = os.path.join(folder_path, filename)
                            # Extract cmdline from the grep result
                            cmdline_content = parts[3] if len(parts) > 3 else parts[2]
                            cmdline_match = self.cmdline_pattern.search(cmdline_content)
                            if not cmdline_match:
                                # Try to extract from the full line
                                cmdline_match = self.cmdline_pattern.search(line)
                            if cmdline_match:
                                cmdline = cmdline_match.group(1).strip()
                                results.append((filepath, cmdline, line_number))
                
                print(f"grep found {len(results)} files with Cmdline in {folder_path}")
            
        except subprocess.TimeoutExpired:
            print(f"grep timeout in {folder_path}, falling back to file reading")
        except Exception as e:
            print(f"grep error in {folder_path}: {e}")
        
        return results
    
    def extract_full_info_from_file(self, file_path: str, cmdline: str = None, line_number: int = None) -> Dict:
        """Extract full information from a file (timestamp, etc.)"""
        info = {
            'file': file_path,
            'filename': os.path.basename(file_path),
            'type': 'ANR' if 'anr' in file_path.lower() else 'Tombstone',
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
        
        # Extract process name from cmdline if available
        if cmdline:
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
                        cmdline_match = self.cmdline_pattern.search(line)
                        if cmdline_match:
                            info['cmdline'] = cmdline_match.group(1).strip()
                            info['line_number'] = line_no
                            # Extract process name
                            info['process'] = self.extract_process_name(info['cmdline'])
                    
                    # If we have cmdline but not line number, find it
                    elif not info['line_number'] and info['cmdline']:
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
        info = {
            'file': file_path,
            'filename': os.path.basename(file_path),
            'type': 'ANR' if 'anr' in file_path.lower() else 'Tombstone',
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
                    # Extract command line with line number
                    if not info['cmdline']:
                        cmdline_match = self.cmdline_pattern.search(line)
                        if cmdline_match:
                            info['cmdline'] = cmdline_match.group(1).strip()
                            info['line_number'] = line_no
                            # Extract process name from cmdline
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
            'zip_files_extracted': len(extracted_paths)
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
                # 非 regex 模式：使用固定字串搜尋
                cmd.extend(['-F', '-i'])  # -F: 固定字串（禁用 regex），-i: 不區分大小寫
            else:
                # regex 模式：使用延伸正則表達式
                cmd.append('-E')  # -E: 延伸正則表達式
                # 注意：在 regex 模式下不加 -i，讓使用者自己在 regex 中控制大小寫
            
            # 限制結果數量以提升效能
            cmd.extend(['-m', str(max_results * 2)])  # 多抓一些以確保有足夠結果
            cmd.extend([search_text, file_path])
            
            # 執行 grep
            result = subprocess.run(cmd, 
                                  capture_output=True, 
                                  text=True,
                                  timeout=20)  # 縮短 timeout
            
            if result.returncode == 0 and result.stdout.strip():
                # 根據搜尋模式編譯正則表達式
                if use_regex:
                    try:
                        # regex 模式：直接使用使用者的 regex
                        pattern = re.compile(search_text)
                    except re.error:
                        # 如果 regex 無效，返回空結果
                        return []
                else:
                    # 非 regex 模式：轉義特殊字符，進行字面匹配
                    escaped_text = re.escape(search_text)
                    pattern = re.compile(escaped_text, re.IGNORECASE)
                
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
    
analyzer = AndroidLogAnalyzer()

# HTML template with beautiful charts
HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Android ANR/Tombstone Analyzer</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            background-color: #f0f2f5;
            color: #333;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            flex: 1;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            position: relative;
        }
        
        .header h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
        }
        
        .export-html-btn {
            position: absolute;
            top: 30px;
            right: 30px;
            background: rgba(255, 255, 255, 0.2);
            color: white;
            border: 2px solid rgba(255, 255, 255, 0.5);
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s;
            display: none;
        }
        
        .export-html-btn:hover {
            background: rgba(255, 255, 255, 0.3);
            border-color: rgba(255, 255, 255, 0.8);
            transform: translateY(-2px);
        }
        
        @media (max-width: 768px) {
            .export-html-btn {
                position: static;
                margin-top: 20px;
                display: block;
                width: 100%;
            }
        }
        
        /* Navigation Bar Styles */
        .nav-bar {
            position: fixed;
            right: 90px;  /* 調整位置，在按鈕旁邊 */
            bottom: 90px;
            background: white;
            border: 1px solid #e1e4e8;
            border-radius: 12px;
            padding: 15px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            z-index: 100;
            max-width: 200px;
            transform: translateX(300px);  /* 預設隱藏在右側外 */
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            visibility: hidden;
        }
        
        .nav-bar.show {
            transform: translateX(0);
            opacity: 1;
            visibility: visible;
        }
        
        .nav-title {
            font-weight: 600;
            color: #333;
            margin-bottom: 10px;
            font-size: 14px;
        }
        
        .nav-links {
            display: flex;
            flex-direction: column;  /* 改為垂直排列 */
            gap: 8px;               /* 調整間距 */
        }
        
        .nav-link {
            background: #f0f0f0;
            color: #667eea;
            padding: 10px 14px;     /* 調整 padding */
            border-radius: 8px;
            text-decoration: none;
            font-size: 13px;        /* 稍微縮小字體 */
            transition: all 0.2s;
            white-space: nowrap;
            text-align: center;     /* 新增文字置中 */
        }
        
        .nav-link:hover {
            background: #667eea;
            color: white;
            transform: translateY(-2px);
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        /* Navigation Toggle Button */
        .nav-toggle-btn {
            position: fixed;
            right: 30px;
            bottom: 90px;  /* 在返回頂部按鈕上方 */
            background: #667eea;
            color: white;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            cursor: pointer;
            transition: all 0.3s;
            opacity: 0;
            visibility: hidden;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }

        .nav-toggle-btn.show {
            opacity: 1;
            visibility: visible;
        }

        .nav-toggle-btn:hover {
            background: #5a67d8;
            transform: translateY(-5px) rotate(10deg);
            box-shadow: 0 6px 16px rgba(102, 126, 234, 0.6);
        }

        .nav-toggle-btn.active {
            background: #5a67d8;
            transform: rotate(180deg);
        }

        /* 添加展開動畫 */
        @keyframes slideIn {
            from {
                transform: translateX(300px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }

        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(300px);
                opacity: 0;
            }
        }

        .nav-bar.animating-in {
            animation: slideIn 0.3s ease-out forwards;
        }

        .nav-bar.animating-out {
            animation: slideOut 0.3s ease-in forwards;
        }
        
        /* Back to Top Button */
        .back-to-top {
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: #667eea;
            color: white;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            cursor: pointer;
            transition: all 0.3s;
            opacity: 0;
            visibility: hidden;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }
        
        .back-to-top.show {
            opacity: 1;
            visibility: visible;
        }
        
        .back-to-top:hover {
            background: #5a67d8;
            transform: translateY(-5px);
            box-shadow: 0 6px 16px rgba(102, 126, 234, 0.6);
        }
        
        /* Section Back to Top Links */
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .section-title {
            font-size: 1.2rem;
            font-weight: 600;
            color: #333;
        }
        
        .top-link {
            color: #667eea;
            text-decoration: none;
            font-size: 14px;
            padding: 5px 10px;
            border-radius: 5px;
            transition: all 0.2s;
        }
        
        .top-link:hover {
            background: #f0f0f0;
            color: #5a67d8;
        }
        
        .control-panel {
            background-color: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 50px;
        }
        
        .input-group {
            margin-bottom: 20px;
            position: relative;
        }
        
        .path-autocomplete {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: white;
            border: 2px solid #e1e4e8;
            border-top: none;
            border-radius: 0 0 8px 8px;
            max-height: 300px;
            overflow-y: auto;
            display: none;
            z-index: 1000;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        .path-suggestion {
            padding: 12px;
            cursor: pointer;
            border-bottom: 1px solid #f0f0f0;
            font-family: monospace;
            font-size: 14px;
            color: #333;
            transition: background-color 0.2s;          
        }
        
        .path-suggestion:hover {
            background-color: #f8f9fa;
        }
        
        .path-suggestion.selected {
            background-color: #e8eaf6;
        }
        
        .path-suggestion .star {
            color: #ffd700;
            margin-left: 5px;
        }
        
        .path-loading {
            padding: 12px;
            text-align: center;
            color: #667eea;
            font-size: 14px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #555;
        }
        
        input[type="text"] {
            width: 100%;
            padding: 12px;
            border: 2px solid #e1e4e8;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        
        input[type="text"]:focus {
            outline: none;
            border-color: #667eea;
        }
        
        #pathInput {
            background-color: #f8f9fa;
            padding: 15px;
            border: 2px solid #e1e4e8;
            border-left: 5px solid #28a745;
            border-radius: 8px;
            margin-top: 5px;
            display: flex;
            align-items: flex-start;
            font-family: monospace;
            font-size: 90%;            
        }
        
        #pathInput:focus ~ .path-autocomplete {
            border-color: #667eea;
        }
        
        #pathInput.autocomplete-open {
            border-bottom-left-radius: 0;
            border-bottom-right-radius: 0;
        }
        
        .button-group {
            display: flex;
            gap: 10px;
            margin-top: 20px;
            margin-bottom: 5px;
        }
        
        button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }
        
        button:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        
        .loading {
            display: none;
            text-align: center;
            padding: 20px;
            color: #667eea;
        }
        
        .loading::after {
            content: '...';
            animation: dots 1.5s steps(4, end) infinite;
        }
        
        @keyframes dots {
            0%, 20% { content: ''; }
            40% { content: '.'; }
            60% { content: '..'; }
            80%, 100% { content: '...'; }
        }
        
        .error {
            color: #e53e3e;
            padding: 15px;
            background-color: #fff5f5;
            border: 1px solid #feb2b2;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        
        .success {
            color: #38a169;
            padding: 15px;
            background-color: #f0fff4;
            border: 1px solid #9ae6b4;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        
        .info {
            color: #3182ce;
            padding: 15px;
            background-color: #ebf8ff;
            border: 1px solid #90cdf4;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        
        .stats-summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            text-align: center;
        }
        
        .stat-card h3 {
            color: #667eea;
            font-size: 2.5rem;
            margin-bottom: 5px;
        }
        
        .stat-card p {
            color: #666;
            font-size: 0.9rem;
        }
        
        .stat-card.highlight {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .stat-card.highlight h3 {
            color: white;
        }
        
        .stat-card.highlight p {
            color: rgba(255, 255, 255, 0.9);
        }
        
        .chart-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 30px;
            margin-bottom: 30px;
        }
        
        .chart-container {
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        
        .chart-container h3 {
            margin-bottom: 20px;
            color: #333;
            font-size: 1.3rem;
        }
        
        .chart-wrapper {
            position: relative;
            height: 300px;
        }
        
        .summary-table {
            background-color: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
            margin-bottom: 30px;
        }
        
        .summary-table h3 {
            padding: 20px;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-bottom: 2px solid #e1e4e8;
            color: white;
            font-size: 1.2rem;
        }
        
        .table-controls {
            padding: 15px 20px;
            background-color: #f8f9fa;
            border-bottom: 1px solid #e1e4e8;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }
        
        .search-box {
            position: relative;
            flex: 1;
        }
        
        .search-box input {
            width: 100%;
            padding: 8px 35px 8px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
        }
        
        .search-box::after {
            content: '🔍';
            position: absolute;
            right: 10px;
            top: 50%;
            transform: translateY(-50%);
            opacity: 0.5;
        }
        
        /* 新增 regex 開關樣式 */
        .regex-toggle {
            display: flex;
            align-items: center;
            gap: 5px;
            color: #666;
            font-size: 12px;
            cursor: pointer;
            user-select: none;
            margin-left: 10px;
            margin-top: 10px;
        }
        
        .regex-toggle input {
            cursor: pointer;
        }
        
        .regex-toggle:hover {
            color: #667eea;
        }
        
        .pagination {
            display: flex;
            gap: 5px;
            align-items: center;
            flex-wrap: wrap;
        }
        
        .pagination button {
            padding: 5px 10px;
            font-size: 14px;
            background: white;
            color: #667eea;
            border: 1px solid #667eea;
            min-width: 35px;
        }
        
        .pagination button:hover:not(:disabled) {
            background: #667eea;
            color: white;
        }
        
        .pagination button:disabled {
            background: #f0f0f0;
            color: #999;
            border-color: #ddd;
            cursor: not-allowed;
        }
        
        .pagination button.active {
            background: #667eea;
            color: white;
        }
        
        .pagination .page-numbers {
            display: flex;
            gap: 5px;
            align-items: center;
        }
        
        .pagination span {
            padding: 0 10px;
            font-size: 14px;
            color: #666;
        }
        
        .table-wrapper {
            overflow-x: auto;
        }
        
        .summary-table table {
            width: 100%;
        }
        
        .summary-table thead {
            position: sticky;
            top: 0;
            z-index: 10;
        }
        
        .summary-table th {
            background-color: #f8f9fa;
            color: #333;
            font-weight: 600;
            padding: 12px;
            text-align: left;
            border-bottom: 2px solid #e1e4e8;
            position: sticky;
            top: 0;
            white-space: nowrap;  /* 防止標題折行 */
        }
        
        .summary-table td {
            padding: 12px;
            border-bottom: 1px solid #eee;
        }
        
        .summary-table tr:nth-child(even) {
            background-color: #f8f9fa;
        }
        
        .summary-table tr:hover {
            background-color: #e8eaf6;
        }
        
        .rank-number {
            font-weight: bold;
            color: #667eea;
            text-align: center;
        }
        
        .process-name {
            font-weight: 600;
            color: #667eea;
        }
        
        .logs-table {
            background-color: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
            margin-bottom: 30px;
        }
        
        .logs-table-content {
            overflow-x: auto;
        }
        
        .table-header {
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-bottom: 2px solid #e1e4e8;
        }
        
        .table-header h3 {
            color: white;
            margin: 0;
            font-size: 1.2rem;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            background-color: #f8f9fa;
            padding: 15px;
            text-align: left;
            font-weight: 600;
            color: #555;
            border-bottom: 2px solid #e1e4e8;
        }
        
        .logs-table thead {
            position: sticky;
            top: 0;
            z-index: 10;
        }
        
        .logs-table th {
            background-color: #f8f9fa;
            position: sticky;
            top: 0;
        }
        
        td {
            padding: 15px;
            border-bottom: 1px solid #e1e4e8;
        }
        
        tr:hover {
            background-color: #f8f9fa;
        }
        
        .filter-input {
            width: 300px;
            padding: 8px 12px;
            border: 2px solid rgba(255, 255, 255, 0.8);
            border-radius: 8px;
            font-size: 14px;
            background-color: rgba(255, 255, 255, 0.95);
        }
        
        .file-link {
            color: #667eea;
            text-decoration: none;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .file-link:hover {
            text-decoration: underline;
            color: #5a67d8;
        }
        
        .cmdline-cell {
            font-size: 0.9em;
            max-width: 600px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .folder-path-cell {
            font-size: 0.9em;
            color: #999;
            font-family: monospace;
        }
        
        #results {
            display: none;
        }
        
        .grep-badge {
            display: inline-block;
            background: #48bb78;
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            margin-left: 10px;
        }
        
        .no-grep-badge {
            background: #f56565;
        }
        
        .footer {
            background-color: #2d3748;
            color: #a0aec0;
            text-align: center;
            padding: 10px;
            margin-top: 10px;
            font-size: 14px;
        }
        
        .footer p {
            margin: 0;
        }
        
        .filesize {
            color: #666;
            font-size: 0.9em;
        }
        
        .line-number {
            font-weight: bold;
            color: #667eea;
            text-align: center;
            transition: all 0.2s;
        }

        ul {
            list-style: none;
            padding: 0;
            /* 讓整個列表向右縮排 */
            margin-left: 40px;
        }
        
        .icon {
            padding:2px;
            margin:2px;
        }
        
        .path-format {
            background-color: #f8f9fa;
            padding: 15px;
            border: 2px solid #e1e4e8;
            border-left: 5px solid #3498db;
            border-radius: 8px;
            margin-top: 5px;
            display: flex;
            align-items: flex-start;
        }
        
        .path-format strong {
            color: #3498db;
        }

        .line-number {
            padding: 0 15px;
            cursor: pointer;
            position: relative;
            transition: all 0.2s;
        }

        .line-number:hover::after {
            content: "📌";
            position: absolute;
            right: 2px;
            font-size: 10px;
            opacity: 0.5;
        }

        .line-number.bookmarked:hover::after {
            content: "❌";
            opacity: 0.7;
        }

        .process-name div {
            padding: 2px 0;
        }

        .process-name div:not(:last-child) {
            border-bottom: 1px solid #f0f0f0;
        }

        .table-highlight {
            background-color: #fff59d !important;
            color: #000;
            font-weight: 600;
        }

        .logs-table-content table thead tr th {
            white-space: nowrap
        }
       
    </style>
    <style>
        .sortable {
            cursor: pointer;
            user-select: none;
            position: relative;
        }

        .sortable:hover {
            background-color: #e8eaf6;
        }

        .sort-indicator {
            position: absolute;
            right: 5px;
            color: #667eea;
            font-size: 12px;
        }    
    </style>
    <style>
    /* ===== 區塊容器和開合功能 ===== */
    .section-container {
        position: relative;
        margin-bottom: 30px;
    }

    .section-content {
        transition: all 0.3s ease-in-out;
        overflow: hidden;
    }

    .section-container.collapsed .section-content {
        max-height: 0;
        opacity: 0;
        padding: 0;
        margin: 0;
    }

    /* ===== 表頭樣式 ===== */
    .table-header {
        position: relative;
        padding: 20px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        border-bottom: 2px solid #e1e4e8;
    }

    .table-header .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 60px 0 0 !important;
        margin: 0;
    }

    .table-header h3 {
        margin: 0;
        flex: 1;
        color: white;
        padding-right: 50px;
    }

    .table-header .top-link {
        margin-left: auto;
        margin-right: 5px;
        color: white;
        text-decoration: none;
        font-size: 14px;
        padding: 5px 10px;
        border-radius: 5px;
        transition: all 0.2s;
    }

    /* ===== 區塊開合按鈕 ===== */
    .section-toggle {
        position: absolute;
        right: 20px;
        top: 50%;
        transform: translateY(-50%);
        width: 36px;
        height: 36px;
        background: rgba(255, 255, 255, 0.2);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: all 0.3s;
        z-index: 10;
        border: 2px solid rgba(255, 255, 255, 0.3);
    }

    .section-toggle:hover {
        background: rgba(255, 255, 255, 0.3);
        transform: translateY(-50%) scale(1.1);
    }

    .section-toggle .toggle-icon {
        font-size: 20px;
        color: white;
        line-height: 1;
        font-weight: normal;
    }

    .section-toggle .toggle-icon::before {
        content: "+";
        display: block;
    }

    .section-container.collapsed .section-toggle .toggle-icon::before {
        content: "×";
    }

    /* 表格區塊的特殊定位 */
    .logs-table .section-toggle {
        top: 15px;
        right: 15px;
        transform: none;
    }

    /* ===== 區塊開合按鈕 Tooltip ===== */
    .section-toggle[data-tooltip]::before {
        content: attr(data-tooltip);
        position: absolute;
        right: calc(100% + 15px);
        top: 50%;
        transform: translateY(-50%);
        background: rgba(0, 0, 0, 0.9);
        color: white;
        padding: 6px 12px;
        border-radius: 4px;
        font-size: 12px;
        white-space: nowrap;
        opacity: 0;
        visibility: hidden;
        transition: all 0.2s ease;
        pointer-events: none;
        z-index: 10000;
    }

    .section-toggle[data-tooltip]::after {
        content: '';
        position: absolute;
        right: calc(100% + 7px);
        top: 50%;
        transform: translateY(-50%);
        width: 0;
        height: 0;
        border-style: solid;
        border-width: 5px 0 5px 8px;
        border-color: transparent transparent transparent rgba(0, 0, 0, 0.9);
        opacity: 0;
        visibility: hidden;
        transition: all 0.2s ease;
        pointer-events: none;
    }

    .section-toggle[data-tooltip]:hover::before,
    .section-toggle[data-tooltip]:hover::after {
        opacity: 1;
        visibility: visible;
    }

    /* ===== 右下角浮動按鈕 ===== */
    .back-to-top,
    .nav-toggle-btn,
    .global-toggle-btn {
        position: fixed !important;
        width: 50px;
        height: 50px;
        border-radius: 50%;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 24px;
        cursor: pointer;
        transition: all 0.3s;
        z-index: 9999 !important;
        right: 30px !important;
        left: auto !important;
        background: #667eea;
        color: white;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        text-align: center;
        line-height: 1;
    }

    .back-to-top {
        bottom: 30px !important;
    }

    .nav-toggle-btn {
        bottom: 90px !important;
    }

    .global-toggle-btn {
        bottom: 150px !important;
    }

    .back-to-top.show,
    .nav-toggle-btn.show,
    .global-toggle-btn.show {
        opacity: 1;
        visibility: visible;
    }

    .back-to-top:hover,
    .nav-toggle-btn:hover,
    .global-toggle-btn:hover {
        background: #5a67d8;
        transform: translateY(-5px) !important;
        box-shadow: 0 6px 16px rgba(102, 126, 234, 0.6);
    }

    /* ===== 浮動按鈕 Tooltip ===== */
    .floating-tooltip {
        position: absolute;
        right: calc(100% + 15px);
        top: 50%;
        transform: translateY(-50%);
        background: rgba(0, 0, 0, 0.9);
        color: white;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
        white-space: nowrap;
        opacity: 0;
        visibility: hidden;
        transition: all 0.3s ease;
        pointer-events: none;
        z-index: 10000;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    }

    .floating-tooltip::after {
        content: '';
        position: absolute;
        left: 100%;
        top: 50%;
        transform: translateY(-50%);
        width: 0;
        height: 0;
        border-style: solid;
        border-width: 6px 0 6px 8px;
        border-color: transparent transparent transparent rgba(0, 0, 0, 0.9);
    }

    /* ===== 其他樣式優化 ===== */
    .container {
        padding-bottom: 200px;
    }

    .section-container,
    .logs-table {
        position: relative;
        z-index: 1;
    }

    .logs-table,
    .section-container > div:first-child {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }

    .section-container.collapsed .table-header {
        border-radius: 12px;
        margin-bottom: 0;
    }

    /* 頁面回到頂部連結位置 */
    .section-header {
        padding-right: 60px;
    }

    /* 圖標大小調整 */
    #globalToggleIcon,
    .nav-icon {
        font-size: 20px;
        line-height: 1;
    }

    /* 成功訊息樣式 */
    .success {
        color: #38a169;
        padding: 10px 15px;
        background-color: #f0fff4;
        border: 1px solid #9ae6b4;
        border-radius: 8px;
        margin-bottom: 15px;
        line-height: 1.4;
    }

    .grep-badge {
        display: inline-block;
        background: #48bb78;
        color: white;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75rem;
        margin-left: 8px;
        vertical-align: middle;
    }

    /* 控制面板間距 */
    .control-panel {
        background-color: white;
        padding: 25px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin-bottom: 30px;
    }
    
    /* ===== 區塊開合按鈕 Tooltip（右側顯示） ===== */
    .section-toggle[data-tooltip]::before {
        content: attr(data-tooltip);
        position: absolute;
        left: calc(100% + 15px);  /* 改為左側定位（顯示在按鈕右邊） */
        top: 50%;
        transform: translateY(-50%);
        background: rgba(0, 0, 0, 0.9);
        color: white;
        padding: 6px 12px;
        border-radius: 4px;
        font-size: 12px;
        white-space: nowrap;
        opacity: 0;
        visibility: hidden;
        transition: all 0.2s ease;
        pointer-events: none;
        z-index: 10000;
    }

    /* Tooltip 箭頭（指向左側） */
    .section-toggle[data-tooltip]::after {
        content: '';
        position: absolute;
        left: calc(100% + 7px);  /* 改為左側定位 */
        top: 50%;
        transform: translateY(-50%);
        width: 0;
        height: 0;
        border-style: solid;
        border-width: 5px 8px 5px 0;  /* 改變箭頭方向 */
        border-color: transparent rgba(0, 0, 0, 0.9) transparent transparent;  /* 箭頭指向左側 */
        opacity: 0;
        visibility: hidden;
        transition: all 0.2s ease;
        pointer-events: none;
    }
    
    /* 調整表頭佈局 */
    .table-header .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 !important;
        margin: 0;
        position: relative;
    }

    /* 回到頂部連結靠右對齊 */
    .table-header .top-link {
        position: absolute;
        right: 60px; /* 與開合按鈕對齊 */
        top: 50%;
        transform: translateY(-50%);
        color: white;
        text-decoration: none;
        font-size: 14px;
        padding: 5px 10px;
        border-radius: 5px;
        transition: all 0.2s;
        white-space: nowrap;
    }

    .table-header .top-link:hover {
        background: rgba(255, 255, 255, 0.2);
    }

    /* 確保標題不會與連結重疊 */
    .table-header h3 {
        margin: 0;
        padding-right: 150px; /* 為連結和按鈕預留更多空間 */
        color: white;
    }
   
    </style>    
</head>
<body>
    <div class="container">
        <div class="header" id="top">
            <h1>Android ANR/Tombstone Analyzer</h1>
            <p>分析 anr/ 和 tombstones/ 資料夾中的 Cmd line: / Cmdline: 統計資訊</p>
            <button class="export-html-btn" id="exportHtmlBtn" onclick="exportResults('html')">匯出 HTML</button>
        </div>
        
        <!-- Navigation Bar -->
        <div class="nav-bar" id="navBar">
            <div class="nav-title">快速導覽</div>
            <div class="nav-links">
                <a href="#stats-section" class="nav-link">📊 統計摘要</a>
                <a href="#charts-section" class="nav-link">📈 圖表分析</a>
                <a href="#process-summary-section" class="nav-link">🔧 程序統計</a>
                <a href="#summary-section" class="nav-link">📋 彙整資訊</a>
                <a href="#files-section" class="nav-link">📁 檔案統計</a>
                <a href="#logs-section" class="nav-link">📝 詳細記錄</a>
            </div>
        </div>
        
        <!-- Back to Top Button -->
        <div class="back-to-top" id="backToTop" onclick="scrollToTop()">↑</div>
        <div class="global-toggle-btn" id="globalToggleBtn" onclick="toggleAllSections()">
            <span id="globalToggleIcon">⊕</span>
        </div>        
        <div class="nav-toggle-btn" id="navToggleBtn" onclick="toggleNavBar()">
            <span class="nav-icon">☰</span>
        </div>        
        <div class="control-panel">
            <div class="input-group">
                <label for="pathInput">📁 <span style="margin-left: 5px;">選擇基礎路徑 (包含 anr/ 或 tombstones/ 子資料夾):</span></label>
                <input type="text" id="pathInput" placeholder="/path/to/logs" value="/R306_ShareFolder/nightrun_log/Demo_stress_Test_log/2025" autocomplete="off">
                <div id="pathAutocomplete" class="path-autocomplete"></div>
            </div>
            <small style="display: block; margin-top: 8px;">
                <h2 style="margin-bottom:10px">✨ 功能特色</h2>
                <ul>
                    <li><span class="icon">🔍</span> <strong>路徑自動建議：</strong> 當您輸入時，工具會自動建議可用的子資料夾，讓您更輕鬆地導航到所需的目錄。</li>
                    <li><span class="icon">📂</span> <strong>自動解壓縮 ZIP 檔案：</strong> 指定路徑下的所有 ZIP 檔案將會自動解壓縮，方便您的操作。</li>
                    <li><span class="icon">🔄</span> <strong>遞迴資料夾搜尋：</strong> 工具會遞迴搜尋所有 <strong>anr</strong> 和 <strong>tombstones</strong> 資料夾，確保不會遺漏任何相關的紀錄檔資料。</li>
                    <li><span class="icon">📜</span> <strong>彈性命令列解析：</strong> 支援 "Cmd line:" 和 "Cmdline:" 兩種格式，從紀錄檔中擷取命令列資訊。</li>
                    <li><span class="icon">👆</span> <strong>可點擊檔案名稱：</strong> 只需點擊檔案名稱，即可輕鬆查看任何紀錄檔的內容。</li>
                </ul>
                <h2 style="margin-top:10px;margin-bottom:10px">💻 支援路徑格式</h2>
                <div class="path-format">
                    <p><strong>Linux/Unix：</strong> <code>/R306_ShareFolder/nightrun_log/Demo_stress_Test_log</code></p>
                </div>
            </small>                
            <div class="button-group">
                <button onclick="analyzeLogs()" id="analyzeBtn">開始分析</button>
                <button onclick="exportResults('json')" id="exportJsonBtn" disabled>匯出 JSON</button>
                <button onclick="exportResults('csv')" id="exportCsvBtn" disabled>匯出 CSV</button>
            </div>
            
            <div class="loading" id="loading">
                正在分析中
            </div>
            
            <div id="message"></div>
        </div>
        
        <div id="results">
            <div class="section-container" id="stats-section-container">
                <div class="logs-table" id="stats-section">
                    <div class="table-header" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                        <div class="section-header" style="padding: 0;">
                            <h3 style="color: white;">統計摘要</h3>
                            <a href="#top" class="top-link" style="color: white;">⬆ 回到頂部</a>
                        </div>
                        <div class="section-toggle" onclick="toggleSection('stats-section-container')">
                            <span class="toggle-icon"></span>
                        </div>
                    </div>
                    <div class="section-content">
                        <div class="stats-summary" id="statsSummary" style="padding: 20px;"></div>
                    </div>
                </div>
            </div>
            
            <div class="section-container" id="charts-section-container">
                <div class="logs-table" id="charts-section" style="margin-top: 40px;">
                    <div class="table-header" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                        <div class="section-header" style="padding: 0;">
                            <h3 style="color: white;">圖表分析</h3>
                            <a href="#top" class="top-link" style="color: white;">⬆ 回到頂部</a>
                        </div>
                        <div class="section-toggle" onclick="toggleSection('charts-section-container')">
                            <span class="toggle-icon"></span>
                        </div>
                    </div>
                    <div class="section-content">
                        <div class="chart-grid" style="padding: 20px;">
                            <div class="chart-container">
                                <h3>Top 10 問題程序 (Process)</h3>
                                <div class="chart-wrapper">
                                    <canvas id="processChart"></canvas>
                                </div>
                            </div>
                            
                            <div class="chart-container">
                                <h3>問題類型分佈</h3>
                                <div class="chart-wrapper">
                                    <canvas id="typeChart"></canvas>
                                </div>
                            </div>
                            
                            <div class="chart-container">
                                <h3>每日問題趨勢</h3>
                                <div class="chart-wrapper">
                                    <canvas id="dailyChart"></canvas>
                                </div>
                            </div>
                            
                            <div class="chart-container">
                                <h3>每小時分佈</h3>
                                <div class="chart-wrapper">
                                    <canvas id="hourlyChart"></canvas>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
 
            <div class="section-container" id="process-summary-section-container">
                <div class="logs-table" id="process-summary-section" style="margin-top: 40px;">
                    <div class="table-header">
                        <div class="section-header" style="padding: 0;">
                            <h3>彙整資訊 - 程序統計</h3>
                            <a href="#top" class="top-link" style="color: white;">⬆ 回到頂部</a>
                        </div>
                        <div class="section-toggle" onclick="toggleSection('process-summary-section-container')">
                            <span class="toggle-icon"></span>
                        </div>
                    </div>
                    <div class="section-content">
                        <div class="table-controls">
                            <div class="search-wrapper" style="display: flex; align-items: center; gap: 10px; flex: 1; max-width: 500px;">
                                <div class="search-box">
                                    <input type="text" id="processSummarySearchInput" placeholder="搜尋程序..." style="flex: 1;">
                                </div>
                                <label class="regex-toggle">
                                    <input type="checkbox" id="processSummaryRegexToggle">
                                    Regex
                                </label>
                                <span class="search-count" id="processSummarySearchCount" style="color: #667eea; font-weight: bold; font-size: 12px; white-space: nowrap; display: none;"></span>
                            </div>
                            <div class="pagination" id="processSummaryPagination">
                                <button onclick="changeProcessSummaryPage('first')" id="processSummaryFirstBtn">第一頁</button>
                                <button onclick="changeProcessSummaryPage(-1)" id="processSummaryPrevBtn">上一頁</button>
                                <span id="processSummaryPageInfo">第 1 頁 / 共 1 頁</span>
                                <button onclick="changeProcessSummaryPage(1)" id="processSummaryNextBtn">下一頁</button>
                                <button onclick="changeProcessSummaryPage('last')" id="processSummaryLastBtn">最後一頁</button>
                            </div>
                        </div>
                        <div class="table-wrapper">
                            <table>
                                <thead>
                                    <tr>
                                        <th style="width: 80px; text-align: center;" class="sortable" onclick="sortProcessSummaryTable('rank')">
                                            排名 <span class="sort-indicator" data-column="rank"></span>
                                        </th>
                                        <th class="sortable" onclick="sortProcessSummaryTable('process')">
                                            程序 <span class="sort-indicator" data-column="process"></span>
                                        </th>
                                        <th style="width: 100px; text-align: center;" class="sortable" onclick="sortProcessSummaryTable('count')">
                                            次數 <span class="sort-indicator" data-column="count">▼</span>
                                        </th>
                                    </tr>
                                </thead>
                                <tbody id="processSummaryTableBody">
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <div class="section-container" id="summary-section-container">
                <div class="logs-table" id="summary-section" style="margin-top: 40px;">
                    <div class="table-header">
                        <div class="section-header" style="padding: 0;">
                            <h3>彙整資訊 - 按類型和程序統計</h3>
                            <a href="#top" class="top-link" style="color: white;">⬆ 回到頂部</a>
                        </div>
                        <div class="section-toggle" onclick="toggleSection('summary-section-container')">
                            <span class="toggle-icon"></span>
                        </div>
                    </div>
                    <div class="section-content">
                        <div class="table-controls">
                            <div class="search-wrapper" style="display: flex; align-items: center; gap: 10px; flex: 1; max-width: 500px;">
                                <div class="search-box">
                                    <input type="text" id="summarySearchInput" placeholder="搜尋類型或程序..." style="flex: 1;">
                                </div>
                                <label class="regex-toggle">
                                    <input type="checkbox" id="summaryRegexToggle">
                                    Regex
                                </label>
                                <span class="search-count" id="summarySearchCount" style="color: #667eea; font-weight: bold; font-size: 12px; white-space: nowrap; display: none;"></span>
                            </div>
                            <div class="pagination" id="summaryPagination">
                                <button onclick="changeSummaryPage('first')" id="summaryFirstBtn">第一頁</button>
                                <button onclick="changeSummaryPage(-1)" id="summaryPrevBtn">上一頁</button>
                                <span id="summaryPageInfo">第 1 頁 / 共 1 頁</span>
                                <button onclick="changeSummaryPage(1)" id="summaryNextBtn">下一頁</button>
                                <button onclick="changeSummaryPage('last')" id="summaryLastBtn">最後一頁</button>
                            </div>
                        </div>
                        <div class="table-wrapper">
                            <table>
                                <thead>
                                    <tr>
                                        <th style="width: 80px; text-align: center;" class="sortable" onclick="sortSummaryTable('rank')">
                                            排名 <span class="sort-indicator" data-column="rank"></span>
                                        </th>
                                        <th style="width: 120px;" class="sortable" onclick="sortSummaryTable('type')">
                                            類型 <span class="sort-indicator" data-column="type"></span>
                                        </th>
                                        <th class="sortable" onclick="sortSummaryTable('process')">
                                            程序 <span class="sort-indicator" data-column="process"></span>
                                        </th>
                                        <th style="width: 100px; text-align: center;" class="sortable" onclick="sortSummaryTable('count')">
                                            次數 <span class="sort-indicator" data-column="count">▼</span>
                                        </th>
                                    </tr>
                                </thead>
                                <tbody id="summaryTableBody">
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="section-container" id="files-section-container">
                <div class="logs-table" id="files-section" style="margin-top: 40px;">
                    <div class="table-header">
                        <div class="section-header" style="padding: 0;">
                            <h3>詳細記錄 (依檔案)</h3>
                            <a href="#top" class="top-link" style="color: white;">⬆ 回到頂部</a>
                        </div>
                        <div class="section-toggle" onclick="toggleSection('files-section-container')">
                            <span class="toggle-icon"></span>
                        </div>                     
                    </div>
                    <div class="section-content">
                        <div class="table-controls">
                            <div class="search-wrapper" style="display: flex; align-items: center; gap: 10px; flex: 1; max-width: 500px;">
                                <div class="search-box">
                                    <input type="text" id="filesSearchInput" placeholder="搜尋檔案名稱..." style="flex: 1;">
                                </div>
                                <label class="regex-toggle">
                                    <input type="checkbox" id="filesRegexToggle">
                                    Regex
                                </label>
                                <span class="search-count" id="filesSearchCount" style="color: #667eea; font-weight: bold; font-size: 12px; white-space: nowrap; display: none;"></span>
                            </div>
                            <div class="pagination" id="filesPagination">
                                <button onclick="changeFilesPage('first')" id="filesFirstBtn">第一頁</button>
                                <button onclick="changeFilesPage(-1)" id="filesPrevBtn">上一頁</button>
                                <span id="filesPageInfo">第 1 頁 / 共 1 頁</span>
                                <button onclick="changeFilesPage(1)" id="filesNextBtn">下一頁</button>
                                <button onclick="changeFilesPage('last')" id="filesLastBtn">最後一頁</button>
                            </div>
                        </div>
                        <div class="logs-table-content">
                            <table>
                                <thead>
                                    <tr>
                                        <th style="width: 60px;" class="sortable" onclick="sortFilesTable('index')">
                                            編號 <span class="sort-indicator" data-column="index"></span>
                                        </th>
                                        <th style="width: 100px;" class="sortable" onclick="sortFilesTable('type')">
                                            類型 <span class="sort-indicator" data-column="type"></span>
                                        </th>
                                        <th class="sortable" onclick="sortFilesTable('processes')">
                                            相關程序 <span class="sort-indicator" data-column="processes"></span>
                                        </th>
                                        <th style="width: 200px;" class="sortable" onclick="sortFilesTable('folder_path')">
                                            資料夾路徑 <span class="sort-indicator" data-column="folder_path"></span>
                                        </th>
                                        <th style="width: 250px;" class="sortable" onclick="sortFilesTable('filename')">
                                            檔案 <span class="sort-indicator" data-column="filename"></span>
                                        </th>
                                        <th style="width: 80px;" class="sortable" onclick="sortFilesTable('count')">
                                            次數 <span class="sort-indicator" data-column="count">▼</span>
                                        </th>
                                        <th style="width: 180px;" class="sortable" onclick="sortFilesTable('timestamp')">
                                            時間戳記 <span class="sort-indicator" data-column="timestamp"></span>
                                        </th>
                                    </tr>
                                </thead>
                                <tbody id="filesTableBody">
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="section-container" id="logs-section-container">
                <div class="logs-table" id="logs-section" style="margin-top: 40px;">
                    <div class="table-header">
                        <div class="section-header" style="padding: 0;">
                            <h3>詳細記錄 (依行號)</h3>
                            <a href="#top" class="top-link" style="color: white;">⬆ 回到頂部</a>
                        </div>
                        <div class="section-toggle" onclick="toggleSection('logs-section-container')">
                            <span class="toggle-icon"></span>
                        </div>                    
                    </div>
                    <div class="section-content">
                        <div class="table-controls">
                            <div class="search-wrapper" style="display: flex; align-items: center; gap: 10px; flex: 1; max-width: 500px;">
                                <div class="search-box">
                                    <input type="text" id="logsSearchInput" placeholder="搜尋類型、程序、檔案名稱或資料夾路徑..." style="flex: 1;">
                                </div>
                                <label class="regex-toggle">
                                    <input type="checkbox" id="logsRegexToggle">
                                    Regex
                                </label>
                                <span class="search-count" id="logsSearchCount" style="color: #667eea; font-weight: bold; font-size: 12px; white-space: nowrap; display: none;"></span>
                            </div>
                            <div class="pagination" id="logsPagination">
                                <button onclick="changeLogsPage('first')" id="logsFirstBtn">第一頁</button>
                                <button onclick="changeLogsPage(-1)" id="logsPrevBtn">上一頁</button>
                                <span id="logsPageInfo">第 1 頁 / 共 1 頁</span>
                                <button onclick="changeLogsPage(1)" id="logsNextBtn">下一頁</button>
                                <button onclick="changeLogsPage('last')" id="logsLastBtn">最後一頁</button>
                            </div>
                        </div>
                        <div class="logs-table-content">
                            <table>
                                <thead>
                                    <tr>
                                        <th style="width: 60px;" class="sortable" onclick="sortLogsTable('index')">
                                            編號 <span class="sort-indicator" data-column="index"></span>
                                        </th>
                                        <th style="width: 100px;" class="sortable" onclick="sortLogsTable('type')">
                                            類型 <span class="sort-indicator" data-column="type"></span>
                                        </th>
                                        <th class="sortable" onclick="sortLogsTable('process')">
                                            相關程序 <span class="sort-indicator" data-column="process"></span>
                                        </th>
                                        <th style="width: 80px;" class="sortable" onclick="sortLogsTable('line_number')">
                                            行號 <span class="sort-indicator" data-column="line_number"></span>
                                        </th>
                                        <th style="width: 200px;" class="sortable" onclick="sortLogsTable('folder_path')">
                                            資料夾路徑 <span class="sort-indicator" data-column="folder_path"></span>
                                        </th>
                                        <th style="width: 250px;" class="sortable" onclick="sortLogsTable('filename')">
                                            檔案 <span class="sort-indicator" data-column="filename"></span>
                                        </th>
                                        <th style="width: 180px;" class="sortable" onclick="sortLogsTable('timestamp')">
                                            時間戳記 <span class="sort-indicator" data-column="timestamp"></span>
                                        </th>
                                    </tr>
                                </thead>
                                <tbody id="logsTableBody">
                                </tbody>
                            </table>
                        </div>
                   </div>
                </div>
            </div>
        </div>
    <footer class="footer">
        <p>&copy; 2025 Copyright by Vince. All rights reserved.</p>
    </footer>
    
    <script>
        let currentAnalysisId = null;
        let allLogs = [];
        let allSummary = [];
        let allFileStats = [];
        let charts = {};
        
        // Pagination state
        let summaryPage = 1;
        let logsPage = 1;
        let filesPage = 1;
        const itemsPerPage = 50;
        
        // Filtered data
        let filteredSummary = [];
        let filteredLogs = [];
        let filteredFiles = [];
        
        // Autocomplete state
        let selectedSuggestionIndex = -1;
        let currentSuggestions = [];
        let autocompleteTimeout = null;

        let allProcessSummary = [];
        let filteredProcessSummary = [];
        let processSummaryPage = 1;
        let processSummarySort = { column: 'count', order: 'desc' };

        // 排序狀態
        let summarySort = { column: 'count', order: 'desc' };
        let filesSort = { column: 'count', order: 'desc' };
        let logsSort = { column: null, order: 'asc' };
        
        // 添加導覽列開關狀態
        let navBarOpen = false;
        
        // 區塊收縮狀態
        let sectionStates = {
            'stats-section-container': false,
            'charts-section-container': false,
            'process-summary-section-container': false,
            'summary-section-container': false,
            'files-section-container': false,  // 改為 -container
            'logs-section-container': false     // 改為 -container
        };

        // 切換單個區塊
        function toggleSection(sectionId) {
            let container;
            let actualSectionId;
            
            // 先嘗試直接找到容器
            container = document.getElementById(sectionId);
            
            // 如果沒找到，嘗試加上 -container 後綴
            if (!container && !sectionId.endsWith('-container')) {
                container = document.getElementById(sectionId + '-container');
                actualSectionId = sectionId;
            } else if (container && sectionId.endsWith('-container')) {
                // 如果找到了且有 -container 後綴，去掉它
                actualSectionId = sectionId.replace('-container', '');
            } else if (container) {
                // 找到了但沒有 -container 後綴
                actualSectionId = sectionId;
            }
            
            if (!container) {
                console.error('找不到區塊容器:', sectionId);
                return;
            }
            
            container.classList.toggle('collapsed');
            sectionStates[actualSectionId] = container.classList.contains('collapsed');
            
            // 如果是圖表區塊，需要重新渲染圖表
            if (actualSectionId === 'charts-section' && !sectionStates[actualSectionId]) {
                setTimeout(() => {
                    // 重新渲染所有圖表
                    Object.values(charts).forEach(chart => {
                        if (chart) chart.resize();
                    });
                }, 300);
            }
            
            updateToggleTooltips();
        }

        // 切換所有區塊
        function toggleAllSections() {
            const allCollapsed = Object.values(sectionStates).every(state => state);
            const icon = document.getElementById('globalToggleIcon');
            
            // 如果全部收縮，則全部展開；否則全部收縮
            const newState = !allCollapsed;
            
            Object.keys(sectionStates).forEach(sectionId => {
                let container = document.getElementById(sectionId + '-container');
                // 如果沒找到，嘗試不帶 -container 的
                if (!container) {
                    container = document.getElementById(sectionId);
                }
                
                if (container) {
                    if (newState) {
                        container.classList.add('collapsed');
                    } else {
                        container.classList.remove('collapsed');
                    }
                    sectionStates[sectionId] = newState;
                }
            });
            
            // 更新圖標
            icon.textContent = newState ? '⊖' : '⊕';
            
            // 如果展開圖表區塊，重新渲染
            if (!newState) {
                setTimeout(() => {
                    Object.values(charts).forEach(chart => {
                        if (chart) chart.resize();
                    });
                }, 300);
            }
            
            // 更新全局按鈕的 Tooltip
            const globalBtn = document.getElementById('globalToggleBtn');
            if (globalBtn) {
                globalBtn.setAttribute('data-tooltip', allCollapsed ? '全部展開' : '全部收合');
            }
            
            // 更新 tooltip
            updateToggleTooltips();
            updateGlobalToggleTooltip();
    
        }
        
        // Initialize autocomplete
        document.addEventListener('DOMContentLoaded', function() {
            const pathInput = document.getElementById('pathInput');
            const autocompleteDiv = document.getElementById('pathAutocomplete');
            
            // Handle input events
            pathInput.addEventListener('input', function(e) {
                clearTimeout(autocompleteTimeout);
                const value = e.target.value;
                
                // Always fetch suggestions, even for empty input
                autocompleteTimeout = setTimeout(() => {
                    fetchPathSuggestions(value);
                }, 300);
            });
            
            // Handle keyboard navigation
            pathInput.addEventListener('keydown', function(e) {
                switch(e.key) {
                    case 'ArrowDown':
                        if (currentSuggestions.length > 0) {
                            e.preventDefault();
                            selectSuggestion(selectedSuggestionIndex + 1);
                        }
                        break;
                    case 'ArrowUp':
                        if (currentSuggestions.length > 0) {
                            e.preventDefault();
                            selectSuggestion(selectedSuggestionIndex - 1);
                        }
                        break;
                    case 'Enter':
                        if (currentSuggestions.length > 0 && selectedSuggestionIndex >= 0) {
                            e.preventDefault();
                            const cleanPath = currentSuggestions[selectedSuggestionIndex].replace(/ [⭐📁]$/, '');
                            applySuggestion(cleanPath);
                        } else if (currentSuggestions.length === 0 || selectedSuggestionIndex === -1) {
                            // 如果沒有選擇任何建議，就關閉提示框
                            hideAutocomplete();
                        }
                        break;
                    case 'Tab':
                        if (currentSuggestions.length > 0) {
                            e.preventDefault();
                            // If no selection, select first suggestion
                            const index = selectedSuggestionIndex >= 0 ? selectedSuggestionIndex : 0;
                            applySuggestion(currentSuggestions[index].replace(/ [⭐📁]$/, ''));
                        }
                        break;
                    case 'Escape':
                        hideAutocomplete();
                        break;
                }
            });
            
            // Handle focus
            pathInput.addEventListener('focus', function() {
                if (currentSuggestions.length > 0) {
                    showAutocomplete();
                } else {
                    // Fetch suggestions for current value
                    fetchPathSuggestions(this.value);
                }
            });

            pathInput.addEventListener('blur', function(e) {
                // 延遲執行，給予時間點擊提示項
                setTimeout(() => {
                    // 檢查當前焦點是否在自動完成框內
                    if (!document.activeElement.closest('#pathAutocomplete')) {
                        hideAutocomplete();
                    }
                }, 200);
            });
            
            // Handle click outside
            document.addEventListener('click', function(e) {
                if (navBarOpen && 
                    !e.target.closest('.nav-bar') && 
                    !e.target.closest('.nav-toggle-btn')) {
                    toggleNavBar();
                }
                const pathInput = document.getElementById('pathInput');
                const autocompleteDiv = document.getElementById('pathAutocomplete');
                
                // 如果點擊的不是輸入框或自動完成框，則隱藏提示框
                if (!pathInput.contains(e.target) && !autocompleteDiv.contains(e.target)) {
                    hideAutocomplete();
                }                
            });
            
            // Back to top button functionality
            window.addEventListener('scroll', function() {
                const backToTopBtn = document.getElementById('backToTop');
                const navToggleBtn = document.getElementById('navToggleBtn');
                const globalToggleBtn = document.getElementById('globalToggleBtn');
                const resultsDiv = document.getElementById('results');
                
                if (window.pageYOffset > 300) {
                    backToTopBtn.classList.add('show');
                    
                    // 只有在結果已顯示時才顯示導覽按鈕
                    if (resultsDiv && resultsDiv.style.display !== 'none') {
                        navToggleBtn.classList.add('show');
                        // 全局按鈕不在這裡控制顯示，由 showGlobalToggleButton 控制
                    }
                } else {
                    backToTopBtn.classList.remove('show');
                    navToggleBtn.classList.remove('show');
                    // 不要在這裡隱藏全局按鈕
                    
                    // 滾動到頂部時關閉導覽列
                    if (navBarOpen) {
                        toggleNavBar();
                    }
                }
            });
            
            // 為右下角浮動按鈕添加 tooltip
            const globalToggleBtn = document.getElementById('globalToggleBtn');
            const backToTopBtn = document.getElementById('backToTop');
            const navToggleBtn = document.getElementById('navToggleBtn');
            
            if (backToTopBtn) backToTopBtn.setAttribute('data-tooltip', '回到頂部');
            if (navToggleBtn) navToggleBtn.setAttribute('data-tooltip', '快速導覽');
            if (globalToggleBtn) globalToggleBtn.setAttribute('data-tooltip', '全部展開/收合');
            
            // 添加 tooltip-container class
            if (backToTopBtn) {
                backToTopBtn.classList.add('tooltip-container');
                backToTopBtn.setAttribute('data-tooltip', '回到頂部');
            }
            if (navToggleBtn) {
                navToggleBtn.classList.add('tooltip-container');
                navToggleBtn.setAttribute('data-tooltip', '快速導覽');
            }
            if (globalToggleBtn) {
                globalToggleBtn.classList.add('tooltip-container');
                globalToggleBtn.setAttribute('data-tooltip', '全部展開/收合');
            }
    
            // 強制重置浮動按鈕位置
            const floatingButtons = [
                document.getElementById('backToTop'),
                document.getElementById('navToggleBtn'),
                document.getElementById('globalToggleBtn')
            ];
            
            floatingButtons.forEach(btn => {
                if (btn) {
                    // 移除可能的內聯樣式
                    btn.style.removeProperty('left');
                    btn.style.removeProperty('top');
                    btn.style.removeProperty('transform');
                }
            });
            
            // 為所有開合按鈕設置 Tooltip
            updateToggleTooltips();
            
            // 為右下角浮動按鈕創建 tooltip
            setupFloatingTooltips();
            
            // 為區塊開合按鈕設置 Tooltip
            updateToggleTooltips();            
            
        });

        // 新增函數：設置浮動按鈕的 tooltip
        function setupFloatingTooltips() {
            const tooltipData = [
                { id: 'backToTop', text: '回到頂部' },
                { id: 'navToggleBtn', text: '快速導覽' },
                { id: 'globalToggleBtn', text: '全部展開/收合' }
            ];
            
            tooltipData.forEach(item => {
                const btn = document.getElementById(item.id);
                if (btn) {
                    // 創建 tooltip 元素
                    const tooltip = document.createElement('span');
                    tooltip.className = 'floating-tooltip';
                    tooltip.textContent = item.text;
                    btn.appendChild(tooltip);
                    
                    // 特別處理導覽按鈕
                    if (item.id === 'navToggleBtn') {
                        btn.addEventListener('mouseenter', function() {
                            // 只有在菜單關閉時才顯示 tooltip
                            if (!navBarOpen) {
                                tooltip.style.opacity = '1';
                                tooltip.style.visibility = 'visible';
                            }
                        });
                    } else {
                        // 其他按鈕正常處理
                        btn.addEventListener('mouseenter', function() {
                            tooltip.style.opacity = '1';
                            tooltip.style.visibility = 'visible';
                        });
                    }
                    
                    btn.addEventListener('mouseleave', function() {
                        // 導覽按鈕特殊處理
                        if (item.id === 'navToggleBtn' && navBarOpen) {
                            return; // 菜單開啟時不恢復 tooltip
                        }
                        tooltip.style.opacity = '0';
                        tooltip.style.visibility = 'hidden';
                    });
                }
            });
        }

        // 更新全局按鈕的 tooltip 文字
        function updateGlobalToggleTooltip() {
            const globalBtn = document.getElementById('globalToggleBtn');
            if (globalBtn) {
                const tooltip = globalBtn.querySelector('.floating-tooltip');
                if (tooltip) {
                    const allCollapsed = Object.values(sectionStates).every(state => state);
                    tooltip.textContent = allCollapsed ? '全部展開' : '全部收合';
                }
            }
        }

        // 新增函數：更新開合按鈕的 Tooltip
        function updateToggleTooltips() {
            document.querySelectorAll('.section-toggle').forEach(toggle => {
                const container = toggle.closest('.section-container');
                if (container && container.classList.contains('collapsed')) {
                    toggle.setAttribute('data-tooltip', '展開區塊');
                } else {
                    toggle.setAttribute('data-tooltip', '收合區塊');
                }
            });
        }

        function toggleNavBar() {
            const navBar = document.getElementById('navBar');
            const toggleBtn = document.getElementById('navToggleBtn');
            const tooltip = toggleBtn.querySelector('.floating-tooltip');
            
            navBarOpen = !navBarOpen;
            
            if (navBarOpen) {
                navBar.classList.remove('animating-out');
                navBar.classList.add('show', 'animating-in');
                toggleBtn.classList.add('active');
                
                // 隱藏 tooltip
                if (tooltip) {
                    tooltip.style.opacity = '0';
                    tooltip.style.visibility = 'hidden';
                }
                
                // 移除動畫類別
                setTimeout(() => {
                    navBar.classList.remove('animating-in');
                }, 300);
            } else {
                navBar.classList.remove('animating-in');
                navBar.classList.add('animating-out');
                toggleBtn.classList.remove('active');
                
                // 延遲顯示 tooltip（等菜單完全關閉後）
                setTimeout(() => {
                    if (tooltip) {
                        tooltip.style.opacity = '';
                        tooltip.style.visibility = '';
                    }
                }, 300);
                
                // 延遲移除 show 類別
                setTimeout(() => {
                    navBar.classList.remove('show', 'animating-out');
                }, 300);
            }
        }
        
        async function fetchPathSuggestions(path) {
            const autocompleteDiv = document.getElementById('pathAutocomplete');
            
            // Show loading
            autocompleteDiv.innerHTML = '<div class="path-loading">載入中...</div>';
            showAutocomplete();
            
            try {
                const response = await fetch('/suggest-path', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ path: path })
                });
                
                const data = await response.json();
                currentSuggestions = data.suggestions || [];
                selectedSuggestionIndex = -1;
                
                if (currentSuggestions.length > 0) {
                    displaySuggestions(currentSuggestions);
                } else {
                    autocompleteDiv.innerHTML = '<div class="path-loading">沒有找到符合的路徑</div>';
                }
            } catch (error) {
                console.error('Error fetching suggestions:', error);
                hideAutocomplete();
            }
        }
        
        function displaySuggestions(suggestions) {
            const autocompleteDiv = document.getElementById('pathAutocomplete');
            autocompleteDiv.innerHTML = '';
            
            suggestions.forEach((suggestion, index) => {
                const div = document.createElement('div');
                div.className = 'path-suggestion';
                div.dataset.index = index;
                
                // Check if this is a marked folder
                if (suggestion.includes(' ⭐')) {
                    const cleanPath = suggestion.replace(' ⭐', '');
                    div.innerHTML = `${escapeHtml(cleanPath)}<span class="star">⭐</span>`;
                    div.dataset.path = cleanPath;
                } else if (suggestion.includes(' 📁')) {
                    const cleanPath = suggestion.replace(' 📁', '');
                    div.innerHTML = `${escapeHtml(cleanPath)}<span class="star">📁</span>`;
                    div.dataset.path = cleanPath;
                } else {
                    div.textContent = suggestion;
                    div.dataset.path = suggestion;
                }
                
                div.addEventListener('click', function() {
                    applySuggestion(div.dataset.path);
                });
                
                div.addEventListener('mouseenter', function() {
                    selectSuggestion(index);
                });
                
                autocompleteDiv.appendChild(div);
            });
            
            showAutocomplete();
        }
        
        function selectSuggestion(index) {
            const suggestions = document.querySelectorAll('.path-suggestion');
            
            // Remove previous selection
            suggestions.forEach(s => s.classList.remove('selected'));
            
            // Validate index
            if (index < 0) index = suggestions.length - 1;
            if (index >= suggestions.length) index = 0;
            
            selectedSuggestionIndex = index;
            
            // Add selection
            if (index >= 0 && index < suggestions.length) {
                suggestions[index].classList.add('selected');
                suggestions[index].scrollIntoView({ block: 'nearest' });
            }
        }
        
        function applySuggestion(suggestion) {
            const pathInput = document.getElementById('pathInput');
            // Use the clean path from dataset
            pathInput.value = suggestion;
            hideAutocomplete();
            
            // Trigger another suggestion fetch if path ends with separator
            if (suggestion.endsWith('/') || suggestion.endsWith('\\')) {
                fetchPathSuggestions(suggestion);
            }
        }
        
        function showAutocomplete() {
            document.getElementById('pathAutocomplete').style.display = 'block';
            document.getElementById('pathInput').classList.add('autocomplete-open');
        }
        
        function hideAutocomplete() {
            document.getElementById('pathAutocomplete').style.display = 'none';
            document.getElementById('pathInput').classList.remove('autocomplete-open');
            selectedSuggestionIndex = -1;
            currentSuggestions = [];
        }
        
        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function scrollToTop() {
            window.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        }
        
        async function analyzeLogs() {
            const path = document.getElementById('pathInput').value;
            if (!path) {
                showMessage('請輸入路徑', 'error');
                return;
            }
            
            // Disable analyze button
            document.getElementById('analyzeBtn').disabled = true;
            document.getElementById('loading').style.display = 'block';
            document.getElementById('results').style.display = 'none';
            document.getElementById('exportHtmlBtn').style.display = 'none';
            clearMessage();
            
            try {
                const response = await fetch('/analyze', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ path: path })
                });
                
                const data = await response.json();
                
                if (!response.ok) {
                    throw new Error(data.error || 'Analysis failed');
                }
                
                if (data.files_with_cmdline === 0) {
                    showMessage('警告: 在 anr/ 和 tombstones/ 資料夾中沒有找到包含 Cmd line: 或 Cmdline: 的檔案', 'error');
                    document.getElementById('analyzeBtn').disabled = false;
                    return;
                }
                
                currentAnalysisId = data.analysis_id;
                
                // Sort logs by timestamp
                const sortedLogs = data.logs.sort((a, b) => {
                    if (!a.timestamp && !b.timestamp) return 0;
                    if (!a.timestamp) return 1;
                    if (!b.timestamp) return -1;
                    return a.timestamp.localeCompare(b.timestamp);
                });
                
                allLogs = sortedLogs;
                allSummary = data.statistics.type_process_summary || [];
                allFileStats = data.file_statistics || [];
                
                // Reset filters and pagination
                resetFiltersAndPagination();
                
                // Update UI
                updateResults(data);
                
                // Enable export buttons
                document.getElementById('exportJsonBtn').disabled = false;
                document.getElementById('exportCsvBtn').disabled = false;
                document.getElementById('exportHtmlBtn').style.display = 'block';
                
                let message = `分析完成！共掃描 ${data.total_files} 個檔案，找到 ${data.files_with_cmdline} 個包含 Cmdline 的檔案`;
                message += `<br>分析耗時: ${data.analysis_time} 秒`;
                if (data.used_grep) {
                    message += '<span class="grep-badge">使用 grep 加速</span>';
                } else {
                    message += '<span class="grep-badge no-grep-badge">未使用 grep</span>';
                }
                
                showMessage(message, 'success');
                
            } catch (error) {
                showMessage('錯誤: ' + error.message, 'error');
            } finally {
                document.getElementById('loading').style.display = 'none';
                document.getElementById('analyzeBtn').disabled = false;
            }
        }

        // 修改 CSS，確保全局按鈕預設隱藏
        const globalToggleStyle = `
        <style>
        .global-toggle-btn {
            position: fixed !important;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 24px;
            cursor: pointer;
            transition: all 0.3s;
            z-index: 9999 !important;
            right: 30px !important;
            left: auto !important;
            bottom: 150px !important;
            background: #667eea;
            color: white;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
            text-align: center;
            line-height: 1;
            opacity: 0;
            visibility: hidden;
        }

        .global-toggle-btn.show {
            opacity: 1;
            visibility: visible;
        }

        .global-toggle-btn:hover {
            background: #5a67d8;
            transform: translateY(-5px) !important;
            box-shadow: 0 6px 16px rgba(102, 126, 234, 0.6);
        }
        </style>`;

        // 在 DOMContentLoaded 時注入樣式
        document.addEventListener('DOMContentLoaded', function() {
            // 注入全局按鈕樣式
            const styleElement = document.createElement('div');
            styleElement.innerHTML = globalToggleStyle;
            const style = styleElement.querySelector('style');
            if (style) {
                document.head.appendChild(style);
            }
            
            // 確保全局按鈕初始狀態是隱藏的
            const globalToggleBtn = document.getElementById('globalToggleBtn');
            if (globalToggleBtn) {
                globalToggleBtn.classList.remove('show');
            }
        });
        
        function resetFiltersAndPagination() {
            summaryPage = 1;
            logsPage = 1;
            filesPage = 1;
            processSummaryPage = 1;
            filteredSummary = [...allSummary];
            filteredLogs = [...allLogs];
            filteredFiles = [...allFileStats];
            filteredProcessSummary = [...allProcessSummary];
            document.getElementById('summarySearchInput').value = '';
            document.getElementById('logsSearchInput').value = '';
            document.getElementById('filesSearchInput').value = '';
            document.getElementById('processSummarySearchInput').value = '';
            // 重置 regex toggles
            document.getElementById('summaryRegexToggle').checked = false;
            document.getElementById('logsRegexToggle').checked = false;
            document.getElementById('filesRegexToggle').checked = false;
            document.getElementById('processSummaryRegexToggle').checked = false;
        }
        
        function updateResults(data) {
            // 生成程序統計（不分類型）
            const processOnlyCount = {};
            data.statistics.type_process_summary.forEach(item => {
                if (!processOnlyCount[item.process]) {
                    processOnlyCount[item.process] = 0;
                }
                processOnlyCount[item.process] += item.count;
            });
            
            // 轉換為陣列格式
            allProcessSummary = Object.entries(processOnlyCount)
                .map(([process, count]) => ({ process, count }))
                .sort((a, b) => b.count - a.count);
            
            filteredProcessSummary = [...allProcessSummary];

            // Update summary statistics
            const uniqueProcesses = data.statistics.total_unique_processes || 0;
            const summaryHtml = `
                <div class="stat-card">
                    <h3>${data.total_files}</h3>
                    <p>總掃描檔案數</p>
                </div>
                <div class="stat-card highlight">
                    <h3>${data.files_with_cmdline}</h3>
                    <p>包含 Cmdline</p>
                </div>
                <div class="stat-card">
                    <h3>${uniqueProcesses}</h3>
                    <p>不同的程序</p>
                </div>
                <div class="stat-card">
                    <h3>${data.anr_folders + data.tombstone_folders}</h3>
                    <p>資料夾總數</p>
                </div>
            `;
            document.getElementById('statsSummary').innerHTML = summaryHtml;
            
            // Update charts
            updateProcessChart(data.statistics.type_process_summary);
            updateTypeChart(data.statistics.by_type);
            updateDailyChart(data.statistics.by_date, data.statistics.by_date_type);
            updateHourlyChart(data.statistics.by_hour, data.statistics.by_hour_type);
            
            // Update tables with pagination
            updateSummaryTable();
            updateFilesTable();
            updateLogsTable();
            
            // Show results
            document.getElementById('results').style.display = 'block';
            
            // Setup search handlers
            setupSearchHandlers();

            // 更新程序統計表格
            updateProcessSummaryTable();
            
            // 只有在有結果時才顯示全局按鈕
            if (data.files_with_cmdline > 0) {
                showGlobalToggleButton();
            }
        }

        // 顯示全局展開/收合按鈕
        function showGlobalToggleButton() {
            const globalToggleBtn = document.getElementById('globalToggleBtn');
            if (globalToggleBtn) {
                globalToggleBtn.classList.add('show');
            }
        }

        // 更新程序統計表格
        function updateProcessSummaryTable() {
            const tbody = document.getElementById('processSummaryTableBody');
            tbody.innerHTML = '';
            
            // 更新排序指示器
            document.querySelectorAll('#process-summary-section .sort-indicator').forEach(span => {
                const col = span.dataset.column;
                if (col === processSummarySort.column) {
                    span.textContent = processSummarySort.order === 'asc' ? '▲' : '▼';
                } else {
                    span.textContent = '';
                }
            });
            
            const totalPages = Math.max(1, Math.ceil(filteredProcessSummary.length / itemsPerPage));
            const startIndex = (processSummaryPage - 1) * itemsPerPage;
            const endIndex = Math.min(startIndex + itemsPerPage, filteredProcessSummary.length);
            const pageData = filteredProcessSummary.slice(startIndex, endIndex);
            
            if (pageData.length === 0) {
                const row = tbody.insertRow();
                row.innerHTML = `<td colspan="3" style="text-align: center; padding: 20px; color: #666;">
                    ${filteredProcessSummary.length === 0 && document.getElementById('processSummarySearchInput').value ? 
                      '沒有找到符合搜尋條件的資料' : '沒有資料'}
                </td>`;
            } else {
                const searchTerm = document.getElementById('processSummarySearchInput').value;
                const useRegex = document.getElementById('processSummaryRegexToggle').checked;
                
                pageData.forEach((item, index) => {
                    const row = tbody.insertRow();
                    const globalIndex = startIndex + index + 1;
                    
                    row.innerHTML = `
                        <td class="rank-number" style="text-align: center;">${globalIndex}</td>
                        <td class="process-name">${highlightText(item.process, searchTerm, useRegex)}</td>
                        <td style="text-align: center; font-weight: bold; color: #e53e3e;">${item.count}</td>
                    `;
                });
            }
            
            // 更新分頁資訊
            document.getElementById('processSummaryPageInfo').textContent = 
                `第 ${processSummaryPage} 頁 / 共 ${totalPages} 頁 (總計 ${filteredProcessSummary.length} 筆)`;
            
            updatePaginationButtons('processSummary', processSummaryPage, totalPages);
        }
        
        // 排序函數
        function sortProcessSummaryTable(column) {
            if (processSummarySort.column === column) {
                processSummarySort.order = processSummarySort.order === 'asc' ? 'desc' : 'asc';
            } else {
                processSummarySort.column = column;
                processSummarySort.order = column === 'count' ? 'desc' : 'asc';
            }
            
            filteredProcessSummary.sort((a, b) => {
                let aVal, bVal;
                
                switch (column) {
                    case 'rank':
                        aVal = allProcessSummary.indexOf(a);
                        bVal = allProcessSummary.indexOf(b);
                        break;
                    case 'process':
                        aVal = a.process;
                        bVal = b.process;
                        break;
                    case 'count':
                        aVal = a.count;
                        bVal = b.count;
                        break;
                }
                
                if (typeof aVal === 'string') {
                    return processSummarySort.order === 'asc' ? 
                        aVal.localeCompare(bVal) : 
                        bVal.localeCompare(aVal);
                } else {
                    return processSummarySort.order === 'asc' ? 
                        aVal - bVal : 
                        bVal - aVal;
                }
            });
            
            processSummaryPage = 1;
            updateProcessSummaryTable();
        }

        // 分頁函數
        function changeProcessSummaryPage(direction) {
            const totalPages = Math.ceil(filteredProcessSummary.length / itemsPerPage);
            
            if (direction === 'first') {
                processSummaryPage = 1;
            } else if (direction === 'last') {
                processSummaryPage = totalPages;
            } else {
                processSummaryPage = Math.max(1, Math.min(processSummaryPage + direction, totalPages));
            }
            
            updateProcessSummaryTable();
        }
        
        function setupSearchHandlers() {
            // Summary search with regex support
            const summarySearchHandler = (e) => {
                const searchTerm = e.target.value;
                const countElement = document.getElementById('summarySearchCount');
                const useRegex = document.getElementById('summaryRegexToggle').checked;
                
                if (searchTerm === '') {
                    // Reset to show all data
                    filteredSummary = [...allSummary];
                    countElement.style.display = 'none';
                } else {
                    try {
                        let searchFunction;
                        if (useRegex) {
                            const regex = new RegExp(searchTerm, 'i');
                            searchFunction = item => 
                                regex.test(item.type) || regex.test(item.process);
                        } else {
                            const lowerSearchTerm = searchTerm.toLowerCase();
                            searchFunction = item => 
                                item.type.toLowerCase().includes(lowerSearchTerm) ||
                                item.process.toLowerCase().includes(lowerSearchTerm);
                        }
                        
                        filteredSummary = allSummary.filter(searchFunction);
                        
                        // 計算總次數
                        const totalCount = filteredSummary.reduce((sum, item) => sum + item.count, 0);
                        
                        // 顯示搜尋結果數量和總次數
                        countElement.innerHTML = `找到 <span style="color: #e53e3e;">${filteredSummary.length}</span> 筆項目，總次數: <span style="color: #e53e3e;">${totalCount}</span>`;
                        countElement.style.display = 'inline';
                    } catch (error) {
                        // Invalid regex
                        countElement.innerHTML = `<span style="color: #e53e3e;">無效的正則表達式</span>`;
                        countElement.style.display = 'inline';
                        filteredSummary = [];
                    }
                }
                summaryPage = 1; // Reset to first page
                updateSummaryTable();
            };
            
            document.getElementById('summarySearchInput').addEventListener('input', summarySearchHandler);
            document.getElementById('summaryRegexToggle').addEventListener('change', function() {
                // 強制觸發搜尋處理器
                summarySearchHandler({ target: document.getElementById('summarySearchInput') });
            });
            
            // Logs search with regex support
            const logsSearchHandler = (e) => {
                const searchTerm = e.target.value;
                const countElement = document.getElementById('logsSearchCount');
                const useRegex = document.getElementById('logsRegexToggle').checked;
                
                if (searchTerm === '') {
                    // Reset to show all data
                    filteredLogs = [...allLogs];
                    countElement.style.display = 'none';
                } else {
                    try {
                        let searchFunction;
                        if (useRegex) {
                            const regex = new RegExp(searchTerm, 'i');
                            searchFunction = log => 
                                (log.process && regex.test(log.process)) ||
                                (log.type && regex.test(log.type)) ||
                                (log.filename && regex.test(log.filename)) ||
                                (log.folder_path && regex.test(log.folder_path));
                        } else {
                            const lowerSearchTerm = searchTerm.toLowerCase();
                            searchFunction = log => 
                                (log.process && log.process.toLowerCase().includes(lowerSearchTerm)) ||
                                (log.type && log.type.toLowerCase().includes(lowerSearchTerm)) ||
                                (log.filename && log.filename.toLowerCase().includes(lowerSearchTerm)) ||
                                (log.folder_path && log.folder_path.toLowerCase().includes(lowerSearchTerm));
                        }
                        
                        filteredLogs = allLogs.filter(searchFunction);
                        
                        countElement.innerHTML = `找到 <span style="color: #e53e3e;">${filteredLogs.length}</span> 筆記錄`;
                        countElement.style.display = 'inline';
                    } catch (error) {
                        // Invalid regex
                        countElement.innerHTML = `<span style="color: #e53e3e;">無效的正則表達式</span>`;
                        countElement.style.display = 'inline';
                        filteredLogs = [];
                    }
                }
                logsPage = 1;
                updateLogsTable();
            };
            
            document.getElementById('logsSearchInput').addEventListener('input', logsSearchHandler);
            document.getElementById('logsRegexToggle').addEventListener('change', function() {
                // 強制觸發搜尋處理器
                logsSearchHandler({ target: document.getElementById('logsSearchInput') });
            });
            
            // Files search with regex support
            const filesSearchHandler = (e) => {
                const searchTerm = e.target.value;
                const countElement = document.getElementById('filesSearchCount');
                const useRegex = document.getElementById('filesRegexToggle').checked;
                
                if (searchTerm === '') {
                    // Reset to show all data
                    filteredFiles = [...allFileStats];
                    countElement.style.display = 'none';
                } else {
                    try {
                        let searchFunction;
                        if (useRegex) {
                            const regex = new RegExp(searchTerm, 'i');
                            searchFunction = file => 
                                regex.test(file.filename) ||
                                file.processes.some(proc => regex.test(proc));
                        } else {
                            const lowerSearchTerm = searchTerm.toLowerCase();
                            searchFunction = file => 
                                file.filename.toLowerCase().includes(lowerSearchTerm) ||
                                file.processes.some(proc => proc.toLowerCase().includes(lowerSearchTerm));
                        }
                        
                        filteredFiles = allFileStats.filter(searchFunction);
                        
                        // 計算總次數
                        let totalCount = 0;
                        filteredFiles.forEach(file => {
                            // 解析每個程序的次數
                            file.processes.forEach(procStr => {
                                // procStr 格式: "程序名稱 (次數)"
                                const match = procStr.match(/^(.+)\s+\((\d+)\)$/);
                                if (match) {
                                    const processName = match[1];
                                    const count = parseInt(match[2]);
                                    // 檢查程序名稱是否符合搜尋條件
                                    if (useRegex) {
                                        const regex = new RegExp(searchTerm, 'i');
                                        if (regex.test(processName)) {
                                            totalCount += count;
                                        }
                                    } else {
                                        if (processName.toLowerCase().includes(searchTerm.toLowerCase())) {
                                            totalCount += count;
                                        }
                                    }
                                }
                            });
                        });
                        
                        // 顯示搜尋結果數量和總次數
                        countElement.innerHTML = `找到 <span style="color: #e53e3e;">${filteredFiles.length}</span> 筆檔案，總次數: <span style="color: #e53e3e;">${totalCount}</span>`;
                        countElement.style.display = 'inline';
                    } catch (error) {
                        // Invalid regex
                        countElement.innerHTML = `<span style="color: #e53e3e;">無效的正則表達式</span>`;
                        countElement.style.display = 'inline';
                        filteredFiles = [];
                    }
                }
                filesPage = 1;
                updateFilesTable();
            };
            
            document.getElementById('filesSearchInput').addEventListener('input', filesSearchHandler);
            document.getElementById('filesRegexToggle').addEventListener('change', function() {
                // 強制觸發搜尋處理器
                filesSearchHandler({ target: document.getElementById('filesSearchInput') });
            });
            
            const processSummarySearchHandler = (e) => {
                const searchTerm = e.target.value;
                const countElement = document.getElementById('processSummarySearchCount');
                const useRegex = document.getElementById('processSummaryRegexToggle').checked;
                
                if (searchTerm === '') {
                    filteredProcessSummary = [...allProcessSummary];
                    countElement.style.display = 'none';
                } else {
                    try {
                        let searchFunction;
                        if (useRegex) {
                            const regex = new RegExp(searchTerm, 'i');
                            searchFunction = item => regex.test(item.process);
                        } else {
                            const lowerSearchTerm = searchTerm.toLowerCase();
                            searchFunction = item => 
                                item.process.toLowerCase().includes(lowerSearchTerm);
                        }
                        
                        filteredProcessSummary = allProcessSummary.filter(searchFunction);
                        
                        const totalCount = filteredProcessSummary.reduce((sum, item) => sum + item.count, 0);
                        
                        countElement.innerHTML = `找到 <span style="color: #e53e3e;">${filteredProcessSummary.length}</span> 筆項目，總次數: <span style="color: #e53e3e;">${totalCount}</span>`;
                        countElement.style.display = 'inline';
                    } catch (error) {
                        countElement.innerHTML = `<span style="color: #e53e3e;">無效的正則表達式</span>`;
                        countElement.style.display = 'inline';
                        filteredProcessSummary = [];
                    }
                }
                processSummaryPage = 1;
                updateProcessSummaryTable();
            };

            document.getElementById('processSummarySearchInput').addEventListener('input', processSummarySearchHandler);
            document.getElementById('processSummaryRegexToggle').addEventListener('change', function() {
                // 強制觸發搜尋處理器
                processSummarySearchHandler({ target: document.getElementById('processSummarySearchInput') });
            });
        }

        function sortSummaryTable(column) {
            // 切換排序順序
            if (summarySort.column === column) {
                summarySort.order = summarySort.order === 'asc' ? 'desc' : 'asc';
            } else {
                summarySort.column = column;
                summarySort.order = column === 'count' ? 'desc' : 'asc'; // 次數預設降序，其他升序
            }
            
            // 排序資料
            filteredSummary.sort((a, b) => {
                let aVal, bVal;
                
                switch (column) {
                    case 'rank':
                        // 按原始順序
                        aVal = allSummary.indexOf(a);
                        bVal = allSummary.indexOf(b);
                        break;
                    case 'type':
                        aVal = a.type;
                        bVal = b.type;
                        break;
                    case 'process':
                        aVal = a.process;
                        bVal = b.process;
                        break;
                    case 'count':
                        aVal = a.count;
                        bVal = b.count;
                        break;
                }
                
                if (typeof aVal === 'string') {
                    return summarySort.order === 'asc' ? 
                        aVal.localeCompare(bVal) : 
                        bVal.localeCompare(aVal);
                } else {
                    return summarySort.order === 'asc' ? 
                        aVal - bVal : 
                        bVal - aVal;
                }
            });
            
            // 重置到第一頁
            summaryPage = 1;
            updateSummaryTable();
        }

        function sortFilesTable(column) {
            if (filesSort.column === column) {
                filesSort.order = filesSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                filesSort.column = column;
                filesSort.order = column === 'count' ? 'desc' : 'asc';
            }
            
            filteredFiles.sort((a, b) => {
                let aVal, bVal;
                
                switch (column) {
                    case 'type':
                        aVal = a.type;
                        bVal = b.type;
                        break;
                    case 'filename':
                        aVal = a.filename;
                        bVal = b.filename;
                        break;
                    case 'count':
                        aVal = a.count;
                        bVal = b.count;
                        break;
                    case 'timestamp':
                        aVal = a.timestamp;
                        bVal = b.timestamp;
                        break;
                }
                
                if (typeof aVal === 'string') {
                    return filesSort.order === 'asc' ? 
                        aVal.localeCompare(bVal) : 
                        bVal.localeCompare(aVal);
                } else {
                    return filesSort.order === 'asc' ? 
                        aVal - bVal : 
                        bVal - aVal;
                }
            });
            
            filesPage = 1;
            updateFilesTable();
        }

        function sortFilesTable(column) {
            if (filesSort.column === column) {
                filesSort.order = filesSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                filesSort.column = column;
                filesSort.order = column === 'count' ? 'desc' : 'asc';
            }
            
            filteredFiles.sort((a, b) => {
                let aVal, bVal;
                
                switch (column) {
                    case 'index':
                        aVal = allFileStats.indexOf(a);
                        bVal = allFileStats.indexOf(b);
                        break;
                    case 'type':
                        aVal = a.type || '';
                        bVal = b.type || '';
                        break;
                    case 'processes':
                        // 使用第一個程序名稱排序
                        aVal = a.processes[0] || '';
                        bVal = b.processes[0] || '';
                        break;
                    case 'folder_path':
                        aVal = a.folder_path || '';
                        bVal = b.folder_path || '';
                        break;
                    case 'filename':
                        aVal = a.filename || '';
                        bVal = b.filename || '';
                        break;
                    case 'count':
                        aVal = a.count || 0;
                        bVal = b.count || 0;
                        break;
                    case 'timestamp':
                        aVal = a.timestamp || '';
                        bVal = b.timestamp || '';
                        break;
                }
                
                if (typeof aVal === 'string') {
                    return filesSort.order === 'asc' ? 
                        aVal.localeCompare(bVal) : 
                        bVal.localeCompare(aVal);
                } else {
                    return filesSort.order === 'asc' ? 
                        aVal - bVal : 
                        bVal - aVal;
                }
            });
            
            filesPage = 1;
            updateFilesTable();
        }
        
        function sortLogsTable(column) {
            if (logsSort.column === column) {
                logsSort.order = logsSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                logsSort.column = column;
                logsSort.order = 'asc';
            }
            
            filteredLogs.sort((a, b) => {
                let aVal, bVal;
                
                switch (column) {
                    case 'index':
                        aVal = allLogs.indexOf(a);
                        bVal = allLogs.indexOf(b);
                        break;
                    case 'type':
                        aVal = a.type || '';
                        bVal = b.type || '';
                        break;
                    case 'process':
                        aVal = a.process || '';
                        bVal = b.process || '';
                        break;
                    case 'line_number':
                        aVal = a.line_number || 0;
                        bVal = b.line_number || 0;
                        break;
                    case 'folder_path':
                        aVal = a.folder_path || '';
                        bVal = b.folder_path || '';
                        break;
                    case 'filename':
                        aVal = a.filename || '';
                        bVal = b.filename || '';
                        break;
                    case 'timestamp':
                        aVal = a.timestamp || '';
                        bVal = b.timestamp || '';
                        break;
                }
                
                if (typeof aVal === 'string') {
                    return logsSort.order === 'asc' ? 
                        aVal.localeCompare(bVal) : 
                        bVal.localeCompare(aVal);
                } else {
                    return logsSort.order === 'asc' ? 
                        aVal - bVal : 
                        bVal - aVal;
                }
            });
            
            logsPage = 1;
            updateLogsTable();
        }
        
        function updateSummaryTable() {
            const tbody = document.getElementById('summaryTableBody');
            tbody.innerHTML = '';
            
            // 更新排序指示器
            document.querySelectorAll('#summary-section .sort-indicator').forEach(span => {
                const col = span.dataset.column;
                if (col === summarySort.column) {
                    span.textContent = summarySort.order === 'asc' ? '▲' : '▼';
                } else {
                    span.textContent = '';
                }
            });
            
            const totalPages = Math.max(1, Math.ceil(filteredSummary.length / itemsPerPage));
            const startIndex = (summaryPage - 1) * itemsPerPage;
            const endIndex = Math.min(startIndex + itemsPerPage, filteredSummary.length);
            const pageData = filteredSummary.slice(startIndex, endIndex);
            
            if (pageData.length === 0) {
                // Show no data message
                const row = tbody.insertRow();
                row.innerHTML = `<td colspan="4" style="text-align: center; padding: 20px; color: #666;">
                    ${filteredSummary.length === 0 && document.getElementById('summarySearchInput').value ? 
                      '沒有找到符合搜尋條件的資料' : '沒有資料'}
                </td>`;
            } else {
                pageData.forEach((item, index) => {
                    const row = tbody.insertRow();
                    const globalIndex = startIndex + index + 1;
                    const searchTerm = document.getElementById('summarySearchInput').value;
                    const useRegex = document.getElementById('summaryRegexToggle').checked;
                    
                    row.innerHTML = `
                        <td class="rank-number" style="text-align: center;">${globalIndex}</td>
                        <td>${highlightText(item.type, searchTerm, useRegex)}</td>
                        <td class="process-name">${highlightText(item.process, searchTerm, useRegex)}</td>
                        <td style="text-align: center; font-weight: bold; color: #e53e3e;">${item.count}</td>
                    `;
                });
            }
            
            // Update pagination info
            document.getElementById('summaryPageInfo').textContent = 
                `第 ${summaryPage} 頁 / 共 ${totalPages} 頁 (總計 ${filteredSummary.length} 筆)`;
            
            // Update pagination buttons state
            updatePaginationButtons('summary', summaryPage, totalPages);
        }

        function updateLogsTable() {
            const tbody = document.getElementById('logsTableBody');
            tbody.innerHTML = '';

            // 更新排序指示器
            document.querySelectorAll('#logs-section .sort-indicator').forEach(span => {
                const col = span.dataset.column;
                if (col === logsSort.column) {
                    span.textContent = logsSort.order === 'asc' ? '▲' : '▼';
                } else {
                    span.textContent = '';
                }
            });
    
            const totalPages = Math.max(1, Math.ceil(filteredLogs.length / itemsPerPage));
            const startIndex = (logsPage - 1) * itemsPerPage;
            const endIndex = Math.min(startIndex + itemsPerPage, filteredLogs.length);
            const pageData = filteredLogs.slice(startIndex, endIndex);
            
            if (pageData.length === 0) {
                // Show no data message
                const row = tbody.insertRow();
                row.innerHTML = `<td colspan="7" style="text-align: center; padding: 20px; color: #666;">
                    ${filteredLogs.length === 0 && document.getElementById('logsSearchInput').value ? 
                      '沒有找到符合搜尋條件的資料' : '沒有資料'}
                </td>`;
            } else {
                const searchTerm = document.getElementById('logsSearchInput').value;
                const useRegex = document.getElementById('logsRegexToggle').checked;
                
                pageData.forEach((log, index) => {
                    const row = tbody.insertRow();
                    const globalIndex = startIndex + index + 1;
                    
                    // Create clickable file link
                    const fileLink = `/view-file?path=${encodeURIComponent(log.file)}`;
                    
                    // Process display
                    const processDisplay = log.process || '-';
                    
                    // Line number display
                    const lineNumber = log.line_number || '-';
                    
                    // Folder path display
                    const folderPath = log.folder_path || '-';
                    
                    row.innerHTML = `
                        <td style="text-align: center; color: #666;">${globalIndex}</td>
                        <td>${highlightText(log.type, searchTerm, useRegex)}</td>
                        <td class="process-name">${highlightText(processDisplay, searchTerm, useRegex)}</td>
                        <td style="text-align: center; font-weight: bold; color: #667eea;">${lineNumber}</td>
                        <td style="color: #999; font-size: 0.9em;">${highlightText(folderPath, searchTerm, useRegex)}</td>
                        <td><a href="${fileLink}" target="_blank" class="file-link">${highlightText(log.filename, searchTerm, useRegex)}</a></td>
                        <td>${log.timestamp || '-'}</td>
                    `;
                });
            }
            
            // Update pagination info
            document.getElementById('logsPageInfo').textContent = 
                `第 ${logsPage} 頁 / 共 ${totalPages} 頁 (總計 ${filteredLogs.length} 筆)`;
            
            // Update pagination buttons state
            updatePaginationButtons('logs', logsPage, totalPages);
        }
        
        function changeSummaryPage(direction) {
            const totalPages = Math.ceil(filteredSummary.length / itemsPerPage);
            
            if (direction === 'first') {
                summaryPage = 1;
            } else if (direction === 'last') {
                summaryPage = totalPages;
            } else {
                summaryPage = Math.max(1, Math.min(summaryPage + direction, totalPages));
            }
            
            updateSummaryTable();
        }
        
        function updatePaginationButtons(type, currentPage, totalPages) {
            const firstBtn = document.getElementById(`${type}FirstBtn`);
            const prevBtn = document.getElementById(`${type}PrevBtn`);
            const nextBtn = document.getElementById(`${type}NextBtn`);
            const lastBtn = document.getElementById(`${type}LastBtn`);
            
            // Disable/enable buttons based on current page
            firstBtn.disabled = currentPage === 1;
            prevBtn.disabled = currentPage === 1;
            nextBtn.disabled = currentPage === totalPages || totalPages === 0;
            lastBtn.disabled = currentPage === totalPages || totalPages === 0;
        }
        
        function updateFilesTable() {
            const tbody = document.getElementById('filesTableBody');
            tbody.innerHTML = '';

            // 更新排序指示器
            document.querySelectorAll('#files-section .sort-indicator').forEach(span => {
                const col = span.dataset.column;
                if (col === filesSort.column) {
                    span.textContent = filesSort.order === 'asc' ? '▲' : '▼';
                } else {
                    span.textContent = '';
                }
            });
    
            const totalPages = Math.max(1, Math.ceil(filteredFiles.length / itemsPerPage));
            const startIndex = (filesPage - 1) * itemsPerPage;
            const endIndex = Math.min(startIndex + itemsPerPage, filteredFiles.length);
            const pageData = filteredFiles.slice(startIndex, endIndex);
            
            if (pageData.length === 0) {
                // Show no data message
                const row = tbody.insertRow();
                row.innerHTML = `<td colspan="7" style="text-align: center; padding: 20px; color: #666;">
                    ${filteredFiles.length === 0 && document.getElementById('filesSearchInput').value ? 
                      '沒有找到符合搜尋條件的資料' : '沒有資料'}
                </td>`;
            } else {
                const searchTerm = document.getElementById('filesSearchInput').value;
                const useRegex = document.getElementById('filesRegexToggle').checked;
                
                pageData.forEach((file, index) => {
                    const row = tbody.insertRow();
                    const globalIndex = startIndex + index + 1;
                    
                    // 直接使用 file.filepath
                    const fileLink = `/view-file?path=${encodeURIComponent(file.filepath || '')}`;
                    const folderPath = file.folder_path || '-';
                    
                    // 處理 processes 高亮
                    const processesHtml = file.processes.length > 0 ? 
                        file.processes.map(p => {
                            // 解析程序名稱和次數
                            const match = p.match(/^(.+)\s+\((\d+)\)$/);
                            if (match) {
                                const processName = match[1];
                                const count = match[2];
                                const highlightedName = highlightText(processName, searchTerm, useRegex);
                                return `${highlightedName} <span style="color: #e53e3e; font-weight: bold;">(${count})</span>`;
                            }
                            return highlightText(p, searchTerm, useRegex);
                        }).join(', ') : '-';
                    
                    const timestamp = file.timestamp || '-';
                    
                    row.innerHTML = `
                        <td style="text-align: center; color: #666;">${globalIndex}</td>
                        <td>${highlightText(file.type, searchTerm, useRegex)}</td>
                        <td class="process-name">${processesHtml}</td>
                        <td style="color: #999; font-size: 0.9em;">${highlightText(folderPath, searchTerm, useRegex)}</td>
                        <td><a href="${fileLink}" target="_blank" class="file-link">${highlightText(file.filename, searchTerm, useRegex)}</a></td>
                        <td style="text-align: center; font-weight: bold; color: #e53e3e;">${file.count}</td>
                        <td>${timestamp}</td>
                    `;
                });
            }
            
            // Update pagination info
            document.getElementById('filesPageInfo').textContent = 
                `第 ${filesPage} 頁 / 共 ${totalPages} 頁 (總計 ${filteredFiles.length} 筆)`;
            
            // Update pagination buttons state
            updatePaginationButtons('files', filesPage, totalPages);
        }
        
        function changeLogsPage(direction) {
            const totalPages = Math.ceil(filteredLogs.length / itemsPerPage);
            
            if (direction === 'first') {
                logsPage = 1;
            } else if (direction === 'last') {
                logsPage = totalPages;
            } else {
                logsPage = Math.max(1, Math.min(logsPage + direction, totalPages));
            }
            
            updateLogsTable();
        }
        
        function changeFilesPage(direction) {
            const totalPages = Math.ceil(filteredFiles.length / itemsPerPage);
            
            if (direction === 'first') {
                filesPage = 1;
            } else if (direction === 'last') {
                filesPage = totalPages;
            } else {
                filesPage = Math.max(1, Math.min(filesPage + direction, totalPages));
            }
            
            updateFilesTable();
        }
        
        function updateProcessChart(typeSummaryData) {
            const ctx = document.getElementById('processChart').getContext('2d');
            
            // 從 type_process_summary 計算每個程序的總數
            const processCount = {};
            typeSummaryData.forEach(item => {
                if (!processCount[item.process]) {
                    processCount[item.process] = 0;
                }
                processCount[item.process] += item.count;
            });
            
            // 排序並取前10
            const sortedProcesses = Object.entries(processCount)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10);
            
            const labels = sortedProcesses.map(([process, _]) => process);
            const totals = sortedProcesses.map(([_, count]) => count);
            
            // 從 typeSummaryData 獲取每個程序的 ANR 和 Tombstone 數據
            const anrData = [];
            const tombstoneData = [];
            
            labels.forEach(process => {
                let anrCount = 0;
                let tombstoneCount = 0;
                
                typeSummaryData.forEach(item => {
                    if (item.process === process) {
                        if (item.type === 'ANR') {
                            anrCount = item.count;
                        } else if (item.type === 'Tombstone') {
                            tombstoneCount = item.count;
                        }
                    }
                });
                
                anrData.push(anrCount);
                tombstoneData.push(tombstoneCount);
            });
            
            if (charts.process) charts.process.destroy();
            
            charts.process = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'ANR',
                            data: anrData,
                            backgroundColor: 'rgba(102, 126, 234, 0.8)',
                            borderColor: 'rgba(102, 126, 234, 1)',
                            borderWidth: 1
                        },
                        {
                            label: 'Tombstone',
                            data: tombstoneData,
                            backgroundColor: 'rgba(234, 102, 102, 0.8)',
                            borderColor: 'rgba(234, 102, 102, 1)',
                            borderWidth: 1
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        },
                        tooltip: {
                            callbacks: {
                                afterLabel: function(context) {
                                    const total = anrData[context.dataIndex] + tombstoneData[context.dataIndex];
                                    return `總計: ${total}`;
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            stacked: false,
                            ticks: {
                                stepSize: 1
                            }
                        },
                        x: {
                            ticks: {
                                autoSkip: false,
                                maxRotation: 45,
                                minRotation: 45
                            }
                        }
                    }
                }
            });
        }
        
        function updateTypeChart(typeData) {
            const ctx = document.getElementById('typeChart').getContext('2d');
            
            const labels = Object.keys(typeData);
            const values = Object.values(typeData);
            
            if (charts.type) charts.type.destroy();
            
            charts.type = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: values,
                        backgroundColor: [
                            'rgba(102, 126, 234, 0.8)',
                            'rgba(234, 102, 102, 0.8)'
                        ],
                        borderColor: [
                            'rgba(102, 126, 234, 1)',
                            'rgba(234, 102, 102, 1)'
                        ],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom'
                        }
                    }
                }
            });
        }
        
        function updateDailyChart(dailyData, dailyByType) {
            const ctx = document.getElementById('dailyChart').getContext('2d');
            
            const labels = Object.keys(dailyData);
            const anrData = labels.map(date => dailyByType.ANR[date] || 0);
            const tombstoneData = labels.map(date => dailyByType.Tombstone[date] || 0);
            
            if (charts.daily) charts.daily.destroy();
            
            charts.daily = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'ANR',
                            data: anrData,
                            borderColor: 'rgba(102, 126, 234, 1)',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            tension: 0.3,
                            fill: true
                        },
                        {
                            label: 'Tombstone',
                            data: tombstoneData,
                            borderColor: 'rgba(234, 102, 102, 1)',
                            backgroundColor: 'rgba(234, 102, 102, 0.1)',
                            tension: 0.3,
                            fill: true
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                stepSize: 1
                            }
                        }
                    }
                }
            });
        }
        
        function updateHourlyChart(hourlyData, hourlyByType) {
            const ctx = document.getElementById('hourlyChart').getContext('2d');
            
            // Create all 24 hours
            const allHours = [];
            for (let i = 0; i < 24; i++) {
                allHours.push(`${i.toString().padStart(2, '0')}:00`);
            }
            
            const anrData = allHours.map(hour => hourlyByType.ANR[hour] || 0);
            const tombstoneData = allHours.map(hour => hourlyByType.Tombstone[hour] || 0);
            
            if (charts.hourly) charts.hourly.destroy();
            
            charts.hourly = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: allHours,
                    datasets: [
                        {
                            label: 'ANR',
                            data: anrData,
                            backgroundColor: 'rgba(102, 126, 234, 0.8)',
                            borderColor: 'rgba(102, 126, 234, 1)',
                            borderWidth: 1
                        },
                        {
                            label: 'Tombstone',
                            data: tombstoneData,
                            backgroundColor: 'rgba(234, 102, 102, 0.8)',
                            borderColor: 'rgba(234, 102, 102, 1)',
                            borderWidth: 1
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            stacked: true,  // 使用堆疊
                            ticks: {
                                stepSize: 1
                            }
                        },
                        x: {
                            stacked: true   // 使用堆疊
                        }
                    }
                }
            });
        }
        
        async function exportResults(format) {
            if (!currentAnalysisId) {
                showMessage('請先執行分析', 'error');
                return;
            }
            
            if (format === 'html') {
                // 獲取當前服務器資訊並通過 URL 參數傳遞
                try {
                    const serverResponse = await fetch('/server-info');
                    const serverInfo = await serverResponse.json();
                    
                    // 使用 URL 參數傳遞 base_url
                    const encodedBaseUrl = encodeURIComponent(serverInfo.base_url);
                    window.location.href = `/export/${format}/${currentAnalysisId}?base_url=${encodedBaseUrl}`;
                } catch (error) {
                    // 如果無法獲取服務器資訊，使用原有方式
                    window.location.href = `/export/${format}/${currentAnalysisId}`;
                }
            } else {
                window.location.href = `/export/${format}/${currentAnalysisId}`;
            }
        }
        
        function showMessage(message, type) {
            const messageDiv = document.getElementById('message');
            messageDiv.className = type;
            messageDiv.innerHTML = message;
        }
        
        function clearMessage() {
            document.getElementById('message').innerHTML = '';
            document.getElementById('message').className = '';
        }
        
        function highlightText(text, searchTerm, useRegex = false) {
            if (!searchTerm || !text) return escapeHtml(text);
            
            const escapedText = escapeHtml(text);
            
            try {
                let regex;
                if (useRegex) {
                    regex = new RegExp(`(${searchTerm})`, 'gi');
                } else {
                    const escapedSearchTerm = escapeHtml(searchTerm).replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
                    regex = new RegExp(`(${escapedSearchTerm})`, 'gi');
                }
                
                return escapedText.replace(regex, '<span class="table-highlight">$1</span>');
            } catch (error) {
                // If regex is invalid, return text without highlighting
                return escapedText;
            }
        }

        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    """Main page"""
    return HTML_TEMPLATE

@app.route('/analyze', methods=['POST'])
def analyze():
    """Analyze logs endpoint"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data received'}), 400
        
        path = data.get('path', '')
        
        if not path:
            return jsonify({'error': 'Path is required'}), 400
        
        # Handle Windows UNC paths and regular paths
        original_path = path
        
        # Convert Windows backslashes to forward slashes for consistency
        # But preserve UNC paths starting with \\
        if path.startswith('\\\\'):
            # This is a UNC path, keep it as is
            print(f"UNC path detected: {path}")
        else:
            # Expand user path and convert to absolute
            path = os.path.expanduser(path)
            path = os.path.abspath(path)
        
        print(f"Analyzing path: {path}")
        print(f"Original input: {original_path}")
        
        if not os.path.exists(path):
            return jsonify({
                'error': f'Path does not exist: {path}',
                'original_path': original_path,
                'resolved_path': path,
                'hint': 'For network paths, ensure the share is accessible and mounted'
            }), 400
        
        if not os.path.isdir(path):
            return jsonify({'error': f'Path is not a directory: {path}'}), 400
        
        # 生成包含時間戳和 UUID 的唯一 ID
        analysis_id = datetime.now().strftime('%Y%m%d%H%M%S') + '_' + str(uuid.uuid4())[:8]
        
        # 執行分析 - 這裡是關鍵，確保 results 被定義
        results = analyzer.analyze_logs(path)
        
        # 使用新的 cache
        analysis_cache.set(analysis_id, results)
        
        # Return results
        return jsonify({
            'analysis_id': analysis_id,
            'total_files': results['total_files'],
            'files_with_cmdline': results['files_with_cmdline'],
            'anr_folders': results['anr_folders'],
            'tombstone_folders': results['tombstone_folders'],
            'statistics': results['statistics'],
            'file_statistics': results['file_statistics'],
            'logs': results['logs'],
            'analysis_time': results['analysis_time'],
            'used_grep': results['used_grep'],
            'zip_files_extracted': results.get('zip_files_extracted', 0)
        })
        
    except Exception as e:
        print(f"Error in analyze endpoint: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/search-in-file', methods=['POST'])
def search_in_file():
    """優化的檔案搜尋端點"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data received'}), 400
        
        file_path = data.get('file_path', '')
        search_text = data.get('search_text', '')
        use_regex = data.get('use_regex', False)
        max_results = data.get('max_results', 500)  # 客戶端可以指定最大結果數
        
        if not file_path or not search_text:
            return jsonify({'error': 'file_path and search_text are required'}), 400
        
        # Security check
        if '..' in file_path:
            return jsonify({'error': 'Invalid file path'}), 403
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        # 嘗試使用優化的 grep 搜尋
        grep_results = analyzer.search_in_file_with_grep_optimized(
            file_path, search_text, use_regex, max_results
        )
        
        if grep_results is not None:
            # Grep 成功
            return jsonify({
                'success': True,
                'used_grep': True,
                'results': grep_results,
                'truncated': len(grep_results) >= max_results
            })
        else:
            # Grep 不可用或失敗
            return jsonify({
                'success': False,
                'used_grep': False,
                'message': 'Grep not available, use frontend search'
            })
            
    except Exception as e:
        print(f"Error in search_in_file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/export/<format>/<analysis_id>')
def export(format, analysis_id):
    # 使用 LimitedCache 的 get 方法
    data = analysis_cache.get(analysis_id)

    if data is None:
        return jsonify({'error': 'Analysis not found or expired'}), 404
    
    if format == 'json':
        # Create JSON file
        output = io.BytesIO()
        output.write(json.dumps(data, indent=2).encode('utf-8'))
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/json',
            as_attachment=True,
            download_name=f'cmdline_analysis_{analysis_id}.json'
        )
    
    elif format == 'csv':
        # Create CSV file
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write summary
        writer.writerow(['Summary'])
        writer.writerow(['Total Files Scanned', data['total_files']])
        writer.writerow(['Files with Cmdline', data['files_with_cmdline']])
        writer.writerow(['Unique Processes', data['statistics'].get('total_unique_processes', 0)])
        writer.writerow(['ANR Folders', data['anr_folders']])
        writer.writerow(['Tombstone Folders', data['tombstone_folders']])
        writer.writerow(['Analysis Time (seconds)', data.get('analysis_time', 'N/A')])
        writer.writerow(['Used grep', 'Yes' if data.get('used_grep', False) else 'No'])
        writer.writerow(['ZIP Files Extracted', data.get('zip_files_extracted', 0)])
        writer.writerow([])
        
        # Write summary by type and process
        if 'type_process_summary' in data['statistics']:
            writer.writerow(['Summary by Type and Process'])
            writer.writerow(['Rank', 'Type', 'Process', 'Count'])
            for i, item in enumerate(data['statistics']['type_process_summary'], 1):
                writer.writerow([i, item['type'], item['process'], item['count']])
            writer.writerow([])
        
        # Write file statistics
        if 'file_statistics' in data:
            writer.writerow(['File Statistics'])
            writer.writerow(['Type', 'Filename', 'Folder Path', 'Cmdline Count', 'Processes', 'Timestamp'])
            for file_stat in data['file_statistics']:
                writer.writerow([
                    file_stat['type'],
                    file_stat['filename'],
                    file_stat.get('folder_path', '-'),
                    file_stat['count'],
                    ', '.join(file_stat['processes']),
                    file_stat.get('timestamp', '-')
                ])
            writer.writerow([])
        
        # Write unique processes list
        if 'unique_processes' in data['statistics']:
            writer.writerow(['Unique Process Names'])
            for proc in data['statistics']['unique_processes']:
                writer.writerow([proc])
            writer.writerow([])
        
        # Write process statistics
        writer.writerow(['Process Statistics'])
        writer.writerow(['Process', 'Count'])
        for process, count in data['statistics']['by_process'].items():
            writer.writerow([process, count])
        writer.writerow([])
        
                        # Write log data
        writer.writerow(['Detailed Logs'])
        writer.writerow(['Row Number', 'Type', 'Process', 'Command Line', 'Line Number', 'Folder Path', 'Timestamp', 'File'])
        for i, log in enumerate(data['logs'], 1):
            writer.writerow([
                i,
                log['type'],
                log['process'] or '',
                log['cmdline'] or '',
                log.get('line_number', '-'),
                log.get('folder_path', '-'),
                log['timestamp'] or '',
                log['filename']
            ])
        
        # Convert to bytes
        output_bytes = io.BytesIO()
        output_bytes.write(output.getvalue().encode('utf-8'))
        output_bytes.seek(0)
        
        return send_file(
            output_bytes,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'cmdline_analysis_{analysis_id}.csv'
        )
    
    elif format == 'html':
        # 從 URL 參數獲取 base_url
        base_url = request.args.get('base_url', '')
        if not base_url:
            # 如果沒有提供，嘗試自動獲取
            base_url = f"{request.scheme}://{request.host}"
        
        # 創建 HTML 報告
        html_report = HTML_TEMPLATE
        
        # 在注入的腳本中修改檔案連結
        static_script = f'''
<script>
    // 靜態頁面標記
    window.isStaticExport = true;
    window.exportBaseUrl = "{base_url}";
    
    // 在頁面載入後設定靜態頁面提示
    window.addEventListener('DOMContentLoaded', function() {{
        setTimeout(function() {{
            // 移除控制面板
            const controlPanel = document.querySelector('.control-panel');
            if (controlPanel) {{
                controlPanel.style.display = 'none';
            }}
            
            // 顯示導覽列按鈕而不是導覽列本身
            const navToggleBtn = document.getElementById('navToggleBtn');
            if (navToggleBtn) {{
                navToggleBtn.classList.add('show');
            }}
            
            // 移除匯出相關按鈕
            const exportHtmlBtn = document.getElementById('exportHtmlBtn');
            if (exportHtmlBtn) {{
                exportHtmlBtn.style.display = 'none';
            }}
        }}, 500);
    }});
    
    // 覆寫更新表格函數以使用完整連結
    const originalUpdateFilesTable = window.updateFilesTable;
    const originalUpdateLogsTable = window.updateLogsTable;
    
    window.updateFilesTable = function() {{
        originalUpdateFilesTable.call(this);
        // 替換所有檔案連結為完整連結
        document.querySelectorAll('.file-link').forEach(link => {{
            const href = link.getAttribute('href');
            if (href && href.startsWith('/')) {{
                link.setAttribute('href', window.exportBaseUrl + href);
                link.setAttribute('target', '_blank');
            }}
        }});
    }};
    
    window.updateLogsTable = function() {{
        originalUpdateLogsTable.call(this);
        // 替換所有檔案連結為完整連結
        document.querySelectorAll('.file-link').forEach(link => {{
            const href = link.getAttribute('href');
            if (href && href.startsWith('/')) {{
                link.setAttribute('href', window.exportBaseUrl + href);
                link.setAttribute('target', '_blank');
            }}
        }});
    }};
</script>
'''
        
        # Inject the data directly into the HTML
        script_injection = static_script + f'''
<script>

    // 設定 base URL
    window.exportBaseUrl = "{base_url}";
    
    // 修改 updateFilesTable 和 updateLogsTable 函數
    window.originalUpdateFilesTable = updateFilesTable;
    window.originalUpdateLogsTable = updateLogsTable;
    
    updateFilesTable = function() {{
        window.originalUpdateFilesTable();
        // 替換所有檔案連結
        document.querySelectorAll('.file-link').forEach(link => {{
            if (link.href && !link.href.startsWith('http')) {{
                link.href = window.exportBaseUrl + link.getAttribute('href');
            }}
        }});
    }};
    
    updateLogsTable = function() {{
        window.originalUpdateLogsTable();
        // 替換所有檔案連結
        document.querySelectorAll('.file-link').forEach(link => {{
            if (link.href && !link.href.startsWith('http')) {{
                link.href = window.exportBaseUrl + link.getAttribute('href');
            }}
        }});
    }};
    
    // Injected analysis data
    window.injectedData = {json.dumps({
        'analysis_id': data.get('analysis_id', analysis_id),
        'total_files': data['total_files'],
        'files_with_cmdline': data['files_with_cmdline'],
        'anr_folders': data['anr_folders'],
        'tombstone_folders': data['tombstone_folders'],
        'statistics': data['statistics'],
        'file_statistics': data['file_statistics'],
        'logs': data['logs'],
        'analysis_time': data['analysis_time'],
        'used_grep': data['used_grep'],
        'zip_files_extracted': data.get('zip_files_extracted', 0)
    })};
    
    // Auto-load the data when page loads
    window.addEventListener('DOMContentLoaded', function() {{
        currentAnalysisId = window.injectedData.analysis_id;
        allLogs = window.injectedData.logs.sort((a, b) => {{
            if (!a.timestamp && !b.timestamp) return 0;
            if (!a.timestamp) return 1;
            if (!b.timestamp) return -1;
            return a.timestamp.localeCompare(b.timestamp);
        }});
        allSummary = window.injectedData.statistics.type_process_summary || [];
        allFileStats = window.injectedData.file_statistics || [];
        
        // Reset filters and pagination
        resetFiltersAndPagination();
        
        // Update UI
        updateResults(window.injectedData);
        
        // Hide controls
        document.querySelector('.control-panel').style.display = 'none';
        document.getElementById('exportHtmlBtn').style.display = 'none';
        
        // Show navigation bar
        document.getElementById('navBar').classList.add('show');
        
        // Show analysis info
        let message = `分析完成！共掃描 ${{window.injectedData.total_files}} 個檔案，找到 ${{window.injectedData.files_with_cmdline}} 個包含 Cmdline 的檔案`;
        message += `<br>分析耗時: ${{window.injectedData.analysis_time}} 秒`;
        if (window.injectedData.used_grep) {{
            message += '<span class="grep-badge">使用 grep 加速</span>';
        }} else {{
            message += '<span class="grep-badge no-grep-badge">未使用 grep</span>';
        }}
        if (window.injectedData.zip_files_extracted > 0) {{
            message += `<br>已解壓縮 ${{window.injectedData.zip_files_extracted}} 個 ZIP 檔案`;
        }}
        message += `<br><br>報告生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`;
        
        const infoDiv = document.createElement('div');
        infoDiv.className = 'success';
        infoDiv.innerHTML = message;
        document.querySelector('.header').appendChild(infoDiv);
    }});
</script>
'''
        
        # Insert the script before closing body tag
        html_report = html_report.replace('</body>', script_injection + '</body>')
        
        # Convert to bytes
        output_bytes = io.BytesIO()
        output_bytes.write(html_report.encode('utf-8'))
        output_bytes.seek(0)
        
        return send_file(
            output_bytes,
            mimetype='text/html',
            as_attachment=True,
            download_name=f'cmdline_analysis_{analysis_id}_full.html'
        )
    
    else:
        return jsonify({'error': 'Invalid format'}), 400

@app.route('/server-info')
def server_info():
    """Get current server information"""
    # 獲取請求的主機資訊
    host = request.host  # 這會包含 IP:port
    protocol = 'https' if request.is_secure else 'http'
    base_url = f"{protocol}://{host}"
    
    return jsonify({
        'base_url': base_url,
        'host': request.host_url.rstrip('/')
    })
    
@app.route('/suggest-path', methods=['POST'])
def suggest_path():
    """Suggest paths based on user input"""
    try:
        data = request.json
        if not data:
            return jsonify({'suggestions': []})
        
        current_path = data.get('path', '')
        
        # Handle empty path - suggest root directories and common paths
        if not current_path:
            suggestions = []
            # Windows drives
            if os.name == 'nt':
                import string
                for drive in string.ascii_uppercase:
                    drive_path = f"{drive}:\\"
                    if os.path.exists(drive_path):
                        suggestions.append(drive_path)
            # Unix/Linux common paths
            else:
                suggestions.append('/')
                suggestions.append('~/')
                if os.path.exists('/home'):
                    suggestions.append('/home/')
                if os.path.exists('/data'):
                    suggestions.append('/data/')
                if os.path.exists('/sdcard'):
                    suggestions.append('/sdcard/')
                if os.path.exists('/storage'):
                    suggestions.append('/storage/')
            
            # Add current directory
            suggestions.append('./')
            suggestions.append('../')
            
            return jsonify({'suggestions': suggestions[:10]})
        
        # Expand user path
        if current_path.startswith('~'):
            current_path = os.path.expanduser(current_path)
        
        # Determine the directory to list and the prefix to match
        if current_path.endswith(os.sep) or current_path.endswith('/'):
            # If path ends with separator, list contents of this directory
            list_dir = current_path
            prefix = ''
        else:
            # Otherwise, list contents of parent directory
            list_dir = os.path.dirname(current_path)
            prefix = os.path.basename(current_path).lower()
        
        suggestions = []
        
        try:
            # Special handling for Windows network paths
            if current_path.startswith('\\\\'):
                # This is a UNC path
                if current_path.count('\\') == 2:
                    # Just \\server, can't list network computers
                    return jsonify({'suggestions': []})
                
            # Check if directory exists
            if os.path.exists(list_dir) and os.path.isdir(list_dir):
                items = os.listdir(list_dir)
                
                for item in items:
                    # Skip hidden files unless user is specifically looking for them
                    if item.startswith('.') and not prefix.startswith('.'):
                        continue
                    
                    # Check if item matches prefix
                    if item.lower().startswith(prefix):
                        full_path = os.path.join(list_dir, item)
                        
                        # Only suggest directories
                        if os.path.isdir(full_path):
                            # Add path separator for directories
                            if not full_path.endswith(os.sep):
                                full_path += os.sep
                            
                            # Check for anr/tombstones folders
                            item_lower = item.lower()
                            if item_lower in ['anr', 'tombstone', 'tombstones']:
                                # Add a marker to indicate this is a target folder
                                suggestions.append(f"{full_path} ⭐")
                            else:
                                # Check if this directory contains anr/tombstones subdirectories
                                try:
                                    subdirs = os.listdir(full_path.rstrip(os.sep))
                                    has_target = any(sub.lower() in ['anr', 'tombstone', 'tombstones'] 
                                                   for sub in subdirs 
                                                   if os.path.isdir(os.path.join(full_path.rstrip(os.sep), sub)))
                                    if has_target:
                                        suggestions.append(f"{full_path} 📁")
                                    else:
                                        suggestions.append(full_path)
                                except:
                                    suggestions.append(full_path)
                
                # Sort suggestions
                suggestions.sort()
                
                # Limit to 20 suggestions
                suggestions = suggestions[:20]
                
        except PermissionError:
            # Can't read directory
            pass
        except Exception as e:
            print(f"Error listing directory: {e}")
        
        return jsonify({'suggestions': suggestions})
        
    except Exception as e:
        print(f"Error in suggest_path: {e}")
        return jsonify({'suggestions': []})

# 添加新的 AI 分析端點
@app.route('/analyze-with-ai', methods=['POST'])
def analyze_with_ai():
    """使用 Claude API 分析日誌內容"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data received'}), 400
        
        file_path = data.get('file_path', '')
        content = data.get('content', '')
        file_type = data.get('file_type', 'log')  # ANR 或 Tombstone 或 custom_with_context
        selected_model = data.get('model', 'claude-3-5-sonnet-20241022')
        is_custom_question = data.get('is_custom_question', False)
        original_question = data.get('original_question', '')  # 原始問題（不含檔案內容）
        
        if not content:
            return jsonify({'error': 'No content provided'}), 400
        
        # 檢查 API key
        if not CLAUDE_API_KEY:
            return jsonify({'error': 'Claude API key not configured'}), 500
        
        # 限制內容長度（Claude 有 token 限制）
        max_content_length = 50000  # 約 50KB
        truncated = False
        
        if len(content) > max_content_length:
            truncated = True
            # 如果是帶檔案上下文的自訂問題，智能截取
            if file_type == 'custom_with_context':
                # 分離檔案內容和問題
                file_content_match = re.search(r'=== 當前檔案內容 ===\n(.*?)\n=== 檔案內容結束 ===', content, re.DOTALL)
                if file_content_match:
                    file_content = file_content_match.group(1)
                    # 截取檔案內容的關鍵部分
                    lines = file_content.split('\n')
                    
                    # 優先保留前面的系統信息和堆棧追蹤
                    important_sections = []
                    current_section = []
                    in_stack_trace = False
                    
                    for line in lines:
                        if any(keyword in line for keyword in ['Cmd line:', 'Cmdline:', 'Build:', 'ABI:', 'pid:', 'tid:', 'name:', 'signal']):
                            important_sections.append(line)
                        elif 'backtrace:' in line or 'stack:' in line.lower():
                            in_stack_trace = True
                            current_section = [line]
                        elif in_stack_trace and (line.strip() == '' or not line.strip().startswith('#')):
                            if current_section:
                                important_sections.extend(current_section[:20])  # 最多保留20行堆棧
                            in_stack_trace = False
                            current_section = []
                        elif in_stack_trace:
                            current_section.append(line)
                    
                    # 組合重要部分
                    truncated_file_content = '\n'.join(important_sections[:500])  # 最多500行
                    
                    # 重新構建內容
                    content = f"{data.get('file_path', '')}\n=== 當前檔案內容（已截取關鍵部分）===\n{truncated_file_content}\n=== 檔案內容結束 ===\n\n使用者問題：{original_question or '請分析這個檔案'}"
            else:
                # 其他類型的截取邏輯
                lines = content.split('\n')
                important_sections = []
                current_section = []
                in_stack_trace = False
                
                for line in lines:
                    if any(keyword in line for keyword in ['Cmd line:', 'Cmdline:', 'Build:', 'ABI:', 'pid:', 'tid:', 'name:', 'signal']):
                        important_sections.append(line)
                    elif 'backtrace:' in line or 'stack:' in line.lower():
                        in_stack_trace = True
                        current_section = [line]
                    elif in_stack_trace and (line.strip() == '' or not line.strip().startswith('#')):
                        if current_section:
                            important_sections.extend(current_section[:20])
                        in_stack_trace = False
                        current_section = []
                    elif in_stack_trace:
                        current_section.append(line)
                
                truncated_content = '\n'.join(important_sections[:500])
                content = f"[日誌已截斷，只顯示關鍵部分]\n\n{truncated_content}"
        
        # 準備 Claude API 請求
        try:
            client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            
            # 根據文件類型設計不同的提示詞
            if file_type == 'custom_with_context':
                system_prompt = """你是一位 Android 系統專家，擅長分析 Android 日誌和解決系統問題。
用戶提供了一個檔案的完整內容，並基於這個檔案提出了問題。

分析時請遵循以下原則：
1. 仔細閱讀提供的檔案內容
2. 根據檔案內容準確回答用戶的問題
3. 提供具體、可操作的建議
4. 如果檔案中沒有足夠的信息來回答問題，請明確指出
5. 引用檔案中的具體內容來支持你的分析

請用繁體中文回答，並使用結構化的格式。"""
            elif is_custom_question:
                system_prompt = """你是一位 Android 系統專家，擅長分析 Android 日誌和解決系統問題。
請根據用戶的問題提供詳細、準確的分析。

分析時請遵循以下原則：
1. 提供具體、可操作的建議
2. 解釋技術概念時要清楚易懂
3. 如果需要更多信息才能準確回答，請明確指出
4. 使用結構化的格式組織回答

請用繁體中文回答。"""
            elif file_type == 'ANR':
                system_prompt = """你是一位 Android 系統專家，擅長分析 ANR (Application Not Responding) 日誌。
請分析這個 ANR 日誌並提供：
1. 問題摘要：簡潔說明發生了什麼
2. 根本原因：識別導致 ANR 的主要原因
3. 影響的進程：哪個應用或服務受到影響
4. 關鍵堆棧信息：最重要的堆棧追蹤部分
5. 建議解決方案：如何修復這個問題

請用繁體中文回答，並使用結構化的格式。"""
            else:
                system_prompt = """你是一位 Android 系統專家，擅長分析 Tombstone 崩潰日誌。
請分析這個 Tombstone 日誌並提供：
1. 崩潰摘要：簡潔說明發生了什麼類型的崩潰
2. 崩潰原因：信號類型和觸發原因
3. 影響的進程：哪個應用或服務崩潰了
4. 關鍵堆棧信息：定位問題的關鍵堆棧幀
5. 可能的修復方向：如何避免這類崩潰

請用繁體中文回答，並使用結構化的格式。"""
            
            # 構建消息內容
            if is_custom_question and file_type != 'custom_with_context':
                user_message = content
            else:
                user_message = content
            
            # 調用 Claude API
            message_params = {
                "model": selected_model,
                "max_tokens": 4000,  # 增加到 4000 以支援更長的回應
                "temperature": 0,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": user_message
                    }
                ]
            }
            
            message = client.messages.create(**message_params)
            
            # 提取回應文本
            response_text = message.content[0].text if message.content else "無法獲取分析結果"
            
            return jsonify({
                'success': True,
                'analysis': response_text,
                'truncated': truncated,
                'model': selected_model,
                'thinking': None  # 如果 API 支援 thinking，可以在這裡返回
            })
            
        except anthropic.APIError as e:
            error_message = str(e)
            return jsonify({
                'error': f'Claude API 錯誤: {error_message}',
                'details': '請檢查 API key 是否有效',
                'available_models': [
                    'claude-3-5-sonnet-20241022',
                    'claude-3-5-haiku-20241022', 
                    'claude-3-opus-20240229',
                    'claude-3-haiku-20240307'
                ]
            }), 500
            
    except Exception as e:
        print(f"AI analysis error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'分析錯誤: {str(e)}'}), 500

@app.route('/view-file')
def view_file():
    """View file content endpoint with enhanced features and AI split view"""
    file_path = request.args.get('path')
    download = request.args.get('download', 'false').lower() == 'true'
    
    if not file_path:
        return "No file path provided", 400
    
    # Security check - prevent directory traversal
    if '..' in file_path:
        return "Invalid file path", 403
    
    # Check if file exists
    if not os.path.exists(file_path):
        return f"File not found: {file_path}", 404
    
    # Check if it's a file
    if not os.path.isfile(file_path):
        return "Not a file", 400
    
    try:
        # Read file content
        with open(file_path, 'r', errors='ignore') as f:
            content = f.read()
        
        if download:
            # Force download
            response = Response(content, mimetype='text/plain; charset=utf-8')
            response.headers['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
        else:
            # Escape content for JavaScript - CRITICAL for preventing syntax errors
            escaped_content = json.dumps(content)
            escaped_filename = json.dumps(os.path.basename(file_path))
            
            # 使用原始字符串 r""" 來避免轉義序列問題
            html_content = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>""" + html.escape(os.path.basename(file_path)) + r""" - Android Log Viewer</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            background-color: #1e1e1e;
            color: #d4d4d4;
            overflow: hidden;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        /* Split View Container */
        .main-container {
            display: flex;
            flex: 1;
            overflow: hidden;
            position: relative;
        }
        
        .left-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transition: flex 0.3s ease;
        }
        
        .right-panel {
            width: 0;
            background: #252526;
            border-left: 2px solid #007acc;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transition: width 0.3s ease;
        }
        
        .right-panel.active {
            width: 40%;
            min-width: 400px;
        }
        
        /* Resize Handle */
        .resize-handle {
            position: absolute;
            width: 5px;
            height: 100%;
            background: transparent;
            cursor: col-resize;
            z-index: 100;
            left: 60%;
            display: none;
        }
        
        .resize-handle.active {
            display: block;
        }
        
        .resize-handle:hover {
            background: #007acc;
        }
        
        /* AI Panel Header */
        .ai-panel-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        
        .ai-panel-header h2 {
            font-size: 18px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .close-ai-panel {
            background: none;
            border: none;
            color: white;
            font-size: 24px;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            transition: all 0.2s;
        }
        
        .close-ai-panel:hover {
            background: rgba(255, 255, 255, 0.2);
        }
        
        /* AI Panel Content */
        .ai-panel-content {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }
        
        /* Model Selection */
        .model-selection {
            background: #1e1e1e;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        .model-selection h3 {
            color: #e8e8e8;
            font-size: 16px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .model-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 15px;
        }
        
        .model-option {
            background: #2d2d30;
            border: 2px solid #3e3e42;
            border-radius: 6px;
            padding: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .model-option:hover {
            border-color: #007acc;
            background: #3e3e42;
        }
        
        .model-option.selected {
            border-color: #667eea;
            background: #3e3e42;
        }
        
        .model-option input[type="radio"] {
            display: none;
        }
        
        .model-name {
            font-weight: 600;
            color: #4ec9b0;
            font-size: 14px;
            margin-bottom: 4px;
        }
        
        .model-desc {
            font-size: 12px;
            color: #969696;
        }
        
        /* Quick Actions */
        .quick-actions {
            margin-bottom: 20px;
        }
        
        .analyze-current-btn {
            width: 100%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 15px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }
        
        .analyze-current-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }
        
        .analyze-current-btn.loading {
            opacity: 0.8;
            pointer-events: none;
        }
        
        /* Custom Question Section */
        .custom-question {
            background: #1e1e1e;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        .custom-question h3 {
            color: #e8e8e8;
            font-size: 16px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .question-input {
            width: 100%;
            background: #2d2d30;
            border: 2px solid #3e3e42;
            border-radius: 6px;
            padding: 12px;
            color: #d4d4d4;
            font-size: 14px;
            resize: vertical;
            min-height: 100px;
            font-family: inherit;
            margin-bottom: 10px;
        }
        
        .question-input:focus {
            outline: none;
            border-color: #007acc;
        }
        
        .ask-ai-btn {
            background: #0e639c;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
            float: right;
        }
        
        .ask-ai-btn:hover {
            background: #1177bb;
            transform: translateY(-1px);
        }
        
        .ask-ai-btn:disabled {
            background: #3c3c3c;
            cursor: not-allowed;
            transform: none;
        }
        
        /* AI Limitations Info */
        .ai-info-box {
            background: #2d2d30;
            border: 1px solid #3e3e42;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 20px;
        }
        
        .ai-info-box h4 {
            color: #4ec9b0;
            font-size: 14px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .ai-info-box ul {
            margin: 0;
            padding-left: 20px;
        }
        
        .ai-info-box li {
            color: #969696;
            font-size: 12px;
            margin-bottom: 5px;
        }
        
        /* AI Response Section */
        .ai-response {
            background: #1e1e1e;
            border-radius: 8px;
            padding: 20px;
            display: none;
        }
        
        .ai-response.active {
            display: block;
        }
        
        .ai-response-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .ai-response-title {
            color: #e8e8e8;
            font-size: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .ai-response-content {
            color: #d4d4d4;
            line-height: 1.8;
            font-size: 14px;
        }
        
        /* Loading Animation */
        .ai-loading {
            text-align: center;
            padding: 40px;
        }
        
        .ai-spinner {
            width: 40px;
            height: 40px;
            border: 3px solid #3c3c3c;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        /* Header */
        .header {
            background: linear-gradient(135deg, #2d2d30 0%, #3e3e42 100%);
            border-bottom: 2px solid #007acc;
            padding: 16px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        
        .header-left {
            display: flex;
            align-items: center;
            gap: 20px;
        }
        
        .file-info h1 {
            font-size: 18px;
            font-weight: 600;
            color: #e8e8e8;
            margin: 0;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .file-info h1::before {
            content: "📄";
            font-size: 24px;
        }
        
        .file-info p {
            font-size: 13px;
            color: #a0a0a0;
            margin: 6px 0 0 34px;
            font-family: 'Consolas', 'Monaco', monospace;
        }
        
        .header-buttons {
            display: flex;
            gap: 10px;
        }
        
        .btn {
            background: #0e639c;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .btn:hover {
            background: #1177bb;
            transform: translateY(-1px);
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        
        .btn-danger {
            background: #d73a49;
        }
        
        .btn-danger:hover {
            background: #cb2431;
        }
        
        .btn-success {
            background: #28a745;
        }
        
        .btn-success:hover {
            background: #218838;
        }
        
        /* AI 按鈕樣式 */
        .btn-ai {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            position: relative;
            overflow: hidden;
        }

        .btn-ai:hover {
            background: linear-gradient(135deg, #5a67d8 0%, #6b42a0 100%);
        }

        .btn-ai.active {
            background: linear-gradient(135deg, #5a67d8 0%, #6b42a0 100%);
        }
        
        .btn:disabled {
            background: #3c3c3c;
            color: #666;
            cursor: not-allowed;
            transform: none;
        }
        
        .btn:active {
            transform: translateY(0);
            box-shadow: 0 1px 2px rgba(0,0,0,0.2);
        }
        
        a.btn {
            text-decoration: none;
        }
        
        /* Toolbar */
        .toolbar {
            background: #252526;
            border-bottom: 1px solid #3e3e42;
            padding: 10px 20px;
            display: flex;
            align-items: center;
            gap: 20px;
            flex-shrink: 0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }
        
        .search-container {
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
            max-width: 500px;
        }
        
        .search-box {
            flex: 1;
            background: #3c3c3c;
            border: 1px solid #3e3e42;
            border-radius: 4px;
            padding: 6px 12px;
            color: #cccccc;
            font-size: 13px;
            font-family: inherit;
            transition: all 0.2s;
        }
        
        .search-box:focus {
            outline: none;
            border-color: #007acc;
            background: #464647;
            box-shadow: 0 0 0 1px #007acc inset;
        }
        
        .regex-toggle {
            display: flex;
            align-items: center;
            gap: 5px;
            color: #cccccc;
            font-size: 12px;
            cursor: pointer;
            user-select: none;
        }
        
        .regex-toggle input {
            cursor: pointer;
        }
        
        .search-info {
            color: #4ec9b0;
            font-size: 13px;
            font-weight: 500;
            min-width: 150px;
        }
        
        .grep-indicator {
            color: #ffd700;
            font-size: 12px;
            display: none;
            margin-left: 10px;
        }
        
        .grep-indicator.active {
            display: inline;
        }
        
        .bookmark-info {
            color: #969696;
            font-size: 12px;
            margin-left: auto;
        }
        
        /* Keywords */
        .keywords-bar {
            background: #252526;
            border-bottom: 1px solid #3e3e42;
            padding: 8px 20px;
            display: none;
            flex-shrink: 0;
        }
        
        .keywords-bar.active {
            display: block;
        }
        
        .keyword-list {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            align-items: center;
        }
        
        .keyword-tag {
            padding: 4px 10px;
            border-radius: 3px;
            font-size: 12px;
            cursor: pointer;
            position: relative;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            transition: opacity 0.2s;
        }
        
        .keyword-tag:hover {
            opacity: 0.8;
        }
        
        .keyword-tag .remove {
            font-size: 16px;
            line-height: 1;
            opacity: 0.7;
        }
        
        .keyword-tag .remove:hover {
            opacity: 1;
        }
        
        /* Content area */
        .content-wrapper {
            flex: 1;
            display: flex;
            overflow: hidden;
            background: #1e1e1e;
        }
        
        .line-numbers {
            background: #1e1e1e;
            color: #858585;
            padding: 10px 0;
            text-align: right;
            user-select: none;
            font-size: 13px;
            line-height: 20px;
            border-right: 1px solid #2d2d30;
            overflow: hidden;
            flex-shrink: 0;
        }
        
        .line-number {
            padding: 0 15px;
            cursor: pointer;
            position: relative;
        }
        
        .line-number:hover {
            color: #d4d4d4;
            background: #2d2d30;
        }

        /* 已標記的行號懸停時顯示不同圖標 */
        .line-number.bookmarked:hover::after {
            content: "❌";
            opacity: 0.7;
        }

        .line-number:hover::after {
            content: "📌";
            position: absolute;
            right: 2px;
            font-size: 10px;
            opacity: 0.5;
        }
        
        .line-number.bookmarked::before {
            content: "●";
            position: absolute;
            left: 5px;
            color: #4ec9b0;
        }
        
        .line-number.current-line {
            background: #004c8c;
            color: white;
        }
        
        .content-area {
            flex: 1;
            overflow: auto;
            position: relative;
        }
        
        #content {
            white-space: pre;
            font-size: 13px;
            line-height: 20px;
            padding: 10px 20px;
            tab-size: 4;
            min-width: max-content;
        }
        
        /* Highlights */
        .highlight-1 { background-color: rgba(255, 235, 59, 0.5); color: #000; }
        .highlight-2 { background-color: rgba(76, 175, 80, 0.5); color: #fff; }
        .highlight-3 { background-color: rgba(33, 150, 243, 0.5); color: #fff; }
        .highlight-4 { background-color: rgba(255, 152, 0, 0.5); color: #fff; }
        .highlight-5 { background-color: rgba(233, 30, 99, 0.5); color: #fff; }
        
        .search-highlight {
            background-color: #515c6a;
            color: inherit;
            outline: 1px solid #007acc;
            transition: all 0.2s;
        }
        
        .search-highlight.current {
            background-color: #ff6b00;
            color: white;
            outline: 2px solid #ff6b00;
            animation: pulse 0.5s ease-in-out;
        }
        
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.05); }
            100% { transform: scale(1); }
        }
        
        /* Context menu */
        .context-menu {
            position: fixed;
            background: #252526;
            border: 1px solid #454545;
            border-radius: 4px;
            padding: 4px 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
            display: none;
            z-index: 1000;
            min-width: 180px;
        }
        
        .context-menu-item {
            padding: 6px 20px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            color: #cccccc;
            font-size: 13px;
        }
        
        .context-menu-item:hover {
            background-color: #094771;
            color: white;
        }
        
        .color-box {
            width: 16px;
            height: 16px;
            border-radius: 2px;
            border: 1px solid #454545;
        }
        
        .separator {
            border-top: 1px solid #454545;
            margin: 4px 0;
        }
        
        /* AI 分析結果相關樣式 */
        .ai-analysis-content {
            color: #d4d4d4;
            line-height: 1.8;
            font-size: 14px;
        }

        .ai-analysis-content h3 {
            color: #4ec9b0;
            margin: 20px 0 10px 0;
            font-size: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .ai-analysis-content h3:first-child {
            margin-top: 0;
        }

        .ai-analysis-content p {
            margin: 10px 0;
        }

        .ai-analysis-content code {
            background: #1e1e1e;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 13px;
            color: #ce9178;
        }

        .ai-analysis-content pre {
            background: #1e1e1e;
            padding: 15px;
            border-radius: 6px;
            overflow-x: auto;
            margin: 10px 0;
            border-left: 3px solid #667eea;
        }

        .ai-analysis-content pre code {
            background: none;
            padding: 0;
            color: #d4d4d4;
        }

        .ai-analysis-content ul, .ai-analysis-content ol {
            margin: 10px 0;
            padding-left: 30px;
        }

        .ai-analysis-content li {
            margin: 5px 0;
        }

        .ai-error {
            background: #f44336;
            color: white;
            padding: 15px;
            border-radius: 6px;
            margin: 10px 0;
        }

        .ai-warning {
            background: #ff9800;
            color: white;
            padding: 15px;
            border-radius: 6px;
            margin: 10px 0;
        }
        
        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 14px;
            height: 14px;
        }
        
        ::-webkit-scrollbar-track {
            background: #1e1e1e;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #424242;
            border: 3px solid #1e1e1e;
            border-radius: 7px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #4f4f4f;
        }
        
        /* Status bar */
        .status-bar {
            background: linear-gradient(90deg, #007acc 0%, #005a9e 100%);
            color: white;
            padding: 6px 20px;
            font-size: 12px;
            display: flex;
            justify-content: space-between;
            flex-shrink: 0;
            box-shadow: 0 -2px 4px rgba(0,0,0,0.2);
        }
        
        .status-left {
            display: flex;
            gap: 20px;
        }
        
        .status-right {
            display: flex;
            gap: 20px;
        }
        
        /* Shortcuts help */
        .shortcuts-help {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: #252526;
            border: 1px solid #454545;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.5);
            display: none;
            z-index: 2000;
            max-width: 400px;
        }
        
        .shortcuts-help h3 {
            margin: 0 0 15px 0;
            color: #e8e8e8;
            font-size: 16px;
        }
        
        .shortcuts-help table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .shortcuts-help td {
            padding: 5px 10px;
            color: #cccccc;
            font-size: 13px;
        }
        
        .shortcuts-help td:first-child {
            text-align: right;
            color: #4ec9b0;
            font-weight: bold;
        }
        
        .shortcuts-help .close-btn {
            position: absolute;
            top: 10px;
            right: 10px;
            background: none;
            border: none;
            color: #969696;
            font-size: 20px;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .shortcuts-help .close-btn:hover {
            color: #e8e8e8;
        }
 
        #prevSearchBtn, #nextSearchBtn {
            transition: opacity 0.2s;
        }
        
        #prevSearchBtn:disabled, #nextSearchBtn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
    </style>
    <style>
        /* 對話樣式 */
        .conversation-item {
            margin-bottom: 20px;
            padding-bottom: 20px;
            border-bottom: 1px solid #3e3e42;
        }

        .conversation-item:last-child {
            border-bottom: none;
        }

        .conversation-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
            color: #969696;
            font-size: 12px;
        }

        .conversation-icon {
            font-size: 16px;
        }

        .conversation-type {
            font-weight: 600;
            color: #4ec9b0;
        }

        .conversation-time {
            margin-left: auto;
        }

        .user-question {
            background: #2d2d30;
            border-left: 3px solid #667eea;
            padding: 12px 15px;
            margin-bottom: 15px;
            border-radius: 6px;
            color: #d4d4d4;
        }

        .ai-response-item {
            display: flex;
            gap: 15px;
        }

        .ai-icon {
            font-size: 24px;
            flex-shrink: 0;
        }

        .ai-message {
            flex: 1;
        }

        .ai-footer {
            margin-top: 15px;
            padding-top: 10px;
            border-top: 1px solid #3e3e42;
            color: #666;
            font-size: 12px;
        }    
    </style>
    <style>
        .quick-question-btn {
            background: #2d2d30;
            border: 1px solid #3e3e42;
            color: #d4d4d4;
            padding: 10px 15px;
            border-radius: 6px;
            text-align: left;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .quick-question-btn:hover {
            background: #3e3e42;
            border-color: #007acc;
            transform: translateX(5px);
        }

        .quick-question-btn:active {
            transform: translateX(3px);
        }
        </style> 
        <style>
        .clear-conversation-btn {
            background: rgba(255, 255, 255, 0.1);
            border: none;
            color: white;
            font-size: 18px;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            transition: all 0.2s;
        }

        .clear-conversation-btn:hover {
            background: rgba(255, 255, 255, 0.2);
            transform: scale(1.1);
        }

        .ai-panel-header > div {
            display: flex;
            gap: 10px;
            align-items: center;
        }
    </style>  
    <style>
        /* 重新設計的 AI 面板佈局樣式 */

        /* 調整右側面板的 flex 佈局 */
        .right-panel {
            width: 0;
            background: #252526;
            border-left: 2px solid #007acc;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transition: width 0.3s ease;
            height: 100%;
        }

        .right-panel.active {
            width: 40%;
            min-width: 400px;
        }

        /* AI 面板主要內容區 */
        .ai-panel-main {
            flex: 1;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            min-height: 0; /* 重要：讓 flex 子元素可以收縮 */
        }

        .ai-panel-scrollable {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            padding-bottom: 10px;
        }

        /* 固定在底部的自訂問題區 */
        .ai-panel-footer {
            border-top: 2px solid #3e3e42;
            background: #1e1e1e;
            padding: 0;
            flex-shrink: 0;
        }

        .ai-panel-footer .custom-question {
            padding: 15px 20px;
            margin: 0;
            border-radius: 0;
            background: #1e1e1e;
        }

        .ai-panel-footer .custom-question h3 {
            margin-bottom: 10px;
            font-size: 14px;
        }

        .ai-panel-footer .question-input {
            min-height: 60px;
            max-height: 120px;
            resize: vertical;
        }

        /* 資訊按鈕樣式 */
        .info-btn {
            background: rgba(255, 255, 255, 0.1);
            border: none;
            color: white;
            font-size: 16px;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            transition: all 0.2s;
        }

        .info-btn:hover {
            background: rgba(255, 255, 255, 0.2);
            transform: scale(1.1);
        }

        /* AI 使用限制彈出視窗 */
        .ai-info-modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.6);
            z-index: 10000;
            display: flex;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(5px);
        }

        .ai-info-modal-content {
            background: #252526;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
            max-width: 500px;
            width: 90%;
            max-height: 80vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }

        .ai-info-modal-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .ai-info-modal-header h4 {
            margin: 0;
            font-size: 18px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .modal-close-btn {
            background: none;
            border: none;
            color: white;
            font-size: 24px;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            transition: all 0.2s;
        }

        .modal-close-btn:hover {
            background: rgba(255, 255, 255, 0.2);
        }

        .ai-info-modal-body {
            padding: 20px;
            overflow-y: auto;
        }

        .ai-info-modal-body ul {
            margin: 0;
            padding-left: 25px;
        }

        .ai-info-modal-body li {
            color: #d4d4d4;
            font-size: 14px;
            margin-bottom: 10px;
            line-height: 1.6;
        }

        /* 調整原有元素的間距 */
        .model-selection {
            background: #1e1e1e;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
        }

        .quick-actions {
            margin-bottom: 15px;
        }

        .quick-questions {
            background: #1e1e1e;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
        }

        .quick-questions h3 {
            font-size: 14px;
            margin-bottom: 12px;
        }

        .ai-response {
            background: #1e1e1e;
            border-radius: 8px;
            padding: 0;
            margin-bottom: 0;
            display: block;
        }

        .ai-response-content {
            max-height: none;
            overflow: visible;
        }

        /* 移除原本的 ai-info-box */
        .ai-info-box {
            display: none;
        }

        /* 調整 AI 面板內部的滾動條樣式 */
        .ai-panel-scrollable::-webkit-scrollbar {
            width: 10px;
        }

        .ai-panel-scrollable::-webkit-scrollbar-track {
            background: #1e1e1e;
        }

        .ai-panel-scrollable::-webkit-scrollbar-thumb {
            background: #424242;
            border-radius: 5px;
        }

        .ai-panel-scrollable::-webkit-scrollbar-thumb:hover {
            background: #4f4f4f;
        }

        /* 對話項目間距調整 */
        .conversation-item {
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 1px solid #3e3e42;
        }

        .conversation-item:last-child {
            border-bottom: none;
            margin-bottom: 0;
        }

        /* 確保自訂問題區在所有情況下都固定在底部 */
        @media (max-height: 600px) {
            .ai-panel-footer .question-input {
                min-height: 40px;
                max-height: 80px;
            }
            
            .ai-panel-scrollable {
                padding: 15px;
            }
        }    
    </style>
    <style>
        /* Claude 風格的 AI 面板樣式 */

        /* 調整右側面板佈局 */
        .right-panel {
            display: flex;
            flex-direction: column;
            height: 100%;
            position: relative;
        }

        /* AI 對話區 */
        .ai-chat-area {
            flex: 1;
            min-height: 200px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }

        /* 分析檔案按鈕區 */
        .analyze-file-section {
            padding: 15px 20px;
            border-bottom: 1px solid #3e3e42;
            flex-shrink: 0;
        }

        .analyze-current-btn {
            width: 100%;
            background: #0e639c;
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .analyze-current-btn:hover {
            background: #1177bb;
            transform: translateY(-1px);
            box-shadow: 0 2px 8px rgba(14, 99, 156, 0.3);
        }

        /* 可拖曳的分隔線 */
        .resize-divider {
            height: 8px;
            background: transparent;
            cursor: ns-resize;
            position: relative;
            flex-shrink: 0;
            user-select: none;
        }

        .resize-divider:hover .resize-handle-line,
        .resize-divider.dragging .resize-handle-line {
            background: #007acc;
        }

        .resize-handle-line {
            position: absolute;
            top: 50%;
            left: 20%;
            right: 20%;
            height: 2px;
            background: #3e3e42;
            transform: translateY(-50%);
            transition: background 0.2s;
        }

        /* 底部輸入區 */
        .ai-input-area {
            flex-shrink: 0;
            background: #1e1e1e;
            border-top: 2px solid #3e3e42;
            padding: 15px 20px;
            min-height: 120px;
            max-height: 50%;
        }

        .custom-question-wrapper {
            display: flex;
            flex-direction: column;
            height: 100%;
        }

        .question-input {
            flex: 1;
            background: #2d2d30;
            border: 2px solid #3e3e42;
            border-radius: 8px;
            padding: 12px;
            color: #d4d4d4;
            font-size: 14px;
            resize: none;
            font-family: inherit;
            margin-bottom: 10px;
            min-height: 60px;
        }

        .question-input:focus {
            outline: none;
            border-color: #007acc;
        }

        /* 輸入控制區 */
        .input-controls {
            display: flex;
            gap: 10px;
            align-items: center;
        }

        /* 模型選擇器（Claude 風格） */
        .model-selector {
            flex: 1;
        }

        .model-select {
            width: 100%;
            background: #2d2d30;
            border: 1px solid #3e3e42;
            border-radius: 6px;
            padding: 8px 12px;
            color: #d4d4d4;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .model-select:hover {
            border-color: #007acc;
        }

        .model-select:focus {
            outline: none;
            border-color: #007acc;
            box-shadow: 0 0 0 2px rgba(0, 122, 204, 0.2);
        }

        /* 發送按鈕 */
        .ask-ai-btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 8px 20px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .ask-ai-btn:hover {
            background: #5a67d8;
            transform: translateY(-1px);
        }

        .ask-ai-btn:disabled {
            background: #3c3c3c;
            cursor: not-allowed;
            transform: none;
        }

        /* 快速問題下拉選單 */
        .quick-questions-dropdown {
            position: relative;
        }

        .quick-questions-toggle {
            background: rgba(255, 255, 255, 0.1);
            border: none;
            color: white;
            font-size: 18px;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            transition: all 0.2s;
        }

        .quick-questions-toggle:hover {
            background: rgba(255, 255, 255, 0.2);
            transform: scale(1.1);
        }

        .quick-questions-menu {
            position: absolute;
            top: 100%;
            right: 0;
            margin-top: 8px;
            background: #252526;
            border: 1px solid #3e3e42;
            border-radius: 8px;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
            display: none;
            z-index: 1000;
            min-width: 280px;
        }

        .quick-questions-menu.show {
            display: block;
        }

        .quick-questions-header {
            padding: 10px 15px;
            border-bottom: 1px solid #3e3e42;
            font-weight: 600;
            color: #d4d4d4;
            font-size: 13px;
        }

        .quick-question-item {
            display: block;
            width: 100%;
            text-align: left;
            background: none;
            border: none;
            padding: 10px 15px;
            color: #d4d4d4;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 13px;
        }

        .quick-question-item:hover {
            background: #2d2d30;
            color: white;
        }

        /* 匯出按鈕 */
        .export-chat-btn {
            background: rgba(255, 255, 255, 0.1);
            border: none;
            color: white;
            font-size: 18px;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            transition: all 0.2s;
        }

        .export-chat-btn:hover {
            background: rgba(255, 255, 255, 0.2);
            transform: scale(1.1);
        }

        /* 匯出彈出視窗 */
        .export-modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.6);
            z-index: 10000;
            display: flex;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(5px);
        }

        .export-modal-content {
            background: #252526;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
            width: 450px;
            max-width: 90%;
        }

        .export-modal-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 20px;
            border-radius: 12px 12px 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .export-modal-body {
            padding: 20px;
        }

        .export-modal-body p {
            color: #d4d4d4;
            margin-bottom: 15px;
        }

        .export-options {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .export-option-btn {
            background: #2d2d30;
            border: 1px solid #3e3e42;
            color: #d4d4d4;
            padding: 15px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 15px;
            text-align: left;
        }

        .export-option-btn:hover {
            background: #3e3e42;
            border-color: #007acc;
            transform: translateY(-1px);
        }

        .export-icon {
            font-size: 24px;
        }

        .export-text strong {
            display: block;
            font-size: 14px;
            margin-bottom: 2px;
        }

        .export-text small {
            display: block;
            font-size: 12px;
            color: #969696;
        }

        /* 調整 AI 回應區域 */
        .ai-response {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }

        .ai-response-content {
            max-height: none;
        }

        /* 隱藏原有的元素 */
        .model-selection,
        .quick-actions,
        .quick-questions,
        .ai-info-box {
            display: none;
        }

        /* 對話區域滾動條 */
        .ai-chat-area::-webkit-scrollbar {
            width: 10px;
        }

        .ai-chat-area::-webkit-scrollbar-track {
            background: #1e1e1e;
        }

        .ai-chat-area::-webkit-scrollbar-thumb {
            background: #424242;
            border-radius: 5px;
        }

        .ai-chat-area::-webkit-scrollbar-thumb:hover {
            background: #4f4f4f;
        }
    </style>
    <style>
        /* 修正底部輸入區的樣式 */

        /* 調整輸入區預設大小和對齊 */
        .ai-input-area {
            flex-shrink: 0;
            background: #1e1e1e;
            border-top: 2px solid #3e3e42;
            padding: 15px 20px;
            min-height: 180px;  /* 增加預設高度 */
            max-height: 70%;    /* 最多可佔 70% */
            display: flex;
            flex-direction: column;
            justify-content: flex-end;  /* 內容靠下對齊 */
        }

        /* 優化輸入框容器 */
        .custom-question-wrapper {
            display: flex;
            flex-direction: column;
            gap: 10px;
            width: 100%;
        }

        /* 調整輸入框樣式 */
        .question-input {
            flex: 1;
            background: #2d2d30;
            border: 2px solid #3e3e42;
            border-radius: 8px;
            padding: 12px;
            color: #d4d4d4;
            font-size: 14px;
            resize: none;
            font-family: inherit;
            min-height: 80px;   /* 增加最小高度 */
            max-height: 300px;  /* 設定最大高度 */
            overflow-y: auto;   /* 超過高度時顯示滾動條 */
        }

        /* 輸入控制區 - 改善對齊 */
        .input-controls {
            display: flex;
            gap: 10px;
            align-items: stretch;  /* 讓所有元素高度一致 */
            height: 38px;         /* 固定高度 */
        }

        /* 模型選擇器容器 */
        .model-selector {
            flex: 1;
            display: flex;
            align-items: center;
        }

        /* 模型選擇下拉選單 */
        .model-select {
            width: 100%;
            height: 100%;
            background: #2d2d30;
            border: 1px solid #3e3e42;
            border-radius: 6px;
            padding: 0 12px;
            color: #d4d4d4;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
            appearance: none;  /* 移除預設樣式 */
            background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23d4d4d4' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
            background-repeat: no-repeat;
            background-position: right 8px center;
            background-size: 16px;
            padding-right: 32px;
        }

        /* 發送按鈕 - 確保對齊 */
        .ask-ai-btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 0 20px;
            height: 100%;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            white-space: nowrap;
        }

        /* 調整對話區初始大小 */
        .ai-chat-area {
            flex: 1;
            min-height: 300px;  /* 增加最小高度 */
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }

        /* 優化拖曳分隔線的樣式和位置 */
        .resize-divider {
            height: 12px;  /* 增加高度便於拖曳 */
            background: transparent;
            cursor: ns-resize;
            position: relative;
            flex-shrink: 0;
            user-select: none;
            margin: -6px 0;  /* 負邊距讓它與上下區域重疊 */
            z-index: 10;
        }

        /* 分隔線視覺效果 */
        .resize-handle-line {
            position: absolute;
            top: 50%;
            left: 10%;
            right: 10%;
            height: 3px;
            background: #3e3e42;
            transform: translateY(-50%);
            transition: all 0.2s;
            border-radius: 2px;
        }

        /* 懸停和拖曳時的效果 */
        .resize-divider:hover .resize-handle-line,
        .resize-divider.dragging .resize-handle-line {
            background: #007acc;
            height: 4px;
            box-shadow: 0 0 8px rgba(0, 122, 204, 0.5);
        }

        /* 為拖曳時添加視覺提示 */
        .resize-divider::before {
            content: '⋮⋮⋮';
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #3e3e42;
            font-size: 12px;
            letter-spacing: 2px;
            opacity: 0;
            transition: opacity 0.2s;
        }

        .resize-divider:hover::before {
            opacity: 0.5;
        }

        /* 確保右側面板使用正確的 flex 佈局 */
        .right-panel {
            display: flex;
            flex-direction: column;
            height: 100%;
            position: relative;
            overflow: hidden;
        }

        /* 修正面板標題不被壓縮 */
        .ai-panel-header {
            flex-shrink: 0;
        }

        /* 響應式調整 */
        @media (max-height: 700px) {
            .ai-input-area {
                min-height: 150px;
            }
            
            .question-input {
                min-height: 60px;
            }
        }

        /* 深色主題下的聚焦效果 */
        .question-input:focus,
        .model-select:focus {
            outline: none;
            border-color: #007acc;
            box-shadow: 0 0 0 2px rgba(0, 122, 204, 0.2);
        }

        /* 平滑過渡動畫 */
        .ai-chat-area,
        .ai-input-area {
            transition: flex 0.3s ease, height 0.3s ease;
        }
    </style>
    <style>

        /* 修改模型選擇器樣式 */
        .model-selector {
            flex: none;  /* 改為不佔用 flex 空間 */
            width: auto;
        }

        .model-select {
            width: 180px;  /* 固定寬度，縮小 */
            height: 36px;  /* 稍微縮小高度 */
            font-size: 13px;
        }

        /* 新增模型選擇彈出卡片樣式 */
        .model-popup {
            position: absolute;
            bottom: 100%;
            right: 0;
            margin-bottom: 10px;
            background: #252526;
            border: 1px solid #3e3e42;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
            padding: 15px;
            display: none;
            z-index: 1000;
            min-width: 500px;
        }

        .model-popup.show {
            display: block;
        }

        .model-popup-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }

        .model-card {
            background: #1e1e1e;
            border: 2px solid #3e3e42;
            border-radius: 8px;
            padding: 15px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .model-card:hover {
            border-color: #007acc;
            background: #2d2d30;
        }

        .model-card.selected {
            border-color: #667eea;
            background: #2d2d30;
        }

        .model-card-name {
            color: #4ec9b0;
            font-weight: 600;
            font-size: 14px;
            margin-bottom: 5px;
        }

        .model-card-desc {
            color: #969696;
            font-size: 12px;
        }

        /* 優化拖曳分隔線的樣式 */
        .resize-divider {
            height: 8px;  /* 縮小高度 */
            background: transparent;
            cursor: ns-resize;
            position: relative;
            flex-shrink: 0;
            user-select: none;
            margin: 0;  /* 移除負邊距 */
            z-index: 10;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        /* 使用更簡潔的拖曳條樣式 */
        .resize-handle-line {
            position: absolute;
            left: 20%;
            right: 20%;
            height: 4px;
            background: #3e3e42;
            border-radius: 2px;
            transition: all 0.2s;
        }

        /* 移除拖曳時的裝飾 */
        .resize-divider::before {
            display: none;
        }

        .resize-divider:hover .resize-handle-line {
            background: #007acc;
            height: 5px;
        }

        .resize-divider.dragging .resize-handle-line {
            background: #007acc;
            height: 6px;
        }

        /* 修復區塊開合按鈕 Tooltip 的 z-index 問題 */
        .section-toggle[data-tooltip]::before {
            z-index: 10001;  /* 提高 z-index */
            background: rgba(0, 0, 0, 0.95);  /* 加深背景色 */
        }

        .section-toggle[data-tooltip]::after {
            z-index: 10001;  /* 提高 z-index */
        }

        /* 確保 tooltip 容器的定位正確 */
        .section-container {
            position: relative;
            z-index: 1;
        }

        .table-header {
            position: relative;
            z-index: 2;  /* 確保不會遮擋 tooltip */
        }

        /* 調整開合按鈕的 z-index */
        .section-toggle {
            z-index: 100;  /* 提高按鈕本身的 z-index */
        }

    </style> 
    <style>
        /* 模型選擇器容器 */
        .model-selector {
            position: relative;
            flex: none;
        }

        /* 模型選擇按鈕 */
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
            white-space: nowrap;
        }

        .model-select-btn:hover {
            border-color: #007acc;
            background: #3e3e42;
        }

        .dropdown-arrow {
            font-size: 10px;
            opacity: 0.7;
        }

        /* 模型選擇彈出卡片 */
        .model-popup {
            position: absolute;
            bottom: 100%;
            right: 0;
            margin-bottom: 10px;
            background: #252526;
            border: 1px solid #3e3e42;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
            padding: 15px;
            display: none;
            z-index: 10000;
            min-width: 500px;
        }

        .model-popup.show {
            display: block !important;
        }

        .model-popup-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }

        .model-card {
            background: #1e1e1e;
            border: 2px solid #3e3e42;
            border-radius: 8px;
            padding: 15px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .model-card:hover {
            border-color: #007acc;
            background: #2d2d30;
            transform: translateY(-2px);
        }

        .model-card.selected {
            border-color: #667eea;
            background: #2d2d30;
            box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.3);
        }

        .model-card-name {
            color: #4ec9b0;
            font-weight: 600;
            font-size: 14px;
            margin-bottom: 5px;
        }

        .model-card-desc {
            color: #969696;
            font-size: 12px;
        }

        /* 調整輸入控制區佈局 */
        .input-controls {
            display: flex;
            gap: 10px;
            align-items: center;
            justify-content: space-between;
            height: 36px;
        }

        /* 調整發送按鈕 */
        .ask-ai-btn {
            height: 36px;
            padding: 0 20px;
            font-size: 14px;
        }

        .model-popup {
            position: absolute;
            bottom: 100%;
            right: 0;
            margin-bottom: 10px;
            background: #252526;
            border: 2px solid #667eea; /* 更明顯的邊框 */
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.8);
            padding: 15px;
            display: none;
            z-index: 99999; /* 極高的 z-index */
            min-width: 500px;
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.3s, visibility 0.3s;
        }

        .model-popup.show {
            display: block !important;
            opacity: 1 !important;
            visibility: visible !important;
        }

        /* 確保模型選擇器容器不會裁剪彈出框 */
        .model-selector {
            position: relative;
            flex: none;
            z-index: 9999;
        }

        /* 確保 AI 輸入區不會裁剪內容 */
        .ai-input-area {
            overflow: visible !important;
        }

        .custom-question-wrapper {
            overflow: visible !important;
        }

        .input-controls {
            overflow: visible !important;
        }        
    </style>
    <style>
        /* 拖曳分隔線樣式 */
        .resize-divider {
            height: 12px;
            background: transparent;
            cursor: ns-resize;
            position: relative;
            flex-shrink: 0;
            user-select: none;
            z-index: 100;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s;
        }

        /* 拖曳條視覺效果 */
        .resize-handle-line {
            position: absolute;
            left: 10%;
            right: 10%;
            height: 3px;
            background: #3e3e42;
            border-radius: 2px;
            transition: all 0.2s;
        }

        /* 懸停效果 */
        .resize-divider:hover {
            background: rgba(0, 122, 204, 0.1);
        }

        .resize-divider:hover .resize-handle-line {
            background: #007acc;
            height: 4px;
        }

        /* 拖曳中的效果 */
        .resize-divider.dragging {
            background: rgba(0, 122, 204, 0.2);
        }

        .resize-divider.dragging .resize-handle-line {
            background: #007acc;
            height: 5px;
            box-shadow: 0 0 10px rgba(0, 122, 204, 0.5);
        }

        /* 確保 AI 面板使用正確的佈局 */
        .right-panel {
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
        }

        .ai-panel-header {
            flex-shrink: 0;
        }

        .ai-chat-area {
            flex: none; /* 不使用 flex，改用固定高度 */
            overflow-y: auto;
            min-height: 50px;
        }

        .ai-input-area {
            flex: none; /* 不使用 flex，改用固定高度 */
            overflow-y: auto;
            min-height: 50px;
        }

        /* 防止內容溢出 */
        .ai-response {
            height: 100%;
            overflow-y: auto;
        }    
    </style>
</head>
<body>
    <div class="header">
        <div class="header-left">
            <div class="file-info">
                <h1 id="filename"></h1>
                <p id="filepath"></p>
            </div>
        </div>
        <div class="header-buttons">
            <button class="btn" onclick="toggleHelp()">⌨️ 快捷鍵說明 (F1)</button>
            <button class="btn btn-ai" id="aiToggleBtn" onclick="toggleAIPanel()">🤖 AI 助手</button>
            <button class="btn btn-danger" onclick="clearAllHighlights()">🗑️ 清除高亮</button>
            <button class="btn btn-success" onclick="downloadAsHTML()">💾 匯出 HTML</button>
            <a href="/view-file?path=""" + quote(file_path) + r"""&download=true" class="btn">📥 下載原始檔</a>
        </div>
    </div>
    
    <div class="main-container">
        <div class="left-panel">
            <div class="toolbar">
                <div class="search-container">
                    <input type="text" class="search-box" id="searchBox" placeholder="搜尋... (Ctrl+F)">
                    <label class="regex-toggle">
                        <input type="checkbox" id="regexToggle">
                        Regex
                    </label>           
                    <button class="btn" onclick="findPrevious()" id="prevSearchBtn" style="display: none;">◀ 上一個</button>
                    <button class="btn" onclick="findNext()" id="nextSearchBtn" style="display: none;">下一個 ▶</button>
                </div>
                <div class="search-info" id="searchInfo"></div>
                <span class="grep-indicator" id="grepIndicator">⚡ Grep 加速搜尋</span>
                <div class="bookmark-info" id="bookmarkInfo">F2: 標記行 | F3: 下一個書籤</div>
            </div>
            
            <div class="keywords-bar" id="keywordsBar">
                <div class="keyword-list" id="keywordList">
                    <span style="color: #969696; font-size: 12px; margin-right: 10px;">高亮關鍵字：</span>
                </div>
            </div>
            
            <div class="content-wrapper">
                <div class="line-numbers" id="lineNumbers"></div>
                <div class="content-area" id="contentArea">
                    <pre id="content"></pre>
                </div>
            </div>
            
            <div class="status-bar">
                <div class="status-left">
                    <span id="lineInfo">行 1, 列 1</span>
                    <span id="selectionInfo"></span>
                </div>
                <div class="status-right">
                    <span id="encodingInfo">UTF-8</span>
                    <span id="fileSizeInfo"></span>
                </div>
            </div>
        </div>
        
        <div class="resize-handle" id="resizeHandle"></div>
        
        <!-- Claude 風格的 AI 面板結構 -->
        <div class="right-panel" id="rightPanel">
            <!-- AI 面板標題 -->
            <div class="ai-panel-header">
                <h2><span>🤖</span> AI 助手</h2>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <!-- 快速問題下拉選單 -->
                    <div class="quick-questions-dropdown">
                        <button class="quick-questions-toggle" onclick="toggleQuickQuestions()" title="快速問題">
                            💡
                        </button>
                        <div class="quick-questions-menu" id="quickQuestionsMenu">
                            <div class="quick-questions-header">快速問題</div>
                            <button class="quick-question-item" onclick="useQuickQuestion('這個崩潰的根本原因是什麼？請詳細分析堆棧追蹤。')">
                                🔍 分析崩潰原因
                            </button>
                            <button class="quick-question-item" onclick="useQuickQuestion('請列出所有涉及的進程和線程，並說明它們的狀態。')">
                                📋 列出進程狀態
                            </button>
                            <button class="quick-question-item" onclick="useQuickQuestion('這個問題是否與記憶體相關？如果是，請解釋詳情。')">
                                💾 檢查記憶體問題
                            </button>
                            <button class="quick-question-item" onclick="useQuickQuestion('請提供修復這個問題的具體步驟和程式碼建議。')">
                                🛠️ 提供修復建議
                            </button>
                            <button class="quick-question-item" onclick="useQuickQuestion('這個崩潰發生的時間點和頻率如何？是否有模式？')">
                                ⏰ 分析發生模式
                            </button>
                        </div>
                    </div>
                    <button class="export-chat-btn" onclick="exportAIChat()" title="匯出對話">
                        📥
                    </button>
                    <button class="info-btn" onclick="toggleAIInfo()" title="使用限制">
                        ℹ️
                    </button>
                    <button class="clear-conversation-btn" onclick="clearConversationHistory()" title="清空對話記錄">
                        🗑️
                    </button>
                    <button class="close-ai-panel" onclick="toggleAIPanel()">×</button>
                </div>
            </div>
            
            <!-- AI 對話區（可調整大小） -->
            <div class="ai-chat-area" id="aiChatArea">
                <!-- 分析本文按鈕 -->
                <div class="analyze-file-section">
                    <button class="analyze-current-btn" id="analyzeBtn" onclick="analyzeCurrentFile()">
                        <span>🔍</span> 分析本文件
                    </button>
                </div>
                
                <!-- AI Response -->
                <div class="ai-response" id="aiResponse">
                    <div class="ai-response-content" id="aiResponseContent">
                        <!-- 分析結果將顯示在這裡 -->
                    </div>
                </div>
            </div>
            
            <!-- 可拖曳的分隔線 -->
            <div class="resize-divider" id="aiResizeDivider">
                <div class="resize-handle-line"></div>
            </div>
            
            <!-- 底部輸入區（可調整大小） -->
            <div class="ai-input-area" id="aiInputArea">
                <div class="custom-question-wrapper">
                    <textarea class="question-input" id="customQuestion" 
                              placeholder="詢問關於這個檔案的任何問題..."></textarea>
                    <div class="input-controls">
                        <!-- 發送按鈕 -->
                        <button class="ask-ai-btn" id="askBtn" onclick="askCustomQuestion()">
                            ➤ 發送
                        </button>
                        
                        <!-- 模型選擇器 -->
                        <div class="model-selector">
                            <button class="model-select-btn" id="modelSelectBtn">
                                <span id="selectedModelName">Claude 3.5 Sonnet</span>
                                <span class="dropdown-arrow">▼</span>
                            </button>
                            
                            <!-- 模型選擇彈出卡片 -->
                            <div class="model-popup" id="modelPopup">
                                <div class="model-popup-grid">
                                    <div class="model-card selected" data-model="claude-3-5-sonnet-20241022" onclick="selectModel(this)">
                                        <div class="model-card-name">Claude 3.5 Sonnet</div>
                                        <div class="model-card-desc">最新最強，推薦使用</div>
                                    </div>
                                    <div class="model-card" data-model="claude-3-5-haiku-20241022" onclick="selectModel(this)">
                                        <div class="model-card-name">Claude 3.5 Haiku</div>
                                        <div class="model-card-desc">快速回應，輕量級</div>
                                    </div>
                                    <div class="model-card" data-model="claude-3-opus-20240229" onclick="selectModel(this)">
                                        <div class="model-card-name">Claude 3 Opus</div>
                                        <div class="model-card-desc">功能強大，深度分析</div>
                                    </div>
                                    <div class="model-card" data-model="claude-3-haiku-20240307" onclick="selectModel(this)">
                                        <div class="model-card-name">Claude 3 Haiku</div>
                                        <div class="model-card-desc">經濟實惠，基本分析</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 匯出選項彈出視窗 -->
        <div class="export-modal" id="exportModal" style="display: none;">
            <div class="export-modal-content">
                <div class="export-modal-header">
                    <h4>📥 匯出 AI 對話</h4>
                    <button class="modal-close-btn" onclick="closeExportModal()">×</button>
                </div>
                <div class="export-modal-body">
                    <p>選擇匯出格式：</p>
                    <div class="export-options">
                        <button class="export-option-btn" onclick="exportChat('markdown')">
                            <span class="export-icon">📝</span>
                            <span class="export-text">
                                <strong>Markdown</strong>
                                <small>適合在文件編輯器中使用</small>
                            </span>
                        </button>
                        <button class="export-option-btn" onclick="exportChat('html')">
                            <span class="export-icon">🌐</span>
                            <span class="export-text">
                                <strong>HTML</strong>
                                <small>完整格式，可在瀏覽器中查看</small>
                            </span>
                        </button>
                        <button class="export-option-btn" onclick="exportChat('text')">
                            <span class="export-icon">📄</span>
                            <span class="export-text">
                                <strong>純文字</strong>
                                <small>最簡單的格式</small>
                            </span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="context-menu" id="contextMenu">
        <div class="context-menu-item" onclick="highlightKeyword(1)">
            <div class="color-box" style="background-color: rgba(255, 235, 59, 0.5);"></div>
            <span>高亮 1 (黃色)</span>
        </div>
        <div class="context-menu-item" onclick="highlightKeyword(2)">
            <div class="color-box" style="background-color: rgba(76, 175, 80, 0.5);"></div>
            <span>高亮 2 (綠色)</span>
        </div>
        <div class="context-menu-item" onclick="highlightKeyword(3)">
            <div class="color-box" style="background-color: rgba(33, 150, 243, 0.5);"></div>
            <span>高亮 3 (藍色)</span>
        </div>
        <div class="context-menu-item" onclick="highlightKeyword(4)">
            <div class="color-box" style="background-color: rgba(255, 152, 0, 0.5);"></div>
            <span>高亮 4 (橘色)</span>
        </div>
        <div class="context-menu-item" onclick="highlightKeyword(5)">
            <div class="color-box" style="background-color: rgba(233, 30, 99, 0.5);"></div>
            <span>高亮 5 (粉紅)</span>
        </div>
        <div class="separator"></div>
        <div class="context-menu-item" onclick="removeHighlight()">
            <span>移除此高亮</span>
        </div>
        <div class="context-menu-item" onclick="clearAllHighlights()">
            <span>清除所有高亮</span>
        </div>
    </div>
    
    <div class="shortcuts-help" id="shortcutsHelp">
        <button class="close-btn" onclick="toggleHelp()">×</button>
        <h3>快捷鍵說明</h3>
        <table>
            <tr><td>F1</td><td>顯示/隱藏此說明</td></tr>
            <tr><td>F2</td><td>切換滑鼠所在行的書籤</td></tr>
            <tr><td>F3</td><td>跳到下一個書籤</td></tr>
            <tr><td>Shift+F3</td><td>跳到上一個書籤</td></tr>
            <tr><td>Ctrl+F</td><td>搜尋</td></tr>
            <tr><td>Ctrl+G</td><td>跳到指定行</td></tr>
            <tr><td>Ctrl+A</td><td>全選</td></tr>
            <tr><td>Ctrl+C</td><td>複製</td></tr>
            <tr><td>Esc</td><td>關閉搜尋/清除選取</td></tr>
            <tr><td>滑鼠右鍵</td><td>高亮選取文字</td></tr>
        </table>
    </div>
    <script>

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
    </script>
    <script>
        // Initialize with file data
        const fileContent = """ + escaped_content + r""";
        const fileName = """ + escaped_filename + r""";
        const filePath = """ + json.dumps(file_path) + r""";
        
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
        let selectedModel = 'claude-3-5-sonnet-20241022';
        let conversationHistory = [];
        let isAnalyzing = false;  // 防止重複請求
        
        // Toggle AI Panel
        function toggleAIPanel() {
            const rightPanel = document.getElementById('rightPanel');
            const resizeHandle = document.getElementById('resizeHandle');
            const aiBtn = document.getElementById('aiToggleBtn');
            
            isAIPanelOpen = !isAIPanelOpen;
            
            if (isAIPanelOpen) {
                rightPanel.classList.add('active');
                resizeHandle.classList.add('active');
                aiBtn.classList.add('active');
            } else {
                rightPanel.classList.remove('active');
                resizeHandle.classList.remove('active');
                aiBtn.classList.remove('active');
            }
        }
        
        // Analyze current file
        async function analyzeCurrentFile() {
            // 防止重複點擊
            if (isAnalyzing) {
                console.log('已經在分析中，請稍候...');
                return;
            }

            // 獲取選擇的模型
            const modelSelect = document.getElementById('aiModelSelect');
            if (modelSelect) {
                selectedModel = modelSelect.value;
            }
    
            const analyzeBtn = document.getElementById('analyzeBtn');
            const responseDiv = document.getElementById('aiResponse');
            let responseContent = document.getElementById('aiResponseContent');
            
            if (!analyzeBtn || !responseDiv) {
                console.error('找不到必要的元素');
                return;
            }

            // 確保 AI 回應區域有正確的結構
            if (!responseContent) {
                responseDiv.innerHTML = `
                    <div class="ai-response-header">
                        <div class="ai-response-title">
                            <span>📝</span> AI 分析結果
                        </div>
                    </div>
                    <div class="ai-response-content" id="aiResponseContent">
                        <!-- 分析結果將顯示在這裡 -->
                    </div>
                `;
                responseContent = document.getElementById('aiResponseContent');
            }
            
            // Get selected model
            const modelRadio = document.querySelector('input[name="aiModel"]:checked');
            if (modelRadio) {
                selectedModel = modelRadio.value;
            }
            
            // 設置分析狀態
            isAnalyzing = true;
            
            // Show loading state
            analyzeBtn.classList.add('loading');
            analyzeBtn.disabled = true;
            analyzeBtn.innerHTML = '<span>⏳</span> 分析中...';
            
            responseDiv.classList.add('active');
            
            // 創建新的 loading 元素並添加到對話區域
            const loadingDiv = document.createElement('div');
            loadingDiv.className = 'ai-loading';
            loadingDiv.innerHTML = `
                <div class="ai-spinner"></div>
                <div>正在使用 ${getModelDisplayName(selectedModel)} 分析日誌...</div>
                <div style="margin-top: 10px; color: #969696; font-size: 12px;">
                    ${selectedModel.includes('sonnet') ? '🧠 啟用深度思考模式...' : ''}
                </div>
            `;
            responseContent.appendChild(loadingDiv);
            
            // 滾動到 loading 元素
            setTimeout(() => {
                loadingDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
            }, 100);
            
            // 設置超時處理
            const timeoutId = setTimeout(() => {
                if (isAnalyzing) {
                    console.error('AI 分析超時');
                    // 移除 loading
                    if (loadingDiv && loadingDiv.parentNode) {
                        loadingDiv.remove();
                    }
                    // 顯示錯誤訊息
                    const errorDiv = document.createElement('div');
                    errorDiv.className = 'ai-error';
                    errorDiv.innerHTML = `
                        <h3>⏱️ 分析超時</h3>
                        <p>分析時間過長，請重試或選擇較小的檔案片段。</p>
                        <p style="margin-top: 10px;">
                            <button class="retry-btn" onclick="analyzeCurrentFile()">🔄 重試</button>
                        </p>
                    `;
                    responseContent.appendChild(errorDiv);
                    resetAnalyzeButton();
                }
            }, 60000); // 60 秒超時
            
            try {
                // 判斷文件類型
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
                        model: selectedModel
                    })
                });
                
                clearTimeout(timeoutId);
                
                // 移除 loading
                if (loadingDiv && loadingDiv.parentNode) {
                    loadingDiv.remove();
                }
                
                const data = await response.json();
                
                if (response.ok && data.success) {
                    // 顯示分析結果，包括 thinking 內容（如果有）
                    displayAIAnalysis(data.analysis, data.truncated, data.model, false, data.thinking);
                } else {
                    // 顯示錯誤
                    const errorDiv = document.createElement('div');
                    errorDiv.className = 'ai-error';
                    errorDiv.innerHTML = `
                        <h3>❌ 分析失敗</h3>
                        <p>${data.error || '無法完成 AI 分析'}</p>
                        ${data.details ? `<p><small>${data.details}</small></p>` : ''}
                        ${data.available_models ? `
                            <div style="margin-top: 10px;">
                                <p>可用的模型：</p>
                                <ul style="margin-left: 20px;">
                                    ${data.available_models.map(m => `<li>${m}</li>`).join('')}
                                </ul>
                            </div>
                        ` : ''}
                    `;
                    responseContent.appendChild(errorDiv);
                }
                
            } catch (error) {
                clearTimeout(timeoutId);
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
                        <button class="retry-btn" onclick="analyzeCurrentFile()">🔄 重試</button>
                    </p>
                `;
                responseContent.appendChild(errorDiv);
            } finally {
                resetAnalyzeButton();
            }
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

        // 添加重試按鈕樣式
        const retryButtonStyle = `
        <style>
        .retry-btn {
            background: #0e639c;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .retry-btn:hover {
            background: #1177bb;
            transform: translateY(-1px);
        }

        .ai-loading {
            position: relative;
        }

        .ai-loading .cancel-btn {
            position: absolute;
            top: 10px;
            right: 10px;
            background: #d73a49;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
        }

        .ai-loading .cancel-btn:hover {
            background: #cb2431;
        }
        </style>`;

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
            
            // 根據內容自動調整高度
            function adjustHeight() {
                const inputArea = document.getElementById('aiInputArea');
                const maxHeight = inputArea ? inputArea.offsetHeight - 80 : 300; // 留出控制按鈕的空間
                
                textarea.style.height = 'auto';
                const scrollHeight = textarea.scrollHeight;
                
                if (scrollHeight > maxHeight) {
                    textarea.style.height = maxHeight + 'px';
                    textarea.style.overflowY = 'auto';
                } else {
                    textarea.style.height = scrollHeight + 'px';
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

        // Ask custom question
        async function askCustomQuestion() {
            const askBtn = document.getElementById('askBtn');
            const customQuestionElement = document.getElementById('customQuestion');
            const responseDiv = document.getElementById('aiResponse');
            const responseContent = document.getElementById('aiResponseContent');
            
            // 確保元素存在
            if (!askBtn || !customQuestionElement || !responseDiv || !responseContent) {
                console.error('找不到必要的元素');
                return;
            }
            
            // 獲取選擇的模型
            const modelSelect = document.getElementById('aiModelSelect');
            if (modelSelect) {
                selectedModel = modelSelect.value;
            }            
            
            const customQuestion = customQuestionElement.value.trim();
            
            if (!customQuestion) {
                alert('請輸入您的問題或貼上要分析的日誌片段');
                return;
            }
            
            // Get selected model
            const modelRadio = document.querySelector('input[name="aiModel"]:checked');
            if (modelRadio) {
                selectedModel = modelRadio.value;
            }
            
            // Show loading state
            askBtn.disabled = true;
            askBtn.textContent = '詢問中...';
            
            responseDiv.classList.add('active');
            
            // 創建新的 loading 元素並添加到對話區域
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
                
                // 組合問題和檔案上下文
                const fullContent = `${fileInfo}${fileContext}使用者問題：${customQuestion}`;
                
                // 發送自訂問題請求，包含檔案內容作為上下文
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
                        original_question: customQuestion  // 保留原始問題以便顯示
                    })
                });
                
                // 移除 loading
                if (loadingDiv && loadingDiv.parentNode) {
                    loadingDiv.remove();
                }
                
                const data = await response.json();
                
                if (response.ok && data.success) {
                    // 顯示分析結果
                    displayAIAnalysisWithContext(data.analysis, false, data.model, customQuestion, data.thinking);
                    customQuestionElement.value = '';
                } else {
                    // 顯示錯誤
                    const errorDiv = document.createElement('div');
                    errorDiv.className = 'ai-error';
                    errorDiv.innerHTML = `
                        <h3>❌ 分析失敗</h3>
                        <p>${data.error || '無法完成 AI 分析'}</p>
                        ${data.details ? `<p><small>${data.details}</small></p>` : ''}
                    `;
                    responseContent.appendChild(errorDiv);
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
                `;
                responseContent.appendChild(errorDiv);
            } finally {
                // 恢復按鈕狀態
                askBtn.disabled = false;
                askBtn.textContent = '詢問 AI';
            }
        }

        // 設置 Enter 鍵送出功能
        function setupEnterKeySubmit() {
            const customQuestion = document.getElementById('customQuestion');
            if (!customQuestion) return;
            
            // 先移除可能存在的舊事件監聽器
            customQuestion.removeEventListener('keydown', handleEnterKey);
            
            // 定義事件處理函數
            function handleEnterKey(e) {
                // 檢查是否按下 Enter 鍵（不包含 Shift）
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault(); // 防止換行
                    e.stopPropagation(); // 阻止事件冒泡
                    
                    // 檢查是否有內容
                    const content = this.value.trim();
                    if (content) {
                        // 觸發送出
                        askCustomQuestion();
                    }
                }
                // Shift+Enter 保持預設行為（換行）
            }
            
            // 添加事件監聽器
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
            
            if (!responseContent) {
                console.error('找不到 AI 回應區域');
                return;
            }
            
            // 移除任何現有的 loading 元素
            const existingLoading = responseContent.querySelector('.ai-loading');
            if (existingLoading) {
                existingLoading.remove();
            }
            
            // 格式化分析結果
            let formattedAnalysis = analysis
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
                    ${escapeHtml(originalQuestion)}
                    <div style="margin-top: 5px; font-size: 11px; color: #969696;">
                        📄 關於檔案: ${escapeHtml(fileName)}
                    </div>
                </div>
                <div class="ai-response-item">
                    <div class="ai-icon">🤖</div>
                    <div class="ai-message">
                        ${truncated ? '<div class="ai-warning">⚠️ 由於內容過長，僅分析了關鍵部分</div>' : ''}
            `;
            
            // 如果有 thinking 內容，顯示它
            if (thinking) {
                conversationHTML += `
                    <details class="ai-thinking-section" style="margin-bottom: 15px;">
                        <summary style="cursor: pointer; color: #4ec9b0; font-weight: 600; margin-bottom: 10px;">
                            🧠 AI 思考過程 (點擊展開)
                        </summary>
                        <div style="background: #2d2d30; padding: 15px; border-radius: 6px; margin-top: 10px; border-left: 3px solid #4ec9b0;">
                            <pre style="white-space: pre-wrap; color: #969696; font-size: 13px; margin: 0;">${escapeHtml(thinking)}</pre>
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
            
            // 滾動到最新回應
            setTimeout(() => {
                conversationItem.scrollIntoView({ behavior: 'smooth', block: 'end' });
            }, 100);
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
                'askBtn',
                'customQuestion'
            ];
            
            let allElementsExist = true;
            requiredElements.forEach(id => {
                if (!document.getElementById(id)) {
                    console.error(`找不到元素: ${id}`);
                    allElementsExist = false;
                }
            });
            
            if (!allElementsExist) {
                console.error('某些必要的元素不存在，請檢查 HTML 結構');
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
        
        function displayAIAnalysis(analysis, truncated, model, isCustomQuestion = false, thinking = null) {
            const responseContent = document.getElementById('aiResponseContent');
            
            if (!responseContent) {
                console.error('找不到 AI 回應區域');
                return;
            }
            
            // 移除任何現有的 loading 元素
            const existingLoading = responseContent.querySelector('.ai-loading');
            if (existingLoading) {
                existingLoading.remove();
            }
            
            // 格式化分析結果
            let formattedAnalysis = analysis
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
                        ${escapeHtml(document.getElementById('customQuestion').value || '檔案分析請求')}
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
                                    <pre style="white-space: pre-wrap; color: #969696; font-size: 13px; margin: 0;">${escapeHtml(thinking)}</pre>
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
            
            // 滾動到最新回應
            setTimeout(() => {
                conversationItem.scrollIntoView({ behavior: 'smooth', block: 'end' });
            }, 100);
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
    </` + `script>    
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
    </script>
    <script>
        // 切換模型選擇彈出卡片
        function toggleModelPopup() {
            console.log('toggleModelPopup called');
            const popup = document.getElementById('modelPopup');
            
            if (!popup) {
                console.error('Model popup element not found!');
                return;
            }
            
            console.log('Current popup classes:', popup.className);
            console.log('Current popup display:', window.getComputedStyle(popup).display);
            
            // 切換 show 類
            popup.classList.toggle('show');
            
            console.log('After toggle classes:', popup.className);
            console.log('After toggle display:', window.getComputedStyle(popup).display);
            
            // 確保樣式生效
            if (popup.classList.contains('show')) {
                popup.style.display = 'block';
                console.log('Popup should be visible now');
            } else {
                popup.style.display = 'none';
                console.log('Popup hidden');
            }
            
            // 阻止事件冒泡
            if (event) {
                event.stopPropagation();
            }
            
            // 點擊外部關閉
            if (popup.classList.contains('show')) {
                setTimeout(() => {
                    document.addEventListener('click', handleModelPopupOutsideClick);
                }, 100);
            } else {
                document.removeEventListener('click', handleModelPopupOutsideClick);
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
            event.stopPropagation(); // 阻止事件冒泡
            
            const model = card.dataset.model;
            const modelName = card.querySelector('.model-card-name').textContent;
            
            // 更新選中狀態
            document.querySelectorAll('.model-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            
            // 更新顯示的模型名稱
            const selectedModelNameElement = document.getElementById('selectedModelName');
            if (selectedModelNameElement) {
                selectedModelNameElement.textContent = modelName;
            }
            
            // 更新全局變量
            selectedModel = model;
            console.log('Selected model:', selectedModel); // 調試用
            
            // 關閉彈出框
            const popup = document.getElementById('modelPopup');
            if (popup) {
                popup.classList.remove('show');
            }
            
            // 移除外部點擊監聽
            document.removeEventListener('click', handleModelPopupOutsideClick);
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

            // 綁定模型選擇按鈕事件
            const modelSelectBtn = document.getElementById('modelSelectBtn');
            if (modelSelectBtn) {
                // 移除可能存在的舊事件監聽器
                modelSelectBtn.replaceWith(modelSelectBtn.cloneNode(true));
                
                // 重新獲取按鈕（因為 cloneNode）
                const newModelSelectBtn = document.getElementById('modelSelectBtn');
                
                // 添加點擊事件
                newModelSelectBtn.addEventListener('click', function(e) {
                    console.log('Model button clicked');
                    e.preventDefault();
                    e.stopPropagation();
                    toggleModelPopup();
                });
                
                console.log('Model select button event listener added');
            } else {
                console.error('Model select button not found during initialization');
            }
            
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
    </script>
</body>
</html>"""
            
            response = Response(html_content, mimetype='text/html; charset=utf-8')
        
        return response
    except Exception as e:
        return f"Error reading file: {str(e)}", 500
		
if __name__ == '__main__':
    print("="*60)
    print("Android Cmdline Analyzer - Web Version")
    print("="*60)
    print("訪問 http://localhost:5000 來使用網頁介面")
    print("\n新功能說明:")
    print("1. 支援 'Cmd line:' 和 'Cmdline:' 兩種格式")
    print("2. 自動解壓縮 ZIP 檔案 (使用 unzip)")
    print("3. 檔案名稱可點擊直接查看內容")
    print("4. 使用 grep -E 加速搜尋")
    print("5. 智能提取程序名稱 (正確處理 app_process)")
    print("6. 支援 Windows UNC 網路路徑")
    print("7. 完整 HTML 報告匯出功能")
    print("8. 分頁和搜尋功能")
    print("9. 檔案統計資訊")
    print("10. 路徑自動完成功能 (輸入時顯示可用的子資料夾)")
    print("11. 增強檔案檢視器：")
    print("    - 行號顯示與跳轉")
    print("    - F2 書籤功能（像 Notepad++）")
    print("    - 快速搜尋（支援 Regex）")
    print("    - 右鍵高亮（5種顏色）")
    print("    - 匯出完整功能 HTML")
    print("    - 深色主題設計")
    print("12. 按檔案行號顯示 Cmdline 位置")
    print("13. 新增資料夾路徑欄位 (智能縮短路徑顯示)")
    print("\n修正功能:")
    print("1. ✅ Enter 鍵選擇路徑並關閉提示框")
    print("2. ✅ 匯出 HTML 保留檔案連結功能")
    print("3. ✅ 新增快速導覽列和返回頂部功能")
    print("="*60)
    
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
