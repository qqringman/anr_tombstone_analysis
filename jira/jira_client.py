# jira_client.py
import requests
from typing import List, Dict, Optional
import base64
import os

class JiraClient:
    """處理與 JIRA API 的交互"""
    
    def __init__(self, url: str, token: str, username: Optional[str] = None):
        self.url = url.rstrip('/')
        self.token = token
        self.username = username
        self.session = requests.Session()
        self._setup_auth()
    
    def _setup_auth(self):
        """設定認證"""
        if self.username:
            # 使用 Basic Auth (username:token)
            auth_str = f"{self.username}:{self.token}"
            auth_bytes = auth_str.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            self.session.headers.update({
                'Authorization': f'Basic {auth_b64}'
            })
        else:
            # 使用 Bearer Token
            self.session.headers.update({
                'Authorization': f'Bearer {self.token}'
            })

        # 預設使用 Bearer Token
        self.session.headers.update({
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def get_issue(self, issue_key: str) -> Dict:
        """取得 JIRA issue 資訊"""
        url = f"{self.url}/rest/api/2/issue/{issue_key}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def get_attachments(self, issue_key: str) -> List[Dict]:
        """取得 issue 的所有附件"""
        issue = self.get_issue(issue_key)
        return issue.get('fields', {}).get('attachment', [])
    
    def download_attachment(self, attachment_url: str, save_path: str):
        """下載附件"""
        response = self.session.get(attachment_url, stream=True)
        response.raise_for_status()
        
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    
    def upload_attachment(self, issue_key: str, file_path: str) -> Dict:
        """上傳附件到 JIRA issue"""
        url = f"{self.url}/rest/api/2/issue/{issue_key}/attachments"
        
        # 準備 headers - 使用 Bearer token
        headers = {
            'Authorization': f'Bearer {self.token}',
            'X-Atlassian-Token': 'no-check'
            # 不要設定 Content-Type，讓 requests 處理 multipart
        }
        
        try:
            with open(file_path, 'rb') as f:
                # 檔名使用 UTF-8 編碼
                filename = os.path.basename(file_path)
                
                # 決定 MIME type
                if file_path.endswith('.zip'):
                    mime_type = 'application/zip'
                elif file_path.endswith('.txt'):
                    mime_type = 'text/plain'
                elif file_path.endswith('.html'):
                    mime_type = 'text/html'
                elif file_path.endswith('.xlsx'):
                    mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                else:
                    mime_type = 'application/octet-stream'
                
                files = {'file': (filename, f, mime_type)}
                
                print(f"    發送 POST 請求到: {url}")
                response = requests.post(url, headers=headers, files=files)
                print(f"    回應狀態碼: {response.status_code}")
                
            # 檢查回應
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 413:
                raise Exception(f"檔案太大: {response.status_code} - {response.text}")
            elif response.status_code == 403:
                raise Exception(f"沒有權限: {response.status_code} - {response.text}")
            elif response.status_code == 404:
                raise Exception(f"Issue 不存在: {response.status_code} - {response.text}")
            elif response.status_code == 415:
                raise Exception(f"不支援的媒體類型: {response.status_code} - {response.text}")
            else:
                response.raise_for_status()
                
        except requests.exceptions.RequestException as e:
            print(f"    請求失敗: {str(e)}")
            raise
        except Exception as e:
            print(f"    上傳錯誤: {str(e)}")
            raise
    
    def add_comment(self, issue_key: str, comment: str):
        """新增評論到 issue"""
        url = f"{self.url}/rest/api/2/issue/{issue_key}/comment"
        data = {"body": comment}
        response = self.session.post(url, json=data)
        response.raise_for_status()
        return response.json()

    def get_transitions(self, issue_key: str) -> List[Dict]:
        """獲取 issue 可用的狀態轉換"""
        url = f"{self.url}/rest/api/2/issue/{issue_key}/transitions"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json().get('transitions', [])

    def transition_issue(self, issue_key: str, transition_id: str) -> bool:
        """執行 issue 狀態轉換"""
        url = f"{self.url}/rest/api/2/issue/{issue_key}/transitions"
        data = {
            "transition": {
                "id": transition_id
            }
        }
        response = self.session.post(url, json=data)
        return response.status_code == 204

    def reopen_issue(self, issue_key: str) -> bool:
        """重新開啟 issue"""
        transitions = self.get_transitions(issue_key)
        
        # 尋找 reopen 相關的 transition
        reopen_keywords = ['reopen', 'open', 're-open', '重新開啟', '重新打開']
        reopen_transition = None
        
        for trans in transitions:
            trans_name = trans['name'].lower()
            if any(keyword in trans_name for keyword in reopen_keywords):
                reopen_transition = trans
                break
        
        if reopen_transition:
            print(f"  找到 reopen transition: {reopen_transition['name']} (ID: {reopen_transition['id']})")
            return self.transition_issue(issue_key, reopen_transition['id'])
        else:
            print(f"  找不到 reopen transition")
            print(f"  可用的 transitions: {[t['name'] for t in transitions]}")
            return False

    def close_issue(self, issue_key: str) -> bool:
        """關閉 issue"""
        transitions = self.get_transitions(issue_key)
        
        # 尋找 close 相關的 transition
        close_keywords = ['close', 'done', 'resolved', '關閉', '完成']
        close_transition = None
        
        for trans in transitions:
            trans_name = trans['name'].lower()
            if any(keyword in trans_name for keyword in close_keywords):
                close_transition = trans
                break
        
        if close_transition:
            print(f"  找到 close transition: {close_transition['name']} (ID: {close_transition['id']})")
            return self.transition_issue(issue_key, close_transition['id'])
        else:
            print(f"  找不到 close transition")
            return False
            