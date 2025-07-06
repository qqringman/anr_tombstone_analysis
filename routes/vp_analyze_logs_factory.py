"""
分析器工廠類別 - 獨立檔案避免循環引入
"""

from typing import TYPE_CHECKING

# 使用 TYPE_CHECKING 避免運行時的循環引入
if TYPE_CHECKING:
    from vp_analyze_logs import BaseAnalyzer

class AnalyzerFactory:
    """分析器工廠"""
    
    @staticmethod
    def create_analyzer(file_type: str) -> 'BaseAnalyzer':
        """創建分析器"""
        # 延遲導入避免循環引入
        from vp_analyze_logs import ANRAnalyzer, TombstoneAnalyzer
        
        if file_type.lower() == "anr":
            return ANRAnalyzer()
        elif file_type.lower() in ["tombstone", "tombstones"]:
            return TombstoneAnalyzer()
        else:
            raise ValueError(f"不支援的檔案類型: {file_type}")