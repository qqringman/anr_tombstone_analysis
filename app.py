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
import asyncio
import queue

# 從新的檔案中導入藍圖
from routes.ai_analyzer import ai_analyzer_bp
from routes.view_file import view_file_bp
from routes.main_page import main_page_bp
from routes.view_analysis import view_analysis_bp

# 添加進度隊列
progress_queues = {}

app = Flask(__name__)

# 註冊藍圖
app.register_blueprint(ai_analyzer_bp)
app.register_blueprint(view_file_bp)
app.register_blueprint(main_page_bp)
app.register_blueprint(view_analysis_bp)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.config['JSON_AS_ASCII'] = False

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