from flask import Blueprint, request, jsonify, render_template_string, Response, send_file
import pandas as pd
import json
import os
from datetime import datetime
import plotly.graph_objs as go
import plotly.utils
from collections import defaultdict
import io
import base64

# 創建藍圖
excel_report_bp = Blueprint('excel_report_bp', __name__)

# 在檔案最開始加入一個輔助函數
def get_problem_set(row):
    """取得問題集欄位，支援多種欄位名稱"""
    for key in ['問題 set', '問題set', 'Problem set', 'problem set']:
        if key in row:
            return row[key] or '未分類'
    return '未分類'

# HTML 模板
EXCEL_REPORT_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Excel 分析報告</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        /* 全局優化 */
        * {
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            background-color: #f0f2f5;
            margin: 0;
            padding: 0;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 0;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            position: relative;
        }
        
        .header-container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 20px;
        }
        
        .header h1 {
            font-size: 2rem;
            margin: 0 0 15px 0;
            font-weight: 600;
        }
        
        .header-info {
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 12px;
            padding: 20px 25px;
            margin-top: 20px;
            backdrop-filter: blur(10px);
            display: inline-block;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        }
        
        .header-info p {
            margin: 8px 0;
            display: flex;
            align-items: center;
            gap: 15px;
            font-size: 0.95rem;
        }
        
        .header-info p:last-child {
            margin-bottom: 0;
        }

        .header-info .info-icon {
            font-size: 1.2rem;
            width: 24px;
            text-align: center;
            opacity: 0.9;
        }

        .header-info .info-label {
            font-weight: 500;
            opacity: 0.85;
            min-width: 80px;
        }

        .header-info code {
            background: rgba(255, 255, 255, 0.2);
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 0.9rem;
            font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
            font-weight: 500;
            letter-spacing: 0.3px;
        }
        
        .export-html-btn {
            position: absolute;
            top: 50%;
            right: 30px;
            transform: translateY(-50%);
            background: rgba(255, 255, 255, 0.9);
            color: #667eea;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .export-html-btn:hover {
            background: white;
            transform: translateY(-50%) translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 30px 20px;
        }
        
        .card {
            background: white;
            border-radius: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.04);
            margin-bottom: 25px;
            padding: 30px;
            border: 1px solid rgba(0,0,0,0.06);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .card:hover {
            box-shadow: 0 8px 24px rgba(0,0,0,0.08);
            transform: translateY(-2px);
        }
        
        .card h3 {
            color: #333;
            margin-bottom: 20px;
            font-weight: 600;
            border-bottom: 2px solid #f0f2f5;
            padding-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .stat-card {
            background: white;
            border-radius: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.04);
            padding: 28px;
            text-align: center;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            border: 1px solid rgba(0,0,0,0.06);
            position: relative;
            overflow: hidden;
        }
        
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 5px;
            background: linear-gradient(90deg, #667eea, #764ba2);
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-6px);
            box-shadow: 0 12px 28px rgba(0,0,0,0.12);
            border-color: rgba(102, 126, 234, 0.2);
        }
        
        .stat-card:hover::before {
            opacity: 1;
        }
        
        .stat-card h3 {
            font-size: 2.5rem;
            color: #667eea;
            margin: 0;
            border: none;
            padding: 0;
        }
        
        .stat-card p {
            color: #666;
            margin: 10px 0 0 0;
            font-weight: 500;
            font-size: 0.95rem;
        }
        
        .stat-card.highlight {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.35);
        }
        
        .stat-card.highlight:hover {
            transform: translateY(-6px) scale(1.02);
            box-shadow: 0 14px 32px rgba(102, 126, 234, 0.45);
        }

        .stat-card.highlight h3,
        .stat-card.highlight p {
            color: white;
        }
        
        .chart-container {
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            padding: 25px;
            margin-bottom: 20px;
            transition: all 0.3s;
        }
        
        .chart-container:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        .chart-container h4 {
            margin-bottom: 20px;
            color: #333;
            font-weight: 600;
            text-align: center;
        }
        
        /* 圖表置中 */
        .chart-wrapper {
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 400px;
            width: 100%;
            position: relative;
        }

        /* 確保 Plotly 圖表置中 */
        .chart-wrapper > div {
            margin: 0 auto !important;
        }

        /* 修正特定圖表的大小 */
        #typeChart, #problemSetPieChart {
            max-width: 600px !important;
            margin: 0 auto !important;
        }

        /* 表格樣式（與主頁面一致） */
        .logs-table {
            background-color: white;
            border-radius: 12px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            overflow: hidden;
            margin-bottom: 30px;
            transition: all 0.3s;
        }
        
        .logs-table:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        .table-header {
            position: relative;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
            border-bottom: none;
        }
        
        .table-header h3 {
            color: white;
            margin: 0;
            font-size: 1.2rem;
            font-weight: 600;
        }
        
        .table-controls {
            padding: 20px;
            background-color: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .search-box {
            position: relative;
            flex: 1;
            max-width: 400px;
        }
        
        .search-box input {
            width: 100%;
            padding: 10px 40px 10px 15px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.3s;
        }
        
        .search-box input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .search-box::after {
            content: '🔍';
            position: absolute;
            right: 15px;
            top: 50%;
            transform: translateY(-50%);
            opacity: 0.5;
        }
        
        /* 分頁樣式 */
        .pagination {
            display: flex;
            gap: 8px;
            align-items: center;
            flex-wrap: wrap;
        }
        
        .pagination button {
            padding: 8px 16px;
            font-size: 14px;
            background: white;
            color: #667eea;
            border: 1px solid #667eea;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.3s;
            font-weight: 500;
        }
        
        .pagination button:hover:not(:disabled) {
            background: #667eea;
            color: white;
            transform: translateY(-1px);
        }
        
        .pagination button:disabled {
            background: #f0f0f0;
            color: #999;
            border-color: #ddd;
            cursor: not-allowed;
        }
        
        .pagination span {
            padding: 0 10px;
            color: #666;
            font-weight: 500;
        }
        
        /* 表格內容樣式 */
        .table-wrapper {
            overflow-x: auto;
            padding: 0;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        thead {
            position: sticky;
            top: 0;
            z-index: 10;
        }
        
        th {
            background-color: #f8f9fa;
            color: #333;
            font-weight: 600;
            padding: 15px;
            text-align: left;
            border-bottom: 2px solid #e9ecef;
            white-space: nowrap;
            cursor: pointer;
            user-select: none;
            position: relative;
            transition: all 0.2s;
        }
        
        th:hover {
            background-color: #e9ecef;
        }
        
        .sort-indicator {
            position: absolute;
            right: 10px;
            top: 50%;
            transform: translateY(-50%);
            color: #667eea;
            font-size: 12px;
            opacity: 0.7;
        }
        
        td {
            padding: 15px;
            border-bottom: 1px solid #f0f2f5;
            vertical-align: top;
        }
        
        tr:hover {
            background-color: #f8f9fa;
        }
        
        .anr-row {
            background-color: #fff3cd !important;
        }
        
        .tombstone-row {
            background-color: #f8d7da !important;
        }
        
        /* 導航標籤 */
        .nav-tabs {
            border-bottom: none;
            margin-bottom: 30px;
            display: flex;
            gap: 8px;
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            padding: 8px;
            border-radius: 16px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            position: relative;
        }

        .nav-tabs::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            border-radius: 16px;
            padding: 1px;
            background: linear-gradient(135deg, #e0e0e0, #f5f5f5);
            -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
            -webkit-mask-composite: destination-out;
            mask-composite: exclude;
            z-index: -1;
        }

        .nav-link {
            color: #666;
            border: none;
            padding: 14px 28px;
            border-radius: 12px;
            transition: all 0.3s ease;
            background: transparent;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.95rem;
            position: relative;
            overflow: hidden;
            letter-spacing: 0.3px;
        }
        
        .nav-link::before {
            font-size: 1.1rem;
            margin-right: 8px;
            vertical-align: middle;
        }

        #mainTabs button:nth-child(1)::before { content: '📊 '; }
        #mainTabs button:nth-child(2)::before { content: '📈 '; }
        #mainTabs button:nth-child(3)::before { content: '🔄 '; }
        #mainTabs button:nth-child(4)::before { content: '📋 '; }

        .nav-link::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 50%;
            transform: translateX(-50%) scaleX(0);
            width: 30px;
            height: 3px;
            background: #667eea;
            transition: transform 0.3s;
        }
        
        .nav-link.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
            transform: translateY(-1px);
        }
        
        .nav-link.active::after {
            display: none;
        }
        
        .nav-link:hover::before {
            opacity: 1;
        }

        .nav-link:hover:not(.active) {
            color: #667eea;
            transform: translateY(-1px);
        }
        
        .nav-link:hover:not(.active)::after {
            transform: translateX(-50%) scaleX(1);
        }
        
        .filter-section {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 25px;
            border: none;
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
        }
        
        .filter-section .row {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            align-items: flex-end;
        }
        
        .filter-section .col-md-3 {
            flex: 1;
            min-width: 220px;
        }
        
        .filter-section label {
            display: block;
            margin-bottom: 10px;
            font-weight: 600;
            color: #444;
            font-size: 0.95rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .filter-section select,
        .filter-section input {
            background: white;
            border: 2px solid #e1e4e8;
            box-shadow: 0 2px 6px rgba(0,0,0,0.05);
        }
        
        .filter-section select:focus,
        .filter-section input:focus {
            border-color: #667eea;
            box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.15);
        }
        
        #loadingOverlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 9999;
            backdrop-filter: blur(5px);
        }
        
        .loading-spinner {
            background: white;
            padding: 40px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        
        .loading-spinner p {
            margin-top: 20px;
            color: #666;
            font-weight: 500;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        /* 樞紐分析表樣式 */
        .pivot-table {
            overflow-x: auto;
            background: white;
            border-radius: 12px;
            padding: 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        
        .pivot-table table {
            border: none;
            width: 100%;
            border-radius: 12px;
            overflow: hidden;
            border-collapse: separate;
            border-spacing: 0;
        }
        
        .pivot-table th,
        .pivot-table td {
            border: none;
            padding: 14px 16px;
            text-align: center;
        }
        
        .pivot-table th {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-weight: 600;
            color: white;
            text-transform: uppercase;
            font-size: 0.85rem;
            letter-spacing: 0.5px;
        }
        
        .pivot-table td {
            background: white;
            border-bottom: 1px solid #f0f2f5;
            border-right: 1px solid #f0f2f5;
        }

        .pivot-table td:last-child {
            border-right: none;
        }

        .pivot-table tr:last-child td {
            border-bottom: none;
        }

        .pivot-table tr:hover td {
            background-color: #f8f9ff;
        }

        .pivot-table .total-row {
            background: linear-gradient(135deg, #42a5f5 0%, #478ed1 100%) !important;
        }
        
        .pivot-table .total-row td {
            color: white !important;
            font-weight: 700 !important;
            font-size: 0.95rem;
            border: none !important;
        }

        .pivot-table .subtotal-row {
            background-color: #e3f2fd !important;
        }

        .pivot-table .subtotal-row td {
            font-weight: 600;
            color: #1976d2;
            border-color: #e3f2fd !important;
        }

        /* 第一列（類別欄）特殊樣式 */
        .pivot-table td:first-child,
        .pivot-table th:first-child {
            background: #f8f9fa;
            font-weight: 600;
            color: #495057;
            text-align: left;
            position: sticky;
            left: 0;
            z-index: 1;
        }

        .pivot-table .total-row td:first-child,
        .pivot-table .subtotal-row td:first-child {
            background: inherit;
            color: inherit;
        }

        /* 數字欄位樣式 */
        .pivot-table td[style*="text-align: center"] {
            font-family: 'SF Mono', Monaco, Consolas, monospace;
            font-weight: 500;
        }

        /* Tab 內容 */
        .tab-content {
            display: none;
            animation: fadeIn 0.3s;
        }
        
        .tab-content.active {
            display: block;
        }
        
        @keyframes fadeIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        /* 單欄圖表 */
        .chart-full-width {
            margin-bottom: 30px;
        }
        
        /* 統計表格樣式 */
        .stats-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .stats-table th,
        .stats-table td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #f0f2f5;
        }
        
        .stats-table th {
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
        }
        
        .stats-table tr:hover {
            background: #f8f9fa;
        }
        
        .stats-table .text-right {
            text-align: right;
        }
        
        .stats-table .text-center {
            text-align: center;
        }
        
        /* 問題集標籤 */
        .problem-set-badge {
            background: linear-gradient(135deg, #42a5f5 0%, #478ed1 100%);
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 8px;
            box-shadow: 0 2px 4px rgba(66, 165, 245, 0.3);
        }
        
        /* 美化滾動條 */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #999;
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #666;
        }
        
        /* 響應式設計 */
        @media (max-width: 768px) {
            .export-html-btn {
                position: static;
                margin-top: 20px;
                transform: none;
                width: 100%;
            }
            
            .stats-grid {
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 15px;
            }
            
            .nav-tabs {
                flex-wrap: wrap;
            }
            
            .table-controls {
                flex-direction: column;
            }
            
            .search-box {
                max-width: 100%;
            }
        }
    </style>
</head>
<body>
    <div id="loadingOverlay">
        <div class="loading-spinner">
            <div style="font-size: 48px; margin-bottom: 20px;">⏳</div>
            <p>正在載入資料...</p>
        </div>
    </div>

    <div class="header">
        <div class="header-container">
            <h1>Excel 分析報告</h1>
            <div class="header-info">
                <p>
                    <span class="info-icon">📄</span>
                    <span class="info-label">檔案名稱</span>
                    <code>{{ filename }}</code>
                </p>
                <p>
                    <span class="info-icon">📁</span>
                    <span class="info-label">檔案路徑</span>
                    <code>{{ filepath }}</code>
                </p>
                <p>
                    <span class="info-icon">🕐</span>
                    <span class="info-label">載入時間</span>
                    <code>{{ load_time }}</code>
                </p>
            </div>
            <button class="export-html-btn" onclick="exportToHTML()">匯出 HTML</button>
        </div>
    </div>

    <div class="container">
        <!-- 統計摘要 -->
        <div class="stats-grid" id="statsGrid">
            <!-- 動態生成 -->
        </div>

        <!-- 標籤頁 -->
        <div class="nav-tabs" id="mainTabs" role="tablist">
            <button class="nav-link active" onclick="switchTab('overview')">總覽</button>
            <button class="nav-link" onclick="switchTab('charts')">圖表分析</button>
            <button class="nav-link" onclick="switchTab('pivot')">樞紐分析</button>
            <button class="nav-link" onclick="switchTab('data')">原始資料</button>
        </div>

        <!-- 總覽標籤 -->
        <div class="tab-content active" id="overview-tab">
            <div class="card">
                <h3>📊 快速統計</h3>
                <div id="quickStats"></div>
            </div>
            
            <div class="card">
                <h3>🏆 Top 10 問題程序</h3>
                <div id="topProcesses"></div>
            </div>
            
            <div class="card">
                <h3>📁 Top 10 問題集</h3>
                <div id="topProblemSets"></div>
            </div>
            
            <div class="card">
                <h3>🤖 AI 分析結果分類</h3>
                <div id="aiResultCategories"></div>
            </div>
        </div>

        <!-- 圖表分析標籤 -->
        <div class="tab-content" id="charts-tab">
            <div class="chart-full-width">
                <div class="chart-container">
                    <h4>類型分佈</h4>
                    <div class="chart-wrapper">
                        <div id="typeChart" style="width: 100%; max-width: 600px;"></div>
                    </div>
                </div>
            </div>
            
            <div class="chart-full-width">
                <div class="chart-container">
                    <h4>每日趨勢</h4>
                    <div class="chart-wrapper">
                        <div id="dailyChart" style="width: 100%;"></div>
                    </div>
                </div>
            </div>
            
            <div class="chart-full-width">
                <div class="chart-container">
                    <h4>程序問題分佈 (Top 20)</h4>
                    <div class="chart-wrapper">
                        <div id="processChart" style="width: 100%;"></div>
                    </div>
                </div>
            </div>
            
            <div class="chart-full-width">
                <div class="chart-container">
                    <h4>問題集分析</h4>
                    <div class="chart-wrapper">
                        <div id="problemSetChart" style="width: 100%;"></div>
                    </div>
                </div>
            </div>
            
            <div class="chart-full-width">
                <div class="chart-container">
                    <h4>問題集統計 (Top 10)</h4>
                    <div class="chart-wrapper">
                        <div id="problemSetPieChart" style="width: 100%; max-width: 600px;"></div>
                    </div>
                </div>
            </div>
            
            <div class="chart-full-width">
                <div class="chart-container">
                    <h4>每小時分佈</h4>
                    <div class="chart-wrapper">
                        <div id="hourlyChart" style="width: 100%;"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 樞紐分析標籤 -->
        <div class="tab-content" id="pivot-tab">
            <div class="card">
                <h3>📊 樞紐分析表</h3>
                <div class="filter-section">
                    <div class="row">
                        <div class="col-md-3">
                            <label>分析維度：</label>
                            <select id="pivotDimension" class="form-select" onchange="updatePivotTable()">
                                <option value="problemSet">依問題集分析</option>
                                <option value="process">依程序分析</option>
                                <option value="type">依類型分析</option>
                                <option value="date">依日期分析</option>
                            </select>
                        </div>
                        <div class="col-md-3">
                            <label>類型篩選：</label>
                            <select id="typeFilter" class="form-select" onchange="updatePivotTable()">
                                <option value="">全部</option>
                                <option value="ANR">ANR</option>
                                <option value="Tombstone">Tombstone</option>
                            </select>
                        </div>
                        <div class="col-md-3">
                            <label>日期起始：</label>
                            <input type="date" id="startDate" class="form-control" onchange="updatePivotTable()">
                        </div>
                        <div class="col-md-3">
                            <label>日期結束：</label>
                            <input type="date" id="endDate" class="form-control" onchange="updatePivotTable()">
                        </div>
                    </div>
                </div>
                <div id="pivotTable" class="pivot-table"></div>
            </div>
        </div>

        <!-- 原始資料標籤 -->
        <div class="tab-content" id="data-tab">
            <div class="logs-table">
                <div class="table-header">
                    <h3>詳細記錄</h3>
                </div>
                <div class="table-controls">
                    <div class="search-box">
                        <input type="text" id="dataSearchInput" placeholder="搜尋..." onkeyup="filterDataTable()">
                    </div>
                    <div class="pagination" id="dataPagination">
                        <button onclick="changeDataPage('first')">第一頁</button>
                        <button onclick="changeDataPage(-1)">上一頁</button>
                        <span id="dataPageInfo">第 1 頁 / 共 1 頁 (總計 0 筆)</span>
                        <button onclick="changeDataPage(1)">下一頁</button>
                        <button onclick="changeDataPage('last')">最後一頁</button>
                    </div>
                </div>
                <div class="table-wrapper">
                    <table id="dataTable">
                        <thead>
                            <tr>
                                <th onclick="sortDataTable('SN')" style="width: 60px;">
                                    SN <span class="sort-indicator" data-column="SN">▼</span>
                                </th>
                                <th onclick="sortDataTable('Date')" style="width: 150px;">
                                    Date <span class="sort-indicator" data-column="Date"></span>
                                </th>
                                <th onclick="sortDataTable('問題 set')" style="width: 120px;">
                                    問題 set <span class="sort-indicator" data-column="問題 set"></span>
                                </th>
                                <th onclick="sortDataTable('Type')" style="width: 100px;">
                                    Type <span class="sort-indicator" data-column="Type"></span>
                                </th>
                                <th onclick="sortDataTable('Process')">
                                    Process <span class="sort-indicator" data-column="Process"></span>
                                </th>
                                <th onclick="sortDataTable('AI result')">
                                    AI result <span class="sort-indicator" data-column="AI result"></span>
                                </th>
                                <th onclick="sortDataTable('Filename')">
                                    Filename <span class="sort-indicator" data-column="Filename"></span>
                                </th>
                                <th onclick="sortDataTable('Folder Path')">
                                    Folder Path <span class="sort-indicator" data-column="Folder Path"></span>
                                </th>
                            </tr>
                        </thead>
                        <tbody id="dataTableBody">
                            <!-- 動態生成 -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // 全域變數
        let rawData = {{ data | tojson }};
        let filteredData = [...rawData];
        let currentPage = 1;
        const itemsPerPage = 10;
        let sortColumn = 'SN';
        let sortOrder = 'asc';
        
        // 儲存原始 Excel 資料 (Base64)
        const excelDataBase64 = "{{ excel_data_base64 }}";
        
        // 初始化
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Raw data:', rawData);
            console.log('Sample row:', rawData[0]);
            
            initializeStats();
            initializeCharts();
            initializeDataTable();
            updatePivotTable();
            
            // 隱藏載入畫面
            document.getElementById('loadingOverlay').style.display = 'none';
        });
        
        // Tab 切換
        function switchTab(tabName) {
            // 更新按鈕狀態
            document.querySelectorAll('.nav-link').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
            
            // 顯示對應內容
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            document.getElementById(tabName + '-tab').classList.add('active');
        }
        
        // 初始化統計
        function initializeStats() {
            const stats = calculateStats();
            
            // 生成統計卡片
            const statsHtml = `
                <div class="stat-card">
                    <h3>${stats.totalRecords}</h3>
                    <p>總記錄數</p>
                </div>
                <div class="stat-card highlight">
                    <h3>${stats.anrCount}</h3>
                    <p>ANR 數量</p>
                </div>
                <div class="stat-card highlight">
                    <h3>${stats.tombstoneCount}</h3>
                    <p>Tombstone 數量</p>
                </div>
                <div class="stat-card">
                    <h3>${stats.uniqueProcesses}</h3>
                    <p>不同程序數</p>
                </div>
                <div class="stat-card">
                    <h3>${stats.uniqueProblemSets}</h3>
                    <p>問題集數量</p>
                </div>
                <div class="stat-card">
                    <h3>${stats.avgDailyIssues}</h3>
                    <p>平均每日問題</p>
                </div>
            `;
            
            document.getElementById('statsGrid').innerHTML = statsHtml;
            
            // 快速統計
            const quickStatsHtml = `
                <table class="stats-table">
                    <tr>
                        <td><strong>資料期間：</strong></td>
                        <td>${stats.dateRange}</td>
                    </tr>
                    <tr>
                        <td><strong>最常見問題程序：</strong></td>
                        <td>${stats.topProcess} <span class="problem-set-badge">${stats.topProcessCount} 次</span></td>
                    </tr>
                    <tr>
                        <td><strong>最常見問題集：</strong></td>
                        <td>${stats.topProblemSet} <span class="problem-set-badge">${stats.topProblemSetCount} 次</span></td>
                    </tr>
                    <tr>
                        <td><strong>AI 分析覆蓋率：</strong></td>
                        <td>${stats.aiCoverage}%</td>
                    </tr>
                    <tr>
                        <td><strong>最活躍時段：</strong></td>
                        <td>${stats.mostActiveHour}</td>
                    </tr>
                </table>
            `;
            
            document.getElementById('quickStats').innerHTML = quickStatsHtml;
            
            // Top 10 程序
            createTopProcessesTable();
            
            // Top 10 問題集
            createTopProblemSetsTable();
            
            // AI 結果分類
            createAIResultCategories();

            // 添加排序功能
            setTimeout(() => {
                addSortingToOverviewTables();
            }, 100);
        }
        
        // 計算統計資料
        function calculateStats() {
            const anrCount = rawData.filter(row => row.Type === 'ANR').length;
            const tombstoneCount = rawData.filter(row => row.Type === 'Tombstone').length;
            const processes = [...new Set(rawData.map(row => row.Process))];
            const problemSets = [...new Set(rawData.map(row => {
                return row['問題 set'] || row['問題set'] || row['Problem set'] || row['problem set'] || '未分類';
            }))];
            
            // 計算最常見的程序
            const processCount = {};
            rawData.forEach(row => {
                processCount[row.Process] = (processCount[row.Process] || 0) + 1;
            });
            const topProcess = Object.entries(processCount)
                .sort((a, b) => b[1] - a[1])[0];
            
            // 計算最常見的問題集
            const problemSetCount = {};
            rawData.forEach(row => {
                const ps = row['問題 set'] || row['問題set'] || '未分類';
                problemSetCount[ps] = (problemSetCount[ps] || 0) + 1;
            });
            const topProblemSet = Object.entries(problemSetCount)
                .sort((a, b) => b[1] - a[1])[0];
            
            // 計算 AI 覆蓋率
            const aiCoverage = Math.round(
                (rawData.filter(row => row['AI result'] && 
                    row['AI result'] !== '找不到分析結果' && 
                    row['AI result'] !== '-').length / rawData.length) * 100
            );
            
            // 日期範圍
            const dates = rawData.map(row => row.Date).sort();
            const dateRange = dates.length > 0 ? 
                `${dates[0].split(' ')[0]} ~ ${dates[dates.length - 1].split(' ')[0]}` : 'N/A';
            
            // 計算平均每日問題數
            const uniqueDates = [...new Set(dates.map(d => d.split(' ')[0]))];
            const avgDailyIssues = uniqueDates.length > 0 ? 
                Math.round(rawData.length / uniqueDates.length) : 0;
            
            // 計算最活躍時段
            const hourCount = {};
            rawData.forEach(row => {
                const hour = parseInt(row.Date.split(' ')[1].split(':')[0]);
                hourCount[hour] = (hourCount[hour] || 0) + 1;
            });
            const mostActiveHour = Object.entries(hourCount)
                .sort((a, b) => b[1] - a[1])[0];
            
            return {
                totalRecords: rawData.length,
                anrCount,
                tombstoneCount,
                uniqueProcesses: processes.length,
                uniqueProblemSets: problemSets.length,
                topProcess: topProcess ? topProcess[0] : 'N/A',
                topProcessCount: topProcess ? topProcess[1] : 0,
                topProblemSet: topProblemSet ? topProblemSet[0] : 'N/A',
                topProblemSetCount: topProblemSet ? topProblemSet[1] : 0,
                aiCoverage,
                dateRange,
                avgDailyIssues,
                mostActiveHour: mostActiveHour ? `${mostActiveHour[0]}:00 (${mostActiveHour[1]} 次)` : 'N/A'
            };
        }
        
        // Top 10 程序表格
        function createTopProcessesTable() {
            const processCount = {};
            rawData.forEach(row => {
                processCount[row.Process] = (processCount[row.Process] || 0) + 1;
            });
            
            const topProcesses = Object.entries(processCount)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10);
            
            let html = '<table class="stats-table">';
            html += '<thead><tr><th>排名</th><th>程序</th><th class="text-right">次數</th><th class="text-right">佔比</th></tr></thead>';
            html += '<tbody>';
            
            topProcesses.forEach(([process, count], index) => {
                const percentage = ((count / rawData.length) * 100).toFixed(2);
                html += `<tr>
                    <td class="text-center">${index + 1}</td>
                    <td>${process}</td>
                    <td class="text-right">${count}</td>
                    <td class="text-right">${percentage}%</td>
                </tr>`;
            });
            
            html += '</tbody></table>';
            document.getElementById('topProcesses').innerHTML = html;
        }
        
        // 添加排序功能到 Top 10 表格
        function addSortingToOverviewTables() {
            // 為所有總覽表格添加排序功能
            document.querySelectorAll('#overview-tab table').forEach(table => {
                const headers = table.querySelectorAll('th');
                headers.forEach((header, index) => {
                    header.style.cursor = 'pointer';
                    header.style.userSelect = 'none';
                    header.onclick = () => sortOverviewTable(table, index);
                });
            });
        }

        function sortOverviewTable(table, columnIndex) {
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            
            // 判斷當前排序方向
            const isAscending = table.dataset.sortColumn == columnIndex && 
                            table.dataset.sortOrder === 'asc';
            
            rows.sort((a, b) => {
                const aText = a.cells[columnIndex].textContent.trim();
                const bText = b.cells[columnIndex].textContent.trim();
                
                // 嘗試轉換為數字
                const aNum = parseFloat(aText.replace(/[^0-9.-]/g, ''));
                const bNum = parseFloat(bText.replace(/[^0-9.-]/g, ''));
                
                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return isAscending ? bNum - aNum : aNum - bNum;
                }
                
                return isAscending ? 
                    bText.localeCompare(aText) : 
                    aText.localeCompare(bText);
            });
            
            // 更新表格
            rows.forEach(row => tbody.appendChild(row));
            
            // 更新排序狀態
            table.dataset.sortColumn = columnIndex;
            table.dataset.sortOrder = isAscending ? 'desc' : 'asc';
        }

        // Top 10 問題集表格
        function createTopProblemSetsTable() {
            const problemSetCount = {};
            rawData.forEach(row => {
                const ps = row['問題 set'] || row['問題set'] || '未分類';
                problemSetCount[ps] = (problemSetCount[ps] || 0) + 1;
            });
            
            const topProblemSets = Object.entries(problemSetCount)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10);
            
            let html = '<table class="stats-table">';
            html += '<thead><tr><th>排名</th><th>問題集</th><th class="text-right">次數</th><th class="text-right">佔比</th></tr></thead>';
            html += '<tbody>';
            
            topProblemSets.forEach(([problemSet, count], index) => {
                const percentage = ((count / rawData.length) * 100).toFixed(2);
                html += `<tr>
                    <td class="text-center">${index + 1}</td>
                    <td>${problemSet}</td>
                    <td class="text-right">${count}</td>
                    <td class="text-right">${percentage}%</td>
                </tr>`;
            });
            
            html += '</tbody></table>';
            document.getElementById('topProblemSets').innerHTML = html;
        }
        
        // AI 結果分類
        function createAIResultCategories() {
            const categories = {
                '有效分析': 0,
                '找不到分析結果': 0,
                '讀取錯誤': 0,
                '無資料': 0
            };
            
            rawData.forEach(row => {
                const result = row['AI result'] || '';
                if (result === '找不到分析結果') {
                    categories['找不到分析結果']++;
                } else if (result.includes('讀取錯誤')) {
                    categories['讀取錯誤']++;
                } else if (result === '-' || result === '') {
                    categories['無資料']++;
                } else {
                    categories['有效分析']++;
                }
            });
            
            let html = '<table class="stats-table">';
            html += '<thead><tr><th>分類</th><th class="text-right">數量</th><th class="text-right">佔比</th></tr></thead>';
            html += '<tbody>';
            
            Object.entries(categories).forEach(([category, count]) => {
                const percentage = ((count / rawData.length) * 100).toFixed(2);
                const rowClass = category === '有效分析' ? 'style="background-color: #d4edda;"' : '';
                html += `<tr ${rowClass}>
                    <td>${category}</td>
                    <td class="text-right">${count}</td>
                    <td class="text-right">${percentage}%</td>
                </tr>`;
            });
            
            html += '</tbody></table>';
            document.getElementById('aiResultCategories').innerHTML = html;
        }
        
        // 初始化圖表
        function initializeCharts() {
            createTypeChart();
            createDailyChart();
            createProcessChart();
            createProblemSetChart();
            createProblemSetPieChart();
            createHourlyChart();
        }
        
        // 類型分佈圖
        function createTypeChart() {
            const typeCounts = {};
            rawData.forEach(row => {
                typeCounts[row.Type] = (typeCounts[row.Type] || 0) + 1;
            });
            
            const data = [{
                values: Object.values(typeCounts),
                labels: Object.keys(typeCounts),
                type: 'pie',
                marker: {
                    colors: ['#ffc107', '#dc3545']
                },
                textinfo: 'label+percent',
                textposition: 'outside',
                hole: .3
            }];
            
            const layout = {
                height: 400,
                autosize: true,
                margin: { l: 50, r: 50, t: 50, b: 50 },
            };
            
            Plotly.newPlot('typeChart', data, layout, {responsive: true});
        }
        
        // 每日趨勢圖
        function createDailyChart() {
            const dailyData = {};
            
            rawData.forEach(row => {
                const date = row.Date.split(' ')[0];
                if (!dailyData[date]) {
                    dailyData[date] = { ANR: 0, Tombstone: 0 };
                }
                dailyData[date][row.Type]++;
            });
            
            const dates = Object.keys(dailyData).sort();
            
            const traces = [
                {
                    x: dates,
                    y: dates.map(d => dailyData[d].ANR),
                    name: 'ANR',
                    type: 'scatter',
                    mode: 'lines+markers',
                    line: { color: '#ffc107', width: 3 },
                    marker: { size: 8 }
                },
                {
                    x: dates,
                    y: dates.map(d => dailyData[d].Tombstone),
                    name: 'Tombstone',
                    type: 'scatter',
                    mode: 'lines+markers',
                    line: { color: '#dc3545', width: 3 },
                    marker: { size: 8 }
                }
            ];
            
            const layout = {
                height: 400,
                xaxis: { 
                    title: '日期',
                    tickangle: -45
                },
                yaxis: { 
                    title: '數量',
                    dtick: 1
                },
                margin: { b: 100 }
            };
            
            Plotly.newPlot('dailyChart', traces, layout, {responsive: true});
        }
        
        // 程序問題分佈圖
        function createProcessChart() {
            const processData = {};
            
            rawData.forEach(row => {
                if (!processData[row.Process]) {
                    processData[row.Process] = { ANR: 0, Tombstone: 0 };
                }
                processData[row.Process][row.Type]++;
            });
            
            // 取前 20 個最多問題的程序
            const sortedProcesses = Object.entries(processData)
                .sort((a, b) => (b[1].ANR + b[1].Tombstone) - (a[1].ANR + a[1].Tombstone))
                .slice(0, 20);
            
            const processes = sortedProcesses.map(p => p[0]);
            
            const traces = [
                {
                    x: processes,
                    y: processes.map(p => processData[p].ANR),
                    name: 'ANR',
                    type: 'bar',
                    marker: { color: '#ffc107' }
                },
                {
                    x: processes,
                    y: processes.map(p => processData[p].Tombstone),
                    name: 'Tombstone',
                    type: 'bar',
                    marker: { color: '#dc3545' }
                }
            ];
            
            const layout = {
                height: 500,
                barmode: 'stack',
                xaxis: { 
                    title: '程序',
                    tickangle: -45
                },
                yaxis: { 
                    title: '數量',
                    dtick: 1
                },
                margin: { b: 200 }
            };
            
            Plotly.newPlot('processChart', traces, layout, {responsive: true});
        }
        
        // 問題集分析圖
        function createProblemSetChart() {
            const problemSetData = {};
            
            rawData.forEach(row => {
                const ps = row['問題 set'] || row['問題set'] || '未分類';
                if (!problemSetData[ps]) {
                    problemSetData[ps] = { ANR: 0, Tombstone: 0 };
                }
                problemSetData[ps][row.Type]++;
            });
            
            const problemSets = Object.keys(problemSetData).sort();
            
            const traces = [
                {
                    x: problemSets,
                    y: problemSets.map(ps => problemSetData[ps].ANR),
                    name: 'ANR',
                    type: 'bar',
                    marker: { color: '#ffc107' }
                },
                {
                    x: problemSets,
                    y: problemSets.map(ps => problemSetData[ps].Tombstone),
                    name: 'Tombstone',
                    type: 'bar',
                    marker: { color: '#dc3545' }
                }
            ];
            
            const layout = {
                height: 400,
                barmode: 'group',
                xaxis: { 
                    title: '問題集',
                    tickangle: -45
                },
                yaxis: { 
                    title: '數量',
                    dtick: 1
                },
                margin: { b: 100 }
            };
            
            Plotly.newPlot('problemSetChart', traces, layout, {responsive: true});
        }
        
        // 問題集餅圖
        function createProblemSetPieChart() {
            const problemSetCount = {};
            rawData.forEach(row => {
                const ps = row['問題 set'] || row['問題set'] || '未分類';
                problemSetCount[ps] = (problemSetCount[ps] || 0) + 1;
            });
            
            // 取前 10 個
            const topProblemSets = Object.entries(problemSetCount)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10);
            
            const data = [{
                values: topProblemSets.map(ps => ps[1]),
                labels: topProblemSets.map(ps => ps[0]),
                type: 'pie',
                textinfo: 'label+percent',
                textposition: 'outside',
                hole: .3
            }];
            
            const layout = {
                height: 400,
                showlegend: true,
                margin: { t: 20, b: 20 }
            };
            
            Plotly.newPlot('problemSetPieChart', data, layout, {responsive: true});
        }
        
        // 每小時分佈圖
        function createHourlyChart() {
            const hourlyData = {};
            
            // 初始化 24 小時
            for (let i = 0; i < 24; i++) {
                hourlyData[i] = { ANR: 0, Tombstone: 0 };
            }
            
            rawData.forEach(row => {
                const hour = parseInt(row.Date.split(' ')[1].split(':')[0]);
                hourlyData[hour][row.Type]++;
            });
            
            const hours = Object.keys(hourlyData).map(h => `${h}:00`);
            
            const traces = [
                {
                    x: hours,
                    y: Object.values(hourlyData).map(d => d.ANR),
                    name: 'ANR',
                    type: 'bar',
                    marker: { color: '#ffc107' }
                },
                {
                    x: hours,
                    y: Object.values(hourlyData).map(d => d.Tombstone),
                    name: 'Tombstone',
                    type: 'bar',
                    marker: { color: '#dc3545' }
                }
            ];
            
            const layout = {
                height: 400,
                barmode: 'stack',
                xaxis: { 
                    title: '小時',
                    dtick: 1
                },
                yaxis: { 
                    title: '數量',
                    dtick: 1
                }
            };
            
            Plotly.newPlot('hourlyChart', traces, layout, {responsive: true});
        }
        
        // 初始化資料表格
        function initializeDataTable() {
            // 先依照 SN 排序
            filteredData.sort((a, b) => {
                const aSN = parseInt(a.SN) || 0;
                const bSN = parseInt(b.SN) || 0;
                return aSN - bSN;
            });
            updateDataTable();
        }
        
        // 更新資料表格
        function updateDataTable() {
            const tbody = document.getElementById('dataTableBody');
            const startIndex = (currentPage - 1) * itemsPerPage;
            const endIndex = Math.min(startIndex + itemsPerPage, filteredData.length);
            const pageData = filteredData.slice(startIndex, endIndex);
            
            let html = '';
            pageData.forEach(row => {
                const rowClass = row.Type === 'ANR' ? 'anr-row' : 'tombstone-row';
                const problemSet = row['問題 set'] || row['問題set'] || '-';
                html += `<tr class="${rowClass}">
                    <td class="text-center">${row.SN}</td>
                    <td>${row.Date}</td>
                    <td>${problemSet}</td>
                    <td>${row.Type}</td>
                    <td>${row.Process}</td>
                    <td>${row['AI result'] || '-'}</td>
                    <td>${row.Filename}</td>
                    <td>${row['Folder Path']}</td>
                </tr>`;
            });
            
            tbody.innerHTML = html || '<tr><td colspan="8" style="text-align: center;">無資料</td></tr>';
            
            // 更新分頁資訊
            const totalPages = Math.ceil(filteredData.length / itemsPerPage) || 1;
            document.getElementById('dataPageInfo').textContent = 
                `第 ${currentPage} 頁 / 共 ${totalPages} 頁 (總計 ${filteredData.length} 筆)`;
            
            // 更新分頁按鈕狀態
            const paginationButtons = document.querySelectorAll('.pagination button');
            paginationButtons[0].disabled = currentPage === 1;
            paginationButtons[1].disabled = currentPage === 1;
            paginationButtons[2].disabled = currentPage === totalPages;
            paginationButtons[3].disabled = currentPage === totalPages;
        }
        
        // 搜尋功能
        function filterDataTable() {
            const searchTerm = document.getElementById('dataSearchInput').value.toLowerCase();
            
            if (searchTerm === '') {
                filteredData = [...rawData];
            } else {
                filteredData = rawData.filter(row => {
                    return Object.values(row).some(value => 
                        String(value).toLowerCase().includes(searchTerm)
                    );
                });
            }
            
            // 重新排序
            if (sortColumn) {
                sortDataTable(sortColumn, false);
            } else {
                currentPage = 1;
                updateDataTable();
            }
        }
        
        // 排序功能
        function sortDataTable(column, updateUI = true) {
            // 更新排序指示器
            if (updateUI) {
                document.querySelectorAll('.sort-indicator').forEach(indicator => {
                    indicator.textContent = '';
                });
                
                if (sortColumn === column) {
                    sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
                } else {
                    sortColumn = column;
                    sortOrder = 'asc';
                }
                
                const indicator = document.querySelector(`.sort-indicator[data-column="${column}"]`);
                indicator.textContent = sortOrder === 'asc' ? '▲' : '▼';
            }
            
            filteredData.sort((a, b) => {
                let aVal = a[column];
                let bVal = b[column];
                
                // 處理問題 set 欄位名稱
                if (column === '問題 set') {
                    aVal = a['問題 set'] || a['問題set'] || '';
                    bVal = b['問題 set'] || b['問題set'] || '';
                }
                
                // 處理 AI result
                if (column === 'AI result') {
                    aVal = aVal || '';
                    bVal = bVal || '';
                }
                
                // 處理 Folder Path
                if (column === 'Folder Path') {
                    aVal = aVal || '';
                    bVal = bVal || '';
                }
                
                // 數字排序
                if (column === 'SN') {
                    aVal = parseInt(aVal) || 0;
                    bVal = parseInt(bVal) || 0;
                }
                
                if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
                if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
                return 0;
            });
            
            currentPage = 1;
            updateDataTable();
        }
        
        // 分頁功能
        function changeDataPage(direction) {
            const totalPages = Math.ceil(filteredData.length / itemsPerPage) || 1;
            
            if (direction === 'first') {
                currentPage = 1;
            } else if (direction === 'last') {
                currentPage = totalPages;
            } else {
                currentPage = Math.max(1, Math.min(currentPage + direction, totalPages));
            }
            
            updateDataTable();
        }
        
        // 更新樞紐分析表
        function updatePivotTable() {
            const dimension = document.getElementById('pivotDimension').value;
            const typeFilter = document.getElementById('typeFilter').value;
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            
            // 篩選資料
            let pivotFilteredData = rawData.filter(row => {
                if (typeFilter && row.Type !== typeFilter) return false;
                if (startDate && row.Date < startDate) return false;
                if (endDate && row.Date > endDate) return false;
                return true;
            });
            
            let pivotHtml = '';
            
            switch (dimension) {
                case 'problemSet':
                    pivotHtml = createPivotByProblemSet(pivotFilteredData);
                    break;
                case 'process':
                    pivotHtml = createPivotByProcess(pivotFilteredData);
                    break;
                case 'type':
                    pivotHtml = createPivotByType(pivotFilteredData);
                    break;
                case 'date':
                    pivotHtml = createPivotByDate(pivotFilteredData);
                    break;
            }
            
            document.getElementById('pivotTable').innerHTML = pivotHtml;
        }
        
        // 依問題集的樞紐分析
        function createPivotByProblemSet(data) {
            const pivotData = {};
            let totals = { ANR: 0, Tombstone: 0, Total: 0 };
            
            data.forEach(row => {
                const ps = row['問題 set'] || row['問題set'] || '未分類';
                if (!pivotData[ps]) {
                    pivotData[ps] = {};
                }
                if (!pivotData[ps][row.Process]) {
                    pivotData[ps][row.Process] = { ANR: 0, Tombstone: 0, Total: 0 };
                }
                pivotData[ps][row.Process][row.Type]++;
                pivotData[ps][row.Process].Total++;
                totals[row.Type]++;
                totals.Total++;
            });
            
            let html = '<table class="table table-bordered">';
            html += '<thead><tr><th>問題集</th><th>程序</th><th style="text-align: center;">ANR</th><th style="text-align: center;">Tombstone</th><th style="text-align: center;">總計</th></tr></thead>';
            html += '<tbody>';
            
            Object.entries(pivotData).forEach(([problemSet, processes]) => {
                const psTotal = { ANR: 0, Tombstone: 0, Total: 0 };
                const processCount = Object.keys(processes).length;
                let firstRow = true;
                
                Object.entries(processes).forEach(([process, counts]) => {
                    html += '<tr>';
                    if (firstRow) {
                        html += `<td rowspan="${processCount + 1}" style="vertical-align: middle;"><strong>${problemSet}</strong></td>`;
                        firstRow = false;
                    }
                    html += `<td>${process}</td>`;
                    html += `<td style="text-align: center;">${counts.ANR}</td>`;
                    html += `<td style="text-align: center;">${counts.Tombstone}</td>`;
                    html += `<td style="text-align: center;"><strong>${counts.Total}</strong></td>`;
                    html += '</tr>';
                    
                    psTotal.ANR += counts.ANR;
                    psTotal.Tombstone += counts.Tombstone;
                    psTotal.Total += counts.Total;
                });
                
                // 小計
                html += '<tr class="subtotal-row">';
                html += `<td><strong>小計</strong></td>`;
                html += `<td style="text-align: center;"><strong>${psTotal.ANR}</strong></td>`;
                html += `<td style="text-align: center;"><strong>${psTotal.Tombstone}</strong></td>`;
                html += `<td style="text-align: center;"><strong>${psTotal.Total}</strong></td>`;
                html += '</tr>';
            });
            
            // 總計
            html += '<tr class="total-row">';
            html += '<td colspan="2" style="text-align: center;"><strong>總計</strong></td>';
            html += `<td style="text-align: center;"><strong>${totals.ANR}</strong></td>`;
            html += `<td style="text-align: center;"><strong>${totals.Tombstone}</strong></td>`;
            html += `<td style="text-align: center;"><strong>${totals.Total}</strong></td>`;
            html += '</tr>';
            
            html += '</tbody></table>';
            return html;
        }
        
        // 依程序的樞紐分析
        function createPivotByProcess(data) {
            const pivotData = {};
            let totals = { ANR: 0, Tombstone: 0, Total: 0 };
            
            data.forEach(row => {
                if (!pivotData[row.Process]) {
                    pivotData[row.Process] = {};
                }
                const ps = row['問題 set'] || row['問題set'] || '未分類';
                if (!pivotData[row.Process][ps]) {
                    pivotData[row.Process][ps] = { ANR: 0, Tombstone: 0, Total: 0 };
                }
                pivotData[row.Process][ps][row.Type]++;
                pivotData[row.Process][ps].Total++;
                totals[row.Type]++;
                totals.Total++;
            });
            
            let html = '<table class="table table-bordered">';
            html += '<thead><tr><th>程序</th><th>問題集</th><th style="text-align: center;">ANR</th><th style="text-align: center;">Tombstone</th><th style="text-align: center;">總計</th></tr></thead>';
            html += '<tbody>';
            
            Object.entries(pivotData).forEach(([process, problemSets]) => {
                const processTotal = { ANR: 0, Tombstone: 0, Total: 0 };
                const psCount = Object.keys(problemSets).length;
                let firstRow = true;
                
                Object.entries(problemSets).forEach(([problemSet, counts]) => {
                    html += '<tr>';
                    if (firstRow) {
                        html += `<td rowspan="${psCount + 1}" style="vertical-align: middle;"><strong>${process}</strong></td>`;
                        firstRow = false;
                    }
                    html += `<td>${problemSet}</td>`;
                    html += `<td style="text-align: center;">${counts.ANR}</td>`;
                    html += `<td style="text-align: center;">${counts.Tombstone}</td>`;
                    html += `<td style="text-align: center;"><strong>${counts.Total}</strong></td>`;
                    html += '</tr>';
                    
                    processTotal.ANR += counts.ANR;
                    processTotal.Tombstone += counts.Tombstone;
                    processTotal.Total += counts.Total;
                });
                
                // 小計
                html += '<tr class="subtotal-row">';
                html += `<td><strong>小計</strong></td>`;
                html += `<td style="text-align: center;"><strong>${processTotal.ANR}</strong></td>`;
                html += `<td style="text-align: center;"><strong>${processTotal.Tombstone}</strong></td>`;
                html += `<td style="text-align: center;"><strong>${processTotal.Total}</strong></td>`;
                html += '</tr>';
            });
            
            // 總計
            html += '<tr class="total-row">';
            html += '<td colspan="2" style="text-align: center;"><strong>總計</strong></td>';
            html += `<td style="text-align: center;"><strong>${totals.ANR}</strong></td>`;
            html += `<td style="text-align: center;"><strong>${totals.Tombstone}</strong></td>`;
            html += `<td style="text-align: center;"><strong>${totals.Total}</strong></td>`;
            html += '</tr>';
            
            html += '</tbody></table>';
            return html;
        }
        
        // 依類型的樞紐分析
        function createPivotByType(data) {
            const pivotData = {};
            let totals = { Total: 0 };
            
            data.forEach(row => {
                if (!pivotData[row.Type]) {
                    pivotData[row.Type] = {};
                }
                const ps = row['問題 set'] || row['問題set'] || '未分類';
                if (!pivotData[row.Type][ps]) {
                    pivotData[row.Type][ps] = 0;
                }
                pivotData[row.Type][ps]++;
                totals.Total++;
            });
            
            let html = '<table class="table table-bordered">';
            html += '<thead><tr><th>類型</th><th>問題集</th><th style="text-align: center;">數量</th></tr></thead>';
            html += '<tbody>';
            
            Object.entries(pivotData).forEach(([type, problemSets]) => {
                const typeTotal = Object.values(problemSets).reduce((sum, count) => sum + count, 0);
                const psCount = Object.keys(problemSets).length;
                let firstRow = true;
                
                Object.entries(problemSets).forEach(([problemSet, count]) => {
                    html += '<tr>';
                    if (firstRow) {
                        html += `<td rowspan="${psCount + 1}" style="vertical-align: middle;"><strong>${type}</strong></td>`;
                        firstRow = false;
                    }
                    html += `<td>${problemSet}</td>`;
                    html += `<td style="text-align: center;">${count}</td>`;
                    html += '</tr>';
                });
                
                // 小計
                html += '<tr class="subtotal-row">';
                html += `<td><strong>小計</strong></td>`;
                html += `<td style="text-align: center;"><strong>${typeTotal}</strong></td>`;
                html += '</tr>';
            });
            
            // 總計
            html += '<tr class="total-row">';
            html += '<td colspan="2" style="text-align: center;"><strong>總計</strong></td>';
            html += `<td style="text-align: center;"><strong>${totals.Total}</strong></td>`;
            html += '</tr>';
            
            html += '</tbody></table>';
            return html;
        }
        
        // 依日期的樞紐分析
        function createPivotByDate(data) {
            const pivotData = {};
            let totals = { ANR: 0, Tombstone: 0, Total: 0 };
            
            data.forEach(row => {
                const date = row.Date.split(' ')[0];
                if (!pivotData[date]) {
                    pivotData[date] = { ANR: 0, Tombstone: 0, Total: 0 };
                }
                pivotData[date][row.Type]++;
                pivotData[date].Total++;
                totals[row.Type]++;
                totals.Total++;
            });
            
            let html = '<table class="table table-bordered">';
            html += '<thead><tr><th>日期</th><th style="text-align: center;">ANR</th><th style="text-align: center;">Tombstone</th><th style="text-align: center;">總計</th></tr></thead>';
            html += '<tbody>';
            
            Object.entries(pivotData).sort().forEach(([date, counts]) => {
                html += '<tr>';
                html += `<td><strong>${date}</strong></td>`;
                html += `<td style="text-align: center;">${counts.ANR}</td>`;
                html += `<td style="text-align: center;">${counts.Tombstone}</td>`;
                html += `<td style="text-align: center;"><strong>${counts.Total}</strong></td>`;
                html += '</tr>';
            });
            
            // 總計
            html += '<tr class="total-row">';
            html += '<td style="text-align: center;"><strong>總計</strong></td>';
            html += `<td style="text-align: center;"><strong>${totals.ANR}</strong></td>`;
            html += `<td style="text-align: center;"><strong>${totals.Tombstone}</strong></td>`;
            html += `<td style="text-align: center;"><strong>${totals.Total}</strong></td>`;
            html += '</tr>';
            
            html += '</tbody></table>';
            return html;
        }
        
        // 匯出 HTML
        function exportToHTML() {
            const htmlContent = document.documentElement.outerHTML;
            const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = '{{ filename }}_report_' + new Date().toISOString().slice(0, 10) + '.html';
            a.click();
            window.URL.revokeObjectURL(url);
        }
    </script>
</body>
</html>
'''

@excel_report_bp.route('/excel-report/<report_id>')
def show_excel_report(report_id):
    """顯示 Excel 分析報告"""
    try:
        # 從主模組導入 cache
        from routes.main_page import analysis_cache
        
        # 獲取檔案資訊
        file_info = analysis_cache.get(f"excel_report_{report_id}")
        if not file_info:
            return "報告不存在或已過期", 404
        
        excel_path = file_info['excel_path']
        is_temp = file_info.get('is_temp', False)
        original_filename = file_info.get('original_filename', os.path.basename(excel_path))
        original_path = file_info.get('original_path', excel_path)
        
        # 檢查檔案是否存在
        if not os.path.exists(excel_path):
            # 如果有 base64 資料，嘗試恢復
            excel_data_base64 = file_info.get('excel_data_base64')
            if excel_data_base64:
                excel_content = base64.b64decode(excel_data_base64)
            else:
                return "檔案已被刪除，請重新上傳", 404
        else:
            # 讀取 Excel 檔案到記憶體
            with open(excel_path, 'rb') as f:
                excel_content = f.read()
        
        # 轉換為 Base64
        excel_data_base64 = base64.b64encode(excel_content).decode('utf-8')
        
        # 更新 cache 中的 base64 資料
        file_info['excel_data_base64'] = excel_data_base64
        analysis_cache.set(f"excel_report_{report_id}", file_info)  # 使用 set 方法
        
        # 讀取 Excel 檔案
        df = pd.read_excel(io.BytesIO(excel_content))
        
        # 處理問題集欄位名稱
        if 'Problem set' in df.columns and '問題 set' not in df.columns:
            df['問題 set'] = df['Problem set']
        elif 'problem set' in df.columns and '問題 set' not in df.columns:
            df['問題 set'] = df['problem set']
        elif '問題set' in df.columns and '問題 set' not in df.columns:
            df['問題 set'] = df['問題set']
        
        # 轉換資料為 JSON
        data = df.to_dict('records')
        
        # 準備模板資料
        template_data = {
            'filename': original_filename,
            'filepath': original_path,
            'load_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data': data,
            'excel_data_base64': excel_data_base64
        }
        
        return render_template_string(EXCEL_REPORT_TEMPLATE, **template_data)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"載入報告時發生錯誤: {str(e)}", 500
        
