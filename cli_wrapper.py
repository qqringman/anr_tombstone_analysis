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

# 將當前目錄加入 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 導入分析器
from routes.grep_analyzer import AndroidLogAnalyzer

def parse_arguments():
    """解析命令列參數"""
    parser = argparse.ArgumentParser(
        description='Android ANR/Tombstone Analyzer CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    # 分析單一檔案
    python3.12 cli_wrapper.py -input anr.txt -output result.zip
    
    # 分析多個檔案和資料夾
    python3.12 cli_wrapper.py -input anr.zip,tombstone.txt,/logs/folder -output result.zip
    
    # 自動分組獨立檔案
    python3.12 cli_wrapper.py -input anr1.txt,anr2.txt -output result.zip --auto-group
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
        run_vp_analyze(temp_dir, output_path)
        
        # 儲存分析結果
        print("\n儲存分析結果...")
        
        # 儲存 JSON 結果
        with open(os.path.join(output_path, 'analysis_results.json'), 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        # 儲存摘要報告
        with open(os.path.join(output_path, 'summary.txt'), 'w', encoding='utf-8') as f:
            f.write("Android ANR/Tombstone Analysis Summary\n")
            f.write("="*50 + "\n")
            f.write(f"分析時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"總掃描檔案數: {results['total_files']}\n")
            f.write(f"ANR 檔案數: {results.get('anr_subject_count', 0)}\n")
            f.write(f"Tombstone 檔案數: {results['files_with_cmdline'] - results.get('anr_subject_count', 0)}\n")
            f.write(f"分析耗時: {results['analysis_time']:.2f} 秒\n")
            f.write("\n程序統計 (Top 10):\n")
            
            # 統計程序
            process_count = {}
            for log in results.get('logs', []):
                process = log.get('process', 'Unknown')
                process_count[process] = process_count.get(process, 0) + 1
            
            sorted_processes = sorted(process_count.items(), key=lambda x: x[1], reverse=True)[:10]
            for process, count in sorted_processes:
                f.write(f"  {process}: {count}\n")
        
        # 建立輸出 ZIP
        output_path_abs = os.path.abspath(args.output)
        create_output_zip(output_path, output_path_abs)
        
        print("\n分析完成！")
        
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