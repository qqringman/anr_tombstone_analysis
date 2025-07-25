pip freeze > requirements.txt
pip3 install --break-system-packages -r requirements.txt


# 基本使用
python3.12 cli_wrapper.py -i anr.zip,tombstone.txt -o result.zip

# 多檔案和資料夾
python3.12 cli_wrapper.py -i file1.zip,file2.txt,/path/to/logs -o output.zip --auto-group

ex: python3.12 cli_wrapper.py -i /home/vince_lin/ai/bugreport-SmartTV_4K-UKR9.250718.002-2025-07-24-03-55-26.zip,/home/vince_lin/ai/anr_2025-07-24-03-56-24-800,/home/vince_lin/ai/tombstone_00 -o vp_anr_tombstone_output.zip --auto-group

# 保留臨時檔案（用於除錯）
python3.12 cli_wrapper.py -i anr.txt -o result.zip --keep-temp
