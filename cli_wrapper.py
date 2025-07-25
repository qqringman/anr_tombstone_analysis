#!/usr/bin/env python3.12
"""
Android ANR/Tombstone Analyzer CLI Wrapper

Usage:
    python3.12 cli_wrapper.py -input file1.zip,file2.txt,/path/to/folder -output result.zip
"""

import argparse
import os
import sys
import tempfile
import shutil
import zipfile
import json
import subprocess
from datetime import datetime
from pathlib import Path
import io

# 將當前目錄加入 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 導入分析器和必要的模組
from routes.grep_analyzer import AndroidLogAnalyzer
from routes.main_page import extract_ai_summary, HTML_TEMPLATE

def parse_arguments():
    """解析命令列參數"""
    parser = argparse.ArgumentParser(
        description='Android ANR/Tombstone Analyzer CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    # 分析單一檔案
    python3.12 cli_wrapper.py -i anr.txt -o result.zip
    
    # 分析多個檔案和資料夾
    python3.12 cli_wrapper.py -i anr.zip,tombstone.txt,/logs/folder -o result.zip
    
    # 自動分組獨立檔案
    python3.12 cli_wrapper.py -i anr1.txt,anr2.txt -o result.zip --auto-group
        '''
    )
    
    parser.add_argument(
        '-i', '--input',
        required=True,
        help='輸入檔案或資料夾，多個項目用逗號分隔'
    )
    
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='輸出 ZIP 檔案名稱'
    )
    
    parser.add_argument(
        '--auto-group',
        action='store_true',
        help='自動將獨立的 ANR/Tombstone 檔案分組'
    )
    
    parser.add_argument(
        '--keep-temp',
        action='store_true',
        help='保留臨時檔案（用於除錯）'
    )
    
    return parser.parse_args()

def prepare_analysis_directory(input_items, temp_dir, auto_group=True):
    """準備分析目錄結構"""
    group_counter = 1
    anr_files = []
    tombstone_files = []
    
    for item in input_items:
        item = item.strip()
        
        if not os.path.exists(item):
            print(f"警告：找不到 {item}，跳過")
            continue
        
        if os.path.isfile(item):
            # 處理單一檔案
            filename = os.path.basename(item)
            file_lower = filename.lower()
            
            # 檢查是否為 ZIP 檔案
            if item.endswith('.zip'):
                # 解壓縮 ZIP 檔案
                try:
                    with zipfile.ZipFile(item, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                    print(f"已解壓縮: {item}")
                    continue
                except Exception as e:
                    print(f"解壓縮 {item} 失敗: {e}")
            
            # 檢查是否為 ANR 或 Tombstone 檔案
            if 'anr' in file_lower or 'tombstone' in file_lower:
                dest_path = os.path.join(temp_dir, filename)
                shutil.copy2(item, dest_path)
                
                if 'anr' in file_lower:
                    anr_files.append((dest_path, filename))
                else:
                    tombstone_files.append((dest_path, filename))
            else:
                # 其他檔案直接複製
                shutil.copy2(item, os.path.join(temp_dir, filename))
        
        elif os.path.isdir(item):
            # 複製整個資料夾
            dest_folder = os.path.join(temp_dir, os.path.basename(item))
            shutil.copytree(item, dest_folder)
            print(f"已複製資料夾: {item}")
    
    # 自動分組處理
    if auto_group:
        # 處理 ANR 檔案
        if anr_files:
            print(f"找到 {len(anr_files)} 個獨立的 ANR 檔案，自動分組中...")
            for file_path, filename in anr_files:
                group_folder = os.path.join(temp_dir, f'Group{group_counter}', 'anr')
                os.makedirs(group_folder, exist_ok=True)
                shutil.move(file_path, os.path.join(group_folder, filename))
                print(f"  {filename} -> Group{group_counter}/anr/")
                group_counter += 1
        
        # 處理 Tombstone 檔案
        if tombstone_files:
            print(f"找到 {len(tombstone_files)} 個獨立的 Tombstone 檔案，自動分組中...")
            for file_path, filename in tombstone_files:
                group_folder = os.path.join(temp_dir, f'Group{group_counter}', 'tombstones')
                os.makedirs(group_folder, exist_ok=True)
                shutil.move(file_path, os.path.join(group_folder, filename))
                print(f"  {filename} -> Group{group_counter}/tombstones/")
                group_counter += 1

def run_vp_analyze(analysis_path, output_path):
    """執行 vp_analyze_logs.py"""
    try:
        vp_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'routes', 'vp_analyze_logs.py')
        
        if not os.path.exists(vp_script_path):
            print("警告：找不到 vp_analyze_logs.py，跳過詳細分析")
            return False
        
        print("執行詳細分析...")
        cmd = ['python3.12', vp_script_path, analysis_path, output_path]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            print("詳細分析完成")
            return True
        else:
            print(f"詳細分析失敗: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"執行 vp_analyze 時發生錯誤: {e}")
        return False

def generate_excel_file(output_path, results, analysis_output_path, base_path):
    """生成 Excel 檔案"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        
        # 準備 Excel 資料
        excel_data = []
        sn = 1
        current_time = datetime.now().strftime('%Y%m%d %H:%M:%S')
        
        for log in results.get('logs', []):
            # 讀取對應的 AI 分析結果
            ai_result = ""
            if log.get('file') and analysis_output_path and os.path.exists(analysis_output_path):
                try:
                    file_path = log['file']
                    if file_path.startswith(base_path):
                        relative_path = os.path.relpath(file_path, base_path)
                    else:
                        relative_path = file_path
                    
                    analyzed_file = os.path.join(analysis_output_path, relative_path + '.analyzed.txt')
                    
                    if os.path.exists(analyzed_file):
                        with open(analyzed_file, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            ai_result = extract_ai_summary(content)
                    else:
                        ai_result = "找不到分析結果"
                except Exception as e:
                    ai_result = f"讀取錯誤: {str(e)}"
            
            excel_data.append({
                'SN': sn,
                'Date': current_time,
                'Problem set': log.get('problem_set', '-'),
                'Type': log.get('type', ''),
                'Process': log.get('process', ''),
                'AI result': ai_result,
                'Filename': log.get('filename', ''),
                'Folder Path': log.get('file', '')
            })
            sn += 1
        
        # 建立 Excel 工作簿
        wb = Workbook()
        ws = wb.active
        ws.title = "ANR Tombstone Analysis"
        
        # 設定標題樣式
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True, size=12)
        header_alignment = Alignment(horizontal="center", vertical="center")
        header_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # 寫入標題
        headers = ['SN', 'Date', 'Problem set', 'Type', 'Process', 'AI result', 'Filename', 'Folder Path']
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_alignment
            cell.border = header_border
        
        # 設定資料樣式
        data_font = Font(size=11)
        data_alignment = Alignment(vertical="top", wrap_text=True)
        data_border = Border(
            left=Side(style='thin', color='D3D3D3'),
            right=Side(style='thin', color='D3D3D3'),
            top=Side(style='thin', color='D3D3D3'),
            bottom=Side(style='thin', color='D3D3D3')
        )
        
        anr_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
        tombstone_fill = PatternFill(start_color="FFE6E6", end_color="FFE6E6", fill_type="solid")
        
        # 寫入資料
        for row_idx, row_data in enumerate(excel_data, 2):
            for col_idx, header in enumerate(headers, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=row_data.get(header, ''))
                cell.font = data_font
                cell.border = data_border
                
                if col_idx == 1:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = data_alignment
                
                if col_idx == 4:  # Type 欄位
                    if row_data.get('Type') == 'ANR':
                        cell.fill = anr_fill
                    elif row_data.get('Type') == 'Tombstone':
                        cell.fill = tombstone_fill
        
        # 調整欄寬
        column_widths = {
            'A': 8,   # SN
            'B': 20,  # Date
            'C': 20,  # 問題 set
            'D': 12,  # Type
            'E': 30,  # Process
            'F': 60,  # AI result
            'G': 40,  # Filename
            'H': 80   # Folder Path
        }
        
        for col, width in column_widths.items():
            ws.column_dimensions[col].width = width
        
        # 凍結標題列
        ws.freeze_panes = 'A2'
        
        # 儲存檔案
        excel_path = os.path.join(output_path, 'all_anr_tombstone_result.xlsx')
        wb.save(excel_path)
        print(f"已生成 Excel 檔案: all_anr_tombstone_result.xlsx")
        
        return excel_data
        
    except Exception as e:
        print(f"生成 Excel 檔案失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        return []

def generate_html_report(output_path, results, analysis_output_path, base_path):
    """生成 HTML 統計報告"""
    try:
        # 準備資料，模擬網頁版的資料結構
        data = {
            'analysis_id': f'cli_{datetime.now().strftime("%Y%m%d%H%M%S")}',
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
            'vp_analyze_output_path': analysis_output_path,
            'vp_analyze_success': os.path.exists(analysis_output_path) if analysis_output_path else False
        }
        
        # 生成程序統計（不分類型）
        process_only_data = {}
        for item in data['statistics']['type_process_summary']:
            if not process_only_data.get(item['process']):
                process_only_data[item['process']] = {
                    'count': 0,
                    'problem_sets': set()
                }
            process_only_data[item['process']]['count'] += item['count']
            
            if item.get('problem_sets'):
                for ps in item['problem_sets']:
                    process_only_data[item['process']]['problem_sets'].add(ps)
        
        # 使用 HTML 模板
        html_report = HTML_TEMPLATE
        
        # 注入資料的腳本
        script_injection = f'''
<script>
    // 靜態頁面標記
    window.isStaticExport = true;
    window.exportBaseUrl = "";
    window.basePath = "{base_path}";
    
    // 保存分析報告相關資訊
    window.vpAnalyzeOutputPath = "{analysis_output_path}";
    window.vpAnalyzeSuccess = {str(data['vp_analyze_success']).lower()};
    
    // Injected analysis data
    window.injectedData = {json.dumps(data)};
    
    // Auto-load the data when page loads
    window.addEventListener('DOMContentLoaded', function() {{
        // 隱藏控制面板並顯示結果
        document.querySelector('.control-panel').style.display = 'none';
        document.getElementById('results').style.display = 'block';
        
        // 隱藏不需要的按鈕
        document.getElementById('exportHtmlBtn').style.display = 'none';
        ['exportExcelBtn', 'exportExcelReportBtn', 'mergeExcelBtn', 'downloadCurrentZipBtn'].forEach(id => {{
            const btn = document.getElementById(id);
            if (btn) btn.style.display = 'none';
        }});
        
        // 載入資料
        currentAnalysisId = window.injectedData.analysis_id;
        allLogs = window.injectedData.logs;
        allSummary = window.injectedData.statistics.type_process_summary || [];
        allFileStats = window.injectedData.file_statistics || [];
        
        // 生成程序統計資料
        const processOnlyData = {json.dumps({k: {'count': v['count'], 'problem_sets': list(v['problem_sets'])} for k, v in process_only_data.items()})};
        
        allProcessSummary = Object.entries(processOnlyData)
            .map(([process, data]) => ({{ 
                process, 
                count: data.count,
                problem_sets: data.problem_sets || []
            }}))
            .sort((a, b) => b.count - a.count);
        
        // Reset filters and pagination
        resetFiltersAndPagination();
        
        // Update UI
        updateResults(window.injectedData);
        
        // Show analysis info message
        let message = `分析完成！共掃描 ${{window.injectedData.total_files}} 個檔案`;
        message += `<br><br>報告生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`;
        
        const infoDiv = document.createElement('div');
        infoDiv.className = 'success';
        infoDiv.innerHTML = message;
        document.querySelector('.header').appendChild(infoDiv);
    }});
</script>
'''
        
        # 插入腳本
        html_report = html_report.replace('</body>', script_injection + '</body>')
        
        # 儲存 HTML
        html_path = os.path.join(output_path, 'all_anr_tombstone_result.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_report)
        
        print(f"已生成 HTML 報告: all_anr_tombstone_result.html")
        
    except Exception as e:
        print(f"生成 HTML 報告失敗: {str(e)}")
        import traceback
        traceback.print_exc()

def generate_excel_report_html(output_path, excel_data, base_path):
    """生成 Excel 報表 HTML"""
    try:
        from routes.excel_report import EXCEL_REPORT_TEMPLATE
        
        # 準備模板資料
        template_data = {
            'filename': 'CLI Analysis Result',
            'filepath': base_path,
            'load_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data': json.dumps(excel_data),
            'excel_data_base64': '',
            'filename_list': ['CLI Analysis Result'],
            'path_list': [base_path]
        }
        
        # 生成 HTML 內容
        html_content = EXCEL_REPORT_TEMPLATE
        
        # 替換模板變數
        for key, value in template_data.items():
            if key in ['data', 'filename_list', 'path_list']:
                if key == 'data':
                    html_content = html_content.replace('{{ data | tojson }}', value)
                elif key == 'filename_list':
                    html_content = html_content.replace('{{ filename_list | tojson }}', json.dumps(value))
                elif key == 'path_list':
                    html_content = html_content.replace('{{ path_list | tojson }}', json.dumps(value))
            else:
                html_content = html_content.replace(f'{{{{ {key} }}}}', str(value))
        
        # 儲存檔案
        report_path = os.path.join(output_path, 'all_anr_tombstone_excel_result.html')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"已生成 Excel 報表: all_anr_tombstone_excel_result.html")
        
    except Exception as e:
        print(f"生成 Excel 報表失敗: {str(e)}")
        import traceback
        traceback.print_exc()

def create_output_zip(analysis_output_path, output_file):
    """建立輸出 ZIP 檔案"""
    print(f"\n建立輸出檔案: {output_file}")
    
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(analysis_output_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(analysis_output_path))
                zipf.write(file_path, arcname)
                
    print(f"已建立 ZIP 檔案: {output_file}")
    print(f"檔案大小: {os.path.getsize(output_file) / 1024 / 1024:.2f} MB")

def main():
    """主程式"""
    args = parse_arguments()
    
    # 解析輸入項目
    input_items = [item.strip() for item in args.input.split(',')]
    
    print("="*60)
    print("Android ANR/Tombstone Analyzer CLI")
    print("="*60)
    print(f"輸入項目: {len(input_items)} 個")
    print(f"輸出檔案: {args.output}")
    print(f"自動分組: {'是' if args.auto_group else '否'}")
    print("="*60)
    
    # 建立臨時目錄
    temp_dir = tempfile.mkdtemp(prefix='anr_cli_')
    print(f"\n臨時目錄: {temp_dir}")
    
    try:
        # 準備分析目錄
        print("\n準備分析資料...")
        prepare_analysis_directory(input_items, temp_dir, args.auto_group)
        
        # 執行分析
        print("\n開始分析...")
        analyzer = AndroidLogAnalyzer()
        results = analyzer.analyze_logs(temp_dir)
        
        # 為每個 log 添加 problem_set
        for log in results['logs']:
            if 'problem_set' not in log and log.get('file'):
                try:
                    file_path = log['file']
                    relative_path = file_path.replace(temp_dir, '').lstrip('/')
                    parts = relative_path.split('/')
                    if len(parts) > 1:
                        log['problem_set'] = parts[0]
                    else:
                        log['problem_set'] = '未分類'
                except:
                    log['problem_set'] = '未分類'
        
        # 為每個 file_stat 添加 problem_set
        for file_stat in results['file_statistics']:
            if 'problem_set' not in file_stat and file_stat.get('filepath'):
                try:
                    file_path = file_stat['filepath']
                    relative_path = file_path.replace(temp_dir, '').lstrip('/')
                    parts = relative_path.split('/')
                    if len(parts) > 1:
                        file_stat['problem_set'] = parts[0]
                    else:
                        file_stat['problem_set'] = '未分類'
                except:
                    file_stat['problem_set'] = '未分類'
        
        print(f"\n分析完成:")
        print(f"  總掃描檔案數: {results['total_files']}")
        print(f"  ANR 檔案數: {results.get('anr_subject_count', 0)}")
        print(f"  Tombstone 檔案數: {results['files_with_cmdline'] - results.get('anr_subject_count', 0)}")
        print(f"  分析耗時: {results['analysis_time']:.2f} 秒")
        
        # 建立輸出目錄
        output_dir_name = f".cli_anr_tombstones_analyze"
        output_path = os.path.join(temp_dir, output_dir_name)
        os.makedirs(output_path, exist_ok=True)
        
        # 執行 vp_analyze
        vp_analyze_success = run_vp_analyze(temp_dir, output_path)
        
        # 生成所有報告檔案
        print("\n生成報告檔案...")
        
        # 1. 生成 Excel 檔案
        excel_data = generate_excel_file(output_path, results, output_path, temp_dir)
        
        # 2. 生成 HTML 統計報告
        generate_html_report(output_path, results, output_path, temp_dir)
        
        # 3. 生成 Excel 報表 HTML
        if excel_data:
            generate_excel_report_html(output_path, excel_data, temp_dir)
        
        # 儲存原始分析結果
        with open(os.path.join(output_path, 'analysis_results.json'), 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        # 建立輸出 ZIP
        output_path_abs = os.path.abspath(args.output)
        create_output_zip(output_path, output_path_abs)
        
        print("\n分析完成！")
        print(f"已生成以下檔案：")
        print(f"  - all_anr_tombstone_result.xlsx")
        print(f"  - all_anr_tombstone_result.html")
        print(f"  - all_anr_tombstone_excel_result.html")
        print(f"  - analysis_results.json")
        print(f"  - vp_analyze 分析結果（如果成功）")
        
    except Exception as e:
        print(f"\n錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        # 清理臨時檔案
        if not args.keep_temp:
            print(f"\n清理臨時檔案: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            print(f"\n保留臨時檔案: {temp_dir}")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())