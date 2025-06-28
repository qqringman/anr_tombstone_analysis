from flask import Blueprint, request, jsonify
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
from rate_limiter import TokenRateLimiter, LimitedCache
from android_log_analyzer import LogType, AnalysisResult, AndroidLogAnalyzer

# 創建一個藍圖實例
ai_bp = Blueprint('ai', __name__)

# Claude API 配置 - 請設置環境變數或直接填入
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')  # 從環境變數讀取

# 更新 AI 配置
AI_CONFIG = {
    'MAX_TOKENS_PER_REQUEST': 180000,  # 單次請求的 token 限制
    'CHARS_PER_TOKEN': 2.5,  # 平均字符/token 比率
    'OVERLAP_SIZE': 2000,  # 減少重疊大小
    'CONTEXT_WINDOW': 5000,  # 減少上下文窗口
    'MAX_THINKING_LENGTH': 50000,
    'RATE_LIMIT_TOKENS_PER_MINUTE': 40000,
    'RATE_LIMIT_TOKENS_PER_SEGMENT': 25000,  # 新增：每段最多 25K tokens
    'RETRY_DELAY': 30,  # 減少重試延遲
    'MAX_RETRIES': 3,
    'PARALLEL_SEGMENTS': 2,  # 新增：並行處理段數
}

MODEL_LIMITS = {
    # Claude 4 系列（最新）
    'claude-opus-4-20250514': {
        'max_tokens': 300000,  # 增加到 300K tokens
        'max_output_tokens': 16384,  # 16K 輸出
        'chars_per_token': 2.5,
        'rate_limit': 60000,  # 每分鐘 60K tokens
        'name': 'Claude 4 Opus',
        'description': '最強大的模型，適合複雜分析'
    },
    'claude-sonnet-4-20250514': {
        'max_tokens': 250000,  # 250K tokens
        'max_output_tokens': 12288,  # 12K 輸出
        'chars_per_token': 2.5,
        'rate_limit': 80000,  # 每分鐘 80K tokens
        'name': 'Claude 4 Sonnet',
        'description': '平衡效能與成本，推薦使用'
    },
    
    # Claude 3.5 系列（保留現有）
    'claude-3-5-sonnet-20241022': {
        'max_tokens': 200000,
        'max_output_tokens': 8192,
        'chars_per_token': 2.5,
        'rate_limit': 40000,
        'name': 'Claude 3.5 Sonnet',
        'description': '快速準確，適合大部分場景'
    },
    'claude-3-5-haiku-20241022': {
        'max_tokens': 200000,
        'max_output_tokens': 8192,
        'chars_per_token': 2.5,
        'rate_limit': 80000,
        'name': 'Claude 3.5 Haiku',
        'description': '輕量快速，適合簡單分析'
    },
    
    # Claude 3 系列（保留兼容）
    'claude-3-opus-20240229': {
        'max_tokens': 200000,
        'max_output_tokens': 4096,
        'chars_per_token': 2.5,
        'rate_limit': 40000,
        'name': 'Claude 3 Opus',
        'description': '深度分析，較慢但詳細'
    },
    'claude-3-haiku-20240307': {
        'max_tokens': 200000,
        'max_output_tokens': 4096,
        'chars_per_token': 2.5,
        'rate_limit': 80000,
        'name': 'Claude 3 Haiku',
        'description': '經濟實惠，基本分析'
    }
}

# 更新默認模型為 Claude 4 Sonnet
DEFAULT_MODEL = 'claude-sonnet-4-20250514'

# 創建全局速率限制器
rate_limiter = TokenRateLimiter(AI_CONFIG['RATE_LIMIT_TOKENS_PER_MINUTE'])

# 新增智能模型選擇功能
def select_optimal_model(content_size, analysis_type, user_preference=None):
    """根據內容大小和分析類型智能選擇最佳模型"""
    if user_preference and user_preference in MODEL_LIMITS:
        return user_preference
    
    # 根據內容大小選擇
    if content_size > 500000:  # 超過 500KB
        # 大檔案使用 Claude 4 Opus
        return 'claude-opus-4-20250514'
    elif content_size > 200000:  # 200KB - 500KB
        # 中等檔案使用 Claude 4 Sonnet
        return 'claude-sonnet-4-20250514'
    elif analysis_type == 'quick':
        # 快速分析使用 Haiku
        return 'claude-3-5-haiku-20241022'
    else:
        # 一般情況使用 Claude 3.5 Sonnet
        return 'claude-3-5-sonnet-20241022'
        
@ai_bp.route('/analyze-with-ai', methods=['POST'])
async def analyze_with_ai():
    """使用 Claude API 分析日誌內容（優化版本）"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        # Extract all required fields from request
        file_path = data.get('file_path', '')
        content = data.get('content', '')
        file_type = data.get('file_type', 'ANR')
        selected_model = data.get('model', 'claude-3-5-sonnet-20241022')
        is_custom_question = data.get('is_custom_question', False)
        original_question = data.get('original_question', '')
        enable_thinking = data.get('enable_thinking', True)
        
        # Validate required fields
        if not content:
            return jsonify({'error': 'No content provided'}), 400
        
        # 檢查是否需要分段
        estimated_tokens = estimate_tokens_accurate(content)
        
        # 使用更嚴格的限制
        needs_segmentation = estimated_tokens > AI_CONFIG['RATE_LIMIT_TOKENS_PER_SEGMENT']
        
        # 修復：取消註解並啟用分段邏輯
        if needs_segmentation:
            # 使用快速分段分析
            return await analyze_in_segments_fast(
                file_path, content, file_type, selected_model,
                is_custom_question, original_question, enable_thinking
            )
        else:
            # 單次分析
            return analyze_single_request(
                file_path, content, file_type, selected_model,
                is_custom_question, original_question, enable_thinking
            )
        
    except Exception as e:
        print(f"AI analysis error: {str(e)}")
        return jsonify({'error': f'分析錯誤: {str(e)}'}), 500
    
@ai_bp.route('/check-file-size-for-ai', methods=['POST'])
def check_file_size_for_ai():
    """預檢檔案大小並根據分析模式提供建議"""
    try:
        data = request.json
        content = data.get('content', '')
        mode = data.get('mode', 'auto')  # 獲取分析模式
        
        content_length = len(content)
        estimated_tokens = estimate_tokens_accurate(content)
        
        # 快速模式：永遠不分段！
        if mode == 'quick':
            return jsonify({
                'content_length': content_length,
                'estimated_tokens': estimated_tokens,
                'max_tokens_per_request': 50000,  # 快速分析的限制
                'suggested_segments': 1,  # 永遠只有 1 段
                'strategy': 'single',  # 單次分析
                'estimated_time': 30,  # 30 秒
                'mode': 'quick'
            })
        
        # 其他模式的邏輯
        model_limits = MODEL_LIMITS.get('claude-sonnet-4-20250514')
        max_tokens = int(model_limits['max_tokens'] * 0.8)
        
        # 根據模式調整分段策略
        if mode == 'comprehensive':
            # 深度分析更積極分段
            segment_threshold = max_tokens * 0.6
        elif mode == 'max_tokens':
            # 最大化分析盡量不分段
            segment_threshold = max_tokens
        else:  # auto
            # 智能模式使用標準閾值
            segment_threshold = max_tokens * 0.8
        
        if estimated_tokens <= segment_threshold:
            suggested_segments = 1
            strategy = 'single'
        else:
            max_chars = int(segment_threshold * model_limits['chars_per_token'])
            suggested_segments = max(1, (content_length + max_chars - 1) // max_chars)
            strategy = 'segmented'
        
        # 時間估算
        time_per_segment = {
            'comprehensive': 60,  # 深度分析每段 60 秒
            'max_tokens': 45,     # 最大化分析每段 45 秒
            'auto': 30            # 智能分析每段 30 秒
        }
        
        estimated_time = suggested_segments * time_per_segment.get(mode, 30)
        
        return jsonify({
            'content_length': content_length,
            'estimated_tokens': estimated_tokens,
            'max_tokens_per_request': max_tokens,
            'suggested_segments': suggested_segments,
            'strategy': strategy,
            'estimated_time': estimated_time,
            'mode': mode
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
        
@ai_bp.route('/check-content-size', methods=['POST'])
def check_content_size():
    """檢查內容大小並建議是否需要分段"""
    try:
        data = request.json
        content = data.get('content', '')
        
        content_length = len(content)
        estimated_tokens = content_length // 2  # 粗略估算
        
        # 建議的分段數
        suggested_segments = calculate_suggested_segments(content_length)
        needs_segmentation = suggested_segments > 1
        
        return jsonify({
            'content_length': content_length,
            'estimated_tokens': estimated_tokens,
            'needs_segmentation': needs_segmentation,
            'suggested_segments': suggested_segments,
            'max_chars_per_segment': 380000
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
        

def estimate_tokens_accurate(text):
    """更準確的 token 估算"""
    if not text:
        return 0
    
    # 使用 tiktoken 的估算方法（如果可用）
    try:
        # 簡單的字符計數方法
        # Claude 的 tokenizer 大約是：
        # - 英文：平均 4 字符 = 1 token
        # - 中文：平均 2-3 字符 = 1 token
        # - 代碼：平均 3 字符 = 1 token
        
        english_chars = len([c for c in text if c.isascii() and c.isalnum()])
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
        other_chars = len(text) - english_chars - chinese_chars
        
        estimated = (
            english_chars / 4 +      # 英文
            chinese_chars / 2.5 +    # 中文
            other_chars / 3          # 其他
        )
        
        return int(estimated * 1.1)  # 加 10% 緩衝
    except:
        # 備用方法
        return int(len(text) / 3)
        
def create_intelligent_segments_optimized(content, max_tokens_per_segment=None):
    """優化的智能分段，確保不超過速率限制"""
    if max_tokens_per_segment is None:
        # 使用更保守的段落大小，確保不超過速率限制
        max_tokens_per_segment = AI_CONFIG['RATE_LIMIT_TOKENS_PER_SEGMENT']
    
    # 根據 token 限制計算字符限制
    max_chars_per_segment = int(max_tokens_per_segment * AI_CONFIG['CHARS_PER_TOKEN'])
    
    # 如果內容很大，使用更小的段
    if len(content) > 500000:  # 500KB+
        max_chars_per_segment = min(max_chars_per_segment, 50000)  # 最多 50K 字符
    
    # 識別自然分段點
    natural_breaks = [
        '\n\n----- pid ',  # 進程分隔
        '\nCmd line:',     # 命令行
        '\nCmdline:',      # 命令行變體
        '\n*** ***',       # 區塊分隔
        '\nbacktrace:',    # 堆疊追蹤
        '\n#00 pc',        # 堆疊幀
        '\n\n',            # 雙換行
    ]
    
    segments = []
    current_pos = 0
    content_length = len(content)
    
    while current_pos < content_length:
        # 計算這個段落的結束位置
        segment_end = min(current_pos + max_chars_per_segment, content_length)
        
        # 如果不是最後一段，嘗試在自然斷點處分割
        if segment_end < content_length:
            # 在結束位置附近尋找自然斷點
            search_start = max(segment_end - 10000, current_pos)
            best_break = segment_end
            
            for break_pattern in natural_breaks:
                pos = content.rfind(break_pattern, search_start, segment_end)
                if pos > current_pos:
                    best_break = pos
                    break
            
            segment_end = best_break
        
        # 確保段落不會太小
        if segment_end - current_pos < 10000 and segment_end < content_length:
            segment_end = min(current_pos + max_chars_per_segment, content_length)
        
        # 提取段落
        segment_content = content[current_pos:segment_end]
        
        # 計算實際 tokens（更準確的估算）
        estimated_tokens = estimate_tokens_accurate(segment_content)
        
        segments.append({
            'content': segment_content,
            'start': current_pos,
            'end': segment_end,
            'has_more': segment_end < content_length,
            'estimated_tokens': estimated_tokens
        })
        
        # 移動到下一段
        current_pos = segment_end
    
    return segments        
    
async def analyze_in_segments_fast(file_path, content, file_type, selected_model, 
                                  is_custom_question, original_question, enable_thinking):
    """快速分段分析，支援並行處理"""
    
    # 使用優化的分段
    segments = create_intelligent_segments_optimized(content)
    
    # 如果段落太多，限制並行數
    if len(segments) > 10:
        print(f"注意：檔案將分成 {len(segments)} 段，這可能需要一些時間")
    
    # 確保 total_segments 一致
    total_segments = len(segments)
    
    response_data = {
        'success': True,
        'is_segmented': True,
        'total_segments': total_segments,  # 使用實際段數
        'segments': [],
        'full_analysis': '',
        'thinking_log': [] if enable_thinking else None,
        'errors': [],
        'rate_limit_info': {
            'total_tokens_used': 0,
            'segments_processed': 0,
            'wait_times': []
        }
    }
    
    print(f"分段分析：總共 {total_segments} 段")  # 添加日誌
    
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    
    # 使用異步處理提高效率
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    async def process_segment(segment_data, segment_num):
        """處理單個段落"""
        try:
            # 檢查速率限制
            wait_time = rate_limiter.get_wait_time(segment_data['estimated_tokens'])
            if wait_time > 0:
                print(f"段落 {segment_num} 需要等待 {wait_time:.1f} 秒")
                await asyncio.sleep(wait_time)
            
            # 記錄 token 使用
            rate_limiter.use_tokens(segment_data['estimated_tokens'])
            
            # 構建精簡的提示
            prompt = build_segment_prompt_fast(
                segment_data, segment_num, total_segments,  # 使用 total_segments
                file_type, original_question
            )
            
            # 調用 API
            message = await asyncio.to_thread(
                client.messages.create,
                model=selected_model,
                max_tokens=2000,  # 減少輸出 tokens
                temperature=0,
                system=prompt['system'],
                messages=[{"role": "user", "content": prompt['user']}]
            )
            
            return {
                'segment_number': segment_num,
                'analysis': message.content[0].text if message.content else "",
                'success': True,
                'tokens_used': segment_data['estimated_tokens']
            }
            
        except Exception as e:
            return {
                'segment_number': segment_num,
                'error': str(e),
                'success': False
            }
    
    # 批次處理段落
    batch_size = AI_CONFIG.get('PARALLEL_SEGMENTS', 2)
    all_results = []

    # 添加進度追蹤
    response_data['progress'] = {
        'current': 0,
        'total': total_segments,
        'percentage': 0
    }
    
    for i in range(0, len(segments), batch_size):
        batch = segments[i:i+batch_size]
        batch_nums = list(range(i+1, min(i+batch_size+1, len(segments)+1)))
        
        # 並行處理這批段落
        tasks = [
            process_segment(seg, num) 
            for seg, num in zip(batch, batch_nums)
        ]
        
        results = await asyncio.gather(*tasks)
        all_results.extend(results)
        
        # 更新進度
        response_data['rate_limit_info']['segments_processed'] = len(all_results)
        response_data['progress']['current'] = i + len(batch)
        response_data['progress']['percentage'] = int((i + len(batch)) / total_segments * 100)
        
        # 如果需要，短暫休息以避免速率限制
        if i + batch_size < len(segments):
            await asyncio.sleep(2)  # 2 秒間隔
    
    # 整理結果
    response_data['segments'] = all_results
    
    # 生成快速摘要
    successful_segments = [r for r in all_results if r.get('success')]
    if successful_segments:
        response_data['full_analysis'] = generate_quick_summary(successful_segments, original_question)
    
    return response_data

def calculate_suggested_segments(content_length):
    """計算建議的分段數"""
    max_chars_per_segment = 380000  # 約 190K tokens
    segments = max(1, (content_length + max_chars_per_segment - 1) // max_chars_per_segment)
    return segments

def synthesize_segments(segments, original_question, model, client):
    """綜合所有段落的分析結果"""
    
    # 準備所有段落的摘要
    all_findings = []
    for seg in segments:
        if not seg.get('error'):
            all_findings.append(f"段落 {seg['segment_number']}：\n{extract_key_findings(seg['analysis'])}")
    
    synthesis_prompt = f"""基於以下各段落的分析結果，請提供一個綜合性的答案。

各段落發現：
{''.join(all_findings)}

原始問題：{original_question}

請提供：
1. 問題的根本原因
2. 關鍵證據（引用具體段落）
3. 建議的解決方案
4. 需要進一步調查的事項"""
    
    try:
        message = client.messages.create(
            model=model,
            max_tokens=4000,
            temperature=0,
            system="你是一位 Android 系統專家，請綜合分析結果並提供完整答案。",
            messages=[{"role": "user", "content": synthesis_prompt}]
        )
        
        return {
            'analysis': message.content[0].text if message.content else "",
            'thinking': getattr(message, 'thinking', None)
        }
    except Exception as e:
        return {
            'analysis': f"綜合分析失敗: {str(e)}",
            'thinking': None
        }

def extract_key_findings(analysis_text):
    """從分析文本中提取關鍵發現"""
    # 簡單實現：提取包含關鍵詞的句子
    key_sentences = []
    sentences = analysis_text.split('。')
    
    keywords = ['崩潰', '原因', '問題', '錯誤', '異常', '死鎖', '阻塞', 
                '記憶體', '堆疊', '線程', 'crash', 'error', 'exception']
    
    for sentence in sentences[:5]:  # 只取前5句
        if any(keyword in sentence.lower() for keyword in keywords):
            key_sentences.append(sentence.strip() + '。')
    
    return '\n'.join(key_sentences) if key_sentences else analysis_text[:200] + '...'

def generate_quick_summary(segments, question):
    """快速生成摘要，不需要額外的 API 調用"""
    summary_parts = [
        f"# 檔案分析摘要",
        f"\n## 問題：{question}",
        f"\n## 分析了 {len(segments)} 個段落",
        "\n## 主要發現：\n"
    ]
    
    # 提取每個段落的關鍵信息
    key_findings = []
    for seg in segments[:10]:  # 只處理前 10 個段落的摘要
        if seg.get('analysis'):
            # 提取第一段或前 200 字
            first_para = seg['analysis'].split('\n\n')[0]
            if len(first_para) > 200:
                first_para = first_para[:200] + "..."
            key_findings.append(f"- 段落 {seg['segment_number']}: {first_para}")
    
    summary_parts.extend(key_findings[:5])  # 只顯示前 5 個發現
    
    if len(segments) > 5:
        summary_parts.append(f"\n... 還有 {len(segments) - 5} 個段落的分析結果")
    
    return '\n'.join(summary_parts)
    
def build_segment_prompt_fast(segment, segment_num, total_segments, file_type, question):
    """生成精簡的提示詞以減少 token 使用"""
    
    # 截取段落的關鍵部分
    content = segment['content']
    if len(content) > 50000:  # 如果還是太長，只保留關鍵部分
        # 保留開頭和結尾，以及包含關鍵詞的部分
        keywords = ['error', 'crash', 'fatal', 'exception', 'fail', 'died']
        important_lines = []
        
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if any(keyword in line.lower() for keyword in keywords):
                # 保留前後各 5 行的上下文
                start = max(0, i - 5)
                end = min(len(lines), i + 6)
                important_lines.extend(lines[start:end])
        
        content = '\n'.join(important_lines[:1000])  # 限制行數
    
    system_prompt = f"Android 專家。分析段落 {segment_num}/{total_segments}。只提供關鍵發現。"
    
    user_prompt = f"""分析此段落並回答：{question}

{content[:30000]}  # 限制內容長度

請提供：
1. 主要問題（1-2句）
2. 關鍵證據（1-2個）
3. 是否需要其他段落資訊
4. 指出發生 ANR/Tombstone 的 Process
5. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
6. 找出 ANR/Tombstone 卡住可能的原因
"""
    
    return {
        'system': system_prompt,
        'user': user_prompt
    }
    
def analyze_single_request(file_path, content, file_type, selected_model,
                         is_custom_question, original_question, enable_thinking):
    """單次分析請求（不需要分段）"""
    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        # 新增：檢查內容是否需要截取
        model_config = MODEL_LIMITS.get(selected_model, MODEL_LIMITS[DEFAULT_MODEL])
        max_tokens = int(model_config['max_tokens'] * 0.8)  # 留 20% 餘量給系統提示
        max_chars = int(max_tokens * model_config['chars_per_token'])
        
        truncated = False
        original_length = len(content)
        
        if len(content) > max_chars:
            # 內容太長，需要截取
            content = content[:max_chars]
            truncated = True
            print(f"Content truncated from {original_length} to {len(content)} chars")
        
        # 構建基礎系統提示詞
        base_system_prompt = """你是一位 Android 系統專家，擅長分析 Android 日誌和解決系統問題。

分析時請遵循以下原則：
1. 仔細閱讀提供的內容
2. 根據內容準確分析問題
3. 提供具體、可操作的建議
4. 使用結構化的格式呈現結果

請用繁體中文回答。"""
        
        # 根據文件類型和問題類型構建提示詞
        if is_custom_question:
            # 自定義問題模式
            system_prompt = base_system_prompt + f"""

用戶提供了一個檔案的內容，並基於這個檔案提出了問題。
請根據檔案內容準確回答用戶的問題。
如果檔案中沒有足夠的信息來回答問題，請明確指出。"""
            
            # 用戶消息
            user_message = f"""使用者問題：{original_question}

檔案內容：
{content}"""
            
        elif file_type == 'ANR':
            # ANR 分析模式
            system_prompt = base_system_prompt + f"""

你現在要分析一個 ANR (Application Not Responding) 日誌。

請提供以下分析：
1. 問題摘要：簡潔說明發生了什麼
2. 根本原因：識別導致 ANR 的主要原因
3. 技術分析：
   - 識別發生 ANR 的 Process 名稱
   - 如果可能，列出該 Process main thread 的 backtrace
   - 分析 main thread 卡住的具體原因
4. 受影響的組件：哪個應用或服務受到影響
5. 建議解決方案：如何修復這個問題
6. 預防措施：如何避免未來發生類似問題"""
            
            user_message = content
            
        elif file_type == 'Tombstone':
            # Tombstone 分析模式
            system_prompt = base_system_prompt + f"""

你現在要分析一個 Tombstone 崩潰日誌。

請提供以下分析：
1. 崩潰摘要：簡潔說明發生了什麼類型的崩潰
2. 崩潰原因：信號類型和觸發原因
3. 技術分析：
   - 識別發生崩潰的 Process 名稱
   - 如果可能，列出崩潰時 main thread 的 backtrace
   - 分析崩潰的具體原因（如空指針、記憶體錯誤等）
4. 崩潰位置：定位問題的關鍵堆棧幀
5. 可能的修復方向：如何避免這類崩潰
6. 相關資訊：其他可能有用的調試信息"""
            
            user_message = content
            
        else:
            # 其他類型或通用分析
            system_prompt = base_system_prompt + """

請分析提供的日誌內容，識別問題並提供解決建議。"""
            
            user_message = content
        
        # 如果內容被截取，在提示中說明
        if truncated:
            system_prompt += f"\n\n注意：由於檔案過大，只提供了前 {len(content)} 個字符（原始大小：{original_length} 字符）。分析結果可能不完整。"
        
        # 調用 Claude API
        message_params = {
            "model": selected_model,
            "max_tokens": 4000,
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
        response_text = ""
        thinking_text = None
        
        if message.content:
            response_text = message.content[0].text
        else:
            response_text = "無法獲取分析結果"
        
        # 嘗試獲取 thinking（如果支援）
        if enable_thinking and hasattr(message, 'thinking'):
            thinking_text = message.thinking
        
        return jsonify({
            'success': True,
            'analysis': response_text,
            'truncated': truncated,
            'original_length': original_length,
            'analyzed_length': len(content) if truncated else original_length,
            'model': selected_model,
            'thinking': thinking_text,
            'file_type': file_type,
            'is_custom_question': is_custom_question
        })
        
    except anthropic.APIError as e:
        error_message = str(e)
        
        # 處理特定的 API 錯誤
        if e.status_code == 429:
            error_message = "API 速率限制，請稍後再試"
        elif e.status_code == 401:
            error_message = "API 認證失敗，請檢查 API key"
        elif e.status_code == 400:
            error_message = "請求格式錯誤"
        
        return jsonify({
            'error': f'Claude API 錯誤: {error_message}',
            'details': '請檢查 API key 是否有效',
            'status_code': e.status_code
        }), 500
        
    except Exception as e:
        print(f"Unexpected error in analyze_single_request: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'error': f'分析錯誤: {str(e)}',
            'type': type(e).__name__
        }), 500
        
def build_segment_prompt(segment, segment_num, total_segments, file_type, question, previous_context):
    """構建段落分析的提示詞"""
    
    # 基礎系統提示
    base_system = f"""你是一位 Android 系統專家，擅長分析 Android 日誌和解決系統問題。
這是一個大型日誌檔案的第 {segment_num}/{total_segments} 段。"""
    
    if previous_context:
        base_system += f"\n\n之前段落的關鍵發現：\n{previous_context}"
    
    # 添加分析指導
    if file_type == 'ANR':
        base_system += """
        
請特別注意：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 這個段落中的堆疊追蹤信息
5. 線程狀態和鎖定情況
6. 主線程是否被阻塞
7. 任何死鎖或資源爭用的跡象"""
    elif file_type == 'Tombstone':
        base_system += """
        
請特別注意：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 崩潰的信號類型和地址
5. 堆疊追蹤的關鍵函數
6. 寄存器狀態
7. 可能的記憶體問題"""
    
    # 用戶提示
    user_prompt = f"""=== 檔案段落 {segment_num}/{total_segments} ===

{segment['context'] + segment['content'] if segment['context'] else segment['content']}

=== 段落結束 ===

問題：{question}

請分析這個段落，並注意：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 如果這不是第一段，請考慮之前的發現
5. 如果還有後續段落，請指出需要在後續段落中尋找的信息
6. 提供這個段落的關鍵發現摘要"""
    
    return {
        'system': base_system,
        'user': user_prompt
    }

def analyze_in_segments_smart(file_path, content, file_type, selected_model, 
                            is_custom_question, original_question, enable_thinking):
    """智能分段分析大檔案（包含速率限制處理）"""
    
    # 創建智能段落
    segments = create_intelligent_segments(content)
    
    # 如果段落太多，警告用戶
    if len(segments) > 5:
        print(f"警告：檔案將分成 {len(segments)} 段，可能需要較長時間完成")
    
    # 準備回應
    response_data = {
        'success': True,
        'is_segmented': True,
        'total_segments': len(segments),
        'segments': [],
        'full_analysis': '',
        'thinking_log': [] if enable_thinking else None,
        'errors': [],
        'rate_limit_info': {
            'total_tokens_used': 0,
            'wait_times': []
        }
    }
    
    # Claude 客戶端
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    
    # 累積的分析上下文
    accumulated_context = ""
    accumulated_thinking = ""
    successful_segments = 0
    total_tokens_used = 0
    
    for i, segment in enumerate(segments):
        segment_num = i + 1
        
        # 估算這個段落需要的 tokens
        segment_content = segment['context'] + segment['content'] if segment['context'] else segment['content']
        estimated_tokens = estimate_tokens_conservative(segment_content)
        
        print(f"段落 {segment_num} 預估 tokens: {estimated_tokens}")
        
        # 檢查速率限制
        wait_time = rate_limiter.get_wait_time(estimated_tokens)
        if wait_time > 0:
            print(f"需要等待 {wait_time:.1f} 秒以避免速率限制")
            response_data['rate_limit_info']['wait_times'].append({
                'segment': segment_num,
                'wait_time': wait_time
            })
            
            # 如果等待時間太長，考慮縮減內容
            if wait_time > 30:
                print(f"等待時間過長，嘗試縮減段落 {segment_num} 的內容")
                # 縮減內容到 75%
                max_chars = int(len(segment_content) * 0.75)
                segment_content = segment_content[:max_chars] + "\n\n[內容已縮減以符合速率限制]"
                estimated_tokens = estimate_tokens_conservative(segment_content)
                wait_time = rate_limiter.get_wait_time(estimated_tokens)
            
            # 等待
            if wait_time > 0:
                time.sleep(wait_time)
        
        # 構建段落提示
        segment_prompt = build_segment_prompt_optimized(
            {'content': segment_content, 'start': segment['start'], 'end': segment['end']},
            segment_num, len(segments),
            file_type, original_question, accumulated_context
        )
        
        # 重試邏輯
        retry_count = 0
        success = False
        
        while retry_count < AI_CONFIG['MAX_RETRIES'] and not success:
            try:
                # 記錄 token 使用
                rate_limiter.use_tokens(estimated_tokens)
                total_tokens_used += estimated_tokens
                
                # 調用 API
                message_params = {
                    "model": selected_model,
                    "max_tokens": 4000,
                    "temperature": 0,
                    "system": segment_prompt['system'],
                    "messages": [
                        {
                            "role": "user",
                            "content": segment_prompt['user']
                        }
                    ]
                }
                
                message = client.messages.create(**message_params)
                
                # 提取回應
                analysis_text = message.content[0].text if message.content else ""
                thinking_text = None
                
                # 儲存段落結果
                segment_result = {
                    'segment_number': segment_num,
                    'analysis': analysis_text,
                    'thinking': thinking_text,
                    'char_range': f"{segment['start']}-{segment['end']}",
                    'success': True,
                    'tokens_used': estimated_tokens,
                    'retry_count': retry_count
                }
                
                response_data['segments'].append(segment_result)
                successful_segments += 1
                success = True
                
                # 更新累積上下文
                key_findings = extract_key_findings(analysis_text)
                accumulated_context += f"\n\n段落 {segment_num} 關鍵發現：\n{key_findings}"
                
                # 段落之間的小延遲，避免太快
                if i < len(segments) - 1:  # 不是最後一段
                    time.sleep(2)  # 2 秒延遲
                
            except anthropic.APIError as e:
                error_msg = str(e)
                print(f"分析段落 {segment_num} 時出錯 (嘗試 {retry_count + 1}): {error_msg}")
                
                if e.status_code == 429:  # Rate limit error
                    # 解析錯誤訊息獲取建議的等待時間
                    if retry_count < AI_CONFIG['MAX_RETRIES'] - 1:
                        wait_time = AI_CONFIG['RETRY_DELAY'] * (2 ** retry_count)  # 指數退避
                        print(f"速率限制錯誤，等待 {wait_time} 秒後重試...")
                        time.sleep(wait_time)
                        retry_count += 1
                        continue
                    else:
                        # 達到最大重試次數
                        segment_result = {
                            'segment_number': segment_num,
                            'analysis': f"段落 {segment_num} 因速率限制無法分析",
                            'thinking': None,
                            'char_range': f"{segment['start']}-{segment['end']}",
                            'error': True,
                            'error_message': '超過速率限制，請稍後再試',
                            'success': False
                        }
                        response_data['segments'].append(segment_result)
                        response_data['errors'].append({
                            'segment': segment_num,
                            'error': '速率限制錯誤',
                            'retry_count': retry_count
                        })
                        break
                else:
                    # 其他 API 錯誤
                    segment_result = {
                        'segment_number': segment_num,
                        'analysis': f"段落 {segment_num} 分析失敗",
                        'thinking': None,
                        'char_range': f"{segment['start']}-{segment['end']}",
                        'error': True,
                        'error_message': error_msg,
                        'success': False
                    }
                    response_data['segments'].append(segment_result)
                    response_data['errors'].append({
                        'segment': segment_num,
                        'error': error_msg
                    })
                    break
                    
            except Exception as e:
                print(f"分析段落 {segment_num} 時發生未預期錯誤: {str(e)}")
                segment_result = {
                    'segment_number': segment_num,
                    'analysis': f"段落 {segment_num} 分析失敗: {str(e)}",
                    'thinking': None,
                    'error': True,
                    'success': False
                }
                response_data['segments'].append(segment_result)
                break
    
    # 更新速率限制資訊
    response_data['rate_limit_info']['total_tokens_used'] = total_tokens_used
    
    # 檢查是否有成功的段落
    if successful_segments == 0:
        response_data['success'] = False
        response_data['error'] = '所有段落分析都失敗了，可能是速率限制問題'
        return jsonify(response_data), 500
    
    # 生成綜合分析（只使用成功的段落）
    successful_segments_data = [s for s in response_data['segments'] if s.get('success', False)]
    
    if len(successful_segments_data) > 0:
        # 等待一下再做綜合分析
        time.sleep(5)
        synthesis = synthesize_segments(successful_segments_data, original_question, selected_model, client)
        response_data['full_analysis'] = synthesis['analysis']
        if synthesis.get('thinking'):
            response_data['thinking_log'].append({
                'stage': '綜合分析',
                'content': synthesis['thinking']
            })
    
    # 如果有錯誤，在分析中提及
    if response_data['errors']:
        error_note = f"\n\n注意：有 {len(response_data['errors'])} 個段落因速率限制或其他錯誤無法分析，結果可能不完整。"
        response_data['full_analysis'] += error_note
    
    return jsonify(response_data)

def build_segment_prompt_optimized(segment, segment_num, total_segments, file_type, question, previous_context):
    """構建優化的段落分析提示詞（更簡潔）"""
    
    # 簡化系統提示以減少 token 使用
    base_system = f"""Android 專家。分析第 {segment_num}/{total_segments} 段。"""
    
    if previous_context and len(previous_context) < 500:  # 限制上下文長度
        base_system += f"\n前段摘要：{previous_context[:500]}"
    
    # 簡化用戶提示
    user_prompt = f"""段落 {segment_num}/{total_segments}:
{segment['content'][:300000]}  # 限制內容長度

問題：{question}

請提供：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 關鍵發現
5. 問題線索
6. 需要後續段落確認的事項"""
    
    return {
        'system': base_system,
        'user': user_prompt
    }
    
# 新增智能分段函數
def create_intelligent_segments(content, max_chars_per_segment=None):
    """智能分段，保持上下文連貫性"""
    if max_chars_per_segment is None:
        # 更保守的估算：假設最壞情況下 2 字符 = 1 token
        # 200K token 限制，留出 20K 給系統提示和回應
        max_chars_per_segment = 180000 * 2  # 360000 字符
    
    # 但如果內容本身很大，使用更小的段
    if len(content) > 1000000:  # 1MB+
        max_chars_per_segment = min(max_chars_per_segment, 300000)  # 最多 300K 字符
    
    # 識別自然分段點
    natural_breaks = [
        '\n\n----- pid ',  # 進程分隔
        '\nCmd line:',     # 命令行
        '\nCmdline:',      # 命令行變體
        '\n*** ***',       # 區塊分隔
        '\nbacktrace:',    # 堆疊追蹤
        '\n#00 pc',        # 堆疊幀
        '\n\n',            # 雙換行
    ]
    
    segments = []
    current_pos = 0
    content_length = len(content)
    
    while current_pos < content_length:
        # 計算這個段落的結束位置
        segment_end = min(current_pos + max_chars_per_segment, content_length)
        
        # 如果不是最後一段，嘗試在自然斷點處分割
        if segment_end < content_length:
            # 在結束位置附近尋找自然斷點
            search_start = max(segment_end - 20000, current_pos)  # 擴大搜尋範圍
            best_break = segment_end
            
            for break_pattern in natural_breaks:
                pos = content.rfind(break_pattern, search_start, segment_end)
                if pos > current_pos:
                    best_break = pos
                    break
            
            segment_end = best_break
        
        # 確保段落不會太小
        if segment_end - current_pos < 50000 and segment_end < content_length:
            # 如果段落太小，擴展到下一個斷點
            segment_end = min(current_pos + max_chars_per_segment, content_length)
        
        # 提取段落
        segment_start = current_pos
        segment_content = content[segment_start:segment_end]
        
        # 添加少量上下文（減少重疊以節省 token）
        context_size = min(2000, AI_CONFIG['OVERLAP_SIZE'])  # 最多 2000 字符的上下文
        context_start = max(0, segment_start - context_size)
        context_content = content[context_start:segment_start] if segment_start > 0 else ""
        
        segments.append({
            'content': segment_content,
            'context': context_content,
            'start': segment_start,
            'end': segment_end,
            'has_more': segment_end < content_length,
            'estimated_tokens': estimate_tokens_conservative(context_content + segment_content)
        })
        
        # 移動到下一段（減少重疊）
        current_pos = segment_end - min(1000, context_size) if segment_end < content_length else content_length
    
    return segments

def estimate_tokens_conservative(text):
    """保守估算 token 數量"""
    # 假設平均 2.5 字符 = 1 token（對中文更保守）
    # 檢查是否包含大量中文
    chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
    total_chars = len(text)
    
    if chinese_chars > total_chars * 0.3:  # 30% 以上是中文
        # 中文較多，使用更保守的估算
        return int(total_chars / 2.0)
    else:
        # 英文為主
        return int(total_chars / 3.0)

def synthesize_segments_v2(segments, original_question, model, client):
    """改進的綜合分析，支援更長的輸出"""
    # 只使用成功的段落
    successful_segments = [s for s in segments if s.get('success')]
    
    if not successful_segments:
        return {
            'analysis': '所有段落分析都失敗了，無法生成綜合報告。',
            'thinking_log': []
        }
    
    # 準備摘要
    segment_summaries = []
    for seg in successful_segments:
        summary = extract_key_findings_advanced(seg['analysis'])
        segment_summaries.append(f"段落 {seg['segment_number']}：\n{summary}")
    
    # 構建綜合提示
    synthesis_prompt = f"""基於以下 {len(successful_segments)} 個段落的分析結果，請提供一個完整的綜合報告。

原始問題：{original_question}

各段落關鍵發現：
{'='*50}
{chr(10).join(segment_summaries)}
{'='*50}

請提供：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. **問題總覽**：用 2-3 句話概括整個問題
5. **根本原因分析**：詳細說明導致問題的根本原因（至少 500 字）
6. **技術細節**：
   - 涉及的進程和線程
   - 關鍵的堆棧信息
   - 內存/資源使用情況
   - 時間線分析
7. **影響評估**：這個問題的嚴重程度和潛在影響
8. **解決方案**：
   - 立即措施（緊急修復）
   - 短期方案（1-2 週內）
   - 長期優化（架構改進）
9. **預防措施**：如何避免類似問題再次發生
10. **需要進一步調查的事項**

請確保回應至少 4000 字，提供詳細和有價值的分析。"""
    
    try:
        # 使用更大的 max_tokens
        model_config = MODEL_LIMITS.get(model, MODEL_LIMITS['claude-3-5-sonnet-20241022'])
        
        message = client.messages.create(
            model=model,
            max_tokens=model_config['max_output_tokens'],  # 使用模型的最大輸出限制
            temperature=0,
            system="你是一位資深的 Android 系統專家，擅長分析複雜的系統問題。請提供詳細、專業且可操作的分析報告。",
            messages=[{"role": "user", "content": synthesis_prompt}]
        )
        
        thinking_log = []
        if hasattr(message, 'thinking'):
            thinking_log.append({
                'stage': '綜合分析',
                'content': message.thinking
            })
        
        return {
            'analysis': message.content[0].text if message.content else "",
            'thinking_log': thinking_log
        }
        
    except Exception as e:
        return {
            'analysis': f"綜合分析失敗: {str(e)}",
            'thinking_log': []
        }

def extract_key_findings_advanced(analysis_text):
    """改進的關鍵發現提取"""
    if not analysis_text:
        return "無分析內容"
    
    # 使用更智能的提取邏輯
    lines = analysis_text.split('\n')
    key_sections = []
    current_section = []
    
    keywords = [
        '原因', '問題', '錯誤', '異常', '崩潰', '死鎖', '阻塞',
        '記憶體', '堆疊', '線程', 'crash', 'error', 'exception',
        '關鍵', '重要', '主要', '核心', 'fatal', 'critical'
    ]
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 檢查是否包含關鍵詞
        if any(keyword in line.lower() for keyword in keywords):
            current_section.append(line)
        elif current_section:
            # 如果當前段落有內容，且這行是延續，也加入
            if len(current_section) < 5 and not line.startswith(('•', '-', '*', '1.', '2.')):
                current_section.append(line)
            else:
                # 結束當前段落
                if current_section:
                    key_sections.append('\n'.join(current_section))
                    current_section = []
    
    # 添加最後一個段落
    if current_section:
        key_sections.append('\n'.join(current_section))
    
    # 如果沒有找到關鍵段落，返回前 300 字
    if not key_sections:
        return analysis_text[:300] + '...' if len(analysis_text) > 300 else analysis_text
    
    # 返回前 3 個關鍵段落
    return '\n\n'.join(key_sections[:3])

def analyze_segment_with_retry(segment, client, file_type, question, 
                              accumulated_context, model, enable_thinking):
    """分析單個段落，包含重試邏輯"""
    max_retries = AI_CONFIG['MAX_RETRIES']
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # 記錄 token 使用
            rate_limiter.use_tokens(segment['estimated_tokens'])
            
            # 構建提示
            prompt = build_segment_prompt_v2(
                segment, file_type, question, accumulated_context, model
            )
            
            # 調用 API
            message_params = {
                "model": model,
                "max_tokens": MODEL_LIMITS[model]['max_output_tokens'],
                "temperature": 0,
                "system": prompt['system'],
                "messages": [{"role": "user", "content": prompt['user']}]
            }
            
            message = client.messages.create(**message_params)
            
            # 提取結果
            analysis_text = message.content[0].text if message.content else ""
            thinking_text = getattr(message, 'thinking', None) if enable_thinking else None
            
            return {
                'segment_number': segment['segment_number'],
                'analysis': analysis_text,
                'thinking': thinking_text,
                'char_range': f"{segment['start']}-{segment['end']}",
                'success': True,
                'tokens_used': segment['estimated_tokens'],
                'retry_count': retry_count
            }
            
        except anthropic.APIError as e:
            retry_count += 1
            if e.status_code == 429 and retry_count < max_retries:
                # 速率限制，等待後重試
                wait_time = min(AI_CONFIG['RETRY_DELAY'] * (2 ** retry_count), 60)
                time.sleep(wait_time)
                continue
            else:
                raise
                
        except Exception as e:
            raise

def create_intelligent_segments_v2(content, model='claude-3-5-sonnet-20241022'):
    """改進的智能分段，根據模型動態調整"""
    model_config = MODEL_LIMITS.get(model, MODEL_LIMITS['claude-3-5-sonnet-20241022'])
    
    # 計算最大 token 數（保留 20% 餘量用於系統提示和回應）
    max_tokens_per_segment = int(model_config['max_tokens'] * 0.8)
    
    # 計算預估的總 tokens
    total_tokens = estimate_tokens_advanced(content, model)
    
    # 如果內容小於限制，不需要分段
    if total_tokens <= max_tokens_per_segment:
        return [{
            'content': content,
            'start': 0,
            'end': len(content),
            'segment_number': 1,
            'total_segments': 1,
            'estimated_tokens': total_tokens,
            'needs_segmentation': False
        }]
    
    # 自然分段點（按優先級排序）
    natural_breaks = [
        (r'\n\n----- pid \d+', 100),      # 進程分隔（最高優先級）
        (r'\n\*\*\* \*\*\*', 90),         # 主要區塊分隔
        (r'\nCmd ?line:', 80),            # 命令行
        (r'\nbacktrace:', 70),            # 堆棧追蹤開始
        (r'\n#\d+ pc', 60),               # 堆棧幀
        (r'\n\n', 50),                    # 雙換行
        (r'\n', 40),                      # 單換行
        (r'\. ', 30),                     # 句號
        (r', ', 20),                      # 逗號
        (r' ', 10),                       # 空格
    ]
    
    segments = []
    current_pos = 0
    content_length = len(content)
    segment_number = 1
    
    # 預計算總段數
    estimated_segments = max(1, int(total_tokens / max_tokens_per_segment) + 1)
    
    while current_pos < content_length:
        # 計算這段的理想結束位置
        ideal_segment_tokens = max_tokens_per_segment
        ideal_segment_chars = int(ideal_segment_tokens * model_config['chars_per_token'])
        segment_end = min(current_pos + ideal_segment_chars, content_length)
        
        # 如果不是最後一段，尋找自然斷點
        if segment_end < content_length:
            best_break = segment_end
            best_priority = -1
            
            # 搜索範圍：理想位置的前後 20%
            search_start = max(current_pos, int(segment_end * 0.8))
            search_end = min(content_length, int(segment_end * 1.2))
            
            # 尋找最佳斷點
            for pattern, priority in natural_breaks:
                matches = list(re.finditer(pattern, content[search_start:search_end]))
                for match in matches:
                    break_pos = search_start + match.start()
                    if priority > best_priority:
                        best_break = break_pos
                        best_priority = priority
            
            segment_end = best_break
        
        # 提取段落內容
        segment_content = content[current_pos:segment_end]
        segment_tokens = estimate_tokens_advanced(segment_content, model)
        
        # 添加上下文（如果不是第一段）
        context = ""
        if segment_number > 1 and current_pos > 0:
            context_start = max(0, current_pos - 1000)
            context = content[context_start:current_pos]
        
        segments.append({
            'content': segment_content,
            'context': context,
            'start': current_pos,
            'end': segment_end,
            'segment_number': segment_number,
            'total_segments': estimated_segments,
            'estimated_tokens': segment_tokens,
            'has_more': segment_end < content_length
        })
        
        current_pos = segment_end
        segment_number += 1
    
    # 更新實際總段數
    for segment in segments:
        segment['total_segments'] = len(segments)
    
    return segments
              
# 改進的 token 估算函數
def estimate_tokens_advanced(text, model='claude-3-5-sonnet-20241022'):
    """更準確的 token 估算，考慮不同語言和特殊字符"""
    if not text:
        return 0
    
    # 獲取模型配置
    model_config = MODEL_LIMITS.get(model, MODEL_LIMITS['claude-3-5-sonnet-20241022'])
    
    # 分析文本組成
    import re
    
    # 統計不同類型的字符
    english_words = len(re.findall(r'\b[a-zA-Z]+\b', text))
    numbers = len(re.findall(r'\d+', text))
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    code_blocks = len(re.findall(r'```[\s\S]*?```', text))
    special_chars = len(re.findall(r'[^\w\s\u4e00-\u9fff]', text))
    
    # 不同類型字符的 token 權重
    estimated_tokens = (
        english_words * 1.3 +  # 英文單詞平均 1.3 tokens
        numbers * 0.5 +        # 數字通常較少 tokens
        chinese_chars * 2.0 +  # 中文字符約 2 tokens
        special_chars * 0.3 +  # 特殊字符
        code_blocks * 1.5      # 代碼塊
    )
    
    # 添加系統提示和格式化的開銷（約 10%）
    estimated_tokens *= 1.1
    
    return int(estimated_tokens)
                  
# ==========================================================================================
# android_log_analysis.py
# ==========================================================================================        

@ai_bp.route('/smart-analyze', methods=['POST'])
def smart_analyze():
    """智能分析 Android 日誌，根據模式自動選擇策略"""
    try:
        data = request.json
        content = data.get('content', '')
        file_path = data.get('file_path', '')
        analysis_mode = data.get('mode', 'auto')
        file_type = data.get('file_type', 'ANR')
        enable_thinking = data.get('enable_thinking', True)
        force_single_analysis = data.get('force_single_analysis', False)
        skip_size_check = data.get('skip_size_check', False)
        
        # 添加內容檢查
        if not content:
            return jsonify({
                'error': '檔案內容為空',
                'success': False,
                'analysis_mode': analysis_mode
            }), 400
        
        print(f"Smart analyze - mode: {analysis_mode}, file size: {len(content)}")
        print(f"Force single: {force_single_analysis}, Skip size check: {skip_size_check}")
        print(f"Content preview: {content[:200]}...")  # 打印內容預覽
        
        # 創建分析器
        analyzer = AndroidLogAnalyzer()
        
        # 檢測日誌類型
        try:
            log_type = analyzer.detect_log_type(content)
            print(f"檢測到的日誌類型: {log_type}")
        except Exception as e:
            print(f"檢測日誌類型失敗: {str(e)}")
            log_type = LogType.UNKNOWN
        
        # 記錄開始時間
        start_time = time.time()
        
        # 根據模式執行不同的分析
        result = None
        
        if analysis_mode == 'quick' or force_single_analysis:
            # 快速分析
            print("執行快速分析模式")
            result = perform_quick_analysis(analyzer, content, log_type)
            
        elif analysis_mode == 'comprehensive':
            # 深度分析
            print("執行深度分析模式")
            result = perform_comprehensive_analysis(analyzer, content, log_type, enable_thinking)
            
        elif analysis_mode == 'max_tokens':
            # 最大化分析
            print("執行最大化分析模式")
            result = perform_max_tokens_analysis(analyzer, content, log_type)
            
        else:  # auto
            # 智能模式
            print("執行智能分析模式")
            result = perform_auto_analysis(analyzer, content, log_type, enable_thinking)
        
        # 確保有結果
        if not result:
            raise Exception("分析未返回結果")
        
        # 如果結果中有錯誤，返回錯誤響應
        if result.get('error'):
            return jsonify({
                'error': result['error'],
                'success': False,
                'analysis_mode': analysis_mode
            }), 500
        
        # 計算耗時
        elapsed_time = round(time.time() - start_time, 2)
        
        # 添加通用信息
        result['elapsed_time'] = f"{elapsed_time}秒"
        result['analysis_mode'] = analysis_mode
        result['success'] = True
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Smart analysis error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': f'分析錯誤: {str(e)}',
            'success': False,
            'analysis_mode': analysis_mode if 'analysis_mode' in locals() else 'unknown'
        }), 500

def perform_quick_analysis(analyzer, content, log_type):
    """執行快速分析"""
    try:
        print(f"開始快速分析 - 日誌類型: {log_type}, 內容長度: {len(content)}")
        
        # 檢查內容是否為空
        if not content or not content.strip():
            print("錯誤：檔案內容為空")
            return {
                'analysis': '無法分析：檔案內容為空',
                'log_type': log_type.value if log_type else 'Unknown',
                'model': 'claude-3-5-haiku-20241022',
                'is_quick': True,
                'is_segmented': False,
                'error': '檔案內容為空'
            }
        
        # 先準備一個基本的分析內容（前 50KB）
        fallback_content = content[:50000] if len(content) > 50000 else content
        
        # 嘗試提取關鍵部分
        try:
            key_sections = analyzer.extract_key_sections(content, log_type)
            print(f"提取到的關鍵部分: {list(key_sections.keys())}")
        except Exception as e:
            print(f"提取關鍵部分失敗: {str(e)}")
            key_sections = {}
        
        # 構建精簡內容
        condensed_content = []
        total_chars = 0
        max_chars = 50000
        
        if log_type == LogType.ANR:
            priority_keys = ['header', 'main_thread', 'deadlocks', 'cpu_info']
        else:
            priority_keys = ['signal_info', 'abort_message', 'backtrace', 'registers']
        
        # 提取內容
        has_extracted_content = False
        for key in priority_keys:
            if key in key_sections and key_sections[key] and key_sections[key].strip():
                section_content = key_sections[key].strip()
                if total_chars + len(section_content) < max_chars:
                    condensed_content.append(f"=== {key.upper()} ===\n{section_content}")
                    total_chars += len(section_content)
                    has_extracted_content = True
                    print(f"添加了 {key} 部分，長度: {len(section_content)}")
        
        # 決定最終內容
        if has_extracted_content and condensed_content:
            final_content = '\n\n'.join(condensed_content)
            print(f"使用提取的內容，總長度: {len(final_content)}")
        else:
            # 使用備用內容
            print("無法提取關鍵部分，使用原始內容")
            final_content = fallback_content
            
            # 如果還是太短，添加一些基本信息
            if len(final_content) < 100:
                final_content = f"日誌類型: {log_type.value if log_type else 'Unknown'}\n\n{final_content}"
        
        # 最終檢查，確保有內容
        if not final_content or not final_content.strip():
            print("警告：最終內容為空，使用最小內容")
            final_content = f"無法提取有效內容。原始檔案長度：{len(content)} 字符"
        
        print(f"最終內容長度: {len(final_content)}")
        
        # 生成分析提示
        try:
            prompts = analyzer.generate_smart_prompts(key_sections, log_type, 'quick')
            if prompts and len(prompts) > 0:
                prompt = prompts[0]
            else:
                prompt = None
        except Exception as e:
            print(f"生成提示失敗: {str(e)}")
            prompt = None
        
        # 確保有有效的 prompt
        if not prompt or not prompt.get('user') or not prompt['user'].strip():
            print("使用預設 prompt")
            prompt = {
                'system': f"你是 Android {log_type.value if log_type else '日誌'} 分析專家。請快速分析並提供關鍵發現。",
                'user': f"""請分析以下 {log_type.value if log_type else '日誌'} 內容：

{final_content}

請提供：
1. 主要問題是什麼
2. 可能的原因
3. 建議的解決方案"""
            }
        else:
            # 如果 prompt 的 user 部分是空的，補充內容
            if not prompt['user'].strip():
                prompt['user'] = final_content
        
        # 最後一次檢查
        if not prompt['user'] or not prompt['user'].strip():
            raise ValueError("無法生成有效的分析內容")
        
        # 調用 Claude API
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        print(f"準備發送 API 請求:")
        print(f"- System prompt 長度: {len(prompt.get('system', ''))}")
        print(f"- User content 長度: {len(prompt.get('user', ''))}")
        print(f"- User content 前 100 字符: {prompt['user'][:100]}...")
        
        try:
            message = client.messages.create(
                model='claude-3-5-haiku-20241022',
                max_tokens=2000,
                temperature=0,
                system=prompt['system'],
                messages=[{"role": "user", "content": prompt['user']}]
            )
            
            analysis_text = message.content[0].text if message.content else "無分析結果"
            
            return {
                'analysis': analysis_text,
                'log_type': log_type.value if log_type else 'Unknown',
                'model': 'claude-3-5-haiku-20241022',
                'is_quick': True,
                'is_segmented': False,
                'analyzed_size': len(final_content),
                'original_size': len(content)
            }
            
        except anthropic.APIError as api_error:
            print(f"API 錯誤: {str(api_error)}")
            print(f"API 錯誤詳情: {api_error.response.text if hasattr(api_error, 'response') else 'No response'}")
            raise
        
    except Exception as e:
        print(f"Quick analysis error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'analysis': f'快速分析失敗: {str(e)}',
            'log_type': log_type.value if log_type else 'Unknown',
            'model': 'claude-3-5-haiku-20241022',
            'is_quick': True,
            'is_segmented': False,
            'error': str(e)
        }

def perform_comprehensive_analysis(analyzer, content, log_type, enable_thinking):
    """執行深度分析"""
    try:
        # 選擇模型
        model = 'claude-opus-4-20250514'
        model_config = MODEL_LIMITS.get(model, MODEL_LIMITS[DEFAULT_MODEL])
        
        # 檢查是否需要分段
        estimated_tokens = estimate_tokens_accurate(content)
        max_tokens = int(model_config['max_tokens'] * 0.8)
        
        if estimated_tokens > max_tokens or len(content) > 100000:
            # 需要分段
            return perform_segmented_analysis(analyzer, content, log_type, model, 'comprehensive')
        else:
            # 單次深度分析
            key_sections = analyzer.extract_key_sections(content, log_type)
            prompts = analyzer.generate_smart_prompts(key_sections, log_type, 'comprehensive')
            
            client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            
            # 使用第一個提示（或合併多個）
            message = client.messages.create(
                model=model,
                max_tokens=model_config['max_output_tokens'],
                temperature=0,
                system=prompts[0]['system'],
                messages=[{"role": "user", "content": prompts[0]['user']}]
            )
            
            return {
                'analysis': message.content[0].text if message.content else "",
                'log_type': log_type.value,
                'model': model,
                'is_segmented': False,
                'thinking': getattr(message, 'thinking', None) if enable_thinking else None
            }
            
    except Exception as e:
        print(f"Comprehensive analysis error: {str(e)}")
        raise


def perform_max_tokens_analysis(analyzer, content, log_type):
    """執行最大化分析"""
    try:
        model = 'claude-sonnet-4-20250514'
        model_config = MODEL_LIMITS.get(model, MODEL_LIMITS[DEFAULT_MODEL])
        
        # 提取關鍵部分
        key_sections = analyzer.extract_key_sections(content, log_type)
        
        # 生成提示
        prompts = analyzer.generate_smart_prompts(key_sections, log_type, 'max_tokens')
        
        # 檢查 prompts 是否為空
        if not prompts or len(prompts) == 0:
            # 使用預設提示
            prompt = {
                'system': f"你是 Android {log_type.value} 分析專家。請提供全面深入的分析。",
                'user': f"""請分析以下 {log_type.value} 日誌，提供最大化的分析內容：

{content[:int(model_config['max_tokens'] * 2.5 * 0.8)]}

請提供：
1. 問題摘要（2-3句話）
2. 根本原因分析（詳細）
3. 影響範圍
4. 修復方案（短期和長期）
5. 預防措施"""
            }
        else:
            prompt = prompts[0]
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        message = client.messages.create(
            model=model,
            max_tokens=model_config['max_output_tokens'],
            temperature=0,
            system=prompt['system'],
            messages=[{"role": "user", "content": prompt['user']}]
        )
        
        return {
            'analysis': message.content[0].text if message.content else "",
            'log_type': log_type.value,
            'model': model,
            'is_segmented': False,
            'content_coverage': f"{len(prompt['user'])}/{len(content)} 字符"
        }
        
    except Exception as e:
        print(f"Max tokens analysis error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'analysis': f'最大化分析失敗: {str(e)}',
            'log_type': log_type.value,
            'model': model if 'model' in locals() else 'claude-sonnet-4-20250514',
            'is_segmented': False,
            'error': str(e)
        }


def perform_auto_analysis(analyzer, content, log_type, enable_thinking):
    """執行智能分析"""
    try:
        content_size = len(content)
        estimated_tokens = estimate_tokens_accurate(content)
        
        # 根據大小選擇策略
        if estimated_tokens < 50000:
            # 小檔案：快速分析
            return perform_quick_analysis(analyzer, content, log_type)
        elif estimated_tokens < 150000:
            # 中等檔案：標準分析
            model = 'claude-3-5-sonnet-20241022'
            key_sections = analyzer.extract_key_sections(content, log_type)
            prompts = analyzer.generate_smart_prompts(key_sections, log_type, 'auto')
            
            # 檢查 prompts 是否為空
            if not prompts:
                # 如果沒有生成提示，使用預設提示
                prompts = [{
                    'system': f"你是 Android {log_type.value} 分析專家。請分析這個日誌檔案。",
                    'user': content[:50000]  # 限制內容長度
                }]
            
            client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            
            message = client.messages.create(
                model=model,
                max_tokens=4000,
                temperature=0,
                system=prompts[0]['system'],
                messages=[{"role": "user", "content": prompts[0]['user']}]
            )
            
            return {
                'analysis': message.content[0].text if message.content else "",
                'log_type': log_type.value,
                'model': model,
                'is_segmented': False
            }
        else:
            # 大檔案：分段分析
            model = 'claude-sonnet-4-20250514'
            return perform_segmented_analysis(analyzer, content, log_type, model, 'auto')
            
    except Exception as e:
        print(f"Auto analysis error: {str(e)}")
        raise


def perform_segmented_analysis(analyzer, content, log_type, model, mode):
    """執行分段分析"""
    try:
        # 創建分段
        if log_type == LogType.ANR:
            segments = create_anr_segments(content)
        elif log_type == LogType.TOMBSTONE:
            segments = create_tombstone_segments(content)
        else:
            segments = create_intelligent_segments_v2(content, model)
        
        print(f"創建了 {len(segments)} 個分段")
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        segment_results = []
        errors = []
        
        # 分析每個段落
        for i, segment in enumerate(segments):
            try:
                segment_content = segment.get('content', '')
                segment_tokens = estimate_tokens_accurate(segment_content)
                
                # 檢查速率限制
                wait_time = rate_limiter.get_wait_time(segment_tokens)
                if wait_time > 0:
                    print(f"段落 {i+1} 需要等待 {wait_time:.1f} 秒")
                    time.sleep(wait_time)
                
                rate_limiter.use_tokens(segment_tokens)
                
                # 生成提示
                prompt = {
                    'system': f"分析第 {i+1}/{len(segments)} 段 {log_type.value} 日誌。",
                    'user': segment_content[:50000]  # 限制長度
                }
                
                # 調用 API
                message = client.messages.create(
                    model=model,
                    max_tokens=3000,
                    temperature=0,
                    system=prompt['system'],
                    messages=[{"role": "user", "content": prompt['user']}]
                )
                
                segment_results.append({
                    'segment_number': i + 1,
                    'analysis': message.content[0].text if message.content else "",
                    'success': True
                })
                
            except Exception as e:
                print(f"段落 {i+1} 分析失敗: {str(e)}")
                errors.append({'segment': i + 1, 'error': str(e)})
                segment_results.append({
                    'segment_number': i + 1,
                    'error': str(e),
                    'success': False
                })
        
        # 生成綜合報告
        final_report = generate_final_report_simple(segment_results, log_type, mode)
        
        return {
            'analysis': final_report,
            'log_type': log_type.value,
            'model': model,
            'is_segmented': True,
            'total_segments': len(segments),
            'segment_results': segment_results,
            'errors': errors
        }
        
    except Exception as e:
        print(f"Segmented analysis error: {str(e)}")
        raise

def generate_final_report_simple(segment_results, log_type, mode):
    """生成簡單的最終報告"""
    successful = [r for r in segment_results if r.get('success')]
    
    if not successful:
        return '所有段落分析都失敗了。'
    
    report = f"# {log_type.value} 分析報告\n\n"
    report += f"成功分析 {len(successful)}/{len(segment_results)} 個段落。\n\n"
    
    # 提取關鍵發現
    report += "## 主要發現\n\n"
    
    for seg in successful[:5]:  # 只顯示前5個
        if seg.get('analysis'):
            # 提取第一段
            first_para = seg['analysis'].split('\n\n')[0] if '\n\n' in seg['analysis'] else seg['analysis'][:200]
            report += f"**段落 {seg['segment_number']}**: {first_para}\n\n"
    
    if len(successful) > 5:
        report += f"... 還有 {len(successful) - 5} 個段落\n"
    
    return report

async def analyze_single_smart(analyzer, content, log_type, model, mode, enable_thinking):
    """智能單次分析"""
    try:
        # 提取關鍵部分
        key_sections = analyzer.extract_key_sections(content, log_type)
        
        # 根據模式生成提示
        prompts = analyzer.generate_smart_prompts(key_sections, log_type, mode)
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        # 根據模式調整輸出長度
        output_tokens = {
            'quick': 2000,
            'auto': 4000,
            'comprehensive': MODEL_LIMITS[model]['max_output_tokens'],
            'max_tokens': MODEL_LIMITS[model]['max_output_tokens']
        }
        
        max_output = output_tokens.get(mode, 4000)
        
        # 調用 API
        message = client.messages.create(
            model=model,
            max_tokens=max_output,
            temperature=0,
            system=prompts[0]['system'],
            messages=[{"role": "user", "content": prompts[0]['user']}]
        )
        
        analysis_text = message.content[0].text if message.content else ""
        thinking_text = getattr(message, 'thinking', None) if enable_thinking else None
        
        # 解析結果
        result = parse_analysis_result(analysis_text, log_type)
        
        return {
            'success': True,
            'analysis': analysis_text,
            'analysis_mode': mode,
            'log_type': log_type.value,
            'model': model,
            'result': result,
            'detailed_analysis': analysis_text,
            'thinking': thinking_text,
            'is_segmented': False,
            'total_segments': 1
        }
        
    except Exception as e:
        print(f"Single analysis error: {str(e)}")
        raise

async def analyze_in_segments_smart_v2(analyzer, content, log_type, model, mode, enable_thinking):
    """智能分段分析"""
    try:
        # 根據日誌類型創建智能分段
        if log_type == LogType.ANR:
            segments = create_anr_segments(content)
        elif log_type == LogType.TOMBSTONE:
            segments = create_tombstone_segments(content)
        else:
            segments = create_intelligent_segments_v2(content, model)
        
        print(f"創建了 {len(segments)} 個分段")
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        segment_results = []
        errors = []
        
        # 分析每個段落
        for i, segment in enumerate(segments):
            try:
                # 速率限制檢查
                segment_content = segment.get('content', '')
                segment_tokens = estimate_tokens_accurate(segment_content)
                wait_time = rate_limiter.get_wait_time(segment_tokens)
                
                if wait_time > 0:
                    print(f"段落 {i+1} 需要等待 {wait_time:.1f} 秒")
                    await asyncio.sleep(wait_time)
                
                # 記錄 token 使用
                rate_limiter.use_tokens(segment_tokens)
                
                # 生成段落提示
                if log_type == LogType.ANR:
                    prompt = generate_anr_segment_prompt(segment, i, len(segments))
                elif log_type == LogType.TOMBSTONE:
                    prompt = generate_tombstone_segment_prompt(segment, i, len(segments))
                else:
                    # 通用提示
                    prompt = {
                        'system': f"分析第 {i+1}/{len(segments)} 段。",
                        'user': segment_content
                    }
                
                # 調用 API
                message = client.messages.create(
                    model=model,
                    max_tokens=3000,
                    temperature=0,
                    system=prompt['system'],
                    messages=[{"role": "user", "content": prompt['user']}]
                )
                
                segment_results.append({
                    'segment_number': i + 1,
                    'analysis': message.content[0].text if message.content else "",
                    'success': True,
                    'tokens_used': segment_tokens
                })
                
            except Exception as e:
                print(f"段落 {i+1} 分析失敗: {str(e)}")
                errors.append({
                    'segment': i + 1,
                    'error': str(e)
                })
                segment_results.append({
                    'segment_number': i + 1,
                    'error': str(e),
                    'success': False
                })
        
        # 生成綜合報告
        final_report = generate_smart_final_report_v2(segment_results, log_type, mode)
        
        return {
            'success': True,
            'analysis': final_report,
            'analysis_mode': mode,
            'log_type': log_type.value,
            'model': model,
            'is_segmented': True,
            'total_segments': len(segments),
            'segment_results': segment_results,
            'errors': errors
        }
        
    except Exception as e:
        print(f"Segmented analysis error: {str(e)}")
        raise

def generate_smart_final_report_v2(segment_results, log_type, mode):
    """生成智能最終報告"""
    successful_segments = [r for r in segment_results if r.get('success')]
    
    if not successful_segments:
        return '所有段落分析都失敗了，無法生成綜合報告。'
    
    # 提取每個段落的關鍵信息
    key_findings = []
    for seg in successful_segments:
        if seg.get('analysis'):
            # 提取前幾行作為摘要
            lines = seg['analysis'].split('\n')
            summary = ' '.join(lines[:3]) if len(lines) >= 3 else seg['analysis']
            key_findings.append(f"段落 {seg['segment_number']}: {summary}")
    
    # 構建報告
    report = f"""# {log_type.value} 分析報告

## 分析概況
- 分析模式：{mode}
- 總段落數：{len(segment_results)}
- 成功分析：{len(successful_segments)} 段

## 主要發現

"""
    
    # 添加關鍵發現
    for finding in key_findings[:10]:  # 最多顯示10個
        report += f"- {finding}\n"
    
    if len(key_findings) > 10:
        report += f"\n... 還有 {len(key_findings) - 10} 個段落的發現\n"
    
    return report

async def quick_analysis_direct_v2(analyzer, content, log_type, model, file_path):
    """快速分析的直接實現 - 確保不會分段"""
    try:
        print(f"執行快速分析 - 日誌類型: {log_type}, 檔案大小: {len(content)}")
        
        # 提取最關鍵的部分（限制在 50KB）
        key_sections = analyzer.extract_key_sections(content, log_type)
        
        # 構建精簡的內容
        condensed_content = []
        total_chars = 0
        max_chars = 50000  # 50KB
        
        # 根據日誌類型選擇優先順序
        if log_type == LogType.ANR:
            priority_keys = ['header', 'main_thread', 'deadlocks', 'cpu_info']
        else:  # Tombstone
            priority_keys = ['signal_info', 'abort_message', 'backtrace', 'registers']
        
        # 按優先順序提取內容
        for key in priority_keys:
            if key in key_sections and key_sections[key]:
                section_content = key_sections[key]
                if total_chars + len(section_content) < max_chars:
                    condensed_content.append(f"=== {key.upper()} ===\n{section_content}")
                    total_chars += len(section_content)
        
        # 如果內容太少，補充一些原始內容
        if total_chars < 10000 and len(content) > 10000:
            # 添加檔案開頭
            header_size = min(5000, max_chars - total_chars)
            condensed_content.insert(0, f"=== FILE HEADER ===\n{content[:header_size]}")
            total_chars += header_size
        
        final_content = '\n\n'.join(condensed_content)
        
        print(f"快速分析：提取了 {total_chars} 字符的關鍵內容")
        
        # 生成快速分析提示
        prompts = analyzer.generate_smart_prompts(key_sections, log_type, 'quick')
        prompt = prompts[0] if prompts else {
            'system': f"你是 Android {log_type.value} 專家。請快速分析並提供關鍵發現。",
            'user': final_content
        }
        
        # 調用 Claude API
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        message = client.messages.create(
            model=model,
            max_tokens=2000,  # 限制輸出長度
            temperature=0,
            system=prompt['system'],
            messages=[{"role": "user", "content": prompt['user']}]
        )
        
        analysis_text = message.content[0].text if message.content else "無分析結果"
        
        # 返回結果
        return {
            'success': True,
            'analysis': analysis_text,
            'analysis_mode': 'quick',
            'log_type': log_type.value,
            'model': model,
            'is_quick': True,
            'is_segmented': False,  # 重要：標記為非分段
            'analyzed_size': total_chars,
            'original_size': len(content),
            'key_sections_found': len(condensed_content)
        }
        
    except Exception as e:
        print(f"Quick analysis error: {str(e)}")
        return {
            'success': False,
            'error': f'快速分析失敗: {str(e)}',
            'analysis_mode': 'quick'
        }
    
async def quick_analysis_strategy_v2(analyzer, content, log_type, model):
    """快速分析策略 - 返回統一格式"""
    try:
        # 提取關鍵部分（最多 50KB）
        key_sections = analyzer.extract_key_sections(content, log_type)
        
        # 構建精簡的內容
        condensed_content = []
        total_chars = 0
        max_chars = 50000  # 50KB
        
        if log_type == LogType.ANR:
            priority_keys = ['header', 'main_thread', 'deadlocks', 'cpu_info']
        else:
            priority_keys = ['signal_info', 'abort_message', 'backtrace']
        
        for key in priority_keys:
            if key in key_sections and key_sections[key]:
                section_content = key_sections[key]
                if total_chars + len(section_content) < max_chars:
                    condensed_content.append(f"=== {key.upper()} ===\n{section_content}")
                    total_chars += len(section_content)
        
        final_content = '\n\n'.join(condensed_content)
        
        # 生成快速分析提示
        prompts = analyzer.generate_smart_prompts(key_sections, log_type, 'quick')
        prompt = prompts[0]
        
        # 調用 API
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        message = client.messages.create(
            model=model,
            max_tokens=2000,
            temperature=0,
            system=prompt['system'],
            messages=[{"role": "user", "content": final_content}]
        )
        
        analysis_text = message.content[0].text if message.content else ""
        
        # 返回統一格式
        return {
            'success': True,
            'analysis': analysis_text,
            'analysis_mode': 'quick',
            'log_type': log_type.value,
            'model': model,
            'analyzed_size': total_chars,
            'original_size': len(content),
            'is_segmented': False
        }
        
    except Exception as e:
        print(f"Quick analysis error: {str(e)}")
        raise

async def comprehensive_analysis_strategy_v2(analyzer, content, log_type, model, enable_thinking):
    """深度分析策略 - 返回統一格式"""
    try:
        # 檢查是否需要分段
        estimated_tokens = estimate_tokens_accurate(content)
        model_config = MODEL_LIMITS.get(model)
        max_tokens = int(model_config['max_tokens'] * 0.8)
        
        if estimated_tokens > max_tokens:
            # 需要分段分析
            return await segmented_analysis_v2(
                analyzer, content, log_type, model, 'comprehensive', enable_thinking
            )
        else:
            # 單次深度分析
            key_sections = analyzer.extract_key_sections(content, log_type)
            prompts = analyzer.generate_smart_prompts(key_sections, log_type, 'comprehensive')
            
            client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            
            # 使用所有提示進行深度分析
            all_analyses = []
            for prompt in prompts:
                message = client.messages.create(
                    model=model,
                    max_tokens=model_config['max_output_tokens'],
                    temperature=0,
                    system=prompt['system'],
                    messages=[{"role": "user", "content": prompt['user']}]
                )
                all_analyses.append(message.content[0].text if message.content else "")
            
            # 合併所有分析
            comprehensive_analysis = "\n\n".join(all_analyses)
            
            return {
                'success': True,
                'analysis': comprehensive_analysis,
                'analysis_mode': 'comprehensive',
                'log_type': log_type.value,
                'model': model,
                'is_segmented': False,
                'thinking': getattr(message, 'thinking', None) if enable_thinking else None
            }
            
    except Exception as e:
        print(f"Comprehensive analysis error: {str(e)}")
        raise

async def max_tokens_analysis_strategy_v2(analyzer, content, log_type, model):
    """最大化分析策略 - 返回統一格式"""
    try:
        model_config = MODEL_LIMITS.get(model)
        max_input = int(model_config['max_tokens'] * 0.85)
        
        # 提取並優先選擇內容
        key_sections = analyzer.extract_key_sections(content, log_type)
        
        # 生成最大化分析提示
        prompts = analyzer.generate_smart_prompts(key_sections, log_type, 'max_tokens')
        prompt = prompts[0]
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        message = client.messages.create(
            model=model,
            max_tokens=model_config['max_output_tokens'],
            temperature=0,
            system=prompt['system'],
            messages=[{"role": "user", "content": prompt['user']}]
        )
        
        return {
            'success': True,
            'analysis': message.content[0].text if message.content else "",
            'analysis_mode': 'max_tokens',
            'log_type': log_type.value,
            'model': model,
            'content_coverage': f"{len(prompt['user'])}/{len(content)} 字符",
            'is_segmented': False
        }
        
    except Exception as e:
        print(f"Max tokens analysis error: {str(e)}")
        raise

async def auto_analysis_strategy_v2(analyzer, content, log_type, model, enable_thinking):
    """智能分析策略 - 自動選擇最佳方法"""
    content_size = len(content)
    estimated_tokens = estimate_tokens_accurate(content)
    
    print(f"Auto analysis: size={content_size}, tokens={estimated_tokens}")
    
    # 根據內容特徵自動決定
    if estimated_tokens < 50000:
        # 小檔案：快速分析
        return await quick_analysis_strategy_v2(analyzer, content, log_type, model)
    elif estimated_tokens < 150000:
        # 中等檔案：標準分析
        return await comprehensive_analysis_strategy_v2(
            analyzer, content, log_type, model, enable_thinking
        )
    else:
        # 大檔案：分段分析
        return await segmented_analysis_v2(
            analyzer, content, log_type, model, 'auto', enable_thinking
        )


async def segmented_analysis_v2(analyzer, content, log_type, model, mode, enable_thinking):
    """統一的分段分析函數"""
    try:
        # 創建分段
        if log_type == LogType.ANR:
            segments = create_anr_segments(content)
        elif log_type == LogType.TOMBSTONE:
            segments = create_tombstone_segments(content)
        else:
            segments = create_intelligent_segments_v2(content, model)
        
        print(f"創建了 {len(segments)} 個分段")
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        segment_results = []
        
        # 分析每個段落
        for i, segment in enumerate(segments):
            try:
                # 生成段落提示
                if log_type == LogType.ANR:
                    prompt = generate_anr_segment_prompt(segment, i, len(segments))
                elif log_type == LogType.TOMBSTONE:
                    prompt = generate_tombstone_segment_prompt(segment, i, len(segments))
                else:
                    prompt = build_segment_prompt_v2(segment, '', '', '', model)
                
                # 調用 API
                message = client.messages.create(
                    model=model,
                    max_tokens=3000,
                    temperature=0,
                    system=prompt['system'],
                    messages=[{"role": "user", "content": prompt['user']}]
                )
                
                segment_results.append({
                    'segment_number': i + 1,
                    'analysis': message.content[0].text if message.content else "",
                    'success': True
                })
                
            except Exception as e:
                print(f"段落 {i+1} 分析失敗: {str(e)}")
                segment_results.append({
                    'segment_number': i + 1,
                    'error': str(e),
                    'success': False
                })
        
        # 生成綜合報告
        final_analysis = generate_final_report(segment_results, log_type)
        
        return {
            'success': True,
            'analysis': final_analysis,
            'analysis_mode': mode,
            'log_type': log_type.value,
            'model': model,
            'is_segmented': True,
            'total_segments': len(segments),
            'segments': segment_results
        }
        
    except Exception as e:
        print(f"Segmented analysis error: {str(e)}")
        raise


def generate_final_report(segment_results, log_type):
    """生成最終的綜合報告"""
    successful_segments = [s for s in segment_results if s.get('success')]
    
    if not successful_segments:
        return "所有段落分析都失敗了"
    
    report = f"# {log_type.value} 綜合分析報告\n\n"
    report += f"成功分析了 {len(successful_segments)}/{len(segment_results)} 個段落。\n\n"
    
    # 提取關鍵發現
    report += "## 主要發現\n\n"
    for seg in successful_segments[:5]:  # 只顯示前5個段落的摘要
        analysis = seg.get('analysis', '')
        if analysis:
            # 提取第一段作為摘要
            first_para = analysis.split('\n\n')[0] if '\n\n' in analysis else analysis[:200]
            report += f"**段落 {seg['segment_number']}**: {first_para}\n\n"
    
    return report

async def quick_analysis_direct(content, file_path, model):
    """快速分析的直接實現 - 不分段"""
    try:
        # 提取最關鍵的 50KB 內容
        key_sections = []
        total_size = 0
        max_size = 50000
        
        # 1. 檔案頭部（重要的元信息）
        header_size = min(2000, len(content))
        key_sections.append(("檔案開頭", content[:header_size]))
        total_size += header_size
        
        # 2. 查找關鍵錯誤模式
        critical_patterns = [
            (r'FATAL EXCEPTION.*?(?=\n\n|\Z)', "致命異常"),
            (r'AndroidRuntime.*?(?=\n\n|\Z)', "運行時錯誤"),
            (r'signal \d+.*?(?=\n\n|\Z)', "信號錯誤"),
            (r'Abort message.*?(?=\n\n|\Z)', "中止消息"),
            (r'"main".*?held by.*?(?=\n\n|\Z)', "主線程阻塞"),
        ]
        
        for pattern, label in critical_patterns:
            if total_size >= max_size:
                break
            matches = list(re.finditer(pattern, content, re.DOTALL | re.IGNORECASE))
            if matches:
                # 只取第一個匹配
                match_content = matches[0].group(0)
                if total_size + len(match_content) <= max_size:
                    key_sections.append((label, match_content))
                    total_size += len(match_content)
        
        # 組合關鍵部分
        final_content = "\n\n===== 關鍵部分提取 =====\n\n".join([
            f"【{label}】\n{content}" for label, content in key_sections
        ])
        
        # 調用 Claude API
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        message = client.messages.create(
            model=model,
            max_tokens=2000,
            temperature=0,
            system="""你是 Android 專家。快速分析提供的關鍵日誌部分。
請在 30 秒內提供簡潔的分析，包含：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 問題是什麼？（1句話）
5. 為什麼發生？（1-2句話）
6. 如何修復？（2-3個要點）

使用簡潔明瞭的語言，直接給出結論。""",
            messages=[{"role": "user", "content": final_content}]
        )
        
        return jsonify({
            'success': True,
            'analysis': message.content[0].text if message.content else "",
            'analysis_mode': 'quick',
            'is_quick': True,
            'model': model,
            'analyzed_size': total_size,
            'original_size': len(content),
            'key_sections_found': len(key_sections)
        })
        
    except Exception as e:
        print(f"Quick analysis error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'快速分析失敗: {str(e)}'
        }), 500
    
async def segmented_analysis_improved(analyzer, content, log_type, model, mode, enable_thinking):
    """改進的分段分析"""
    try:
        # 根據日誌類型創建智能分段
        if log_type == LogType.ANR:
            segments = create_anr_segments(content)
        elif log_type == LogType.TOMBSTONE:
            segments = create_tombstone_segments(content)
        else:
            segments = create_intelligent_segments_v2(content, model)
        
        print(f"創建了 {len(segments)} 個分段")
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        segment_results = []
        errors = []
        
        # 分析每個段落
        for i, segment in enumerate(segments):
            try:
                # 速率限制檢查
                segment_tokens = estimate_tokens_accurate(segment.get('content', ''))
                wait_time = rate_limiter.get_wait_time(segment_tokens)
                
                if wait_time > 0:
                    print(f"段落 {i+1} 需要等待 {wait_time:.1f} 秒")
                    await asyncio.sleep(wait_time)
                
                # 記錄 token 使用
                rate_limiter.use_tokens(segment_tokens)
                
                # 生成段落提示
                if log_type == LogType.ANR:
                    prompt = generate_anr_segment_prompt(segment, i, len(segments))
                elif log_type == LogType.TOMBSTONE:
                    prompt = generate_tombstone_segment_prompt(segment, i, len(segments))
                else:
                    prompt = build_segment_prompt_v2(segment, '', '', '', model)
                
                # 調用 API
                message = await asyncio.to_thread(
                    client.messages.create,
                    model=model,
                    max_tokens=3000,
                    temperature=0,
                    system=prompt['system'],
                    messages=[{"role": "user", "content": prompt['user']}]
                )
                
                segment_results.append({
                    'segment_number': i + 1,
                    'analysis': message.content[0].text if message.content else "",
                    'success': True,
                    'tokens_used': segment_tokens
                })
                
            except Exception as e:
                print(f"段落 {i+1} 分析失敗: {str(e)}")
                errors.append({
                    'segment': i + 1,
                    'error': str(e)
                })
                segment_results.append({
                    'segment_number': i + 1,
                    'error': str(e),
                    'success': False
                })
        
        # 生成綜合報告
        if any(r.get('success') for r in segment_results):
            final_report = generate_smart_final_report(segment_results, log_type, analyzer)
        else:
            final_report = {'error': '所有段落分析都失敗了'}
        
        return jsonify({
            'success': True,
            'analysis_mode': mode,
            'log_type': log_type.value,
            'model': model,
            'is_segmented': True,
            'total_segments': len(segments),
            'segment_results': segment_results,
            'final_report': final_report,
            'result': final_report,  # 兼容前端
            'errors': errors
        })
        
    except Exception as e:
        return jsonify({
            'error': f'分段分析失敗: {str(e)}',
            'success': False
        }), 500
    
async def single_analysis_improved(analyzer, content, log_type, model, mode, enable_thinking):
    """改進的單次分析"""
    try:
        # 提取關鍵部分
        key_sections = analyzer.extract_key_sections(content, log_type)
        
        # 根據模式生成提示
        prompts = analyzer.generate_smart_prompts(key_sections, log_type, mode)
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        # 根據模式調整輸出長度
        output_tokens = {
            'quick': 2000,
            'auto': 4000,
            'comprehensive': MODEL_LIMITS[model]['max_output_tokens'],
            'max_tokens': MODEL_LIMITS[model]['max_output_tokens']
        }
        
        max_output = output_tokens.get(mode, 4000)
        
        # 調用 API
        message = await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=max_output,
            temperature=0,
            system=prompts[0]['system'],
            messages=[{"role": "user", "content": prompts[0]['user']}]
        )
        
        analysis_text = message.content[0].text if message.content else ""
        thinking_text = getattr(message, 'thinking', None) if enable_thinking else None
        
        # 結構化解析
        result = parse_detailed_analysis(analysis_text, log_type)
        
        return jsonify({
            'success': True,
            'analysis_mode': mode,
            'log_type': log_type.value,
            'model': model,
            'result': result,
            'detailed_analysis': analysis_text,
            'thinking': thinking_text,
            'is_segmented': False,
            'total_segments': 1
        })
        
    except Exception as e:
        return jsonify({
            'error': f'分析失敗: {str(e)}',
            'success': False
        }), 500
    
async def quick_analysis_direct(analyzer, content, log_type, model):
    """快速分析 - 只分析最關鍵的部分"""
    try:
        # 提取關鍵部分（限制在 50KB 以內）
        key_sections = analyzer.extract_key_sections(content, log_type)
        
        # 構建精簡的內容
        condensed_content = []
        total_chars = 0
        max_chars = 50000  # 50KB
        
        # 優先級順序
        if log_type == LogType.ANR:
            priority_keys = ['header', 'main_thread', 'deadlocks', 'cpu_info']
        else:
            priority_keys = ['signal_info', 'abort_message', 'backtrace']
        
        for key in priority_keys:
            if key in key_sections and key_sections[key]:
                section_content = key_sections[key]
                if total_chars + len(section_content) < max_chars:
                    condensed_content.append(f"=== {key.upper()} ===\n{section_content}")
                    total_chars += len(section_content)
        
        final_content = '\n\n'.join(condensed_content)
        
        # 快速分析提示
        prompts = analyzer.generate_smart_prompts(key_sections, log_type, 'quick')
        prompt = prompts[0]
        
        # 調用 API
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        message = await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=2000,  # 快速分析用較少的輸出
            temperature=0,
            system=prompt['system'],
            messages=[{"role": "user", "content": final_content + "\n\n" + prompt['user']}]
        )
        
        analysis_text = message.content[0].text if message.content else ""
        
        # 解析結果
        result = parse_analysis_result(analysis_text, log_type)
        
        return jsonify({
            'success': True,
            'analysis_mode': 'quick',
            'log_type': log_type.value,
            'model': model,
            'result': result,
            'detailed_analysis': analysis_text,
            'is_segmented': False,
            'total_segments': 1,
            'content_size': len(content),
            'analyzed_size': total_chars
        })
        
    except Exception as e:
        print(f"Quick analysis error: {str(e)}")
        return jsonify({
            'error': f'快速分析失敗: {str(e)}',
            'success': False
        }), 500
    
async def quick_analysis(analyzer, sections, log_type, model):
    """快速分析模式"""
    prompts = analyzer.generate_smart_prompts(sections, log_type, 'quick')
    
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    
    # 只使用第一個提示
    prompt = prompts[0]
    
    try:
        message = await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=4000,
            temperature=0,
            system=prompt['system'],
            messages=[{"role": "user", "content": prompt['user']}]
        )
        
        analysis = message.content[0].text if message.content else ""
        
        # 解析分析結果
        result = parse_analysis_result(analysis, log_type)
        
        return jsonify({
            'success': True,
            'analysis_mode': 'quick',
            'log_type': log_type.value,
            'model': model,
            'result': result,
            'raw_analysis': analysis
        })
        
    except Exception as e:
        return jsonify({'error': f'快速分析失敗: {str(e)}'}), 500

async def comprehensive_analysis(analyzer, sections, log_type, model):
    """全面分析模式"""
    prompts = analyzer.generate_smart_prompts(sections, log_type, 'comprehensive')
    
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    
    all_analyses = []
    
    # 分段分析
    for i, prompt in enumerate(prompts):
        try:
            # 檢查速率限制
            wait_time = rate_limiter.get_wait_time(10000)  # 估算 tokens
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            message = await asyncio.to_thread(
                client.messages.create,
                model=model,
                max_tokens=4000,
                temperature=0,
                system=prompt['system'],
                messages=[{"role": "user", "content": prompt['user']}]
            )
            
            analysis = message.content[0].text if message.content else ""
            all_analyses.append({
                'part': i + 1,
                'analysis': analysis
            })
            
            # 記錄 token 使用
            rate_limiter.use_tokens(10000)
            
        except Exception as e:
            all_analyses.append({
                'part': i + 1,
                'error': str(e)
            })
    
    # 綜合所有分析
    final_result = synthesize_comprehensive_analysis(all_analyses, log_type)
    
    return jsonify({
        'success': True,
        'analysis_mode': 'comprehensive',
        'log_type': log_type.value,
        'model': model,
        'parts': all_analyses,
        'final_result': final_result
    })

async def max_token_analysis(analyzer, sections, log_type, model):
    """最大 token 分析模式"""
    prompts = analyzer.generate_smart_prompts(sections, log_type, 'max_tokens')
    prompt = prompts[0]
    
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    
    try:
        # 使用模型的最大輸出能力
        model_config = MODEL_LIMITS.get(model, MODEL_LIMITS['claude-sonnet-4-20250514'])
        
        message = await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=model_config['max_output_tokens'],
            temperature=0,
            system=prompt['system'],
            messages=[{"role": "user", "content": prompt['user']}]
        )
        
        analysis = message.content[0].text if message.content else ""
        
        # 結構化解析
        result = parse_detailed_analysis(analysis, log_type)
        
        return jsonify({
            'success': True,
            'analysis_mode': 'max_tokens',
            'log_type': log_type.value,
            'model': model,
            'tokens_used': estimate_tokens_accurate(prompt['user']),
            'result': result,
            'detailed_analysis': analysis
        })
        
    except Exception as e:
        return jsonify({'error': f'最大 token 分析失敗: {str(e)}'}), 500

async def segmented_smart_analysis(analyzer, content, log_type, model):
    """智能分段分析"""
    # 根據日誌結構智能分段
    if log_type == LogType.ANR:
        segments = create_anr_segments(content)
    elif log_type == LogType.TOMBSTONE:
        segments = create_tombstone_segments(content)
    else:
        segments = create_intelligent_segments_v2(content, model)
    
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    
    segment_results = []
    
    # 並行分析優化
    from concurrent.futures import ThreadPoolExecutor
    import asyncio
    
    async def analyze_segment(segment, index):
        try:
            # 為每個段落生成專門的提示
            if log_type == LogType.ANR:
                prompt = generate_anr_segment_prompt(segment, index, len(segments))
            elif log_type == LogType.TOMBSTONE:
                prompt = generate_tombstone_segment_prompt(segment, index, len(segments))
            else:
                prompt = build_segment_prompt_v2(segment, 'Unknown', '', '', model)
            
            # 速率限制檢查
            estimated_tokens = estimate_tokens_accurate(prompt['user'])
            wait_time = rate_limiter.get_wait_time(estimated_tokens)
            
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            # 調用 API
            message = await asyncio.to_thread(
                client.messages.create,
                model=model,
                max_tokens=3000,
                temperature=0,
                system=prompt['system'],
                messages=[{"role": "user", "content": prompt['user']}]
            )
            
            rate_limiter.use_tokens(estimated_tokens)
            
            return {
                'segment': index + 1,
                'success': True,
                'analysis': message.content[0].text if message.content else "",
                'tokens': estimated_tokens
            }
            
        except Exception as e:
            return {
                'segment': index + 1,
                'success': False,
                'error': str(e)
            }
    
    # 批次並行處理
    batch_size = 2  # 同時處理 2 個段落
    for i in range(0, len(segments), batch_size):
        batch = segments[i:i+batch_size]
        tasks = [analyze_segment(seg, i+j) for j, seg in enumerate(batch)]
        results = await asyncio.gather(*tasks)
        segment_results.extend(results)
    
    # 生成最終報告
    final_report = generate_smart_final_report(segment_results, log_type, analyzer)
    
    return jsonify({
        'success': True,
        'analysis_mode': 'segmented',
        'log_type': log_type.value,
        'model': model,
        'total_segments': len(segments),
        'segment_results': segment_results,
        'final_report': final_report
    })

def create_anr_segments(content: str) -> List[Dict]:
    """為 ANR 日誌創建智能分段"""
    segments = []
    
    # ANR 的自然分段點
    segment_markers = [
        (r'\n----- pid \d+', 'Process Section'),
        (r'\nCmd line:', 'Command Line'),
        (r'\n".*?" prio=\d+', 'Thread Section'),
        (r'\nHeld by thread', 'Lock Information'),
        (r'\nCPU usage', 'CPU Statistics'),
        (r'\nTotal memory', 'Memory Statistics')
    ]
    
    current_pos = 0
    content_length = len(content)
    
    # 首先提取頭部信息
    header_end = min(5000, content_length)
    segments.append({
        'content': content[:header_end],
        'type': 'header',
        'description': 'ANR 頭部信息和概要'
    })
    current_pos = header_end
    
    # 按自然分段點分割
    while current_pos < content_length:
        best_match = None
        best_pos = content_length
        best_type = 'unknown'
        
        # 尋找下一個分段點
        for pattern, seg_type in segment_markers:
            match = re.search(pattern, content[current_pos:current_pos+100000])
            if match and match.start() < best_pos:
                best_match = match
                best_pos = match.start()
                best_type = seg_type
        
        if best_match:
            segment_end = current_pos + best_pos
            if segment_end > current_pos:
                segments.append({
                    'content': content[current_pos:segment_end],
                    'type': best_type,
                    'description': f'{best_type} 部分'
                })
            current_pos = segment_end
        else:
            # 沒有找到更多標記，添加剩餘內容
            segments.append({
                'content': content[current_pos:],
                'type': 'remainder',
                'description': '剩餘內容'
            })
            break
    
    return segments

def create_tombstone_segments(content: str) -> List[Dict]:
    """為 Tombstone 日誌創建智能分段"""
    segments = []
    
    # Tombstone 的關鍵部分
    sections = [
        (r'\*\*\* \*\*\*.*?(?=\n\n)', 'header', 'Tombstone 頭部'),
        (r'Build fingerprint:.*?(?=\n\n)', 'build_info', '構建信息'),
        (r'ABI:.*?(?=\n)', 'abi_info', 'ABI 信息'),
        (r'signal \d+.*?(?=\n\n)', 'signal_info', '信號信息'),
        (r'Abort message:.*?(?=\n)', 'abort_message', '中止消息'),
        (r'registers:.*?(?=backtrace:|$)', 'registers', '寄存器狀態'),
        (r'backtrace:.*?(?=stack:|memory map:|$)', 'backtrace', '堆棧追蹤'),
        (r'stack:.*?(?=memory map:|$)', 'stack', '堆棧內容'),
        (r'memory map:.*?(?=open files:|$)', 'memory_map', '內存映射'),
        (r'open files:.*?$', 'open_files', '打開的文件')
    ]
    
    for pattern, seg_type, description in sections:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            segments.append({
                'content': match.group(0),
                'type': seg_type,
                'description': description,
                'start': match.start(),
                'end': match.end()
            })
    
    # 如果沒有找到標準結構，使用通用分段
    if not segments:
        return create_intelligent_segments_v2(content, 'claude-sonnet-4-20250514')
    
    # 按位置排序
    segments.sort(key=lambda x: x.get('start', 0))
    
    return segments

def generate_anr_segment_prompt(segment: Dict, index: int, total: int) -> Dict[str, str]:
    """生成 ANR 段落分析提示詞"""
    seg_type = segment.get('type', 'unknown')
    
    type_prompts = {
        'header': "分析 ANR 的基本信息，包括發生時間、影響的應用和初步原因。",
        'Process Section': "分析進程信息，識別受影響的進程和服務。",
        'Thread Section': "分析線程狀態，找出被阻塞或等待的線程。",
        'Lock Information': "分析鎖信息，檢測死鎖或鎖競爭。",
        'CPU Statistics': "分析 CPU 使用情況，判斷是否存在 CPU 瓶頸。",
        'Memory Statistics': "分析內存使用，檢查是否存在內存壓力。"
    }
    
    system_prompt = type_prompts.get(seg_type, "分析這個 ANR 日誌段落。")
    
    return {
        'system': f"Android ANR 專家。這是第 {index+1}/{total} 段，類型：{seg_type}。{system_prompt}",
        'user': f"""
段落類型：{segment.get('description', '')}

內容：
{segment['content'][:50000]}  # 限制長度

請提供：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 這個段落的關鍵發現
5. 與 ANR 原因的關聯
6. 需要在其他段落確認的信息
"""
    }

def generate_tombstone_segment_prompt(segment: Dict, index: int, total: int) -> Dict[str, str]:
    """生成 Tombstone 段落分析提示詞"""
    seg_type = segment.get('type', 'unknown')
    
    type_prompts = {
        'signal_info': "分析崩潰信號，確定崩潰類型和嚴重性。",
        'abort_message': "解析中止消息，理解崩潰的直接原因。",
        'registers': "分析寄存器狀態，判斷崩潰時的 CPU 狀態。",
        'backtrace': "分析堆棧追蹤，定位崩潰發生的確切位置和調用鏈。",
        'memory_map': "分析內存映射，確定崩潰地址的歸屬。"
    }
    
    system_prompt = type_prompts.get(seg_type, "分析這個 Tombstone 日誌段落。")
    
    return {
        'system': f"Android 崩潰分析專家。段落 {index+1}/{total}，類型：{seg_type}。{system_prompt}",
        'user': f"""
段落描述：{segment.get('description', '')}

內容：
{segment['content'][:50000]}

請分析：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 這個段落揭示的崩潰信息
5. 與崩潰根本原因的關係
6. 可能的修復方向
"""
    }

def parse_analysis_result(raw_analysis: str, log_type: LogType) -> Dict:
    """解析 AI 分析結果為結構化數據"""
    result = {
        'summary': '',
        'root_cause': '',
        'affected_processes': [],
        'key_evidence': [],
        'recommendations': [],
        'severity': 'Unknown',
        'confidence': 0.0
    }
    
    # 使用簡單的模式匹配提取信息
    sections = raw_analysis.split('\n\n')
    
    for section in sections:
        section_lower = section.lower()
        
        if any(keyword in section_lower for keyword in ['摘要', 'summary', '概要']):
            result['summary'] = section.strip()
        elif any(keyword in section_lower for keyword in ['原因', 'cause', 'reason']):
            result['root_cause'] = section.strip()
        elif any(keyword in section_lower for keyword in ['建議', 'recommendation', '解決']):
            result['recommendations'].append(section.strip())
        elif any(keyword in section_lower for keyword in ['進程', 'process', '應用']):
            # 提取進程名
            processes = re.findall(r'(?:進程|process|應用)[:：]\s*(.+)', section)
            result['affected_processes'].extend(processes)
    
    # 評估嚴重性
    if any(word in raw_analysis.lower() for word in ['critical', '嚴重', 'fatal', '致命']):
        result['severity'] = 'Critical'
    elif any(word in raw_analysis.lower() for word in ['high', '高', 'major']):
        result['severity'] = 'High'
    elif any(word in raw_analysis.lower() for word in ['medium', '中等']):
        result['severity'] = 'Medium'
    else:
        result['severity'] = 'Low'
    
    # 計算置信度（基於分析的完整性）
    filled_fields = sum(1 for v in result.values() if v and v != 'Unknown' and v != 0.0)
    result['confidence'] = filled_fields / 7.0
    
    return result

def synthesize_comprehensive_analysis(analyses: List[Dict], log_type: LogType) -> Dict:
    """綜合多個分析部分的結果"""
    synthesis = {
        'comprehensive_summary': '',
        'root_causes': [],
        'evidence_chain': [],
        'action_items': {
            'immediate': [],
            'short_term': [],
            'long_term': []
        },
        'technical_details': {}
    }
    
    # 合併所有分析
    all_text = '\n\n'.join(a['analysis'] for a in analyses if 'analysis' in a)
    
    # 提取和整理信息
    # 這裡可以使用更複雜的 NLP 技術
    
    synthesis['comprehensive_summary'] = f"""
基於 {len(analyses)} 個部分的深入分析，{log_type.value} 問題的完整診斷如下：
{all_text[:500]}...
"""
    
    return synthesis

def generate_smart_final_report(segment_results: List[Dict], log_type: LogType, 
                               analyzer: AndroidLogAnalyzer) -> Dict:
    """生成智能最終報告"""
    successful_segments = [r for r in segment_results if r.get('success')]
    
    report = {
        'executive_summary': '',
        'detailed_findings': {},
        'root_cause_analysis': '',
        'impact_assessment': '',
        'remediation_plan': {
            'immediate_actions': [],
            'preventive_measures': [],
            'monitoring_recommendations': []
        },
        'technical_appendix': {}
    }
    
    # 基於成功分析的段落生成報告
    if log_type == LogType.ANR:
        report['executive_summary'] = f"""
ANR 分析完成。共分析 {len(successful_segments)}/{len(segment_results)} 個段落。

主要發現：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 檢測到的 ANR 類型和嚴重程度
5. 受影響的主要組件
6. 系統資源使用情況
"""
    elif log_type == LogType.TOMBSTONE:
        report['executive_summary'] = f"""
Tombstone 崩潰分析完成。共分析 {len(successful_segments)}/{len(segment_results)} 個段落。

崩潰概要：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 崩潰信號和類型
5. 崩潰位置和調用鏈
6. 內存狀態分析
"""
    
    # 整合所有段落的發現
    for result in successful_segments:
        if result.get('analysis'):
            # 提取關鍵信息添加到報告中
            # 這裡可以進一步解析每個段落的分析結果
            pass
    
    return report

def parse_detailed_analysis(raw_analysis: str, log_type: LogType) -> Dict:
    """解析詳細的 AI 分析結果為結構化數據"""
    result = {
        'summary': '',
        'root_cause': '',
        'affected_processes': [],
        'key_evidence': [],
        'recommendations': [],
        'severity': 'Unknown',
        'confidence': 0.0,
        'technical_details': {},
        'timeline': []
    }
    
    try:
        # 使用更智能的解析
        lines = raw_analysis.split('\n')
        current_section = None
        current_content = []
        
        section_keywords = {
            'summary': ['摘要', 'summary', '概要', '總結', '問題摘要'],
            'root_cause': ['原因', 'cause', 'reason', '根本原因', 'root cause'],
            'processes': ['進程', 'process', '應用', 'app', 'pid'],
            'evidence': ['證據', 'evidence', '堆棧', 'stack', 'trace', '追蹤'],
            'recommendations': ['建議', 'recommendation', '解決', 'solution', '修復'],
            'severity': ['嚴重', 'severity', 'critical', 'high', 'medium', 'low'],
            'technical': ['技術', 'technical', '詳細', 'detail']
        }
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 檢查是否是新的段落標題
            line_lower = line.lower()
            new_section = None
            
            for section, keywords in section_keywords.items():
                if any(keyword in line_lower for keyword in keywords):
                    new_section = section
                    break
            
            if new_section:
                # 保存前一個段落的內容
                if current_section and current_content:
                    save_section_content(result, current_section, current_content)
                
                current_section = new_section
                current_content = []
            else:
                current_content.append(line)
        
        # 保存最後一個段落
        if current_section and current_content:
            save_section_content(result, current_section, current_content)
        
        # 如果沒有找到結構化內容，使用簡單分割
        if not result['summary'] and raw_analysis:
            paragraphs = raw_analysis.split('\n\n')
            if paragraphs:
                result['summary'] = paragraphs[0]
                if len(paragraphs) > 1:
                    result['root_cause'] = paragraphs[1]
                if len(paragraphs) > 2:
                    result['recommendations'] = paragraphs[2:]
        
        # 評估嚴重性
        result['severity'] = assess_severity(raw_analysis, log_type)
        
        # 計算置信度
        result['confidence'] = calculate_confidence(result)
        
    except Exception as e:
        print(f"解析分析結果時出錯: {str(e)}")
        result['summary'] = raw_analysis[:500] + '...' if len(raw_analysis) > 500 else raw_analysis
    
    return result

def save_section_content(result: Dict, section: str, content: List[str]):
    """保存段落內容到結果中"""
    content_text = '\n'.join(content)
    
    if section == 'summary':
        result['summary'] = content_text
    elif section == 'root_cause':
        result['root_cause'] = content_text
    elif section == 'processes':
        # 提取進程列表
        processes = extract_processes(content_text)
        result['affected_processes'].extend(processes)
    elif section == 'evidence':
        # 分割證據項目
        evidence_items = [item.strip() for item in content_text.split('\n') if item.strip()]
        result['key_evidence'].extend(evidence_items[:5])  # 最多 5 個證據
    elif section == 'recommendations':
        # 分割建議項目
        recommendations = [item.strip() for item in content_text.split('\n') if item.strip()]
        result['recommendations'].extend(recommendations)
    elif section == 'technical':
        result['technical_details']['analysis'] = content_text

def extract_processes(text: str) -> List[str]:
    """從文本中提取進程名稱"""
    processes = []
    
    # 常見的進程模式
    patterns = [
        r'pid[:\s]+(\d+)[,\s]+.*?name[:\s]+([^\s,]+)',
        r'Process[:\s]+([^\s,]+)',
        r'應用[:\s]+([^\s,]+)',
        r'com\.[a-zA-Z0-9._]+',  # Android 包名
        r'/system/bin/[a-zA-Z0-9_]+'  # 系統進程
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if isinstance(match, tuple):
                processes.extend([m for m in match if m and not m.isdigit()])
            else:
                processes.append(match)
    
    # 去重並返回
    return list(set(filter(None, processes)))[:10]  # 最多返回 10 個

def assess_severity(analysis: str, log_type: LogType) -> str:
    """評估問題的嚴重程度"""
    analysis_lower = analysis.lower()
    
    # 嚴重性指標
    critical_indicators = [
        'critical', '嚴重', 'fatal', '致命', 'crash', '崩潰',
        'deadlock', '死鎖', 'system failure', '系統失敗',
        'data loss', '數據丟失', 'security', '安全'
    ]
    
    high_indicators = [
        'high', '高', 'major', '主要', 'significant', '顯著',
        'performance', '性能', 'memory leak', '內存洩漏',
        'anr', 'not responding', '無響應'
    ]
    
    medium_indicators = [
        'medium', '中等', 'moderate', '適中', 'warning', '警告',
        'potential', '潛在', 'may cause', '可能導致'
    ]
    
    # 計算各級別的匹配數
    critical_count = sum(1 for ind in critical_indicators if ind in analysis_lower)
    high_count = sum(1 for ind in high_indicators if ind in analysis_lower)
    medium_count = sum(1 for ind in medium_indicators if ind in analysis_lower)
    
    # 根據日誌類型調整
    if log_type == LogType.TOMBSTONE:
        # Tombstone 通常更嚴重
        if critical_count > 0 or high_count > 1:
            return 'Critical'
        elif high_count > 0 or medium_count > 1:
            return 'High'
        else:
            return 'Medium'
    else:  # ANR
        if critical_count > 1 or (critical_count > 0 and high_count > 0):
            return 'Critical'
        elif high_count > 1 or critical_count > 0:
            return 'High'
        elif medium_count > 0 or high_count > 0:
            return 'Medium'
        else:
            return 'Low'

def calculate_confidence(result: Dict) -> float:
    """計算分析結果的置信度"""
    confidence_score = 0.0
    
    # 各部分的權重
    weights = {
        'summary': 0.2,
        'root_cause': 0.3,
        'evidence': 0.25,
        'recommendations': 0.15,
        'severity': 0.1
    }
    
    # 檢查各部分是否存在且有內容
    if result.get('summary') and len(result['summary']) > 50:
        confidence_score += weights['summary']
    
    if result.get('root_cause') and len(result['root_cause']) > 30:
        confidence_score += weights['root_cause']
    
    if result.get('key_evidence') and len(result['key_evidence']) > 0:
        evidence_score = min(len(result['key_evidence']) / 5.0, 1.0)
        confidence_score += weights['evidence'] * evidence_score
    
    if result.get('recommendations') and len(result['recommendations']) > 0:
        rec_score = min(len(result['recommendations']) / 3.0, 1.0)
        confidence_score += weights['recommendations'] * rec_score
    
    if result.get('severity') and result['severity'] != 'Unknown':
        confidence_score += weights['severity']
    
    return round(confidence_score, 2)

async def quick_analysis_strategy(content, file_path, model):
    """快速分析：30秒內完成，只分析最關鍵的部分"""
    try:
        # 提取關鍵部分（最多 50KB）
        key_sections = extract_critical_sections(content, max_size=50000)
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        # 使用簡潔的提示詞
        system_prompt = """你是 Android 系統專家。快速分析日誌，只提供最關鍵的發現。
限制回答在 2500 字以內，包含：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 主要問題（1-2句）
5. 根本原因（1-2句）
6. 立即可行的解決方案（2-3點）
7. 指出發生 ANR/Tombstone 的 Process
8. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
9. 找出 ANR/Tombstone 卡住可能的原因"""
        
        message = client.messages.create(
            model=model,
            max_tokens=2000,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": key_sections}]
        )
        
        return jsonify({
            'success': True,
            'analysis': message.content[0].text if message.content else "",
            'is_quick': True,
            'analyzed_size': len(key_sections),
            'original_size': len(content),
            'analysis_mode': 'quick',
            'model': model
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

async def comprehensive_analysis_strategy(content, file_path, model, enable_thinking):
    """深度分析：詳細分析每個部分，提供完整報告"""
    try:
        # 創建詳細的分段（每段 100KB）
        segments = create_intelligent_segments_v2(content, model)
        
        if len(segments) == 1:
            # 小檔案，直接深度分析
            return await deep_single_analysis(content, model, enable_thinking)
        
        # 大檔案，分段深度分析
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        segment_results = []
        
        for i, segment in enumerate(segments):
            try:
                # 深度分析每個段落
                prompt = f"""
這是第 {i+1}/{len(segments)} 段。請進行深入分析：
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因
4. 識別所有潛在問題和異常
5. 分析根本原因和影響
6. 提供詳細的技術解釋
7. 建議短期和長期解決方案
8. 標注需要進一步調查的線索
"""
                
                message = client.messages.create(
                    model=model,
                    max_tokens=4000,
                    temperature=0,
                    system="Android 系統深度分析專家。提供詳盡的技術分析。",
                    messages=[{"role": "user", "content": prompt + "\n\n" + segment['content'][:100000]}]
                )
                
                segment_results.append({
                    'segment': i + 1,
                    'analysis': message.content[0].text if message.content else "",
                    'success': True
                })
                
            except Exception as e:
                segment_results.append({
                    'segment': i + 1,
                    'error': str(e),
                    'success': False
                })
        
        # 生成綜合報告
        synthesis = await synthesize_comprehensive_report(segment_results, model)
        
        return {
            'success': True,
            'is_segmented': True,
            'total_segments': len(segments),
            'segment_results': segment_results,
            'comprehensive_report': synthesis,
            'analysis': synthesis  # 兼容前端
        }
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

async def max_tokens_analysis_strategy(content, file_path, model):
    """最大化分析：在 token 限制內分析盡可能多的內容"""
    try:
        model_config = MODEL_LIMITS[model]
        max_input = int(model_config['max_tokens'] * 0.85)  # 留 15% 餘量
        
        # 智能選擇最重要的內容填滿 token 限制
        prioritized_content = prioritize_content_smart(content, max_tokens=max_input)
        
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        # 使用模型的最大輸出能力
        message = client.messages.create(
            model=model,
            max_tokens=model_config['max_output_tokens'],
            temperature=0,
            system="""Android 系統分析專家。在有限的內容中提供最大價值的分析。
包含：問題診斷、根本原因、影響評估、解決方案、預防措施。""",
            messages=[{"role": "user", "content": prioritized_content}]
        )
        
        return {
            'success': True,
            'analysis': message.content[0].text if message.content else "",
            'content_coverage': f"{len(prioritized_content)}/{len(content)} 字符",
            'token_usage': f"約 {estimate_tokens_accurate(prioritized_content)} tokens"
        }
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

async def auto_analysis_strategy(content, file_path, model, enable_thinking):
    """智能分析：自動選擇最佳策略"""
    content_size = len(content)
    estimated_tokens = estimate_tokens_accurate(content)
    
    print(f"Auto analysis: size={content_size}, tokens={estimated_tokens}")
    
    # 根據內容特徵自動決定
    if estimated_tokens < 50000:
        # 小檔案：直接完整分析
        return await analyze_single_request(
            file_path, content, 'auto', model, 
            False, '', enable_thinking
        )
    elif estimated_tokens < 150000:
        # 中等檔案：智能分段
        return await smart_segmented_analysis(content, file_path, model, enable_thinking)
    else:
        # 大檔案：優化分段策略
        return await optimized_large_file_analysis(content, file_path, model, enable_thinking)

# 輔助函數
def extract_critical_sections(content, max_size=50000):
    """提取日誌中最關鍵的部分"""
    critical_patterns = [
        r'FATAL EXCEPTION.*?(?=\n\n|\Z)',
        r'AndroidRuntime.*?(?=\n\n|\Z)',
        r'signal \d+.*?(?=\n\n|\Z)',
        r'Abort message.*?(?=\n\n|\Z)',
        r'backtrace:.*?(?=\n\n|\Z)',
        r'"main".*?(?=\n\n|\Z)',  # 主線程
        r'held by thread.*?(?=\n\n|\Z)',  # 鎖信息
    ]
    
    extracted = []
    total_size = 0
    
    # 先提取標題信息
    header = content[:1000]
    extracted.append(header)
    total_size += len(header)
    
    # 提取關鍵部分
    for pattern in critical_patterns:
        if total_size >= max_size:
            break
            
        matches = re.finditer(pattern, content, re.DOTALL | re.IGNORECASE)
        for match in matches:
            if total_size + len(match.group(0)) > max_size:
                break
            extracted.append(match.group(0))
            total_size += len(match.group(0))
    
    return '\n\n=====\n\n'.join(extracted)

def prioritize_content_smart(content, max_tokens):
    """智能優先級選擇內容"""
    # 這裡實現內容優先級算法
    # 簡單實現：保留開頭、結尾和包含關鍵詞的部分
    max_chars = int(max_tokens * 2.5)
    
    if len(content) <= max_chars:
        return content
    
    # 分配字符數
    header_size = min(10000, max_chars // 4)
    footer_size = min(5000, max_chars // 8)
    middle_size = max_chars - header_size - footer_size
    
    # 提取部分
    header = content[:header_size]
    footer = content[-footer_size:] if footer_size > 0 else ""
    
    # 中間部分：查找關鍵內容
    middle_content = extract_critical_sections(content[header_size:-footer_size], middle_size)
    
    return f"{header}\n\n... [內容已優化選擇] ...\n\n{middle_content}\n\n... [內容已優化選擇] ...\n\n{footer}"

async def synthesize_comprehensive_report(segment_results, model):
    """生成綜合分析報告"""
    successful_segments = [r for r in segment_results if r.get('success')]
    
    if not successful_segments:
        return "所有段落分析都失敗了。"
    
    # 組合所有成功的分析
    all_analyses = "\n\n=== 段落分析 ===\n\n".join([
        f"段落 {r['segment']}:\n{r['analysis']}" 
        for r in successful_segments
    ])
    
    # 可以選擇再次調用 AI 來綜合，或直接返回
    return f"""
# 綜合分析報告

## 分析概況
- 總共分析了 {len(successful_segments)}/{len(segment_results)} 個段落
- 使用模型：{model}

## 詳細分析結果

{all_analyses}

## 總結
基於以上分析，請參考各段落的詳細發現和建議。
"""

async def deep_single_analysis(content, model, enable_thinking):
    """對單個檔案進行深度分析"""
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    
    system_prompt = """你是資深的 Android 系統專家，請提供極其詳細的分析報告。

分析格式：
# 執行摘要
[2-3段的問題概述]

# 技術分析
## 1. 問題識別
[詳細列出所有發現的問題]

## 2. 根本原因分析
[深入分析每個問題的根源]
1. 指出發生 ANR/Tombstone 的 Process
2. 列出 ANR/Tombstone Process main thread 卡住 的 backtrace
3. 找出 ANR/Tombstone 卡住可能的原因

## 3. 影響評估
[評估問題的嚴重性和影響範圍]

## 4. 技術細節
[堆棧分析、內存狀態、線程狀態等]

# 解決方案
## 立即措施
[緊急修復步驟]

## 短期改進
[1-2週內的改進計劃]

## 長期優化
[架構級別的改進建議]

# 預防措施
[如何避免類似問題]

# 附錄
[其他技術參考信息]
"""
    
    message = client.messages.create(
        model=model,
        max_tokens=MODEL_LIMITS[model]['max_output_tokens'],
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": content[:int(MODEL_LIMITS[model]['max_tokens'] * 2.5 * 0.8)]}]
    )
    
    return {
        'success': True,
        'analysis': message.content[0].text if message.content else "",
        'is_deep_analysis': True
    }

async def smart_segmented_analysis(content, file_path, model, enable_thinking):
    """智能分段分析"""
    # 使用現有的分段分析邏輯
    return await analyze_in_segments_fast(
        file_path, content, 'auto', model,
        False, '', enable_thinking
    )

async def optimized_large_file_analysis(content, file_path, model, enable_thinking):
    """優化的大檔案分析"""
    # 對超大檔案使用特殊策略
    # 可以實現抽樣分析、關鍵部分提取等
    return await analyze_in_segments_fast(
        file_path, content, 'auto', model,
        False, '', enable_thinking
    )