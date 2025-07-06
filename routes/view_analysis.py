#!/usr/bin/env python3
"""
Android Log 分析報告查看器
支援分割視窗、內容切換和多格式匯出
"""

import os
import json
import html
import re
from flask import Blueprint, render_template, request, send_file, jsonify, Response, make_response
from pathlib import Path
from datetime import datetime
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    
# 建立 Blueprint
view_analysis_bp = Blueprint('view_analysis_bp', __name__)

class AnalysisReportViewer:
    """分析報告查看器類別"""
    
    def __init__(self):
        self.base_path = None
    
    def set_base_path(self, path):
        """設定基礎路徑"""
        self.base_path = path
    
    def load_analysis_content(self, file_path):
        """載入分析報告內容"""
        try:
            # 使用提供的路徑（應該已經是絕對路徑）
            full_path = file_path
            
            # 如果不是絕對路徑且有 base_path，嘗試組合
            if not os.path.isabs(file_path) and self.base_path:
                full_path = os.path.join(self.base_path, file_path)
            
            # 確保路徑安全
            full_path = os.path.abspath(full_path)
            
            # 檢查檔案是否存在
            if not os.path.exists(full_path):
                return {
                    'success': False,
                    'error': f'檔案不存在: {full_path}'
                }
            
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 提取報告類型（ANR 或 Tombstone）
            report_type = self._detect_report_type(content)
            
            return {
                'success': True,
                'content': content,
                'type': report_type,
                'path': file_path
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def load_original_content(self, analysis_path):
        """載入原始檔案內容"""
        try:
            # 從分析檔案路徑推導原始檔案路徑
            original_path = self._get_original_path(analysis_path)
            
            if not original_path:
                return {
                    'success': False,
                    'error': '找不到原始檔案'
                }
            
            # 檢查檔案是否存在
            if not os.path.exists(original_path):
                return {
                    'success': False,
                    'error': f'原始檔案不存在: {original_path}'
                }
            
            with open(original_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            return {
                'success': True,
                'content': content,
                'path': original_path
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'載入原始檔案失敗: {str(e)}'
            }
    
    def _detect_report_type(self, content):
        """檢測報告類型"""
        if 'ANR 分析報告' in content or 'ANR 類型' in content:
            return 'anr'
        elif 'Tombstone 崩潰分析報告' in content or '崩潰類型' in content:
            return 'tombstone'
        return 'unknown'
    
    def _get_original_path(self, analysis_path):
        """從分析檔案路徑推導原始檔案路徑"""
        # 處理絕對路徑
        if os.path.isabs(analysis_path):
            # 移除 .analyzed.html 或 .analyzed.txt
            original_path = analysis_path.replace('.analyzed.html', '').replace('.analyzed.txt', '')
            
            # 檢查原始檔案是否存在
            if os.path.exists(original_path):
                return original_path
        else:
            # 相對路徑處理（向後兼容）
            original_path = analysis_path.replace('.analyzed.html', '').replace('.analyzed.txt', '')
            
            if self.base_path:
                full_path = os.path.join(self.base_path, original_path)
                if os.path.exists(full_path):
                    return full_path
            elif os.path.exists(original_path):
                return original_path
        
        return None
    
    def export_content(self, content, format_type, filename_base, content_type='analysis'):
        """匯出內容為指定格式"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 如果是原始檔案，直接匯出不做轉換
        if content_type == 'original':
            if format_type == 'txt':
                filename = f"{filename_base}_{timestamp}.txt"
                return content, filename, 'text/plain'
            elif format_type == 'html':
                # 原始檔案包裝成 HTML
                wrapped_content = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{filename_base}</title>
        <style>
            body {{ font-family: monospace; white-space: pre-wrap; }}
        </style>
    </head>
    <body>
    <pre>{html.escape(content)}</pre>
    </body>
    </html>"""
                filename = f"{filename_base}_{timestamp}.html"
                return wrapped_content, filename, 'text/html'
            elif format_type == 'markdown':
                # 原始檔案轉為 markdown code block
                md_content = f"# {filename_base}\n\n```\n{content}\n```"
                filename = f"{filename_base}_{timestamp}.md"
                return md_content, filename, 'text/markdown'
        
        # 分析報告的處理
        if format_type == 'html':
            filename = f"{filename_base}_{timestamp}.html"
            return content, filename, 'text/html'
        elif format_type == 'markdown':
            md_content = self._html_to_markdown(content)
            filename = f"{filename_base}_{timestamp}.md"
            return md_content, filename, 'text/markdown'
        elif format_type == 'txt':
            txt_content = self._html_to_text(content)
            filename = f"{filename_base}_{timestamp}.txt"
            return txt_content, filename, 'text/plain'
        else:
            raise ValueError(f"不支援的格式: {format_type}")
    
    def _html_to_markdown(self, html_content):
        """將 HTML 轉換為 Markdown"""
        import re
        from bs4 import BeautifulSoup
        
        try:
            # 使用 BeautifulSoup 解析 HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 如果是完整的 HTML 文檔，提取 body 內容
            body = soup.find('body')
            if body:
                soup = body
            
            # 移除 script 和 style 標籤
            for tag in soup(['script', 'style']):
                tag.decompose()
            
            # 取得文本內容
            text = soup.get_text(separator='\n', strip=True)
            
            # 如果 BeautifulSoup 方法失敗，使用原始的正則方法
            if not text or len(text) < 50:
                return self._html_to_markdown_regex(html_content)
            
            # 處理特殊格式
            lines = text.split('\n')
            md_lines = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # 檢查是否為標題（通常是獨立的短行）
                if len(line) < 50 and line.isupper():
                    md_lines.append(f"## {line}")
                elif line.startswith('ANR 類型:') or line.startswith('崩潰類型:'):
                    md_lines.append(f"### {line}")
                elif line.startswith('時間:') or line.startswith('進程:'):
                    md_lines.append(f"**{line}**")
                else:
                    md_lines.append(line)
                
            return '\n\n'.join(md_lines)
            
        except Exception as e:
            # 如果 BeautifulSoup 不可用，使用備用方法
            return self._html_to_markdown_regex(html_content)

    def _html_to_markdown_regex(self, html_content):
        """使用正則表達式將 HTML 轉換為 Markdown（備用方法）"""
        # 提取 body 內容
        if '<body' in html_content:
            match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
            if match:
                html_content = match.group(1)
        
        # 移除 script 和 style
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        
        # 基本轉換
        md = html_content
        
        # 轉換標題
        md = re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n# \1\n', md, flags=re.IGNORECASE)
        md = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n## \1\n', md, flags=re.IGNORECASE)
        md = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n### \1\n', md, flags=re.IGNORECASE)
        
        # 轉換強調
        md = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', md, flags=re.IGNORECASE)
        md = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', md, flags=re.IGNORECASE)
        
        # 轉換換行和段落
        md = re.sub(r'<br\s*/?>', '\n', md, flags=re.IGNORECASE)
        md = re.sub(r'</p>', '\n\n', md, flags=re.IGNORECASE)
        md = re.sub(r'<p[^>]*>', '', md, flags=re.IGNORECASE)
        
        # 轉換 pre/code
        md = re.sub(r'<pre[^>]*>(.*?)</pre>', lambda m: '\n```\n' + re.sub(r'<[^>]+>', '', m.group(1)) + '\n```\n', md, flags=re.DOTALL | re.IGNORECASE)
        
        # 移除所有剩餘的 HTML 標籤
        md = re.sub(r'<[^>]+>', '', md)
        
        # 解碼 HTML 實體
        md = html.unescape(md)
        
        # 清理空白
        md = re.sub(r'\n{3,}', '\n\n', md)
        md = re.sub(r'^\s+', '', md, flags=re.MULTILINE)
        
        return md.strip()

    def _html_to_text(self, html_content):
        """將 HTML 轉換為純文字"""
        import re
        from bs4 import BeautifulSoup
        
        try:
            # 使用 BeautifulSoup 解析
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 如果是完整的 HTML 文檔，提取 body
            body = soup.find('body')
            if body:
                soup = body
            
            # 移除 script 和 style
            for tag in soup(['script', 'style']):
                tag.decompose()
            
            # 取得純文字
            text = soup.get_text(separator='\n', strip=True)
            
            # 清理多餘空行
            text = re.sub(r'\n{3,}', '\n\n', text)
            
            return text.strip()
            
        except Exception:
            # 備用方法
            return self._html_to_text_regex(html_content)

    def _html_to_text_regex(self, html_content):
        """使用正則表達式轉換（備用方法）"""
        # 提取 body 內容
        if '<body' in html_content:
            match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
            if match:
                html_content = match.group(1)
        
        # 移除 script 和 style
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 保留換行
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
        
        # 移除所有 HTML 標籤
        text = re.sub(r'<[^>]+>', '', text)
        
        # 解碼 HTML 實體
        text = html.unescape(text)
        
        # 清理空白
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)
        
        return text.strip()

# 創建全域實例
viewer = AnalysisReportViewer()

@view_analysis_bp.route('/view-analysis')
def view_analysis():
    """查看分析報告的主頁面"""
    file_path = request.args.get('path', '')
    
    if not file_path:
        return "錯誤：未指定檔案路徑", 400
    
    # 處理下載請求
    if request.args.get('download') == 'true':
        try:
            # 載入檔案內容
            if request.args.get('original') == 'true':
                # 下載原始檔案
                result = viewer.load_original_content(file_path)
                if result['success']:
                    filename = os.path.basename(result['path'])
                    return Response(
                        result['content'],
                        mimetype='text/plain',
                        headers={
                            'Content-Disposition': f'attachment; filename="{filename}"'
                        }
                    )
            else:
                # 下載分析檔案
                result = viewer.load_analysis_content(file_path)
                if result['success']:
                    filename = os.path.basename(file_path)
                    mimetype = 'text/html' if file_path.endswith('.html') else 'text/plain'
                    return Response(
                        result['content'],
                        mimetype=mimetype,
                        headers={
                            'Content-Disposition': f'attachment; filename="{filename}"'
                        }
                    )
            
            return f"錯誤：{result['error']}", 404
        except Exception as e:
            return f"下載失敗：{str(e)}", 500
    
    # 載入分析內容
    analysis_result = viewer.load_analysis_content(file_path)
    
    if not analysis_result['success']:
        return f"錯誤：{analysis_result['error']}", 404
    
    # 準備模板數據
    import urllib.parse
    decoded_file_path = urllib.parse.unquote(file_path)

    # 準備模板數據
    response = make_response(render_template('view_analysis.html',
                         file_path=file_path,
                         escaped_file_path=json.dumps(file_path),
                         report_type=analysis_result['type']))
    
    # 明確設置 Content-Type
    response.headers['Content-Type'] = 'text/html; charset=utf-8'

    return response

@view_analysis_bp.route('/api/load-analysis')
def api_load_analysis():
    """API: 載入分析內容"""
    file_path = request.args.get('path', '')
    
    if not file_path:
        return jsonify({'success': False, 'error': '未指定檔案路徑'}), 400
    
    result = viewer.load_analysis_content(file_path)
    return jsonify(result)

@view_analysis_bp.route('/api/load-original')
def api_load_original():
    """API: 載入原始檔案內容"""
    analysis_path = request.args.get('path', '')
    
    if not analysis_path:
        return jsonify({'success': False, 'error': '未指定檔案路徑'}), 400
    
    result = viewer.load_original_content(analysis_path)
    return jsonify(result)

@view_analysis_bp.route('/api/export-content', methods=['POST'])
def api_export_content():
    """API: 匯出內容"""
    try:
        data = request.get_json()
        content = data.get('content', '')
        format_type = data.get('format', 'txt')
        filename_base = data.get('filename', 'export')
        content_type = data.get('contentType', 'analysis')  # 'analysis' 或 'original'
        
        if not content:
            return jsonify({'success': False, 'error': '沒有內容可供匯出'}), 400
        
        # 根據內容類型調整檔名
        if content_type == 'original':
            filename_base = f"{filename_base}_original"
        else:
            filename_base = f"{filename_base}_analysis"
        
        # 匯出內容
        exported_content, filename, mimetype = viewer.export_content(
            content, format_type, filename_base, content_type
        )
        
        # 創建響應
        response = Response(
            exported_content,
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )
        
        return response
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@view_analysis_bp.route('/api/switch-content', methods=['POST'])
def api_switch_content():
    """API: 切換左右視窗內容"""
    try:
        # 這個 API 主要是為了記錄用戶操作
        # 實際的內容切換在前端完成
        data = request.get_json()
        return jsonify({'success': True, 'message': '內容已切換'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def register_routes(app, base_path=None):
    """註冊路由到 Flask app"""
    if base_path:
        viewer.set_base_path(base_path)
    app.register_blueprint(view_analysis_bp)