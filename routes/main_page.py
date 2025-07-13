from flask import Blueprint, request, jsonify, url_for
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
from routes.grep_analyzer import AndroidLogAnalyzer, LimitedCache
import shutil

# 創建一個藍圖實例
main_page_bp = Blueprint('main_page_bp', __name__)

# Global storage for analysis results
analysis_cache = LimitedCache(max_size=100, max_age_hours=24)
analyzer = AndroidLogAnalyzer()
analysis_lock = threading.Lock()

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
    /* ===== 全域重置和基礎樣式 ===== */
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
        padding-bottom: 200px;
        flex: 1;
    }

    /* ===== 頁首樣式 ===== */
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

    /* ===== 導航欄樣式 ===== */
    .nav-bar {
        position: fixed;
        right: 90px;
        bottom: 90px;
        background: white;
        border: 1px solid #e1e4e8;
        border-radius: 12px;
        padding: 15px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        z-index: 100;
        max-width: 200px;
        transform: translateX(300px);
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
        flex-direction: column;
        gap: 8px;
    }

    .nav-link {
        background: #f0f0f0;
        color: #667eea;
        padding: 10px 14px;
        border-radius: 8px;
        text-decoration: none;
        font-size: 13px;
        transition: all 0.2s;
        white-space: nowrap;
        text-align: center;
    }

    .nav-link:hover {
        background: #667eea;
        color: white;
        transform: translateY(-2px);
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    /* ===== 浮動按鈕樣式 ===== */
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
        opacity: 0;
        visibility: hidden;
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

    .nav-toggle-btn.active {
        background: #5a67d8;
        transform: rotate(180deg);
    }

    /* ===== 動畫效果 ===== */
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

    @keyframes dots {
        0%, 20% { content: ''; }
        40% { content: '.'; }
        60% { content: '..'; }
        80%, 100% { content: '...'; }
    }

    .nav-bar.animating-in {
        animation: slideIn 0.3s ease-out forwards;
    }

    .nav-bar.animating-out {
        animation: slideOut 0.3s ease-in forwards;
    }

    /* ===== 控制面板樣式 ===== */
    .control-panel {
        background-color: white;
        padding: 25px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin-bottom: 30px;
    }

    .input-group {
        margin-bottom: 20px;
        position: relative;
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

    /* ===== 路徑自動完成 ===== */
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

    /* ===== 按鈕樣式 ===== */
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

    /* ===== 載入和狀態訊息 ===== */
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
        padding: 10px 15px;
        background-color: #f0fff4;
        border: 1px solid #9ae6b4;
        border-radius: 8px;
        margin-bottom: 15px;
        line-height: 1.4;
    }

    .info {
        color: #3182ce;
        padding: 15px;
        background-color: #ebf8ff;
        border: 1px solid #90cdf4;
        border-radius: 8px;
        margin-bottom: 20px;
    }

    /* ===== 統計卡片 ===== */
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

    .stat-card.highlight h3,
    .stat-card.highlight p {
        color: white;
    }

    .stat-card.highlight p {
        color: rgba(255, 255, 255, 0.9);
    }

    /* ===== 圖表樣式 ===== */
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

    /* ===== 區塊樣式 ===== */
    .section-container,
    .logs-table {
        position: relative;
        margin-bottom: 30px;
        z-index: 1;
    }

    .section-container > div:first-child,
    .logs-table {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
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

    .section-container.collapsed .table-header {
        border-radius: 12px;
        margin-bottom: 0;
    }

    /* ===== 區塊標題 ===== */
    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 15px;
        padding-right: 60px;
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

    /* ===== 表格標題 ===== */
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
        padding: 0 !important;
        margin: 0;
        position: relative;
    }

    .table-header h3 {
        color: white;
        margin: 0;
        font-size: 1.2rem;
        padding-right: 150px;
    }

    .table-header .top-link {
        position: absolute;
        right: 60px;
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
        content: "x";
        display: block;
    }

    .section-container.collapsed .section-toggle .toggle-icon::before {
        content: "+";
    }

    .logs-table .section-toggle {
        top: 15px;
        right: 15px;
        transform: none;
    }

    /* ===== Tooltip 樣式 ===== */
    .section-toggle[data-tooltip]::before {
        content: attr(data-tooltip);
        position: absolute;
        left: calc(100% + 15px);
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
        left: calc(100% + 7px);
        top: 50%;
        transform: translateY(-50%);
        width: 0;
        height: 0;
        border-style: solid;
        border-width: 5px 8px 5px 0;
        border-color: transparent rgba(0, 0, 0, 0.9) transparent transparent;
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

    /* ===== 表格樣式 ===== */
    .summary-table,
    .logs-table {
        background-color: white;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        overflow: hidden;
        margin-bottom: 30px;
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

    /* ===== 分頁樣式 ===== */
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

    /* ===== 表格內容樣式 ===== */
    .table-wrapper,
    .logs-table-content {
        overflow-x: auto;
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
        padding: 12px;
        text-align: left;
        border-bottom: 2px solid #e1e4e8;
        position: sticky;
        top: 0;
        white-space: nowrap;
    }

    td {
        padding: 12px;
        border-bottom: 1px solid #e1e4e8;
    }

    tr:nth-child(even) {
        background-color: #f8f9fa;
    }

    tr:hover {
        background-color: #e8eaf6;
    }

    .table-highlight {
        background-color: #fff59d !important;
        color: #000;
        font-weight: 600;
    }

    /* ===== 表格內容特定樣式 ===== */
    .rank-number {
        font-weight: bold;
        color: #667eea;
        text-align: center;
    }

    .process-name {
        font-weight: 600;
        color: #667eea;
    }

    .process-name div {
        padding: 2px 0;
    }

    .process-name div:not(:last-child) {
        border-bottom: 1px solid #f0f0f0;
    }

    .line-number {
        font-weight: bold;
        color: #667eea;
        text-align: center;
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

    .filesize {
        color: #666;
        font-size: 0.9em;
    }

    /* ===== 排序功能 ===== */
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

    /* ===== 標籤樣式 ===== */
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

    .no-grep-badge {
        background: #f56565;
    }

    /* ===== 其他元素樣式 ===== */
    #results {
        display: none;
    }

    .filter-input {
        width: 300px;
        padding: 8px 12px;
        border: 2px solid rgba(255, 255, 255, 0.8);
        border-radius: 8px;
        font-size: 14px;
        background-color: rgba(255, 255, 255, 0.95);
    }

    ul {
        list-style: none;
        padding: 0;
        margin-left: 40px;
    }

    .icon {
        padding: 2px;
        margin: 2px;
    }

    #globalToggleIcon,
    .nav-icon {
        font-size: 20px;
        line-height: 1;
    }

    /* ===== 頁尾樣式 ===== */
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

    /* Analysis Result Button */
    .analysis-result-btn {
        position: fixed;
        bottom: 30px;
        right: 90px;  /* 在返回頂部按鈕左邊 */
        background: #28a745;  /* 綠色背景 */
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
        box-shadow: 0 4px 12px rgba(40, 167, 69, 0.4);
        text-decoration: none;
    }

    .analysis-result-btn.show {
        opacity: 1;
        visibility: visible;
    }

    .analysis-result-btn:hover {
        background: #218838;
        transform: translateY(-5px);
        box-shadow: 0 6px 16px rgba(40, 167, 69, 0.6);
        color: white;
        text-decoration: none;
    }

    /* 當有多個按鈕時的排列 */
    @media (max-width: 768px) {
        .analysis-result-btn {
            right: 30px;
            bottom: 90px;  /* 在返回頂部按鈕上方 */
        }
        
        .nav-toggle-btn {
            bottom: 150px;  /* 再往上移 */
        }
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
        <!-- Analysis Result Button -->
        <a class="analysis-result-btn" id="analysisResultBtn" href="" target="_blank" title="查看詳細分析報告">📊</a>        
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
                    <li><span class="icon">📜</span> <strong>彈性解析：</strong> ANR 檔案搜尋 "Subject:"，Tombstone 檔案搜尋 "Cmd line:" 或 "Cmdline:"</li>
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
        const itemsPerPage = 10;
        
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
        
        let analysisIndexPath = null;  // 儲存分析結果的 index.html 路徑

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
                const analysisResultBtn = document.getElementById('analysisResultBtn');
                
                if (window.pageYOffset > 300) {
                    backToTopBtn.classList.add('show');
                    if (document.getElementById('results').style.display !== 'none') {
                        navToggleBtn.classList.add('show');
                        // 如果有分析結果，顯示分析結果按鈕
                        if (window.vpAnalyzeSuccess && analysisIndexPath) {
                            analysisResultBtn.classList.add('show');
                        }
                    }
                } else {
                    backToTopBtn.classList.remove('show');
                    navToggleBtn.classList.remove('show');
                    analysisResultBtn.classList.remove('show');
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
            text = String(text);
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
            
            document.getElementById('analysisResultBtn').classList.remove('show');
            analysisIndexPath = null;            
            
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
                
                // === 新增：保存分析輸出路徑和狀態 ===
                window.vpAnalyzeOutputPath = data.vp_analyze_output_path;
                window.vpAnalyzeSuccess = data.vp_analyze_success;

                // 設定分析結果按鈕
                if (data.vp_analyze_success && data.vp_analyze_output_path) {
                    // 將路徑轉換為 file:// 格式
                    let filePath = data.vp_analyze_output_path + '/index.html';
                    
                    // 新程式碼：使用新的路由
                    analysisIndexPath = '/view-analysis-report?path=' + encodeURIComponent(data.vp_analyze_output_path);
                    const analysisBtn = document.getElementById('analysisResultBtn');
                    analysisBtn.href = analysisIndexPath;
                }
                                
                console.log('vp_analyze 執行結果:', {
                    success: data.vp_analyze_success,
                    outputPath: data.vp_analyze_output_path,
                    error: data.vp_analyze_error
                });
                
                // Update UI
                updateResults(data);
                
                // Enable export buttons
                document.getElementById('exportJsonBtn').disabled = false;
                document.getElementById('exportCsvBtn').disabled = false;
                document.getElementById('exportHtmlBtn').style.display = 'block';
                
                let message = `分析完成！共掃描 ${data.total_files} 個檔案，找到 ${data.anr_subject_count} 個包含 ANR 的檔案，找到 ${data.files_with_cmdline - data.anr_subject_count} 個包含 Tombstone 的檔案`;
                message += `<br>分析耗時: ${data.analysis_time} 秒`;
                if (data.used_grep) {
                    message += '<span class="grep-badge">使用 grep 加速</span>';
                } else {
                    message += '<span class="grep-badge no-grep-badge">未使用 grep</span>';
                }
                
                // 新增 vp_analyze 狀態訊息
                if (data.vp_analyze_success) {
                    message += '<br><span style="color: #28a745;">✓ 詳細分析報告已生成</span>';
                } else if (data.vp_analyze_error) {
                    message += `<br><span style="color: #dc3545;">✗ 詳細分析失敗: ${data.vp_analyze_error}</span>`;
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
                    <h3>${data.anr_subject_count || 0}</h3>
                    <p>ANR (Grep Subject)</p>
                </div>
                <div class="stat-card highlight">
                    <h3>${data.files_with_cmdline - data.anr_subject_count || 0}</h3>
                    <p>Tombstone (Grep Cmdline)</p>
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
            
            // Update charts - 修正這裡，使用 type_process_summary 來確保排序一致
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
                        
                        // 對於 logs，每一筆就是一個記錄，所以總次數等於筆數
                        countElement.innerHTML = `找到 <span style="color: #e53e3e;">${filteredLogs.length}</span> 筆記錄`;
                        countElement.style.display = 'inline';
                    } catch (error) {
                        // Invalid regex
                        countElement.innerHTML = `<span style="color: #e53e3e;">無效的正則表達式</span>`;
                        countElement.style.display = 'inline';
                        filteredLogs = [];
                    }
                }
                logsPage = 1; // Reset to first page
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
                filesPage = 1; // Reset to first page
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
                    
                    // === 新增：建立分析報告連結 ===
                    let analyzeReportLink = '';
                    if (window.vpAnalyzeOutputPath && window.vpAnalyzeSuccess) {
                        // 取得基礎路徑（使用者輸入的路徑）
                        const basePath = document.getElementById('pathInput').value;
                        const filePath = log.file || '';
                        
                        // 從檔案路徑中提取相對路徑
                        if (filePath.startsWith(basePath)) {
                            // 取得從基礎路徑之後的相對路徑
                            let relativePath = filePath.substring(basePath.length);
                            // 移除開頭的斜線
                            if (relativePath.startsWith('/')) {
                                relativePath = relativePath.substring(1);
                            }
                            
                            // 建立分析報告路徑
                            const analyzedFilePath = window.vpAnalyzeOutputPath + '/' + relativePath + '.analyzed.txt';
                            analyzeReportLink = ` <a href="/view-file?path=${encodeURIComponent(analyzedFilePath)}" target="_blank" class="file-link" style="color: #28a745; font-size: 0.9em;">(分析報告)</a>`;
                        }
                    }
                    
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
                        <td><a href="${fileLink}" target="_blank" class="file-link">${highlightText(log.filename, searchTerm, useRegex)}</a>${analyzeReportLink}</td>
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
                    
                    // === 新增：建立分析報告連結 ===
                    let analyzeReportLink = '';
                    if (window.vpAnalyzeOutputPath && window.vpAnalyzeSuccess) {
                        // 取得基礎路徑（使用者輸入的路徑）
                        const basePath = document.getElementById('pathInput').value;
                        const filePath = file.filepath || '';
                        
                        // 從檔案路徑中提取相對路徑
                        if (filePath.startsWith(basePath)) {
                            // 取得從基礎路徑之後的相對路徑
                            let relativePath = filePath.substring(basePath.length);
                            // 移除開頭的斜線
                            if (relativePath.startsWith('/')) {
                                relativePath = relativePath.substring(1);
                            }
                            
                            // 建立分析報告路徑
                            const analyzedFilePath = window.vpAnalyzeOutputPath + '/' + relativePath + '.analyzed.txt';
                            analyzeReportLink = ` <a href="/view-file?path=${encodeURIComponent(analyzedFilePath)}" target="_blank" class="file-link" style="color: #28a745; font-size: 0.9em;">(分析報告)</a>`;
                        }
                    }
                    
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
                        <td><a href="${fileLink}" target="_blank" class="file-link">${highlightText(file.filename, searchTerm, useRegex)}</a>${analyzeReportLink}</td>
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
            text = String(text);
            div.textContent = text;
            return div.innerHTML;
        }
        
    </script>
</body>
</html>
'''

@main_page_bp.route('/suggest-path', methods=['POST'])
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
        
@main_page_bp.route('/server-info')
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
    
@main_page_bp.route('/analyze', methods=['POST'])
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
                      
        # === 新增：執行 vp_analyze_logs.py ===
        # 取得路徑的最後一個資料夾名稱
        last_folder_name = os.path.basename(path.rstrip(os.sep))
        # 建立輸出目錄名稱
        output_dir_name = f"{last_folder_name}_anr_tombstones_analyze"
        output_path = os.path.join(path, output_dir_name)

        # 檢查輸出目錄是否已存在，如果存在則刪除
        if os.path.exists(output_path):
            print(f"發現已存在的輸出目錄: {output_path}")
            try:
                shutil.rmtree(output_path)
                print(f"已刪除舊的輸出目錄: {output_path}")
            except Exception as e:
                print(f"刪除輸出目錄失敗: {e}")
                # 可以選擇是否要繼續執行或返回錯誤
                vp_analyze_error = f"無法刪除現有的輸出目錄: {output_path}, 錯誤: {str(e)}"
                # 如果刪除失敗，您可以選擇：
                # 選項1: 繼續執行（可能會有問題）
                # 選項2: 停止執行並返回錯誤（建議）
                vp_analyze_success = False
        else:
            print(f"輸出目錄不存在，將建立新的: {output_path}")

        # 執行分析 - 這裡是關鍵，確保 results 被定義
        results = analyzer.analyze_logs(path)
            
        # 執行 vp_analyze_logs.py
        vp_analyze_success = False
        vp_analyze_error = None
        
        try:
            # 確保 vp_analyze_logs.py 在同一目錄
            vp_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vp_analyze_logs.py')
            
            if os.path.exists(vp_script_path):
                print(f"找到 vp_analyze_logs.py: {vp_script_path}")
                print(f"執行命令: python3.12 {vp_script_path} {path} {output_path}")
                
                # 使用 python3.12 執行 vp_analyze_logs.py
                cmd = ['python3.12', vp_script_path, path, output_path]
                
                # 執行命令
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    timeout=300,
                    cwd=os.path.dirname(vp_script_path)  # 設定工作目錄
                )
                
                print(f"Return code: {result.returncode}")
                print(f"STDOUT: {result.stdout}")
                print(f"STDERR: {result.stderr}")
                
                if result.returncode == 0:
                    vp_analyze_success = True
                    print("vp_analyze_logs.py 執行成功")
                    print(f"分析結果輸出到: {output_path}")
                    
                    # 檢查輸出目錄是否存在
                    if os.path.exists(output_path):
                        print(f"確認輸出目錄已建立: {output_path}")
                        # 列出目錄內容
                        try:
                            files = os.listdir(output_path)
                            print(f"輸出目錄包含 {len(files)} 個檔案")
                        except:
                            pass
                    else:
                        print("警告：輸出目錄不存在")
                        vp_analyze_success = False
                        vp_analyze_error = "輸出目錄未建立"
                else:
                    vp_analyze_error = f"vp_analyze_logs.py 執行失敗 (return code: {result.returncode})\nSTDERR: {result.stderr}\nSTDOUT: {result.stdout}"
                    print(vp_analyze_error)
            else:
                vp_analyze_error = f"找不到 vp_analyze_logs.py: {vp_script_path}"
                print(vp_analyze_error)
                
        except subprocess.TimeoutExpired:
            vp_analyze_error = "vp_analyze_logs.py 執行超時 (超過 300 秒)"
            print(vp_analyze_error)
        except FileNotFoundError:
            vp_analyze_error = "找不到 python3.12 命令，請確認已安裝 Python 3.12"
            print(vp_analyze_error)
        except Exception as e:
            vp_analyze_error = f"執行 vp_analyze_logs.py 時發生錯誤: {str(e)}"
            print(vp_analyze_error)
            import traceback
            traceback.print_exc()
        
        # 將分析輸出路徑加入結果中
        results['vp_analyze_output_path'] = output_path if vp_analyze_success else None
        results['vp_analyze_success'] = vp_analyze_success
        results['vp_analyze_error'] = vp_analyze_error
        
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
            'zip_files_extracted': results.get('zip_files_extracted', 0),
            'anr_subject_count': results.get('anr_subject_count', 0),
            'vp_analyze_output_path': results.get('vp_analyze_output_path'),
            'vp_analyze_success': results.get('vp_analyze_success', False),
            'vp_analyze_error': results.get('vp_analyze_error')
        })
        
    except Exception as e:
        print(f"Error in analyze endpoint: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
        
@main_page_bp.route('/export/<format>/<analysis_id>')
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

@main_page_bp.route('/view-analysis-report')
def view_analysis_report():
    """查看 vp_analyze 生成的分析報告"""
    file_path = request.args.get('path')

    if not file_path:
        return """
        <html>
        <body style="font-family: Arial; padding: 20px;">
            <h2>錯誤：未提供檔案路徑</h2>
            <p>請從分析結果頁面點擊「查看詳細分析報告」按鈕。</p>
            <button onclick="window.history.back()">返回</button>
        </body>
        </html>
        """, 400
    
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
        # 如果是目錄，尋找 index.html
        index_path = os.path.join(file_path, 'index.html')
        if os.path.exists(index_path) and os.path.isfile(index_path):
            file_path = index_path
        else:
            return "Not a file", 400
    
    try:
        # 根據檔案類型返回適當的內容
        if file_path.endswith('.html'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 修改 HTML 中的相對路徑，使其通過我們的路由
            base_dir = os.path.dirname(file_path)
            
            # 替換相對路徑的連結
            # content = re.sub(
            #    r'(href|src)="(?!http|https|//|#)([^"]+)"',
            #    lambda m: f'{m.group(1)}="/view-file?path={quote(os.path.join(base_dir, m.group(2)))}"',
            #    content
            #)
            
            return Response(content, mimetype='text/html; charset=utf-8')
        
        elif file_path.endswith('.css'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return Response(content, mimetype='text/css; charset=utf-8')
        
        elif file_path.endswith('.js'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return Response(content, mimetype='application/javascript; charset=utf-8')
        
        else:
            # 其他檔案類型
            return send_file(file_path)
            
    except Exception as e:
        return f"Error reading file: {str(e)}", 500
        
@main_page_bp.route('/')
def index():
    """Main page"""
    return HTML_TEMPLATE
