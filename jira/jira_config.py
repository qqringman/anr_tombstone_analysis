# jira/jira_config.py
import json
import os
from typing import Dict, Optional

class JiraConfig:
    """管理多個 JIRA 實例的配置"""
    
    def __init__(self, config_file: str = "jira_config.json"):
        # 如果沒有指定完整路徑，嘗試在 jira 目錄下找
        if not os.path.isabs(config_file) and not config_file.startswith('jira/'):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(script_dir, config_file)
        
        self.config_file = config_file
        self.configs: Dict[str, dict] = {}
        self.load_config()
    
    def load_config(self):
        """從配置檔案載入 JIRA 設定，支援環境變數覆蓋"""
        # 先嘗試從檔案載入
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.configs = json.load(f)
                print(f"成功載入 JIRA 配置: {list(self.configs.keys())}")
            except Exception as e:
                print(f"載入配置檔案失敗: {e}")
                self.configs = {}
        else:
            print(f"配置檔案不存在: {self.config_file}")
            self.configs = {}
        
        # 從環境變數覆蓋或新增配置
        self._load_from_env()
    
    def _load_from_env(self):
        """從環境變數載入配置"""
        # RTK 實例
        if os.environ.get('JIRA_RTK_URL'):
            if 'rtk' not in self.configs:
                self.configs['rtk'] = {}
            self.configs['rtk']['url'] = os.environ['JIRA_RTK_URL']
            
        if os.environ.get('JIRA_RTK_TOKEN'):
            if 'rtk' not in self.configs:
                self.configs['rtk'] = {}
            self.configs['rtk']['token'] = os.environ['JIRA_RTK_TOKEN']
            
        if os.environ.get('JIRA_RTK_USERNAME'):
            if 'rtk' not in self.configs:
                self.configs['rtk'] = {}
            self.configs['rtk']['username'] = os.environ['JIRA_RTK_USERNAME']
        
        # Vendor 實例
        if os.environ.get('JIRA_VENDOR_URL'):
            if 'vendor' not in self.configs:
                self.configs['vendor'] = {}
            self.configs['vendor']['url'] = os.environ['JIRA_VENDOR_URL']
            
        if os.environ.get('JIRA_VENDOR_TOKEN'):
            if 'vendor' not in self.configs:
                self.configs['vendor'] = {}
            self.configs['vendor']['token'] = os.environ['JIRA_VENDOR_TOKEN']
            
        if os.environ.get('JIRA_VENDOR_USERNAME'):
            if 'vendor' not in self.configs:
                self.configs['vendor'] = {}
            self.configs['vendor']['username'] = os.environ['JIRA_VENDOR_USERNAME']
        
        # 通用配置（可用於任何實例）
        instance_name = os.environ.get('JIRA_INSTANCE')
        if instance_name and os.environ.get('JIRA_URL') and os.environ.get('JIRA_TOKEN'):
            self.configs[instance_name] = {
                'url': os.environ['JIRA_URL'],
                'token': os.environ['JIRA_TOKEN'],
                'username': os.environ.get('JIRA_USERNAME', '')
            }
    
    def save_config(self):
        """儲存配置到檔案"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.configs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"儲存配置失敗: {e}")
    
    def add_jira_instance(self, name: str, url: str, token: str, 
                          username: Optional[str] = None):
        """新增 JIRA 實例配置"""
        self.configs[name] = {
            'url': url.rstrip('/'),
            'token': token,
            'username': username
        }
        self.save_config()
    
    def get_jira_config(self, name: str) -> Optional[dict]:
        """取得指定的 JIRA 配置"""
        config = self.configs.get(name)
        if not config:
            print(f"找不到 JIRA 實例 '{name}' 的配置")
            print(f"可用的實例: {', '.join(self.configs.keys())}")
        return config
    
    def list_instances(self) -> list:
        """列出所有已配置的 JIRA 實例"""
        return list(self.configs.keys())