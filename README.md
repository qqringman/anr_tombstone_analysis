pip3 freeze > requirements.txt
pip3 install --break-system-packages -r requirements.txt

# #################################################################
# JIRA 整合配置說明
# #################################################################

## 配置方式

### 方式 1：使用配置檔案
1. 複製範例檔案：`cp jira_config.json.example jira_config.json`
2. 編輯 `jira_config.json`，填入您的 JIRA 資訊

### 方式 2：使用環境變數 
```bash
# RTK 實例
export JIRA_RTK_URL="https://jira.realtek.com"
export JIRA_RTK_TOKEN="your-token-here"
export JIRA_RTK_USERNAME="your-email@realtek.com"

# Vendor 實例
export JIRA_VENDOR_URL="https://vendorjira.realtek.com"
export JIRA_VENDOR_TOKEN="your-vendor-token"
export JIRA_VENDOR_USERNAME="your-email@realtek.com"

# 或使用通用設定
export JIRA_INSTANCE="custom"
export JIRA_URL="https://jira.example.com"
export JIRA_TOKEN="your-token"
export JIRA_USERNAME="your-username"

# #################################################################
# 所有應用組合範例
# #################################################################

# 1. 基本使用場景
# 1.1 只分析本地檔案
# 分析單一本地檔案
python3.12 cli_wrapper.py -i anr.txt -o result.zip

# 分析多個本地檔案
python3.12 cli_wrapper.py -i anr.txt,tombstone.txt -o result.zip

# 分析整個資料夾
python3.12 cli_wrapper.py -i /path/to/logs -o result.zip

# 分析 7z 壓縮檔
python3.12 cli_wrapper.py -i log_archive.7z -o result.zip --auto-group

# 混合分析（檔案 + 資料夾 + 壓縮檔）
python3.12 cli_wrapper.py -i anr.txt,logs.zip,/log/folder,data.7z -o result.zip --auto-group

# 2. JIRA 整合場景
# 2.1 從 JIRA 下載並分析
# 下載單一 issue 的所有附件
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    -o result.zip

# 下載多個 issues 的附件
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660,MAC8QQC-3661,MAC8QQC-3662 \
    -o result.zip

# 只下載特定類型的檔案
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    --jira-file-patterns "*.7z,*.txt,*.log" \
    -o result.zip

# 使用不同的 JIRA 實例（vendor）
python3.12 cli_wrapper.py \
    --jira-instance vendor \
    --jira-issues VEN-1234 \
    --jira-file-patterns "*.zip" \
    -o result.zip

# 2.2 下載、分析並上傳回 JIRA
# 基本：下載→分析→上傳到同一個 issue
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    --jira-file-patterns "*.7z,*.txt" \
    -o result.zip \
    --upload-to-jira

# 從已關閉的 issue 下載，但上傳到開放的 issue
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    --jira-file-patterns "*.7z,*.txt" \
    -o result.zip \
    --upload-to-jira \
    --upload-issue ML9QC-280

# 自動處理已關閉的 issue（reopen→上傳→close）
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    --jira-file-patterns "*.7z,*.txt" \
    -o result.zip \
    --upload-to-jira

# 不要自動 reopen（如果 issue 已關閉則跳過）
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    --jira-file-patterns "*.7z,*.txt" \
    -o result.zip \
    --upload-to-jira \
    --no-auto-reopen

# 3. 混合使用場景
# 3.1 結合本地檔案和 JIRA 檔案
# 本地檔案 + JIRA 下載一起分析
python3.12 cli_wrapper.py \
    -i local_anr.txt,local_logs.7z \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    --jira-file-patterns "*.txt,*.7z" \
    -o combined_result.zip \
    --auto-group

# 從 MAC8QQC-3660 下載，但上傳到 ML9QC-280
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    --jira-file-patterns "*.7z,*.txt" \
    -o vp_result.zip \
    --upload-to-jira \
    --upload-issue ML9QC-280

# 分析多個來源，上傳到特定 issue
python3.12 cli_wrapper.py \
    -i /local/logs \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660,MAC8QQC-3661 \
    --jira-file-patterns "*.log" \
    -o analysis_result.zip \
    --upload-to-jira \
    --upload-issue PROJECT-999

# 3.2 多個 JIRA issues 批次處理
# 從多個 issues 下載，分析後上傳到一個統一的 issue
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660,MAC8QQC-3661,MAC8QQC-3662 \
    --jira-file-patterns "*.7z,*.txt" \
    -o batch_result.zip \
    --upload-to-jira \
    --upload-issue SUMMARY-001

# 每個 issue 分別處理並上傳
for issue in MAC8QQC-3660 MAC8QQC-3661 MAC8QQC-3662; do
    python3.12 cli_wrapper.py \
        --jira-instance rtk \
        --jira-issues $issue \
        --jira-file-patterns "*.7z,*.txt" \
        -o ${issue}_result.zip \
        --upload-to-jira
done

# 4. 進階使用場景
# 4.1 使用自訂配置檔案
# 使用不同的 JIRA 配置檔案
python3.12 cli_wrapper.py \
    --jira-instance prod \
    --jira-issues PROD-123 \
    --jira-config-file /path/to/custom_jira_config.json \
    -o result.zip

# 保留臨時檔案以便除錯
python3.12 cli_wrapper.py \
    -i debug_logs.7z \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    -o result.zip \
    --keep-temp

# 4.2 特殊檔案模式
# 只下載壓縮檔
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    --jira-file-patterns "*.zip,*.7z,*.rar,*.tar.gz" \
    -o compressed_only.zip

# 排除某些檔案（需要下載全部然後手動過濾）
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues MAC8QQC-3660 \
    -o all_files.zip

# 5. 實際工作流程範例
# 5.1 日常 ANR 分析流程
# 每日 ANR 分析任務
DATE=$(date +%Y%m%d)
python3.12 cli_wrapper.py \
    --jira-instance rtk \
    --jira-issues $(cat daily_issues.txt | tr '\n' ',') \
    --jira-file-patterns "*.7z,*.txt,anr*,tombstone*" \
    -o daily_anr_${DATE}.zip \
    --upload-to-jira \
    --upload-issue DAILY-REPORT-${DATE}

# 5.2 問題追蹤分析
# 分析特定問題的所有相關 logs
python3.12 cli_wrapper.py \
    -i customer_logs.7z \
    --jira-instance rtk \
    --jira-issues BUG-1001,BUG-1002,BUG-1003 \
    --jira-file-patterns "*crash*,*anr*,*tombstone*" \
    -o bug_analysis.zip \
    --upload-to-jira \
    --upload-issue BUG-SUMMARY-1000

