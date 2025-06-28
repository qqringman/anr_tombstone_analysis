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
    'claude-3-5-sonnet-20241022': {
        'max_tokens': 200000,  # 輸入 token 限制
        'max_output_tokens': 8192,  # 輸出 token 限制
        'chars_per_token': 2.5,  # 平均字符/token 比率
        'rate_limit': 40000,  # 每分鐘 token 限制
        'name': 'Claude 3.5 Sonnet'
    },
    'claude-3-5-haiku-20241022': {
        'max_tokens': 200000,
        'max_output_tokens': 8192,
        'chars_per_token': 2.5,
        'rate_limit': 80000,  # Haiku 通常有更高的速率限制
        'name': 'Claude 3.5 Haiku'
    },
    'claude-3-opus-20240229': {
        'max_tokens': 200000,
        'max_output_tokens': 4096,
        'chars_per_token': 2.5,
        'rate_limit': 40000,
        'name': 'Claude 3 Opus'
    },
    'claude-3-haiku-20240307': {
        'max_tokens': 200000,
        'max_output_tokens': 4096,
        'chars_per_token': 2.5,
        'rate_limit': 80000,
        'name': 'Claude 3 Haiku'
    }
}

# 創建全局速率限制器
rate_limiter = TokenRateLimiter(AI_CONFIG['RATE_LIMIT_TOKENS_PER_MINUTE'])


# 添加新的 AI 分析端點
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
        
        #if needs_segmentation:
        #    # 使用快速分段分析
        #    return await analyze_in_segments_fast(
        #        file_path, content, file_type, selected_model,
        #        is_custom_question, original_question, enable_thinking
        #    )
        #else:
        #    # 單次分析
        #    return analyze_single_request(
        #        file_path, content, file_type, selected_model,
        #        is_custom_question, original_question, enable_thinking
        #    )

        return analyze_single_request(
                file_path, content, file_type, selected_model,
                is_custom_question, original_question, enable_thinking
        )            
        
    except Exception as e:
        print(f"AI analysis error: {str(e)}")
        return jsonify({'error': f'分析錯誤: {str(e)}'}), 500
        
@ai_bp.route('/analyze-with-ai-stream', methods=['POST'])
def analyze_with_ai_stream():
    """使用 SSE 的流式分析端點"""
    request_id = str(uuid.uuid4())
    progress_queue = queue.Queue()
    progress_queues[request_id] = progress_queue
    
    def generate():
        try:
            # 獲取請求數據
            data = request.get_json()
            file_path = data.get('file_path', '')
            content = data.get('content', '')
            file_type = data.get('file_type', 'ANR')
            selected_model = data.get('model', 'claude-3-5-sonnet-20241022')
            is_custom_question = data.get('is_custom_question', False)
            original_question = data.get('original_question', '')
            enable_thinking = data.get('enable_thinking', True)
            
            # 發送初始化消息
            yield f"data: {json.dumps({'type': 'init', 'request_id': request_id})}\n\n"
            
            # 創建分段
            segments = create_intelligent_segments_v2(content, selected_model)
            
            # 發送分段信息
            yield f"data: {json.dumps({'type': 'segments', 'total': len(segments)})}\n\n"
            
            # 如果不需要分段
            if len(segments) == 1 and not segments[0].get('needs_segmentation', True):
                # 直接分析
                result = analyze_single_segment(segments[0], file_path, file_type, 
                                              selected_model, original_question, enable_thinking)
                yield f"data: {json.dumps({'type': 'complete', 'result': result})}\n\n"
                return
            
            # 分段分析
            results = []
            client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            accumulated_context = ""
            
            for i, segment in enumerate(segments):
                # 發送進度更新
                yield f"data: {json.dumps({
                    'type': 'progress',
                    'current': i + 1,
                    'total': len(segments),
                    'percentage': int((i + 1) / len(segments) * 100),
                    'message': f'正在分析第 {i + 1}/{len(segments)} 段...'
                })}\n\n"
                
                # 檢查速率限制
                wait_time = rate_limiter.get_wait_time(segment['estimated_tokens'])
                if wait_time > 0:
                    yield f"data: {json.dumps({
                        'type': 'rate_limit',
                        'wait_time': wait_time,
                        'message': f'等待速率限制重置 ({wait_time:.1f}秒)...'
                    })}\n\n"
                    time.sleep(wait_time)
                
                # 分析段落
                try:
                    segment_result = analyze_segment_with_retry(
                        segment, client, file_type, original_question, 
                        accumulated_context, selected_model, enable_thinking
                    )
                    
                    results.append(segment_result)
                    
                    # 發送段落結果
                    yield f"data: {json.dumps({
                        'type': 'segment_complete',
                        'segment': i + 1,
                        'result': segment_result
                    })}\n\n"
                    
                    # 更新累積上下文
                    if segment_result.get('success'):
                        key_findings = extract_key_findings(segment_result['analysis'])
                        accumulated_context += f"\n\n段落 {i + 1} 關鍵發現：\n{key_findings}"
                    
                except Exception as e:
                    error_result = {
                        'segment_number': i + 1,
                        'error': str(e),
                        'success': False
                    }
                    results.append(error_result)
                    
                    yield f"data: {json.dumps({
                        'type': 'segment_error',
                        'segment': i + 1,
                        'error': str(e)
                    })}\n\n"
            
            # 生成綜合分析
            yield f"data: {json.dumps({
                'type': 'synthesizing',
                'message': '正在生成綜合分析報告...'
            })}\n\n"
            
            synthesis = synthesize_segments_v2(results, original_question, selected_model, client)
            
            # 發送最終結果
            final_result = {
                'success': True,
                'is_segmented': True,
                'total_segments': len(segments),
                'segments': results,
                'full_analysis': synthesis['analysis'],
                'thinking_log': synthesis.get('thinking_log', []),
                'model': selected_model
            }
            
            yield f"data: {json.dumps({'type': 'final', 'result': final_result})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        finally:
            # 清理
            progress_queues.pop(request_id, None)
    
    return Response(generate(), mimetype="text/event-stream")

# 新增一個端點來預檢檔案大小
@ai_bp.route('/check-file-size-for-ai', methods=['POST'])
def check_file_size_for_ai():
    """預檢檔案大小並提供分析建議"""
    try:
        data = request.json
        content = data.get('content', '')
        
        content_length = len(content)
        estimated_tokens = content_length // int(AI_CONFIG['CHARS_PER_TOKEN'])
        
        # 計算建議的分段數
        if estimated_tokens <= AI_CONFIG['MAX_TOKENS_PER_REQUEST']:
            suggested_segments = 1
            strategy = 'single'
        else:
            max_chars = int(AI_CONFIG['MAX_TOKENS_PER_REQUEST'] * AI_CONFIG['CHARS_PER_TOKEN'])
            suggested_segments = max(1, (content_length + max_chars - 1) // max_chars)
            strategy = 'segmented'
        
        return jsonify({
            'content_length': content_length,
            'estimated_tokens': estimated_tokens,
            'max_tokens_per_request': AI_CONFIG['MAX_TOKENS_PER_REQUEST'],
            'suggested_segments': suggested_segments,
            'strategy': strategy,
            'estimated_time': suggested_segments * 5,  # 假設每段需要 5 秒
            'supports_thinking': True
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
3. 是否需要其他段落資訊"""
    
    return {
        'system': system_prompt,
        'user': user_prompt
    }
    
def analyze_single_request(file_path, content, file_type, selected_model,
                         is_custom_question, original_question, enable_thinking):
    """單次分析請求（不需要分段）"""
    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        
        # 根據文件類型和問題類型構建提示詞
        if is_custom_question:
            system_prompt = f"""你是一位 Android 系統專家，擅長分析 Android 日誌和解決系統問題。
用戶提供了一個檔案的內容，並基於這個檔案提出了問題。

分析時請遵循以下原則：
1. 仔細閱讀提供的檔案內容
2. 根據檔案內容準確回答用戶的問題
3. 提供具體、可操作的建議
4. 如果檔案中沒有足夠的信息來回答問題，請明確指出
5. 引用檔案中的具體內容來支持你的分析

請用繁體中文回答，並使用結構化的格式。"""
        elif file_type == 'ANR':
            system_prompt = f"""你是一位 Android 系統專家，擅長分析 ANR (Application Not Responding) 日誌。
請分析這個 ANR 日誌並提供：
1. 問題摘要：簡潔說明發生了什麼
2. 根本原因：識別導致 ANR 的主要原因
3. 影響的進程：哪個應用或服務受到影響
4. 關鍵堆棧信息：最重要的堆棧追蹤部分
5. 建議解決方案：如何修復這個問題

請用繁體中文回答，並使用結構化的格式。"""
        else:
            system_prompt = f"""你是一位 Android 系統專家，擅長分析 Tombstone 崩潰日誌。
請分析這個 Tombstone 日誌並提供：
1. 崩潰摘要：簡潔說明發生了什麼類型的崩潰
2. 崩潰原因：信號類型和觸發原因
3. 影響的進程：哪個應用或服務崩潰了
4. 關鍵堆棧信息：定位問題的關鍵堆棧幀
5. 可能的修復方向：如何避免這類崩潰

請用繁體中文回答，並使用結構化的格式。"""
        
        # 調用 Claude API
        message_params = {
            "model": selected_model,
            "max_tokens": 4000,
            "temperature": 0,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": content
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
            'truncated': False,
            'original_length': len(content),
            'model': selected_model,
            'thinking': thinking_text
        })
        
    except anthropic.APIError as e:
        error_message = str(e)
        return jsonify({
            'error': f'Claude API 錯誤: {error_message}',
            'details': '請檢查 API key 是否有效'
        }), 500
    except Exception as e:
        return jsonify({
            'error': f'分析錯誤: {str(e)}'
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
1. 這個段落中的堆疊追蹤信息
2. 線程狀態和鎖定情況
3. 主線程是否被阻塞
4. 任何死鎖或資源爭用的跡象"""
    elif file_type == 'Tombstone':
        base_system += """
        
請特別注意：
1. 崩潰的信號類型和地址
2. 堆疊追蹤的關鍵函數
3. 寄存器狀態
4. 可能的記憶體問題"""
    
    # 用戶提示
    user_prompt = f"""=== 檔案段落 {segment_num}/{total_segments} ===

{segment['context'] + segment['content'] if segment['context'] else segment['content']}

=== 段落結束 ===

問題：{question}

請分析這個段落，並注意：
1. 如果這不是第一段，請考慮之前的發現
2. 如果還有後續段落，請指出需要在後續段落中尋找的信息
3. 提供這個段落的關鍵發現摘要"""
    
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
1. 關鍵發現
2. 問題線索
3. 需要後續段落確認的事項"""
    
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
1. **問題總覽**：用 2-3 句話概括整個問題
2. **根本原因分析**：詳細說明導致問題的根本原因（至少 500 字）
3. **技術細節**：
   - 涉及的進程和線程
   - 關鍵的堆棧信息
   - 內存/資源使用情況
   - 時間線分析
4. **影響評估**：這個問題的嚴重程度和潛在影響
5. **解決方案**：
   - 立即措施（緊急修復）
   - 短期方案（1-2 週內）
   - 長期優化（架構改進）
6. **預防措施**：如何避免類似問題再次發生
7. **需要進一步調查的事項**

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
                  
        
