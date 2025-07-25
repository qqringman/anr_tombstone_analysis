# jira_file_manager.py
import os
import tempfile
from typing import List, Optional, Dict
from datetime import datetime

class JiraFileManager:
    """管理 JIRA 檔案的下載和上傳"""
    
    def __init__(self, jira_client):
        self.client = jira_client
        self.download_dir = None
    
    def download_issue_attachments(self, issue_key: str, 
                               file_patterns: Optional[List[str]] = None,
                               download_dir: Optional[str] = None,
                               auto_extract: bool = True) -> List[str]:
        """
        下載 issue 的附件
        
        Args:
            issue_key: JIRA issue key
            file_patterns: 要下載的檔案模式列表（如 ['*.zip', '*.txt']），None 表示全部
            download_dir: 下載目錄，None 則使用臨時目錄
            auto_extract: 是否自動解壓縮壓縮檔
        
        Returns:
            下載的檔案路徑列表
        """
        if download_dir is None:
            download_dir = tempfile.mkdtemp(prefix=f'jira_{issue_key}_')
        
        self.download_dir = download_dir
        os.makedirs(download_dir, exist_ok=True)
        
        attachments = self.client.get_attachments(issue_key)
        downloaded_files = []
        
        for attachment in attachments:
            filename = attachment['filename']
            
            # 檢查是否符合檔案模式
            if file_patterns:
                match = False
                for pattern in file_patterns:
                    if self._match_pattern(filename, pattern):
                        match = True
                        break
                if not match:
                    continue
            
            # 下載檔案
            save_path = os.path.join(download_dir, filename)
            print(f"下載 {filename} 從 {issue_key}...")
            
            try:
                self.client.download_attachment(attachment['content'], save_path)
                downloaded_files.append(save_path)
                print(f"  ✓ 已下載到 {save_path}")
                
                # 自動解壓縮
                if auto_extract and filename.lower().endswith('.7z'):
                    self._extract_7z(save_path, download_dir)
                
            except Exception as e:
                print(f"  ✗ 下載失敗: {e}")
        
        return downloaded_files

    def _extract_7z(self, archive_path: str, extract_to: str):
        """解壓縮 7z 檔案"""
        try:
            import subprocess
            
            extract_dir = os.path.join(
                extract_to, 
                os.path.splitext(os.path.basename(archive_path))[0]
            )
            os.makedirs(extract_dir, exist_ok=True)
            
            # 使用系統 7z 命令
            cmd = ['7z', 'x', archive_path, f'-o{extract_dir}', '-y']
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"  ✓ 已解壓縮 7z: {os.path.basename(archive_path)}")
            else:
                print(f"  ✗ 解壓縮 7z 失敗: {result.stderr}")
                
        except Exception as e:
            print(f"  ✗ 解壓縮 7z 失敗: {e}")
    
    def download_multiple_issues(self, issue_keys: List[str],
                                 file_patterns: Optional[List[str]] = None) -> Dict[str, List[str]]:
        """下載多個 issues 的附件"""
        all_downloads = {}
        
        for issue_key in issue_keys:
            issue_dir = os.path.join(self.download_dir or tempfile.gettempdir(), issue_key)
            downloaded = self.download_issue_attachments(issue_key, file_patterns, issue_dir)
            all_downloads[issue_key] = downloaded
        
        return all_downloads
    
    def upload_analysis_result(self, issue_key: str, result_file: str, 
                           add_comment: bool = True, auto_reopen: bool = True) -> bool:
        """上傳分析結果到 JIRA，如果 issue 已關閉會自動 reopen"""
        try:
            # 檢查檔案是否存在
            if not os.path.exists(result_file):
                print(f"  ✗ 錯誤：找不到要上傳的檔案 {result_file}")
                return False
                
            print(f"  準備上傳檔案: {result_file} ({os.path.getsize(result_file) / 1024 / 1024:.2f} MB)")
            
            # 檢查 issue 狀態
            issue = self.client.get_issue(issue_key)
            original_status = issue['fields']['status']['name']
            was_closed = original_status.lower() in ['closed', 'resolved', 'done']
            reopened = False
            
            if was_closed:
                print(f"  ⚠️  Issue {issue_key} 已關閉（狀態: {original_status}）")
                
                if auto_reopen:
                    print(f"  嘗試重新開啟 issue...")
                    if self.client.reopen_issue(issue_key):
                        print(f"  ✓ 已重新開啟 issue")
                        reopened = True
                    else:
                        print(f"  ✗ 無法重新開啟 issue，嘗試直接上傳")
            
            # 上傳檔案
            print(f"上傳分析結果到 {issue_key}...")
            upload_success = False
            upload_error = None
            
            try:
                result = self.client.upload_attachment(issue_key, result_file)
                print(f"  ✓ 已上傳 {os.path.basename(result_file)}")
                upload_success = True
            except Exception as e:
                upload_error = str(e)
                print(f"  ✗ 上傳失敗: {e}")
                upload_success = False
            
            # 新增評論
            if add_comment:
                try:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    filename = os.path.basename(result_file)
                    filesize_mb = os.path.getsize(result_file) / 1024 / 1024
                    
                    if upload_success:
                        # 成功上傳的評論
                        comment_lines = [
                            f"ANR/Tombstone 自動分析完成 - {timestamp}",
                            f"分析結果檔案：[^{filename}]",  # JIRA Wiki 格式的附件連結
                            f"檔案大小：{filesize_mb:.2f} MB"
                        ]
                        
                        if was_closed and reopened:
                            comment_lines.append("")
                            comment_lines.append(f"注意：此 issue 原為 {original_status} 狀態，已自動重新開啟以上傳分析結果。")
                    else:
                        # 上傳失敗的評論
                        comment_lines = [
                            f"ANR/Tombstone 分析完成 - {timestamp}",
                            f"⚠️ 注意：分析結果上傳失敗",
                            f"檔案名稱：{filename}",
                            f"檔案大小：{filesize_mb:.2f} MB"
                        ]
                        
                        if upload_error:
                            comment_lines.append(f"錯誤原因：{upload_error}")
                        
                        if was_closed and not reopened:
                            comment_lines.extend([
                                "",
                                f"可能原因：issue 狀態為 {original_status}，無法上傳附件。",
                                "建議：請手動重新開啟 issue 後再嘗試上傳。"
                            ])
                        
                        comment_lines.extend([
                            "",
                            "分析結果已保存在本地，請另行獲取。"
                        ])
                    
                    comment = "\n".join(comment_lines)
                    self.client.add_comment(issue_key, comment)
                    print(f"  ✓ 已新增{'分析完成' if upload_success else '上傳失敗'}評論")
                    
                except Exception as e:
                    print(f"  ✗ 新增評論失敗: {e}")
            
            # 如果原本是關閉的，成功上傳，且有 reopen，再關閉回去
            if was_closed and reopened and upload_success:
                print(f"  將 issue 恢復為原始狀態 ({original_status})...")
                if self.client.close_issue(issue_key):
                    print(f"  ✓ 已恢復為 {original_status} 狀態")
                else:
                    print(f"  ✗ 無法恢復為原始狀態，issue 保持開啟")
                    try:
                        self.client.add_comment(
                            issue_key, 
                            f"注意：無法自動恢復 issue 為 {original_status} 狀態，請手動處理。"
                        )
                    except:
                        pass
            
            return upload_success
            
        except Exception as e:
            print(f"  ✗ 處理失敗: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _match_pattern(self, filename: str, pattern: str) -> bool:
        """檢查檔名是否符合模式"""
        import fnmatch
        return fnmatch.fnmatch(filename.lower(), pattern.lower())