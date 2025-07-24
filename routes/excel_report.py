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
from routes.main_page import analysis_cache

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
    <script src="https://cdn.plot.ly/plotly-2.18.0.min.js"></script>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        /* 全局優化 - 北歐藍色系 */
        * {
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            background-color: #f0f4f8;  /* 淺藍灰色背景 */
            margin: 0;
            padding: 0;
        }
        
        .header {
            background: linear-gradient(135deg, #2c5aa0 0%, #1e88e5 100%);  /* 北歐藍漸層 */
            color: white;
            padding: 30px 0;
            box-shadow: 0 2px 8px rgba(44, 90, 160, 0.2);
            position: relative;
        }
        
        .header-container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 20px;
        }
        
        .header h1 {
            font-size: 2.2rem;
            margin: 0 0 20px 0;
            font-weight: 700;
            color: white;
        }
        
        .header-info {
            background: rgba(255, 255, 255, 0.15);
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 8px;
            padding: 20px 25px;
            margin-top: 20px;
            display: inline-block;
            backdrop-filter: blur(10px);
        }
        
        .header-info p {
            margin: 8px 0;
            display: flex;
            align-items: center;
            gap: 15px;
            font-size: 0.95rem;
            color: white;
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
            font-weight: 600;
            min-width: 80px;
            color: white;
        }

        .header-info code {
            background: rgba(255, 255, 255, 0.2);
            padding: 6px 14px;
            border-radius: 4px;
            font-size: 0.9rem;
            font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
            font-weight: 500;
            letter-spacing: 0.3px;
            color: white;
        }
        
        .export-html-btn {
            position: absolute;
            top: 30px;
            right: 30px;
            background: rgba(255, 255, 255, 0.15);  /* 半透明白色背景 */
            backdrop-filter: blur(10px);  /* 模糊效果 */
            color: white;  /* 白色文字 */
            border: 1px solid rgba(255, 255, 255, 0.3);  /* 半透明白色邊框 */
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        }
        
        .export-html-btn:hover {
            background: rgba(255, 255, 255, 0.25);  /* hover 時背景更亮 */
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            border-color: rgba(255, 255, 255, 0.4);
        }

        .export-html-btn:active {
            transform: translateY(0);
            background: rgba(255, 255, 255, 0.2);
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 30px 20px;
        }
        
        .card {
            background: #fafbfc;  /* 非常淺的藍灰色，不是純白 */
            border-radius: 16px;
            box-shadow: 0 4px 12px rgba(44, 90, 160, 0.08);
            margin-bottom: 25px;
            padding: 30px;
            border: 1px solid #e3ecf3;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .card:hover {
            box-shadow: 0 8px 24px rgba(44, 90, 160, 0.12);
            transform: translateY(-2px);
        }
        
        .card h3 {
            color: #1e3a5f;  /* 深藍色標題 */
            margin-bottom: 20px;
            font-weight: 600;
            border-bottom: 2px solid #e3ecf3;
            padding-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .stat-card {
            background: #fafbfc;  /* 非常淺的藍灰色 */
            border-radius: 16px;
            box-shadow: 0 4px 12px rgba(44, 90, 160, 0.08);
            padding: 28px;
            text-align: center;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            border: 1px solid #e3ecf3;
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
            background: linear-gradient(90deg, #2c5aa0, #1e88e5);
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-6px);
            box-shadow: 0 12px 28px rgba(44, 90, 160, 0.15);
            border-color: rgba(44, 90, 160, 0.2);
        }
        
        .stat-card:hover::before {
            opacity: 1;
        }
        
        .stat-card h3 {
            font-size: 2.5rem;
            color: #2c5aa0;
            margin: 0;
            border: none;
            padding: 0;
        }
        
        .stat-card p {
            color: #5a7a9f;
            margin: 10px 0 0 0;
            font-weight: 500;
            font-size: 0.95rem;
        }
        
        .stat-card.highlight {
            background: linear-gradient(135deg, #2c5aa0 0%, #1e88e5 100%);
            color: white;
            border: none;
            box-shadow: 0 4px 8px rgba(44, 90, 160, 0.3);
        }
        
        .stat-card.highlight:hover {
            transform: translateY(-6px) scale(1.02);
            box-shadow: 0 14px 32px rgba(44, 90, 160, 0.4);
        }

        .stat-card.highlight h3,
        .stat-card.highlight p {
            color: white;
        }
        
        .chart-container {
            background: #fafbfc;  /* 非常淺的藍灰色 */
            border-radius: 12px;
            box-shadow: 0 2px 4px rgba(44, 90, 160, 0.08);
            padding: 25px;
            margin-bottom: 20px;
            transition: all 0.3s;
        }
        
        .chart-container:hover {
            box-shadow: 0 4px 12px rgba(44, 90, 160, 0.12);
        }
        
        .chart-container h4 {
            margin-bottom: 20px;
            color: #1e3a5f;
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
            background-color: #fafbfc;  /* 非常淺的藍灰色 */
            border-radius: 12px;
            box-shadow: 0 2px 4px rgba(44, 90, 160, 0.08);
            overflow: hidden;
            margin-bottom: 30px;
            transition: all 0.3s;
        }
        
        .logs-table:hover {
            box-shadow: 0 4px 12px rgba(44, 90, 160, 0.12);
        }
        
        .table-header {
            position: relative;
            padding: 20px;
            background: linear-gradient(135deg, #f5f8fb 0%, #e8f0f8 100%);
            border-bottom: 1px solid #e3ecf3;
        }
        
        .table-header h3 {
            color: #1e3a5f;
            margin: 0;
            font-size: 1.2rem;
            font-weight: 600;
        }
        
        .table-controls {
            padding: 20px;
            background-color: #f5f8fb;
            border-bottom: 1px solid #e3ecf3;
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
            border: 1px solid #d4e3f1;
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.3s;
        }
        
        .search-box input:focus {
            outline: none;
            border-color: #2c5aa0;
            box-shadow: 0 0 0 3px rgba(44, 90, 160, 0.1);
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
            color: #2c5aa0;
            border: 1px solid #2c5aa0;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.3s;
            font-weight: 500;
        }
        
        .pagination button:hover:not(:disabled) {
            background: #2c5aa0;
            color: white;
            transform: translateY(-1px);
        }
        
        .pagination button:disabled {
            background: #f0f4f8;
            color: #9db4d0;
            border-color: #d4e3f1;
            cursor: not-allowed;
        }
        
        .pagination span {
            padding: 0 10px;
            color: #5a7a9f;
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
            background-color: #f5f8fb;
            color: #1e3a5f;
            font-weight: 600;
            padding: 15px 40px 15px 15px;
            text-align: left;
            border-bottom: 2px solid #e3ecf3;
            white-space: nowrap;
            cursor: pointer;
            user-select: none;
            position: relative;
            transition: all 0.2s;
        }
        
        th:hover {
            background-color: #e8f0f8;
        }
        
        .sort-indicator {
            position: absolute;
            right: 15px;
            top: 50%;
            transform: translateY(-50%);
            color: #5a7a9f;
            font-size: 12px;
            opacity: 0.9;
        }
        
        td {
            padding: 15px;
            border-bottom: 1px solid #f0f4f8;
            vertical-align: top;
        }
        
        tr:hover {
            background-color: #f5f8fb !important;  /* 與樞紐分析表相同的 hover 效果 */
        }
        
        .anr-row {
            background-color: #fff !important;
        }
        
        .tombstone-row {
            background-color: transparent !important;  /* 透明背景 */
        }
        
        /* 導航標籤 */
        .nav-tabs {
            border-bottom: none;
            margin-bottom: 30px;
            display: flex;
            gap: 4px;
            background: transparent;
            padding: 0;
            border-radius: 0;
            box-shadow: none;
            position: relative;
            border-bottom: 2px solid #e3ecf3;
        }

        .nav-tabs::before {
            display: none;
        }

        .nav-link {
            color: #5a7a9f;
            border: none;
            padding: 12px 32px;
            border-radius: 12px 12px 0 0;
            transition: all 0.3s ease;
            background: #f5f8fb;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.95rem;
            position: relative;
            overflow: hidden;
            letter-spacing: 0.3px;
            margin-right: 4px;
            border: 1px solid #e3ecf3;
            border-bottom: none;
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
            background: #2c5aa0;
            transition: transform 0.3s;
        }
        
        .nav-link.active {
            background: #ffffff;
            color: #1e3a5f;
            box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.04);
            transform: none;
            z-index: 1;
            border: 1px solid #d4e3f1;
            border-bottom: 0px solid white;
            margin-bottom: -2px;
        }

        .nav-link:focus {
            outline: none;
            background: #e8f0f8;
            border-bottom: 0px solid white;
            box-shadow: 0 0 0 1px rgba(44, 90, 160, 0.1);
        }

        .nav-link.active::after {
            display: none;
        }
        
        .nav-link:hover::before {
            opacity: 1;
        }

        .nav-link:hover:not(.active) {
            background: #e8f0f8;
            color: #1e3a5f;
        }
        
        .nav-link:hover:not(.active)::after {
            transform: translateX(-50%) scaleX(1);
        }
        
        .filter-section {
            background: linear-gradient(135deg, #f5f8fb 0%, #e8f0f8 100%);
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 25px;
            border: 1px solid #e3ecf3;
            box-shadow: 0 2px 8px rgba(44, 90, 160, 0.06);
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
            color: #1e3a5f;
            font-size: 0.95rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .filter-section select,
        .filter-section input {
            background: white;
            border: 2px solid #d4e3f1;
            box-shadow: 0 2px 6px rgba(44, 90, 160, 0.05);
        }
        
        .filter-section select:focus,
        .filter-section input:focus {
            border-color: #2c5aa0;
            box-shadow: 0 0 0 4px rgba(44, 90, 160, 0.15);
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
            color: #5a7a9f;
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
            box-shadow: 0 2px 4px rgba(44, 90, 160, 0.08);
            overflow: hidden;
        }

        .pivot-table:hover {
            box-shadow: 0 4px 12px rgba(44, 90, 160, 0.12);
        }
        
        .pivot-table table {
            table-layout: fixed !important;
            width: 100% !important;
            border-collapse: separate;
            border-spacing: 0;
            overflow: hidden;
            border-radius: 12px;
        }
        
        .pivot-table th,
        .pivot-table td {
            border-bottom: 1px solid #e3ecf3;
            border-right: 1px solid #e3ecf3;
        }

        .pivot-sort-indicator {
            position: absolute;
            right: 8px;
            top: 50%;
            transform: translateY(-50%);
            color: #5a7a9f;
            font-size: 12px;
        }

        .pivot-table th:hover .pivot-sort-indicator {
            color: #1e3a5f;
        }

        .pivot-table th {
            background: #f5f8fb;
            font-weight: 600;
            color: #1e3a5f;
            text-transform: none;
            font-size: 14px;
            letter-spacing: 0.3px;
            border-bottom: 2px solid #e3ecf3;
            cursor: pointer;
            user-select: none;
            padding: 15px 35px 15px 16px !important;
            position: relative;
            transition: all 0.2s ease;
            text-align: left;
            height: 50px;
            line-height: 20px;
        }

        .pivot-table thead tr:first-child th:first-child {
            border-top-left-radius: 12px;
        }

        .pivot-table thead tr:first-child th:last-child {
            border-top-right-radius: 12px;
        }

        .pivot-table tbody tr:last-child td:first-child {
            border-bottom-left-radius: 12px;
        }

        .pivot-table tbody tr:last-child td:last-child {
            border-bottom-right-radius: 12px;
        }        

        /* 數字欄位的表頭置中 - 更明確的選擇器 */
        .pivot-table th:nth-child(3),
        .pivot-table th:nth-child(4),
        .pivot-table th:nth-child(5) {
            text-align: center !important;
        }

        .pivot-table th:hover {
            background: #e8f0f8;
            color: #1e3a5f;
        }

        .pivot-table td {
            height: 40px !important;
            line-height: 40px !important;
            vertical-align: middle !important;
            padding: 0 16px !important;
        }

        /* 問題集欄位（有 rowspan 的） */
        .pivot-table td[rowspan] {
            background: white !important;
            font-weight: 600 !important;
            text-align: left !important;
            vertical-align: middle !important;
            border-right: 2px solid #e3ecf3 !important;
            padding-left: 16px !important;
        }

        /* 程序名稱欄位 - 統一對齊和縮排 */
        .pivot-table tbody tr td:nth-child(2):not([colspan]),
        .pivot-table tbody tr td:first-child:not([rowspan]) {
            text-align: left !important;
            padding-left: 20px !important;
        }

        /* 最重要的部分：確保所有數字欄位都置中 */
        .pivot-table tbody tr td:nth-child(3),
        .pivot-table tbody tr td:nth-child(4),
        .pivot-table tbody tr td:nth-child(5) {
            text-align: center !important;
            padding: 0 12px !important;
            font-family: 'SF Mono', Monaco, Consolas, monospace !important;
            font-variant-numeric: tabular-nums !important;
        }

        /* 小計行樣式 */
        .pivot-table .subtotal-row td {
            background: #e8f0f8 !important;
            color: #1e3a5f !important;
            font-weight: 600 !important;
            height: 45px !important;
            line-height: 45px !important;
        }

        /* 小計行的數字也要置中 */
        .pivot-table .subtotal-row td:nth-child(2),
        .pivot-table .subtotal-row td:nth-child(3),
        .pivot-table .subtotal-row td:nth-child(4) {
            text-align: center !important;
            padding: 0 12px !important;
        }

        /* 總計行樣式 */
        .pivot-table .total-row td {
            background: #2c5aa0 !important;
            color: white !important;
            font-weight: 700 !important;
            font-size: 14px !important;
            height: 50px !important;
            line-height: 50px !important;
        }

        /* 總計行的所有儲存格都要置中（除了第一個） */
        .pivot-table .total-row td:not(:first-child) {
            text-align: center !important;
            padding: 0 12px !important;
        }

        /* 總計行的第一個儲存格（合併的） */
        .pivot-table .total-row td[colspan] {
            text-align: center !important;
            padding: 0 16px !important;
        }

        /* 總計行的圓角 */
        .pivot-table .total-row td:first-child {
            border-bottom-left-radius: 12px;
        }

        .pivot-table .total-row td:last-child {
            border-bottom-right-radius: 12px;
        }

        /* 小計行 hover 效果 */
        .pivot-table .subtotal-row:hover td {
            background: #d4e3f1 !important;
        }

        /* 總計行 hover 效果 */
        .pivot-table .total-row:hover td {
            background: #1e3a5f !important;
        }

        /* 確保所有數據行樣式一致 */
        .pivot-table tr:nth-child(even) td {
            background-color: #fafbfc;
        }

        .pivot-table td:last-child {
            border-right: none;
        }

        .pivot-table tr:last-child td {
            border-bottom: none;
        }

        .pivot-table tr:hover td {
            background-color: #f5f8fb !important;
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
            border-bottom: 1px solid #f0f4f8;
        }
        
        .stats-table th {
            background: #f5f8fb;
            font-weight: 600;
            color: #1e3a5f;
        }
        
        .stats-table tr:hover {
            background: #f5f8fb;
        }
        
        .stats-table .text-right {
            text-align: right;
        }
        
        .stats-table .text-center {
            text-align: center;
        }
        
        /* 問題集標籤 */
        .problem-set-badge {
            background: linear-gradient(135deg, #2c5aa0 0%, #1e88e5 100%);
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 8px;
            box-shadow: 0 2px 4px rgba(44, 90, 160, 0.3);
        }
        
        /* 美化滾動條 */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: #f0f4f8;
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #9db4d0;
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #5a7a9f;
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

        .info-item {
            display: flex;
            align-items: center;  /* 改回 center 讓 icon 和單行文字對齊 */
            padding: 12px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }

        .info-icon {
            font-size: 24px;
            margin-right: 12px;
            flex-shrink: 0;
            display: flex;
            align-items: center;  /* 確保 icon 內容居中 */
            height: 24px;  /* 固定高度 */
        }

        .info-content {
            flex: 1;
            min-width: 0;  /* 防止內容溢出 */
        }

        .info-label {
            font-size: 14px;
            font-weight: 500;
            word-break: break-word;
            line-height: 1.5;  /* 設定行高 */
        }

        .info-value {
            font-size: 14px;
            font-weight: 500;
            word-break: break-word;  /* 允許長文字換行 */
        }

        /* 當有多個檔案時的特殊處理 */
        .info-item.has-list {
            align-items: flex-start;  /* 只有列表時才使用 flex-start */
        }

        .info-item.has-list .info-icon {
            margin-top: 20px;  /* 調整 icon 位置以對齊第一行文字 */
        }

        /* 檔案列表樣式 */
        .file-list {
            margin: 8px 0 0 0;
            padding: 0;
            list-style: none;
        }

        .file-list li {
            padding: 2px 0;
            position: relative;
            padding-left: 20px;
            font-size: 13px;
            color: rgba(255, 255, 255, 0.9);
        }

        .file-list li:before {
            content: "•";
            position: absolute;
            left: 0;
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
                <div class="info-item" id="filenameItem">
                    <div class="info-icon">📄</div>
                    <div class="info-content">
                        <div class="info-label">檔案名稱</div>
                        <div class="info-value" id="filenameDisplay">
                            <!-- 由 JavaScript 填充 -->
                        </div>
                    </div>
                </div>
                <div class="info-item" id="filepathItem">
                    <div class="info-icon">📁</div>
                    <div class="info-content">
                        <div class="info-label">檔案路徑</div>
                        <div class="info-value" id="filepathDisplay">
                            <!-- 由 JavaScript 填充 -->
                        </div>
                    </div>
                </div>
                <div class="info-item">
                    <div class="info-icon">🕐</div>
                    <div class="info-content">
                        <div class="info-label">載入時間</div>
                        <div class="info-value">{{ load_time }}</div>
                    </div>
                </div>
            </div>
            <button class="export-html-btn" onclick="exportToHTML()">
                <span style="margin-right: 8px;">📥</span>匯出 HTML
            </button>
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
                                <th onclick="sortDataTable('SN')" style="width: 100px; position: relative;">
                                    <span style="margin-right: 6px;">🔢</span>SN
                                    <span class="sort-indicator" data-column="SN">▲</span>
                                </th>
                                <th onclick="sortDataTable('Date')" style="width: 170px; position: relative;">
                                    <span style="margin-right: 6px;">📅</span>Date
                                    <span class="sort-indicator" data-column="Date"></span>
                                </th>
                                <th onclick="sortDataTable('問題 set')" style="width: 140px; position: relative;">
                                    <span style="margin-right: 6px;">📁</span>問題 set
                                    <span class="sort-indicator" data-column="問題 set"></span>
                                </th>
                                <th onclick="sortDataTable('Type')" style="width: 120px; position: relative;">
                                    <span style="margin-right: 6px;">🏷️</span>Type
                                    <span class="sort-indicator" data-column="Type"></span>
                                </th>
                                <th onclick="sortDataTable('Process')" style="position: relative;">
                                    <span style="margin-right: 6px;">⚙️</span>Process
                                    <span class="sort-indicator" data-column="Process"></span>
                                </th>
                                <th onclick="sortDataTable('AI result')" style="position: relative;">
                                    <span style="margin-right: 6px;">🤖</span>AI result
                                    <span class="sort-indicator" data-column="AI result"></span>
                                </th>
                                <th onclick="sortDataTable('Filename')" style="position: relative;">
                                    <span style="margin-right: 6px;">📄</span>Filename
                                    <span class="sort-indicator" data-column="Filename"></span>
                                </th>
                                <th onclick="sortDataTable('Folder Path')" style="position: relative;">
                                    <span style="margin-right: 6px;">📂</span>Folder Path
                                    <span class="sort-indicator" data-column="Folder Path"></span>
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
    <!-- 添加頁尾 -->
    <footer style="background-color: #f8f9fa; padding: 20px 0; margin-top: 50px; border-top: 1px solid #e9ecef;">
        <div style="text-align: center; color: #6c757d; font-size: 14px;">
            © 2025 Copyright by Vince. All rights reserved.
        </div>
    </footer>
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

            // 處理檔案名稱和路徑列表
            const filenameList = {{ filename_list | tojson }};
            const pathList = {{ path_list | tojson }};
            
            // 更新檔案名稱顯示
            const filenameDisplay = document.getElementById('filenameDisplay');
            const filenameItem = document.getElementById('filenameItem');
            
            if (filenameList && filenameList.length > 0) {
                if (filenameList.length === 1) {
                    // 單一檔案，直接顯示
                    filenameDisplay.textContent = filenameList[0];
                } else {
                    // 多個檔案，顯示列表
                    filenameItem.classList.add('has-list');
                    let html = `合併 ${filenameList.length} 個檔案：<ul class="file-list">`;
                    filenameList.forEach(filename => {
                        html += `<li>${filename}</li>`;
                    });
                    html += '</ul>';
                    filenameDisplay.innerHTML = html;
                }
            }
            
            // 更新路徑顯示
            const filepathDisplay = document.getElementById('filepathDisplay');
            const filepathItem = document.getElementById('filepathItem');
            
            if (pathList && pathList.length > 0) {
                if (pathList.length === 1) {
                    // 單一路徑，直接顯示完整路徑
                    filepathDisplay.textContent = pathList[0];
                } else {
                    // 多個路徑，顯示列表
                    filepathItem.classList.add('has-list');
                    let html = '<ul class="file-list">';
                    pathList.forEach(path => {
                        html += `<li>${path}</li>`;
                    });
                    html += '</ul>';
                    filepathDisplay.innerHTML = html;
                }
            }
            
            // 預處理資料：統一問題集欄位名稱
            rawData = rawData.map(row => {
                // 如果有 'Problem set' 欄位，複製到 '問題 set'
                if (row['Problem set'] && !row['問題 set']) {
                    row['問題 set'] = row['Problem set'];
                }
                return row;
            });
            
            // 重新初始化 filteredData
            filteredData = [...rawData];
                                    
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
                const ps = row['問題 set'] || row['問題set'] || row['Problem set'] || row['problem set'] || '未分類';
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
                const ps = row['問題 set'] || row['問題set'] || row['Problem set'] || row['problem set'] || '未分類';
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
            // 先隱藏圖表容器
            document.querySelectorAll('.chart-wrapper').forEach(wrapper => {
                wrapper.style.visibility = 'hidden';
            });
            
            createTypeChart();
            createDailyChart();
            createProcessChart();
            createProblemSetChart();
            createProblemSetPieChart();
            createHourlyChart();
            
            // 延遲顯示並觸發 resize
            setTimeout(() => {
                document.querySelectorAll('.chart-wrapper').forEach(wrapper => {
                    wrapper.style.visibility = 'visible';
                });
                window.dispatchEvent(new Event('resize'));
                
                // 再次觸發以確保完全置中
                setTimeout(() => {
                    window.dispatchEvent(new Event('resize'));
                    // 對每個圖表單獨調用 resize
                    ['typeChart', 'dailyChart', 'processChart', 'problemSetChart', 'problemSetPieChart', 'hourlyChart'].forEach(chartId => {
                        if (document.getElementById(chartId)) {
                            Plotly.Plots.resize(chartId);
                        }
                    });
                }, 300);
            }, 200);
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
                    colors: ['#ffb84d', '#ff6b6b']  // 改為北歐風格的橙色和紅色
                },
                textinfo: 'label+percent',
                textposition: 'outside',
                hole: .3
            }];
            
            const layout = {
                height: 400,
                margin: { 
                    l: 80, 
                    r: 80, 
                    t: 50, 
                    b: 50,
                    autoexpand: true
                },
                autosize: true
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
                    line: { color: '#ffb84d', width: 3 },  // ANR 用橙色
                    marker: { size: 8 }
                },
                {
                    x: dates,
                    y: dates.map(d => dailyData[d].Tombstone),
                    name: 'Tombstone',
                    type: 'scatter',
                    mode: 'lines+markers',
                    line: { color: '#ff6b6b', width: 3 },  // Tombstone 用紅色
                    marker: { size: 8 }
                }
            ];
            
            const layout = {
                height: 450,
                xaxis: { 
                    title: '日期',
                    tickangle: -45,
                    tickfont: { size: 11 },
                    automargin: true
                },
                yaxis: { 
                    title: '數量',
                    tickfont: { size: 11 },
                    automargin: true,
                    tickformat: 'd',
                    rangemode: 'tozero'
                    // 不設定 dtick，讓 Plotly 自動決定
                },
                margin: { 
                    l: 100,
                    r: 50,
                    b: 120,  // 因為日期標籤是斜的，需要更多底部空間
                    t: 30,
                    autoexpand: true
                },
                autosize: true
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
                    tickangle: -45,
                    tickfont: { size: 10 },
                    automargin: true
                },
                yaxis: { 
                    title: '數量',
                    tickfont: { size: 11 },
                    automargin: true,
                    tickformat: 'd',
                    rangemode: 'tozero'
                    // 不設定 dtick，讓 Plotly 自動決定
                },
                margin: { 
                    l: 100,
                    r: 50,
                    b: 200,  // 程序名稱通常較長，需要更多底部空間
                    t: 30,
                    autoexpand: true
                },
                autosize: true
            };
            
            Plotly.newPlot('processChart', traces, layout, {responsive: true});           
        }
        
        // 問題集分析圖
        function createProblemSetChart() {
            const problemSetData = {};
            
            rawData.forEach(row => {
                const ps = row['問題 set'] || row['問題set'] || row['Problem set'] || row['problem set'] || '未分類';
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
                height: 450,
                barmode: 'group',
                xaxis: { 
                    title: '問題集',
                    tickangle: -45,
                    tickfont: { size: 11 },
                    automargin: true
                },
                yaxis: { 
                    title: '數量',
                    tickfont: { size: 11 },
                    automargin: true,
                    tickformat: 'd',
                    rangemode: 'tozero'
                    // 不設定 dtick，讓 Plotly 自動決定
                },
                margin: { 
                    l: 100,
                    r: 50,
                    b: 120,
                    t: 30,
                    autoexpand: true
                },
                autosize: true
            };
            
            Plotly.newPlot('problemSetChart', traces, layout, {responsive: true});              
        }
        
        // 問題集餅圖
        function createProblemSetPieChart() {
            const problemSetCount = {};
            rawData.forEach(row => {
                const ps = row['問題 set'] || row['問題set'] || row['Problem set'] || row['problem set'] || '未分類';
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
                height: 450,
                showlegend: true,
                margin: { 
                    l: 50,
                    r: 50,
                    t: 50,
                    b: 50,
                    autoexpand: true
                },
                autosize: true,
                legend: {
                    orientation: "v",
                    x: 1,
                    y: 0.5,
                    xanchor: 'left',
                    font: { size: 11 }
                }
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
                height: 450,
                barmode: 'stack',
                xaxis: { 
                    title: '小時',
                    dtick: 1,  // 小時保持每個都顯示
                    tickfont: { size: 11 },
                    automargin: true
                },
                yaxis: { 
                    title: '數量',
                    tickfont: { size: 11 },
                    automargin: true,
                    tickformat: 'd',
                    rangemode: 'tozero'
                    // 不設定 dtick，讓 Plotly 自動決定
                },
                margin: { 
                    l: 100,
                    r: 50,
                    b: 60,
                    t: 30,
                    autoexpand: true
                },
                autosize: true
            };
            
            Plotly.newPlot('hourlyChart', traces, layout, {responsive: true});           
        }
        
        // 初始化資料表格
        function initializeDataTable() {
            // 先依照 SN 升冪排序
            sortOrder = 'asc';  // 設定預設為升冪
            sortColumn = 'SN';
            filteredData.sort((a, b) => {
                const aSN = parseInt(a.SN) || 0;
                const bSN = parseInt(b.SN) || 0;
                return aSN - bSN;  // 升冪排序
            });
            
            // 更新排序指示器
            document.querySelector('.sort-indicator[data-column="SN"]').textContent = '▲';
            
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
                const problemSet = row['問題 set'] || row['問題set'] || row['Problem set'] || row['problem set'] || '-';
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
                    aVal = a['問題 set'] || a['問題set'] || a['Problem set'] || a['problem set'] || '';
                    bVal = b['問題 set'] || b['問題set'] || b['Problem set'] || b['problem set'] || '';
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
        
        // 添加樞紐分析表排序功能
        function addPivotTableSorting() {
            setTimeout(() => {
                const pivotTable = document.querySelector('#pivotTable table');
                if (pivotTable) {
                    const headers = pivotTable.querySelectorAll('th');
                    headers.forEach((header, index) => {
                        header.style.cursor = 'pointer';
                        header.style.userSelect = 'none';
                        header.onclick = () => sortPivotTable(pivotTable, index);
                    });
                }
            }, 100);
        }

        // 樞紐分析表排序函數
        function sortPivotTable(table, columnIndex) {
            const tbody = table.querySelector('tbody');
            const allRows = Array.from(tbody.querySelectorAll('tr'));
            
            // 先檢查是否有 rowspan（合併儲存格）的情況
            const hasRowspan = allRows.some(row => {
                return Array.from(row.cells).some(cell => cell.rowSpan > 1);
            });
            
            if (hasRowspan) {
                // 如果有合併儲存格，使用特殊的排序邏輯
                sortPivotTableWithRowspan(table, columnIndex);
                return;
            }
            
            // 原本的簡單排序邏輯（適用於沒有合併儲存格的情況）
            const totalRow = allRows.find(row => row.classList.contains('total-row'));
            const dataRows = allRows.filter(row => !row.classList.contains('total-row'));
            
            const isAscending = table.dataset.sortColumn == columnIndex && 
                            table.dataset.sortOrder === 'asc';
            
            dataRows.sort((a, b) => {
                const aText = a.cells[columnIndex]?.textContent.trim() || '';
                const bText = b.cells[columnIndex]?.textContent.trim() || '';
                
                const aNum = parseFloat(aText.replace(/[^0-9.-]/g, ''));
                const bNum = parseFloat(bText.replace(/[^0-9.-]/g, ''));
                
                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return isAscending ? bNum - aNum : aNum - bNum;
                }
                
                return isAscending ? 
                    bText.localeCompare(aText) : 
                    aText.localeCompare(bText);
            });
            
            tbody.innerHTML = '';
            dataRows.forEach(row => tbody.appendChild(row));
            if (totalRow) tbody.appendChild(totalRow);
            
            table.dataset.sortColumn = columnIndex;
            table.dataset.sortOrder = isAscending ? 'desc' : 'asc';
        }

        // 處理有合併儲存格的樞紐分析表排序
        function sortPivotTableWithRowspan(table, columnIndex) {
            const tbody = table.querySelector('tbody');
            const allRows = Array.from(tbody.querySelectorAll('tr'));
            
            // 識別總計行
            const totalRow = allRows.find(row => row.classList.contains('total-row'));
            const rowsWithoutTotal = allRows.filter(row => !row.classList.contains('total-row'));
            
            // 建立分組結構
            const groups = [];
            let currentGroup = null;
            
            rowsWithoutTotal.forEach(row => {
                const firstCell = row.cells[0];
                if (firstCell && firstCell.rowSpan > 1) {
                    // 新的分組開始
                    currentGroup = {
                        headerCell: firstCell,
                        rows: [row],
                        rowspan: firstCell.rowSpan
                    };
                    groups.push(currentGroup);
                } else if (currentGroup && currentGroup.rows.length < currentGroup.rowspan) {
                    // 繼續當前分組
                    currentGroup.rows.push(row);
                } else if (row.classList.contains('subtotal-row')) {
                    // 小計行
                    if (currentGroup) {
                        currentGroup.rows.push(row);
                    }
                }
            });
            
            const isAscending = table.dataset.sortColumn == columnIndex && 
                            table.dataset.sortOrder === 'asc';
            
            // 對每個分組內的數據行排序（不包括小計行）
            groups.forEach(group => {
                const subtotalRow = group.rows[group.rows.length - 1];
                const dataRows = group.rows.slice(0, -1);
                
                dataRows.sort((a, b) => {
                    const aText = a.cells[columnIndex - 1]?.textContent.trim() || '';  // 注意：因為第一個儲存格被合併，索引要調整
                    const bText = b.cells[columnIndex - 1]?.textContent.trim() || '';
                    
                    const aNum = parseFloat(aText.replace(/[^0-9.-]/g, ''));
                    const bNum = parseFloat(bText.replace(/[^0-9.-]/g, ''));
                    
                    if (!isNaN(aNum) && !isNaN(bNum)) {
                        return isAscending ? bNum - aNum : aNum - bNum;
                    }
                    
                    return isAscending ? 
                        bText.localeCompare(aText) : 
                        aText.localeCompare(bText);
                });
                
                // 更新分組內的行順序
                group.rows = [...dataRows, subtotalRow];
            });
            
            // 重建表格
            tbody.innerHTML = '';
            groups.forEach(group => {
                group.rows.forEach((row, index) => {
                    if (index === 0) {
                        // 重新添加合併的儲存格
                        row.insertBefore(group.headerCell, row.firstChild);
                    }
                    tbody.appendChild(row);
                });
            });
            
            // 最後添加總計行
            if (totalRow) {
                tbody.appendChild(totalRow);
            }
            
            table.dataset.sortColumn = columnIndex;
            table.dataset.sortOrder = isAscending ? 'desc' : 'asc';
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
            addPivotTableSorting();  // 添加這一行

            document.getElementById('pivotTable').innerHTML = pivotHtml;
            
            // 綁定點擊事件
            setTimeout(() => {
                const pivotTable = document.querySelector('#pivotTable table');
                if (pivotTable) {
                    const headers = pivotTable.querySelectorAll('thead tr th');
                    
                    // 檢查是否有合併儲存格
                    const tbody = pivotTable.querySelector('tbody');
                    const hasRowspan = Array.from(tbody.querySelectorAll('tr')).some(row => {
                        return Array.from(row.cells).some(cell => cell.rowSpan > 1);
                    });
                    
                    headers.forEach((header, index) => {
                        header.style.cursor = 'pointer';
                        
                        // 添加排序指示器（如果還沒有）
                        if (!header.querySelector('.pivot-sort-indicator')) {
                            header.style.position = 'relative';
                            header.innerHTML += '<span class="pivot-sort-indicator"></span>';
                        }
                        
                        header.onclick = function(e) {
                            e.preventDefault();
                            
                            if (index === 0 && hasRowspan) {
                                // 第一欄且有合併儲存格，使用特殊處理
                                sortPivotTableByFirstColumn(this);
                            } else {
                                // 其他情況使用通用排序
                                sortPivotColumn(this, index);
                            }
                        };
                    });
                }
            }, 100);       
        }
        
        // 依問題集的樞紐分析
        function createPivotByProblemSet(data) {
            const pivotData = {};
            let totals = { ANR: 0, Tombstone: 0, Total: 0 };
            
            data.forEach(row => {
                const ps = row['問題 set'] || row['問題set'] || row['Problem set'] || row['problem set'] || '未分類';
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
            
            let html = '<table class="table table-bordered" style="table-layout: fixed; width: 100%;">';
            html += '<colgroup>';
            html += '<col style="width: 12%;">';
            html += '<col style="width: 43%;">';
            html += '<col style="width: 15%;">';
            html += '<col style="width: 15%;">';
            html += '<col style="width: 15%;">';
            html += '</colgroup>';
            html += '<thead><tr>';
            html += '<th style="position: relative;">問題集<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="position: relative;">程序<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">ANR<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">Tombstone<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">總計<span class="pivot-sort-indicator"></span></th>';
            html += '</tr></thead>';
            html += '<tbody>';
            
            Object.entries(pivotData).forEach(([problemSet, processes]) => {
                const psTotal = { ANR: 0, Tombstone: 0, Total: 0 };
                const processCount = Object.keys(processes).length;
                let firstRow = true;
                
                Object.entries(processes).forEach(([process, counts]) => {
                    html += '<tr>';
                    if (firstRow) {
                        html += `<td rowspan="${processCount + 1}" style="vertical-align: middle; font-weight: 600; background: #f8f9fa; border-right: 2px solid #e2e8f0;">${problemSet}</td>`;
                        firstRow = false;
                    }
                    html += `<td style="padding-left: 16px;">${process}</td>`;
                    html += `<td style="text-align: center !important;">${counts.ANR}</td>`;
                    html += `<td style="text-align: center !important;">${counts.Tombstone}</td>`;
                    html += `<td style="text-align: center !important; font-weight: 600;">${counts.Total}</td>`;
                    html += '</tr>';
                    
                    psTotal.ANR += counts.ANR;
                    psTotal.Tombstone += counts.Tombstone;
                    psTotal.Total += counts.Total;
                });
                
                // 小計行 - 重要：需要添加一個空的 td 來補齊欄位
                html += '<tr class="subtotal-row">';
                html += `<td style="display: none;"></td>`; // 隱藏的 td，用來對齊
                html += `<td style="font-weight: 700; padding-left: 16px; background: #f1f5f9;">小計</td>`;
                html += `<td style="text-align: center !important; font-weight: 700; background: #f1f5f9;">${psTotal.ANR}</td>`;
                html += `<td style="text-align: center !important; font-weight: 700; background: #f1f5f9;">${psTotal.Tombstone}</td>`;
                html += `<td style="text-align: center !important; font-weight: 700; background: #f1f5f9;">${psTotal.Total}</td>`;
                html += '</tr>';
            });
            
            html += '<tr class="total-row">';
            html += '<td colspan="2" style="text-align: center !important; font-weight: 700; background: #334155; color: white;">總計</td>';
            html += `<td style="text-align: center !important; background: #334155; color: white;">${totals.ANR}</td>`;
            html += `<td style="text-align: center !important; background: #334155; color: white;">${totals.Tombstone}</td>`;
            html += `<td style="text-align: center !important; background: #334155; color: white;">${totals.Total}</td>`;
            html += '</tr>';
            
            html += '</tbody></table>';
            return html;
        }

        // 處理問題集欄位（第一列）的排序
        function sortPivotTableByFirstColumn(th) {
            console.log('===== 開始排序第一列 =====');
            
            try {
                const table = th.closest('table');
                const tbody = table.querySelector('tbody');
                const allRows = Array.from(tbody.querySelectorAll('tr'));
                
                // 保存總計行
                const totalRow = tbody.querySelector('.total-row');
                
                // 建立分組
                const groups = [];
                let i = 0;
                
                while (i < allRows.length) {
                    const row = allRows[i];
                    
                    // 跳過總計行
                    if (row.classList.contains('total-row')) {
                        i++;
                        continue;
                    }
                    
                    const firstCell = row.cells[0];
                    
                    if (firstCell && firstCell.rowSpan > 1) {
                        // 這是一個分組的開始
                        const group = {
                            name: firstCell.textContent.trim(),
                            rows: [],
                            rowSpan: firstCell.rowSpan
                        };
                        
                        // 收集這個分組的所有行（包括第一行）
                        for (let j = 0; j < firstCell.rowSpan && i < allRows.length; j++) {
                            if (!allRows[i].classList.contains('total-row')) {
                                group.rows.push(allRows[i]);
                            }
                            i++;
                        }
                        
                        groups.push(group);
                        
                        console.log(`分組 "${group.name}": 包含 ${group.rows.length} 行`);
                    } else {
                        // 沒有 rowspan 的單獨行（不應該發生在正確的樞紐表中）
                        i++;
                    }
                }
                
                console.log(`總共 ${groups.length} 個分組`);
                
                // 排序
                const isAscending = th.dataset.sortOrder !== 'asc';
                groups.sort((a, b) => {
                    return isAscending ? 
                        a.name.localeCompare(b.name) : 
                        b.name.localeCompare(a.name);
                });
                
                console.log('排序後順序:', groups.map(g => g.name).join(', '));
                
                // 重建表格
                tbody.innerHTML = '';
                
                // 按順序添加所有分組
                groups.forEach(group => {
                    group.rows.forEach(row => {
                        tbody.appendChild(row);
                    });
                });
                
                // 最後添加總計行
                if (totalRow) {
                    tbody.appendChild(totalRow);
                }
                
                // 更新排序狀態
                th.dataset.sortOrder = isAscending ? 'asc' : 'desc';
                
                // 更新排序指示器 - 這是缺少的部分！
                updatePivotSortIndicators(th, isAscending);
                
                console.log('===== 排序完成 =====');
                
            } catch (error) {
                console.error('排序時發生錯誤:', error);
                console.error(error.stack);
            }
        }

        // 依程序的樞紐分析
        function createPivotByProcess(data) {
            const pivotData = {};
            let totals = { ANR: 0, Tombstone: 0, Total: 0 };
            
            data.forEach(row => {
                if (!pivotData[row.Process]) {
                    pivotData[row.Process] = {};
                }
                const ps = row['問題 set'] || row['問題set'] || row['Problem set'] || row['problem set'] || '未分類';
                if (!pivotData[row.Process][ps]) {
                    pivotData[row.Process][ps] = { ANR: 0, Tombstone: 0, Total: 0 };
                }
                pivotData[row.Process][ps][row.Type]++;
                pivotData[row.Process][ps].Total++;
                totals[row.Type]++;
                totals.Total++;
            });
            
            let html = '<table class="table table-bordered" style="table-layout: fixed; width: 100%;">';
            html += '<colgroup>';
            html += '<col style="width: 30%;">';
            html += '<col style="width: 25%;">';
            html += '<col style="width: 15%;">';
            html += '<col style="width: 15%;">';
            html += '<col style="width: 15%;">';
            html += '</colgroup>';
            html += '<thead><tr>';
            html += '<th style="position: relative;">程序<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="position: relative;">問題集<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">ANR<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">Tombstone<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">總計<span class="pivot-sort-indicator"></span></th>';
            html += '</tr></thead>';
            html += '<tbody>';
            
            Object.entries(pivotData).forEach(([process, problemSets]) => {
                const processTotal = { ANR: 0, Tombstone: 0, Total: 0 };
                const psCount = Object.keys(problemSets).length;
                let firstRow = true;
                
                Object.entries(problemSets).forEach(([problemSet, counts]) => {
                    html += '<tr>';
                    if (firstRow) {
                        html += `<td rowspan="${psCount + 1}" style="vertical-align: middle; font-weight: 600;">${process}</td>`;
                        firstRow = false;
                    }
                    html += `<td style="padding-left: 16px;">${problemSet}</td>`;
                    html += `<td style="text-align: center !important;">${counts.ANR}</td>`;
                    html += `<td style="text-align: center !important;">${counts.Tombstone}</td>`;
                    html += `<td style="text-align: center !important; font-weight: 600;">${counts.Total}</td>`;
                    html += '</tr>';
                    
                    processTotal.ANR += counts.ANR;
                    processTotal.Tombstone += counts.Tombstone;
                    processTotal.Total += counts.Total;
                });
                
                html += '<tr class="subtotal-row">';
                html += `<td style="font-weight: 700; padding-left: 16px;">小計</td>`;
                html += `<td style="text-align: center !important; font-weight: 700;">${processTotal.ANR}</td>`;
                html += `<td style="text-align: center !important; font-weight: 700;">${processTotal.Tombstone}</td>`;
                html += `<td style="text-align: center !important; font-weight: 700;">${processTotal.Total}</td>`;
                html += '</tr>';
            });
            
            html += '<tr class="total-row">';
            html += '<td colspan="2" style="text-align: center !important; font-weight: 700;">總計</td>';
            html += `<td style="text-align: center !important;">${totals.ANR}</td>`;
            html += `<td style="text-align: center !important;">${totals.Tombstone}</td>`;
            html += `<td style="text-align: center !important;">${totals.Total}</td>`;
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
                const ps = row['問題 set'] || row['問題set'] || row['Problem set'] || row['problem set'] || '未分類';
                if (!pivotData[row.Type][ps]) {
                    pivotData[row.Type][ps] = 0;
                }
                pivotData[row.Type][ps]++;
                totals.Total++;
            });
            
            let html = '<table class="table table-bordered" style="table-layout: fixed; width: 100%;">';
            html += '<colgroup>';
            html += '<col style="width: 20%;">';
            html += '<col style="width: 60%;">';
            html += '<col style="width: 20%;">';
            html += '</colgroup>';
            html += '<thead><tr>';
            html += '<th style="position: relative;">類型<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="position: relative;">問題集<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">數量<span class="pivot-sort-indicator"></span></th>';
            html += '</tr></thead>';
            html += '<tbody>';
            
            Object.entries(pivotData).forEach(([type, problemSets]) => {
                const typeTotal = Object.values(problemSets).reduce((sum, count) => sum + count, 0);
                const psCount = Object.keys(problemSets).length;
                let firstRow = true;
                
                Object.entries(problemSets).forEach(([problemSet, count]) => {
                    html += '<tr>';
                    if (firstRow) {
                        html += `<td rowspan="${psCount + 1}" style="vertical-align: middle; font-weight: 600;">${type}</td>`;
                        firstRow = false;
                    }
                    html += `<td style="padding-left: 16px;">${problemSet}</td>`;
                    html += `<td style="text-align: center !important;">${count}</td>`;
                    html += '</tr>';
                });
                
                html += '<tr class="subtotal-row">';
                html += `<td style="font-weight: 700; padding-left: 16px;">小計</td>`;
                html += `<td style="text-align: center !important; font-weight: 700;">${typeTotal}</td>`;
                html += '</tr>';
            });
            
            html += '<tr class="total-row">';
            html += '<td colspan="2" style="text-align: center !important; font-weight: 700;">總計</td>';
            html += `<td style="text-align: center !important; font-weight: 700;">${totals.Total}</td>`;
            html += '</tr>';
            
            html += '</tbody></table>';
            return html;
        }
        
        // 修正 sortPivotColumn 函數
        function sortPivotColumn(th, columnIndex) {
            console.log(`排序第 ${columnIndex} 欄`);
            
            const table = th.closest('table');
            const tbody = table.querySelector('tbody');
            
            // 先檢查是否有合併儲存格
            const hasRowspan = Array.from(tbody.querySelectorAll('tr')).some(row => {
                return Array.from(row.cells).some(cell => cell.rowSpan > 1);
            });
            
            // 如果沒有合併儲存格，使用簡單排序
            if (!hasRowspan) {
                console.log('沒有合併儲存格，使用簡單排序');
                sortSimpleTable(th, columnIndex);
                return;
            }
            
            // 以下是處理有合併儲存格的邏輯
            const allRows = Array.from(tbody.querySelectorAll('tr'));
            const totalRow = tbody.querySelector('.total-row');
            
            // 建立分組
            const groups = [];
            let i = 0;
            
            while (i < allRows.length) {
                const row = allRows[i];
                
                if (row.classList.contains('total-row')) {
                    i++;
                    continue;
                }
                
                const firstCell = row.cells[0];
                
                if (firstCell && firstCell.rowSpan > 1) {
                    const group = {
                        name: firstCell.textContent.trim(),
                        rows: [],
                        rowSpan: firstCell.rowSpan,
                        // 保存第一行的排序值（用於排序整個分組）
                        sortValue: row.cells[columnIndex]?.textContent.trim() || ''
                    };
                    
                    // 收集這個分組的所有行
                    for (let j = 0; j < firstCell.rowSpan && i < allRows.length; j++) {
                        if (!allRows[i].classList.contains('total-row')) {
                            group.rows.push(allRows[i]);
                        }
                        i++;
                    }
                    
                    groups.push(group);
                } else {
                    i++;
                }
            }
            
            const isAscending = th.dataset.sortOrder !== 'asc';
            
            // 根據指定欄位排序整個分組
            groups.sort((a, b) => {
                const aValue = a.sortValue;
                const bValue = b.sortValue;
                
                const aNum = parseFloat(aValue.replace(/[^0-9.-]/g, ''));
                const bNum = parseFloat(bValue.replace(/[^0-9.-]/g, ''));
                
                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return isAscending ? aNum - bNum : bNum - aNum;
                }
                
                return isAscending ? 
                    aValue.localeCompare(bValue) : 
                    bValue.localeCompare(aValue);
            });
            
            // 重建表格
            tbody.innerHTML = '';
            
            groups.forEach(group => {
                group.rows.forEach(row => {
                    tbody.appendChild(row);
                });
            });
            
            if (totalRow) {
                tbody.appendChild(totalRow);
            }
            
            th.dataset.sortOrder = isAscending ? 'asc' : 'desc';
            updatePivotSortIndicators(th, isAscending);
        }

        // 更新樞紐分析表的排序指示器
        function updatePivotSortIndicators(currentTh, isAscending) {
            // 清除所有指示器
            const allIndicators = currentTh.closest('thead').querySelectorAll('.pivot-sort-indicator');
            allIndicators.forEach(indicator => {
                indicator.textContent = '';
            });
            
            // 設置當前欄位的指示器
            const indicator = currentTh.querySelector('.pivot-sort-indicator');
            if (indicator) {
                indicator.textContent = isAscending ? '▲' : '▼';
            }
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
            
            let html = '<table class="table table-bordered" style="table-layout: fixed; width: 100%;">';
            html += '<colgroup>';
            html += '<col style="width: 25%;">';
            html += '<col style="width: 25%;">';
            html += '<col style="width: 25%;">';
            html += '<col style="width: 25%;">';
            html += '</colgroup>';
            html += '<thead><tr>';
            html += '<th style="position: relative;">日期<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">ANR<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">Tombstone<span class="pivot-sort-indicator"></span></th>';
            html += '<th style="text-align: center; position: relative;">總計<span class="pivot-sort-indicator"></span></th>';
            html += '</tr></thead>';
            html += '<tbody>';
            
            Object.entries(pivotData).sort().forEach(([date, counts]) => {
                html += '<tr>';
                html += `<td style="font-weight: 600;">${date}</td>`;
                html += `<td style="text-align: center !important;">${counts.ANR}</td>`;
                html += `<td style="text-align: center !important;">${counts.Tombstone}</td>`;
                html += `<td style="text-align: center !important; font-weight: 600;">${counts.Total}</td>`;
                html += '</tr>';
            });
            
            html += '<tr class="total-row">';
            html += '<td style="text-align: center !important; font-weight: 700;">總計</td>';
            html += `<td style="text-align: center !important;">${totals.ANR}</td>`;
            html += `<td style="text-align: center !important;">${totals.Tombstone}</td>`;
            html += `<td style="text-align: center !important;">${totals.Total}</td>`;
            html += '</tr>';
            
            html += '</tbody></table>';
            return html;
        }
        
        // 匯出 HTML
        function exportToHTML() {
            // 創建一個新的 HTML 文檔
            const newDoc = document.implementation.createHTMLDocument('Excel 分析報告');
            
            // 複製整個 HTML 內容
            newDoc.documentElement.innerHTML = document.documentElement.innerHTML;
            
            // 確保所有的資料都被保存
            const scriptTag = newDoc.createElement('script');
            scriptTag.textContent = `
                // 保存原始資料
                let rawData = ${JSON.stringify(rawData)};
                let filteredData = [...rawData];
                let currentPage = 1;
                const itemsPerPage = 10;
                let sortColumn = 'SN';
                let sortOrder = 'asc';
                
                // 保存 Excel Base64 資料
                const excelDataBase64 = "${excelDataBase64}";
            `;
            newDoc.body.appendChild(scriptTag);
            
            // 生成 HTML 字符串
            const htmlContent = '<!DOCTYPE html>\\n' + newDoc.documentElement.outerHTML;
            
            // 創建 Blob 並下載
            const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            
            // 使用正確的檔案名稱
            const filename = '{{ filename }}';
            const cleanFilename = filename.replace('.xlsx', '').replace('.xls', '');
            a.download = cleanFilename + '_report_' + new Date().toISOString().slice(0, 10) + '.html';
            
            a.click();
            window.URL.revokeObjectURL(url);
        }

        // 處理簡單表格（沒有合併儲存格）的排序
        function sortSimpleTable(th, columnIndex) {
            console.log('排序簡單表格，第', columnIndex, '欄');
            
            const table = th.closest('table');
            const tbody = table.querySelector('tbody');
            const allRows = Array.from(tbody.querySelectorAll('tr'));
            
            // 分離總計行和數據行
            const totalRow = allRows.find(row => row.classList.contains('total-row'));
            const dataRows = allRows.filter(row => !row.classList.contains('total-row'));
            
            console.log('數據行數:', dataRows.length);
            
            // 如果沒有數據行或只有一行，不需要排序
            if (dataRows.length <= 1) {
                console.log('只有一行或沒有數據，不需要排序');
                // 但仍然要更新排序狀態和圖標
                const isAscending = th.dataset.sortOrder !== 'asc';
                th.dataset.sortOrder = isAscending ? 'asc' : 'desc';
                updatePivotSortIndicators(th, isAscending);
                return;
            }
            
            const isAscending = th.dataset.sortOrder !== 'asc';
            
            // 排序數據行
            dataRows.sort((a, b) => {
                const aText = a.cells[columnIndex]?.textContent.trim() || '';
                const bText = b.cells[columnIndex]?.textContent.trim() || '';
                
                // 嘗試轉換為數字
                const aNum = parseFloat(aText.replace(/[^0-9.-]/g, ''));
                const bNum = parseFloat(bText.replace(/[^0-9.-]/g, ''));
                
                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return isAscending ? aNum - bNum : bNum - aNum;
                }
                
                // 日期比較
                const aDate = new Date(aText);
                const bDate = new Date(bText);
                if (!isNaN(aDate) && !isNaN(bDate)) {
                    return isAscending ? aDate - bDate : bDate - aDate;
                }
                
                // 文字比較
                return isAscending ? 
                    aText.localeCompare(bText) : 
                    bText.localeCompare(aText);
            });
            
            // 重建表格
            tbody.innerHTML = '';
            dataRows.forEach(row => tbody.appendChild(row));
            if (totalRow) tbody.appendChild(totalRow);
            
            // 更新排序狀態和圖標
            th.dataset.sortOrder = isAscending ? 'asc' : 'desc';
            updatePivotSortIndicators(th, isAscending);
        }

    </script>
</body>
</html>
'''

@excel_report_bp.route('/excel-report/<report_id>')
def excel_report(report_id):
    """顯示 Excel 分析報告"""
    try:
        # 從快取獲取檔案資訊
        try:
            from routes.main_page import analysis_cache
        except ImportError:
            from routes.shared_cache import analysis_cache
        
        file_info = analysis_cache.get(f"excel_report_{report_id}")
        if not file_info:
            return "報告已過期或不存在", 404
        
        excel_path = file_info['excel_path']
        is_temp = file_info.get('is_temp', False)
        original_filenames = file_info.get('original_filenames', [])
        original_paths = file_info.get('original_paths', [])
        is_merged = file_info.get('is_merged', False)
        file_count = file_info.get('file_count', 1)
        
        # 讀取 Excel 檔案
        try:
            df = pd.read_excel(excel_path)
            
            # 準備顯示的檔案名稱和路徑
            if is_merged and len(original_filenames) > 1:
                # 多檔案合併的情況
                display_filename = f"合併 {file_count} 個檔案"
                # 使用列表形式傳遞檔案名稱
                filename_list = original_filenames
                # 使用列表形式傳遞路徑
                path_list = original_paths
            else:
                # 單一檔案
                display_filename = original_filenames[0] if original_filenames else "未知檔案"
                filename_list = [display_filename]
                path_list = original_paths if original_paths else ["未知路徑"]
            
            # 轉換為適合前端顯示的格式
            data = df.to_dict('records')
            
            # 渲染模板
            return render_template_string(
                EXCEL_REPORT_TEMPLATE,
                filename=display_filename,
                filepath='',  # 不再使用這個參數
                filename_list=filename_list,  # 新增：檔案名稱列表
                path_list=path_list,  # 新增：路徑列表
                load_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                data=data,
                excel_data_base64='',
                file_count=file_count,
                is_merged=is_merged
            )
            
        except Exception as e:
            return f"讀取 Excel 檔案時發生錯誤: {str(e)}", 500
        finally:
            pass
            
    except Exception as e:
        return f"載入報告時發生錯誤: {str(e)}", 500
        
