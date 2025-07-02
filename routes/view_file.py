from flask import Blueprint, request, jsonify, url_for, render_template
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
from routes.grep_analyzer import AndroidLogAnalyzer

# 創建一個藍圖實例
view_file_bp = Blueprint('view_file_bp', __name__)
analyzer = AndroidLogAnalyzer()

@view_file_bp.route('/search-in-file', methods=['POST'])
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
        
# 添加新的 AI 分析端點
@view_file_bp.route('/view-file')
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
            escaped_file_path = json.dumps(file_path)
            response = render_template('view_file.html', file_path=html.escape(os.path.basename(file_path)), escaped_content=escaped_content, escaped_filename=escaped_filename, escaped_file_path=escaped_file_path)
            
        return response
    except Exception as e:
        return f"Error reading file: {str(e)}", 500