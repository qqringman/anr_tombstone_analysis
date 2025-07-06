# 在 IntelligentAnalysisEngine 類之後添加

import json
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import numpy as np
from typing import List, Dict, Optional, Tuple, Set
import hashlib
import os
import re
import sys
import html
import shutil
import time
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set, TYPE_CHECKING
from enum import Enum
import traceback

# 導入基礎類別
from vp_analyze_logs_base import ANRInfo, ThreadInfo, ThreadState

# 使用 TYPE_CHECKING 避免循環引入
if TYPE_CHECKING:
    from vp_analyze_logs import ANRAnalyzer, TombstoneAnalyzer

class TimelineAnalyzer:
    """時間軸分析器 - 重建事件發生的完整時序"""
    
    def __init__(self):
        self.event_patterns = {
            'gc': r'(GC_\w+).*?freed.*?paused\s+(\d+)ms',
            'binder': r'(BinderProxy|Binder).*?(transact|onTransact)',
            'input': r'Input\s+event.*?dispatching',
            'service': r'(Service|Activity).*?(onCreate|onStart|onBind)',
            'broadcast': r'(Broadcast|Receiver).*?onReceive',
            'anr_trigger': r'ANR\s+in|Input\s+dispatching\s+timed\s+out',
            'cpu_spike': r'CPU\s+usage.*?(\d+)%',
            'memory_pressure': r'(Low\s+memory|Out\s+of\s+memory)',
            'lock_wait': r'waiting\s+to\s+lock|waiting\s+on',
            'thread_state_change': r'tid=\d+.*?state\s+changed',
        }
    
    def analyze_timeline(self, content: str, anr_info: ANRInfo) -> Dict:
        """分析事件時間線"""
        timeline = {
            'events': [],
            'critical_period': None,
            'pattern': None,
            'event_clusters': [],
            'anomalies': [],
            'recommendations': []
        }
        
        # 提取所有時間戳事件
        events = self._extract_timestamped_events(content)
        timeline['events'] = events
        
        # 識別關鍵時期
        timeline['critical_period'] = self._identify_critical_period(events)
        
        # 識別事件模式
        timeline['pattern'] = self._identify_temporal_pattern(events)
        
        # 事件聚類
        timeline['event_clusters'] = self._cluster_events(events)
        
        # 檢測異常
        timeline['anomalies'] = self._detect_temporal_anomalies(events)
        
        # 生成建議
        timeline['recommendations'] = self._generate_timeline_recommendations(timeline)
        
        return timeline
    
    def _extract_timestamped_events(self, content: str) -> List[Dict]:
        """提取所有帶時間戳的事件"""
        events = []
        
        # 多種時間戳格式
        timestamp_patterns = [
            r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\s+(\d+)\s+(\d+)\s+(\w)\s+(.+)',  # logcat格式
            r'(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\s+(.+)',  # 簡化格式
            r'\[(\d+\.\d+)\]\s+(.+)',  # kernel格式
        ]
        
        for pattern in timestamp_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            for match in matches:
                if len(match) >= 2:
                    timestamp = match[0]
                    event_desc = match[-1]
                    
                    event_type = self._classify_event(event_desc)
                    severity = self._assess_event_severity(event_type, event_desc)
                    
                    events.append({
                        'timestamp': timestamp,
                        'type': event_type,
                        'description': event_desc,
                        'severity': severity,
                        'metrics': self._extract_event_metrics(event_desc)
                    })
        
        # 按時間排序
        events.sort(key=lambda x: x['timestamp'])
        
        return events
    
    def _classify_event(self, event_desc: str) -> str:
        """分類事件類型"""
        for event_type, pattern in self.event_patterns.items():
            if re.search(pattern, event_desc, re.IGNORECASE):
                return event_type
        return 'unknown'
    
    def _assess_event_severity(self, event_type: str, event_desc: str) -> int:
        """評估事件嚴重性 (1-10)"""
        severity_map = {
            'anr_trigger': 10,
            'memory_pressure': 9,
            'cpu_spike': 8,
            'lock_wait': 7,
            'gc': 5,
            'binder': 4,
            'service': 3,
            'input': 6,
            'broadcast': 4,
            'thread_state_change': 2,
            'unknown': 1
        }
        
        base_severity = severity_map.get(event_type, 1)
        
        # 根據具體內容調整
        if 'blocked' in event_desc.lower():
            base_severity += 2
        if 'timeout' in event_desc.lower():
            base_severity += 1
        if 'failed' in event_desc.lower() or 'error' in event_desc.lower():
            base_severity += 1
            
        return min(base_severity, 10)
    
    def _extract_event_metrics(self, event_desc: str) -> Dict:
        """提取事件中的度量數據"""
        metrics = {}
        
        # 提取數字
        numbers = re.findall(r'(\d+(?:\.\d+)?)\s*(%|ms|MB|KB|s)', event_desc)
        for value, unit in numbers:
            if unit == '%':
                metrics['percentage'] = float(value)
            elif unit in ['ms', 's']:
                metrics['duration'] = float(value) * (1000 if unit == 's' else 1)
            elif unit in ['MB', 'KB']:
                metrics['memory'] = float(value) * (1024 if unit == 'MB' else 1)
        
        return metrics
    
    def _identify_critical_period(self, events: List[Dict]) -> Optional[Dict]:
        """識別關鍵時期"""
        if not events:
            return None
        
        # 找出高嚴重性事件的時間窗口
        high_severity_events = [e for e in events if e['severity'] >= 7]
        
        if not high_severity_events:
            return None
        
        # 計算事件密度
        time_windows = []
        window_size = 5000  # 5秒窗口
        
        for i in range(len(events)):
            window_start = events[i]['timestamp']
            window_events = []
            
            for j in range(i, len(events)):
                # 簡化時間比較，實際應該解析時間戳
                if self._time_diff_ms(events[i]['timestamp'], events[j]['timestamp']) <= window_size:
                    window_events.append(events[j])
                else:
                    break
            
            if len(window_events) > 3:  # 至少3個事件
                avg_severity = sum(e['severity'] for e in window_events) / len(window_events)
                time_windows.append({
                    'start': window_start,
                    'end': window_events[-1]['timestamp'],
                    'event_count': len(window_events),
                    'avg_severity': avg_severity,
                    'events': window_events
                })
        
        # 返回最關鍵的時期
        if time_windows:
            return max(time_windows, key=lambda w: w['avg_severity'] * w['event_count'])
        
        return None
    
    def _time_diff_ms(self, time1: str, time2: str) -> int:
        """計算時間差（毫秒）- 簡化版本"""
        # 實際應該解析時間戳格式
        return 1000  # 暫時返回固定值
    
    def _identify_temporal_pattern(self, events: List[Dict]) -> Dict:
        """識別時間模式"""
        if len(events) < 3:
            return {'type': 'insufficient_data'}
        
        # 分析事件間隔
        intervals = []
        for i in range(1, len(events)):
            interval = self._time_diff_ms(events[i-1]['timestamp'], events[i]['timestamp'])
            intervals.append(interval)
        
        # 統計分析
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            
            # 判斷模式
            if avg_interval < 100:
                pattern_type = 'burst'
                description = '事件爆發 - 短時間內大量事件'
            elif avg_interval > 5000:
                pattern_type = 'sparse'
                description = '事件稀疏 - 間隔較長'
            else:
                pattern_type = 'regular'
                description = '規律事件流'
            
            # 檢查週期性
            periodicity = self._check_periodicity(intervals)
            
            return {
                'type': pattern_type,
                'description': description,
                'avg_interval': avg_interval,
                'periodicity': periodicity,
                'event_distribution': self._analyze_distribution(events)
            }
        
        return {'type': 'unknown'}
    
    def _check_periodicity(self, intervals: List[int]) -> Optional[Dict]:
        """檢查週期性"""
        if len(intervals) < 5:
            return None
        
        # 簡單的週期檢測
        for period in range(2, min(10, len(intervals) // 2)):
            is_periodic = True
            for i in range(period, len(intervals)):
                if abs(intervals[i] - intervals[i - period]) > 100:  # 100ms 容差
                    is_periodic = False
                    break
            
            if is_periodic:
                return {
                    'detected': True,
                    'period': period,
                    'interval': sum(intervals[i] for i in range(period)) / period
                }
        
        return {'detected': False}
    
    def _analyze_distribution(self, events: List[Dict]) -> Dict:
        """分析事件分布"""
        type_counts = Counter(e['type'] for e in events)
        severity_distribution = Counter(e['severity'] for e in events)
        
        return {
            'by_type': dict(type_counts),
            'by_severity': dict(severity_distribution),
            'dominant_type': type_counts.most_common(1)[0][0] if type_counts else None
        }
    
    def _cluster_events(self, events: List[Dict]) -> List[Dict]:
        """事件聚類"""
        if len(events) < 2:
            return []
        
        clusters = []
        current_cluster = [events[0]]
        cluster_threshold = 1000  # 1秒內的事件歸為一類
        
        for i in range(1, len(events)):
            if self._time_diff_ms(current_cluster[-1]['timestamp'], events[i]['timestamp']) <= cluster_threshold:
                current_cluster.append(events[i])
            else:
                if len(current_cluster) > 1:
                    clusters.append(self._analyze_cluster(current_cluster))
                current_cluster = [events[i]]
        
        if len(current_cluster) > 1:
            clusters.append(self._analyze_cluster(current_cluster))
        
        return clusters
    
    def _analyze_cluster(self, cluster_events: List[Dict]) -> Dict:
        """分析事件簇"""
        return {
            'start_time': cluster_events[0]['timestamp'],
            'end_time': cluster_events[-1]['timestamp'],
            'event_count': len(cluster_events),
            'types': list(set(e['type'] for e in cluster_events)),
            'max_severity': max(e['severity'] for e in cluster_events),
            'description': self._describe_cluster(cluster_events)
        }
    
    def _describe_cluster(self, cluster_events: List[Dict]) -> str:
        """描述事件簇"""
        type_counts = Counter(e['type'] for e in cluster_events)
        dominant_type = type_counts.most_common(1)[0][0]
        
        descriptions = {
            'gc': 'GC 壓力期',
            'binder': 'Binder 通信高峰',
            'lock_wait': '鎖競爭密集',
            'cpu_spike': 'CPU 使用高峰'
        }
        
        return descriptions.get(dominant_type, '混合事件簇')
    
    def _detect_temporal_anomalies(self, events: List[Dict]) -> List[Dict]:
        """檢測時間異常"""
        anomalies = []
        
        # 檢測異常長的間隔
        for i in range(1, len(events)):
            interval = self._time_diff_ms(events[i-1]['timestamp'], events[i]['timestamp'])
            if interval > 10000:  # 10秒
                anomalies.append({
                    'type': 'long_gap',
                    'timestamp': events[i-1]['timestamp'],
                    'duration': interval,
                    'description': f'{interval}ms 的異常長間隔'
                })
        
        # 檢測事件風暴
        for cluster in self._cluster_events(events):
            if cluster['event_count'] > 20:
                anomalies.append({
                    'type': 'event_storm',
                    'timestamp': cluster['start_time'],
                    'count': cluster['event_count'],
                    'description': f'{cluster["event_count"]} 個事件在短時間內發生'
                })
        
        return anomalies
    
    def _generate_timeline_recommendations(self, timeline: Dict) -> List[str]:
        """生成時間線相關建議"""
        recommendations = []
        
        if timeline['pattern'] and timeline['pattern']['type'] == 'burst':
            recommendations.append('檢測到事件爆發模式，建議實施事件限流機制')
        
        if timeline['critical_period']:
            recommendations.append(
                f'關鍵時期包含 {timeline["critical_period"]["event_count"]} 個事件，'
                f'平均嚴重性 {timeline["critical_period"]["avg_severity"]:.1f}'
            )
        
        for anomaly in timeline['anomalies']:
            if anomaly['type'] == 'event_storm':
                recommendations.append(f'事件風暴檢測：{anomaly["description"]}')
        
        return recommendations


class CrossProcessAnalyzer:
    """跨進程分析器 - 分析多個進程間的交互"""
    
    def __init__(self):
        self.binder_transaction_pattern = re.compile(
            r'(\d+):(\d+)\s+.*?Binder.*?transaction.*?from\s+(\d+):(\d+)\s+to\s+(\d+):(\d+)'
        )
        self.shared_resources = {
            'content_providers': [],
            'services': [],
            'broadcasts': [],
            'files': [],
            'sockets': []
        }
    
    def analyze_cross_process(self, log_files: List[str]) -> Dict:
        """分析跨進程問題"""
        analysis = {
            'process_interactions': {},
            'shared_resources': {},
            'contention_points': [],
            'causality_chain': [],
            'synchronization_issues': [],
            'recommendations': []
        }
        
        # 解析所有日誌檔案
        all_events = []
        for file_path in log_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    events = self._extract_process_events(content)
                    all_events.extend(events)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
        
        # 構建進程交互圖
        analysis['process_interactions'] = self._build_interaction_graph(all_events)
        
        # 識別共享資源
        analysis['shared_resources'] = self._identify_shared_resources(all_events)
        
        # 找出競爭點
        analysis['contention_points'] = self._find_contention_points(all_events)
        
        # 構建因果鏈
        analysis['causality_chain'] = self._build_causality_chain(all_events)
        
        # 檢測同步問題
        analysis['synchronization_issues'] = self._detect_sync_issues(all_events)
        
        # 生成建議
        analysis['recommendations'] = self._generate_cross_process_recommendations(analysis)
        
        return analysis
    
    def _extract_process_events(self, content: str) -> List[Dict]:
        """提取進程相關事件"""
        events = []
        
        # Binder 事務
        binder_matches = self.binder_transaction_pattern.findall(content)
        for match in binder_matches:
            events.append({
                'type': 'binder_transaction',
                'from_pid': match[0],
                'from_tid': match[1],
                'to_pid': match[2],
                'to_tid': match[3],
                'timestamp': self._extract_timestamp(match)
            })
        
        # 其他跨進程事件模式...
        
        return events
    
    def _build_interaction_graph(self, events: List[Dict]) -> Dict:
        """構建進程交互圖"""
        graph = defaultdict(lambda: defaultdict(int))
        
        for event in events:
            if event['type'] == 'binder_transaction':
                from_pid = event['from_pid']
                to_pid = event['to_pid']
                graph[from_pid][to_pid] += 1
        
        return dict(graph)
    
    def _identify_shared_resources(self, events: List[Dict]) -> Dict:
        """識別共享資源"""
        resources = defaultdict(set)
        
        for event in events:
            if 'resource' in event:
                resource_type = event['resource_type']
                resource_name = event['resource_name']
                accessor_pid = event['pid']
                resources[resource_type].add((resource_name, accessor_pid))
        
        # 找出被多個進程訪問的資源
        shared = {}
        for resource_type, items in resources.items():
            shared_items = defaultdict(set)
            for name, pid in items:
                shared_items[name].add(pid)
            
            shared[resource_type] = {
                name: list(pids) for name, pids in shared_items.items()
                if len(pids) > 1
            }
        
        return shared
    
    def _find_contention_points(self, events: List[Dict]) -> List[Dict]:
        """找出資源競爭點"""
        contentions = []
        
        # 分析同時訪問相同資源的情況
        resource_timeline = defaultdict(list)
        
        for event in events:
            if 'resource' in event:
                key = (event['resource_type'], event['resource_name'])
                resource_timeline[key].append(event)
        
        # 檢測競爭
        for resource, timeline in resource_timeline.items():
            timeline.sort(key=lambda x: x.get('timestamp', 0))
            
            for i in range(1, len(timeline)):
                if self._is_contention(timeline[i-1], timeline[i]):
                    contentions.append({
                        'resource': resource,
                        'processes': [timeline[i-1]['pid'], timeline[i]['pid']],
                        'type': 'concurrent_access',
                        'severity': self._assess_contention_severity(timeline[i-1], timeline[i])
                    })
        
        return contentions
    
    def _build_causality_chain(self, events: List[Dict]) -> List[Dict]:
        """構建因果關係鏈"""
        chains = []
        
        # 按時間排序
        sorted_events = sorted(events, key=lambda x: x.get('timestamp', 0))
        
        # 尋找因果關係
        for i in range(len(sorted_events) - 1):
            event1 = sorted_events[i]
            event2 = sorted_events[i + 1]
            
            if self._is_causal_related(event1, event2):
                chains.append({
                    'cause': event1,
                    'effect': event2,
                    'confidence': self._calculate_causality_confidence(event1, event2)
                })
        
        return chains
    
    def _detect_sync_issues(self, events: List[Dict]) -> List[Dict]:
        """檢測同步問題"""
        issues = []
        
        # 檢測死鎖可能
        lock_holders = defaultdict(set)
        lock_waiters = defaultdict(set)
        
        for event in events:
            if event.get('type') == 'lock_acquire':
                lock_holders[event['lock_id']].add(event['pid'])
            elif event.get('type') == 'lock_wait':
                lock_waiters[event['lock_id']].add(event['pid'])
        
        # 檢查循環等待
        for lock_id, waiters in lock_waiters.items():
            for waiter in waiters:
                if waiter in lock_holders:
                    # 可能的死鎖
                    issues.append({
                        'type': 'potential_deadlock',
                        'lock': lock_id,
                        'process': waiter,
                        'description': f'進程 {waiter} 持有鎖並等待其他鎖'
                    })
        
        return issues
    
    def _generate_cross_process_recommendations(self, analysis: Dict) -> List[str]:
        """生成跨進程分析建議"""
        recommendations = []
        
        # 基於交互頻率
        for from_pid, interactions in analysis['process_interactions'].items():
            total_interactions = sum(interactions.values())
            if total_interactions > 100:
                recommendations.append(
                    f'進程 {from_pid} 有大量跨進程調用 ({total_interactions} 次)，'
                    f'考慮使用批量操作或快取'
                )
        
        # 基於資源競爭
        if analysis['contention_points']:
            recommendations.append(
                f'檢測到 {len(analysis["contention_points"])} 個資源競爭點，'
                f'建議實施細粒度鎖或無鎖設計'
            )
        
        return recommendations
    
    def _extract_timestamp(self, match) -> int:
        """提取時間戳 - 簡化實現"""
        return 0
    
    def _is_contention(self, event1: Dict, event2: Dict) -> bool:
        """判斷是否存在競爭"""
        # 簡化實現：如果兩個事件時間接近且來自不同進程
        return (event1['pid'] != event2['pid'] and 
                abs(event1.get('timestamp', 0) - event2.get('timestamp', 0)) < 100)
    
    def _assess_contention_severity(self, event1: Dict, event2: Dict) -> str:
        """評估競爭嚴重性"""
        # 簡化實現
        return 'medium'
    
    def _is_causal_related(self, event1: Dict, event2: Dict) -> bool:
        """判斷是否有因果關係"""
        # 簡化實現：如果 event1 的輸出是 event2 的輸入
        return False
    
    def _calculate_causality_confidence(self, event1: Dict, event2: Dict) -> float:
        """計算因果關係置信度"""
        return 0.5


## 2. AI 增強分析模塊
class FeatureExtractor:
    """特徵提取器"""
    
    def extract(self, anr_info: ANRInfo) -> np.ndarray:
        """從 ANR 資訊中提取特徵向量"""
        features = []
        
        # 線程特徵
        features.append(len(anr_info.all_threads))
        features.append(sum(1 for t in anr_info.all_threads if t.state == ThreadState.BLOCKED))
        features.append(sum(1 for t in anr_info.all_threads if t.waiting_locks))
        
        # CPU 特徵
        if anr_info.cpu_usage:
            features.append(anr_info.cpu_usage.get('total', 0))
            features.append(anr_info.cpu_usage.get('user', 0))
            features.append(anr_info.cpu_usage.get('system', 0))
        else:
            features.extend([0, 0, 0])
        
        # 記憶體特徵
        if anr_info.memory_info:
            features.append(anr_info.memory_info.get('available', 0) / 1024)  # MB
            features.append(anr_info.memory_info.get('used_percent', 0))
        else:
            features.extend([0, 0])
        
        # 堆疊深度特徵
        if anr_info.main_thread:
            features.append(len(anr_info.main_thread.backtrace))
        else:
            features.append(0)
        
        return np.array(features)

class MLAnomalyDetector:
    """機器學習異常檢測器"""
    
    def __init__(self):
        self.feature_extractor = FeatureExtractor()
        self.anomaly_model = self._load_or_train_model()
        self.threshold = 0.8
        
    def _load_or_train_model(self):
        """載入或訓練模型 - 簡化實現"""
        # 實際應該使用 sklearn 的 IsolationForest 或類似算法
        return None
    
    def detect_anomalies(self, anr_info: ANRInfo) -> List[Dict]:
        """檢測異常模式"""
        # 提取特徵
        features = self.feature_extractor.extract(anr_info)
        
        # 簡化的異常檢測邏輯
        anomalies = []
        
        # 規則基礎的異常檢測
        if features[0] > 200:  # 線程數異常
            anomalies.append({
                'type': 'unusual_thread_count',
                'score': 0.9,
                'feature': 'thread_count',
                'value': features[0],
                'explanation': f'線程數量異常高: {features[0]} (正常範圍: 50-150)'
            })
        
        if features[3] > 90:  # CPU 異常
            anomalies.append({
                'type': 'unusual_cpu_usage',
                'score': 0.85,
                'feature': 'cpu_usage',
                'value': features[3],
                'explanation': f'CPU 使用率異常: {features[3]}%'
            })
        
        if features[8] > 100:  # 堆疊深度異常
            anomalies.append({
                'type': 'unusual_stack_depth',
                'score': 0.8,
                'feature': 'stack_depth',
                'value': features[8],
                'explanation': f'堆疊深度異常: {features[8]} 層 (可能遞迴)'
            })
        
        return anomalies
    
    def _explain_anomaly(self, features: np.ndarray) -> str:
        """解釋異常"""
        explanations = []
        
        feature_names = [
            '線程總數', '阻塞線程數', '等待鎖線程數',
            'CPU總使用率', 'CPU用戶態', 'CPU內核態',
            '可用記憶體', '記憶體使用率', '堆疊深度'
        ]
        
        # 找出異常特徵
        mean_values = [100, 5, 3, 50, 30, 20, 500, 70, 30]  # 預設正常值
        
        for i, (value, mean) in enumerate(zip(features, mean_values)):
            if abs(value - mean) > mean * 0.5:  # 偏離50%以上
                explanations.append(
                    f'{feature_names[i]}: {value:.1f} (正常: ~{mean})'
                )
        
        return ' | '.join(explanations) if explanations else '無明顯異常特徵'


class RootCausePredictor:
    """根本原因預測器"""
    
    def __init__(self):
        self.symptom_patterns = self._init_symptom_patterns()
        self.fix_strategies = self._init_fix_strategies()
    
    def _init_symptom_patterns(self) -> Dict:
        """初始化症狀模式"""
        return {
            'main_thread_io': {
                'symptoms': ['main.*File', 'main.*SQLite', 'main.*SharedPreferences'],
                'cause': '主線程執行 I/O 操作',
                'confidence_base': 0.9
            },
            'deadlock': {
                'symptoms': ['waiting to lock', 'held by', 'circular'],
                'cause': '線程死鎖',
                'confidence_base': 0.85
            },
            'memory_pressure': {
                'symptoms': ['GC_', 'OutOfMemory', 'lowmemorykiller'],
                'cause': '記憶體壓力',
                'confidence_base': 0.8
            },
            'binder_timeout': {
                'symptoms': ['BinderProxy.transact', 'DeadObjectException'],
                'cause': 'Binder 通信超時',
                'confidence_base': 0.85
            },
            'cpu_contention': {
                'symptoms': ['CPU usage.*9[0-9]%', 'load average.*[4-9]'],
                'cause': 'CPU 資源競爭',
                'confidence_base': 0.75
            }
        }
    
    def _init_fix_strategies(self) -> Dict:
        """初始化修復策略"""
        return {
            'main_thread_io': [
                '使用 AsyncTask 或 Kotlin Coroutines',
                '將 I/O 操作移至 WorkManager',
                'SharedPreferences 使用 apply() 而非 commit()',
                '使用 Room 的異步 API'
            ],
            'deadlock': [
                '使用一致的鎖獲取順序',
                '實施鎖超時機制',
                '使用 java.util.concurrent 的高級同步工具',
                '避免嵌套鎖'
            ],
            'memory_pressure': [
                '優化 Bitmap 使用和回收',
                '實施記憶體快取策略',
                '使用 WeakReference 或 SoftReference',
                '檢查並修復記憶體洩漏'
            ],
            'binder_timeout': [
                '使用 oneway 異步 Binder 調用',
                '實施 Binder 調用超時和重試',
                '減少跨進程數據傳輸量',
                '批量處理 Binder 請求'
            ],
            'cpu_contention': [
                '優化算法複雜度',
                '使用線程池限制並發',
                '實施計算任務的批處理',
                '考慮使用 RenderScript 或 GPU 加速'
            ]
        }
    
    def predict_root_cause(self, symptoms: List[str]) -> List[Dict]:
        """基於症狀預測根本原因"""
        predictions = []
        
        # 將症狀轉換為文本
        symptom_text = ' '.join(symptoms).lower()
        
        # 匹配已知模式
        for pattern_name, pattern_info in self.symptom_patterns.items():
            matching_symptoms = []
            
            for symptom_pattern in pattern_info['symptoms']:
                if re.search(symptom_pattern, symptom_text, re.IGNORECASE):
                    matching_symptoms.append(symptom_pattern)
            
            if matching_symptoms:
                confidence = pattern_info['confidence_base'] * (
                    len(matching_symptoms) / len(pattern_info['symptoms'])
                )
                
                predictions.append({
                    'cause': pattern_info['cause'],
                    'confidence': confidence,
                    'evidence': matching_symptoms,
                    'fix_strategy': self.fix_strategies.get(pattern_name, [])
                })
        
        # 排序並返回
        return sorted(predictions, key=lambda x: x['confidence'], reverse=True)
    
    def _encode_symptoms(self, symptoms: List[str]) -> np.ndarray:
        """將症狀編碼為向量"""
        # 簡化實現 - 實際應使用 TF-IDF 或詞嵌入
        return np.random.rand(len(symptoms), 100)
    
    def _get_fix_strategy(self, cause_type: str) -> List[str]:
        """獲取修復策略"""
        return self.fix_strategies.get(cause_type, ['請諮詢開發團隊'])


## 3. 視覺化增強模塊
class VisualizationGenerator:
    """視覺化生成器"""
    
    def generate_interactive_call_graph(self, anr_info: ANRInfo) -> str:
        """生成互動式調用圖"""
        graph_data = self._prepare_graph_data(anr_info)
        
        return f'''
        <div id="call-graph-container" style="width: 100%; height: 600px;"></div>
        <script src="https://d3js.org/d3.v7.min.js"></script>
        <script>
        // 圖表數據
        const graphData = {json.dumps(graph_data)};
        
        // 創建 SVG
        const width = document.getElementById("call-graph-container").clientWidth;
        const height = 600;
        
        const svg = d3.select("#call-graph-container")
            .append("svg")
            .attr("width", width)
            .attr("height", height);
        
        // 添加縮放功能
        const g = svg.append("g");
        const zoom = d3.zoom()
            .scaleExtent([0.1, 10])
            .on("zoom", (event) => {{
                g.attr("transform", event.transform);
            }});
        svg.call(zoom);
        
        // 創建力導向圖
        const simulation = d3.forceSimulation(graphData.nodes)
            .force("link", d3.forceLink(graphData.links)
                .id(d => d.id)
                .distance(d => d.distance || 100))
            .force("charge", d3.forceManyBody().strength(-500))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(d => d.radius + 10));
        
        // 創建連線
        const link = g.append("g")
            .attr("class", "links")
            .selectAll("line")
            .data(graphData.links)
            .enter().append("line")
            .attr("stroke", d => {{
                if (d.type === "blocked") return "#ff4444";
                if (d.type === "waiting") return "#ffaa44";
                return "#999";
            }})
            .attr("stroke-width", d => Math.sqrt(d.strength || 1) * 2)
            .attr("opacity", 0.6);
        
        // 創建節點
        const node = g.append("g")
            .attr("class", "nodes")
            .selectAll("g")
            .data(graphData.nodes)
            .enter().append("g")
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));
        
        // 節點圓圈
        node.append("circle")
            .attr("r", d => d.radius || 20)
            .attr("fill", d => {{
                if (d.state === "BLOCKED") return "#ff4444";
                if (d.state === "WAITING") return "#ffaa44";
                if (d.state === "RUNNABLE") return "#44ff44";
                return "#4444ff";
            }})
            .attr("stroke", "#fff")
            .attr("stroke-width", 2);
        
        // 節點標籤
        node.append("text")
            .text(d => d.name)
            .attr("x", 0)
            .attr("y", 0)
            .attr("text-anchor", "middle")
            .attr("dy", ".35em")
            .style("font-size", "12px")
            .style("pointer-events", "none");
        
        // 添加提示框
        const tooltip = d3.select("body").append("div")
            .attr("class", "tooltip")
            .style("opacity", 0)
            .style("position", "absolute")
            .style("background", "rgba(0, 0, 0, 0.8)")
            .style("color", "white")
            .style("padding", "10px")
            .style("border-radius", "5px")
            .style("font-size", "12px");
        
        node.on("mouseover", function(event, d) {{
            tooltip.transition().duration(200).style("opacity", .9);
            tooltip.html(getNodeTooltip(d))
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 10) + "px");
        }})
        .on("mouseout", function(d) {{
            tooltip.transition().duration(500).style("opacity", 0);
        }});
        
        // 更新位置
        simulation.on("tick", () => {{
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);
            
            node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
        }});
        
        // 拖動功能
        function dragstarted(event, d) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }}
        
        function dragged(event, d) {{
            d.fx = event.x;
            d.fy = event.y;
        }}
        
        function dragended(event, d) {{
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }}
        
        // 生成提示內容
        function getNodeTooltip(d) {{
            return `
                <strong>${{d.name}}</strong><br/>
                TID: ${{d.tid}}<br/>
                狀態: ${{d.state}}<br/>
                優先級: ${{d.priority || 'N/A'}}<br/>
                ${{d.waiting_info ? '等待: ' + d.waiting_info : ''}}
            `;
        }}
        </script>
        '''
    
    def _prepare_graph_data(self, anr_info: ANRInfo) -> Dict:
        """準備圖表數據"""
        nodes = []
        links = []
        
        # 創建節點
        thread_map = {}
        for i, thread in enumerate(anr_info.all_threads):
            node = {
                'id': thread.tid,
                'tid': thread.tid,
                'name': thread.name[:20],  # 限制長度
                'state': thread.state.value,
                'priority': thread.prio,
                'radius': 30 if thread.tid == '1' else 20,  # 主線程更大
                'importance': 10 if thread.tid == '1' else 5,
                'waiting_info': thread.waiting_info
            }
            nodes.append(node)
            thread_map[thread.tid] = i
        
        # 創建連線（基於等待關係）
        for thread in anr_info.all_threads:
            if thread.waiting_info:
                match = re.search(r'held by (?:thread\s+)?(\d+)', thread.waiting_info)
                if match:
                    holder_tid = match.group(1)
                    if holder_tid in thread_map:
                        links.append({
                            'source': thread.tid,
                            'target': holder_tid,
                            'type': 'blocked',
                            'strength': 2
                        })
        
        return {'nodes': nodes, 'links': links}
    
    def generate_timeline_visualization(self, timeline_data: Dict) -> str:
        """生成時間軸視覺化"""
        return f'''
        <div class="timeline-container">
            <canvas id="timeline-chart" width="800" height="400"></canvas>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/date-fns@2.29.3/index.min.js"></script>
        <script>
        const ctx = document.getElementById('timeline-chart').getContext('2d');
        const timelineData = {json.dumps(timeline_data)};
        
        // 處理數據
        const datasets = {{
            'critical': {{
                label: '嚴重事件',
                data: [],
                backgroundColor: 'rgba(255, 68, 68, 0.8)',
                borderColor: 'rgba(255, 68, 68, 1)',
                pointRadius: 8
            }},
            'warning': {{
                label: '警告事件',
                data: [],
                backgroundColor: 'rgba(255, 170, 68, 0.8)',
                borderColor: 'rgba(255, 170, 68, 1)',
                pointRadius: 6
            }},
            'info': {{
                label: '普通事件',
                data: [],
                backgroundColor: 'rgba(68, 170, 255, 0.8)',
                borderColor: 'rgba(68, 170, 255, 1)',
                pointRadius: 4
            }}
        }};
        
        // 分類事件
        timelineData.events.forEach(event => {{
            const point = {{
                x: event.timestamp,
                y: event.severity,
                event: event
            }};
            
            if (event.severity >= 8) {{
                datasets.critical.data.push(point);
            }} else if (event.severity >= 5) {{
                datasets.warning.data.push(point);
            }} else {{
                datasets.info.data.push(point);
            }}
        }});
        
        // 創建圖表
        const timelineChart = new Chart(ctx, {{
            type: 'scatter',
            data: {{
                datasets: Object.values(datasets)
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{
                        type: 'time',
                        time: {{
                            parser: 'MM-DD HH:mm:ss.SSS',
                            displayFormats: {{
                                millisecond: 'HH:mm:ss.SSS',
                                second: 'HH:mm:ss',
                                minute: 'HH:mm'
                            }}
                        }},
                        title: {{
                            display: true,
                            text: '時間'
                        }}
                    }},
                    y: {{
                        title: {{
                            display: true,
                            text: '嚴重性 (1-10)'
                        }},
                        min: 0,
                        max: 10
                    }}
                }},
                plugins: {{
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                const event = context.raw.event;
                                return [
                                    `類型: ${{event.type}}`,
                                    `嚴重性: ${{event.severity}}`,
                                    `描述: ${{event.description.substring(0, 50)}}...`
                                ];
                            }}
                        }}
                    }},
                    zoom: {{
                        zoom: {{
                            wheel: {{
                                enabled: true,
                            }},
                            pinch: {{
                                enabled: true
                            }},
                            mode: 'x',
                        }},
                        pan: {{
                            enabled: true,
                            mode: 'x',
                        }}
                    }}
                }}
            }}
        }});
        
        // 添加關鍵時期標記
        if (timelineData.critical_period) {{
            const annotation = {{
                type: 'box',
                xMin: timelineData.critical_period.start,
                xMax: timelineData.critical_period.end,
                backgroundColor: 'rgba(255, 0, 0, 0.1)',
                borderColor: 'rgba(255, 0, 0, 0.5)',
                borderWidth: 2
            }};
            
            timelineChart.options.plugins.annotation = {{
                annotations: {{
                    criticalPeriod: annotation
                }}
            }};
            timelineChart.update();
        }}
        </script>
        '''


## 4. 預防性分析模塊
class RiskAssessmentEngine:
    """風險評估引擎"""
    
    def __init__(self):
        self.risk_thresholds = {
            'thread_count': {'low': 50, 'medium': 100, 'high': 150, 'critical': 200},
            'cpu_usage': {'low': 50, 'medium': 70, 'high': 85, 'critical': 95},
            'memory_available': {'critical': 50, 'high': 100, 'medium': 200, 'low': 500},  # MB
            'blocked_threads': {'low': 2, 'medium': 5, 'high': 10, 'critical': 20},
            'gc_frequency': {'low': 5, 'medium': 10, 'high': 20, 'critical': 50}  # per minute
        }
        
        self.risk_weights = {
            'thread_risk': 0.2,
            'memory_risk': 0.3,
            'io_risk': 0.2,
            'cpu_risk': 0.3
        }
    
    def assess_anr_risk(self, system_state: Dict) -> Dict:
        """評估 ANR 風險"""
        risk_factors = {
            'thread_risk': self._assess_thread_risk(system_state),
            'memory_risk': self._assess_memory_risk(system_state),
            'io_risk': self._assess_io_risk(system_state),
            'cpu_risk': self._assess_cpu_risk(system_state),
            'pattern_risk': self._assess_pattern_risk(system_state)
        }
        
        # 計算綜合風險分數
        overall_risk = 0
        for factor, assessment in risk_factors.items():
            if factor in self.risk_weights:
                overall_risk += assessment['score'] * self.risk_weights[factor]
        
        risk_level = self._get_risk_level(overall_risk)
        
        return {
            'overall_risk': overall_risk,
            'risk_level': risk_level,
            'factors': risk_factors,
            'recommendations': self._get_preventive_actions(risk_factors, risk_level),
            'predicted_anr_probability': self._calculate_anr_probability(overall_risk)
        }
    
    def _assess_thread_risk(self, system_state: Dict) -> Dict:
        """評估線程風險"""
        thread_count = system_state.get('thread_count', 0)
        blocked_count = system_state.get('blocked_threads', 0)
        
        # 計算風險分數
        count_score = self._calculate_threshold_score(
            thread_count, self.risk_thresholds['thread_count']
        )
        blocked_score = self._calculate_threshold_score(
            blocked_count, self.risk_thresholds['blocked_threads']
        )
        
        score = (count_score + blocked_score * 2) / 3  # 阻塞線程權重更高
        
        return {
            'score': score,
            'thread_count': thread_count,
            'blocked_count': blocked_count,
            'risk_level': self._get_risk_level(score),
            'details': self._get_thread_risk_details(thread_count, blocked_count)
        }
    
    def _assess_memory_risk(self, system_state: Dict) -> Dict:
        """評估記憶體風險"""
        available_mb = system_state.get('memory_available_mb', float('inf'))
        gc_frequency = system_state.get('gc_frequency', 0)
        
        # 計算風險分數
        memory_score = self._calculate_threshold_score(
            available_mb, self.risk_thresholds['memory_available'], inverse=True
        )
        gc_score = self._calculate_threshold_score(
            gc_frequency, self.risk_thresholds['gc_frequency']
        )
        
        score = (memory_score * 2 + gc_score) / 3  # 可用記憶體權重更高
        
        return {
            'score': score,
            'available_mb': available_mb,
            'gc_frequency': gc_frequency,
            'risk_level': self._get_risk_level(score),
            'details': self._get_memory_risk_details(available_mb, gc_frequency)
        }
    
    def _assess_io_risk(self, system_state: Dict) -> Dict:
        """評估 I/O 風險"""
        main_thread_io = system_state.get('main_thread_io_count', 0)
        binder_calls = system_state.get('binder_call_count', 0)
        file_operations = system_state.get('file_operation_count', 0)
        
        # 基於 I/O 操作計算風險
        score = 0
        if main_thread_io > 0:
            score += 0.5  # 主線程 I/O 直接加分
        
        score += min(binder_calls / 50, 0.3)  # Binder 調用
        score += min(file_operations / 100, 0.2)  # 文件操作
        
        return {
            'score': min(score, 1.0),
            'main_thread_io': main_thread_io,
            'binder_calls': binder_calls,
            'file_operations': file_operations,
            'risk_level': self._get_risk_level(score),
            'details': self._get_io_risk_details(main_thread_io, binder_calls, file_operations)
        }
    
    def _assess_cpu_risk(self, system_state: Dict) -> Dict:
        """評估 CPU 風險"""
        cpu_usage = system_state.get('cpu_usage', 0)
        load_average = system_state.get('load_average', 0)
        
        # 計算風險分數
        cpu_score = self._calculate_threshold_score(
            cpu_usage, self.risk_thresholds['cpu_usage']
        )
        
        # Load average 影響
        load_factor = min(load_average / 4.0, 1.0)  # 4 核心為基準
        
        score = (cpu_score * 0.7 + load_factor * 0.3)
        
        return {
            'score': score,
            'cpu_usage': cpu_usage,
            'load_average': load_average,
            'risk_level': self._get_risk_level(score),
            'details': self._get_cpu_risk_details(cpu_usage, load_average)
        }
    
    def _assess_pattern_risk(self, system_state: Dict) -> Dict:
        """基於歷史模式評估風險"""
        historical_anrs = system_state.get('historical_anr_count', 0)
        recent_anrs = system_state.get('recent_anr_count', 0)  # 最近一小時
        
        # 基於歷史數據的風險評估
        if recent_anrs > 3:
            score = 0.9
            pattern = '頻繁 ANR 模式'
        elif recent_anrs > 1:
            score = 0.7
            pattern = '間歇 ANR 模式'
        elif historical_anrs > 10:
            score = 0.5
            pattern = '歷史 ANR 傾向'
        else:
            score = 0.2
            pattern = '低 ANR 風險'
        
        return {
            'score': score,
            'pattern': pattern,
            'historical_count': historical_anrs,
            'recent_count': recent_anrs
        }
    
    def _calculate_threshold_score(self, value: float, thresholds: Dict, inverse: bool = False) -> float:
        """根據閾值計算分數"""
        if inverse:
            # 反向計算（值越小風險越高）
            if value <= thresholds['critical']:
                return 1.0
            elif value <= thresholds['high']:
                return 0.75
            elif value <= thresholds['medium']:
                return 0.5
            elif value <= thresholds['low']:
                return 0.25
            else:
                return 0.0
        else:
            # 正向計算（值越大風險越高）
            if value >= thresholds['critical']:
                return 1.0
            elif value >= thresholds['high']:
                return 0.75
            elif value >= thresholds['medium']:
                return 0.5
            elif value >= thresholds['low']:
                return 0.25
            else:
                return 0.0
    
    def _get_risk_level(self, score: float) -> str:
        """獲取風險等級"""
        if score >= 0.8:
            return 'critical'
        elif score >= 0.6:
            return 'high'
        elif score >= 0.4:
            return 'medium'
        elif score >= 0.2:
            return 'low'
        else:
            return 'minimal'
    
    def _calculate_anr_probability(self, risk_score: float) -> float:
        """計算 ANR 發生概率"""
        # 使用 sigmoid 函數將風險分數映射到概率
        import math
        return 1 / (1 + math.exp(-10 * (risk_score - 0.5)))
    
    def _get_preventive_actions(self, risk_factors: Dict, risk_level: str) -> List[Dict]:
        """獲取預防措施"""
        actions = []
        
        # 基於風險等級的通用建議
        if risk_level in ['critical', 'high']:
            actions.append({
                'priority': 'immediate',
                'action': '立即進行性能優化',
                'description': '系統處於高風險狀態，需要立即採取行動'
            })
        
        # 基於具體風險因素的建議
        for factor, assessment in risk_factors.items():
            if assessment.get('score', 0) > 0.6:
                if factor == 'thread_risk':
                    actions.append({
                        'priority': 'high',
                        'action': '優化線程管理',
                        'description': f'線程數量 ({assessment["thread_count"]}) 或阻塞線程 ({assessment["blocked_count"]}) 過多'
                    })
                elif factor == 'memory_risk':
                    actions.append({
                        'priority': 'high',
                        'action': '優化記憶體使用',
                        'description': f'可用記憶體不足 ({assessment["available_mb"]}MB) 或 GC 頻繁'
                    })
                elif factor == 'cpu_risk':
                    actions.append({
                        'priority': 'medium',
                        'action': '降低 CPU 負載',
                        'description': f'CPU 使用率過高 ({assessment["cpu_usage"]}%)'
                    })
        
        return actions
    
    def _get_thread_risk_details(self, thread_count: int, blocked_count: int) -> str:
        """獲取線程風險詳情"""
        details = []
        if thread_count > 150:
            details.append(f'線程數量過多: {thread_count}')
        if blocked_count > 10:
            details.append(f'大量阻塞線程: {blocked_count}')
        return ' | '.join(details) if details else '線程狀態正常'
    
    def _get_memory_risk_details(self, available_mb: float, gc_frequency: int) -> str:
        """獲取記憶體風險詳情"""
        details = []
        if available_mb < 100:
            details.append(f'記憶體嚴重不足: {available_mb:.1f}MB')
        if gc_frequency > 20:
            details.append(f'GC 過於頻繁: {gc_frequency}次/分鐘')
        return ' | '.join(details) if details else '記憶體狀態正常'
    
    def _get_io_risk_details(self, main_thread_io: int, binder_calls: int, file_ops: int) -> str:
        """獲取 I/O 風險詳情"""
        details = []
        if main_thread_io > 0:
            details.append(f'主線程 I/O: {main_thread_io}次')
        if binder_calls > 50:
            details.append(f'Binder 調用頻繁: {binder_calls}次')
        if file_ops > 100:
            details.append(f'文件操作頻繁: {file_ops}次')
        return ' | '.join(details) if details else 'I/O 狀態正常'
    
    def _get_cpu_risk_details(self, cpu_usage: float, load_average: float) -> str:
        """獲取 CPU 風險詳情"""
        details = []
        if cpu_usage > 85:
            details.append(f'CPU 使用率高: {cpu_usage}%')
        if load_average > 4:
            details.append(f'系統負載高: {load_average}')
        return ' | '.join(details) if details else 'CPU 狀態正常'


class TrendAnalyzer:
    """趨勢分析器"""
    
    def __init__(self):
        self.trend_window = 24 * 60 * 60  # 24小時窗口
        self.pattern_threshold = 0.7  # 模式識別閾值
    
    def analyze_trends(self, historical_data: List[ANRInfo]) -> Dict:
        """分析歷史趨勢"""
        if not historical_data:
            return {'error': '無歷史數據'}
        
        trends = {
            'anr_frequency': self._calculate_frequency_trend(historical_data),
            'common_patterns': self._identify_recurring_patterns(historical_data),
            'degradation_indicators': self._find_degradation_signs(historical_data),
            'predictions': self._predict_future_issues(historical_data),
            'recommendations': []
        }
        
        # 生成趨勢建議
        trends['recommendations'] = self._generate_trend_recommendations(trends)
        
        return trends
    
    def _calculate_frequency_trend(self, historical_data: List[ANRInfo]) -> Dict:
        """計算 ANR 頻率趨勢"""
        # 按時間分組（小時）
        hourly_counts = defaultdict(int)
        daily_counts = defaultdict(int)
        
        for anr in historical_data:
            if anr.timestamp:
                # 簡化處理，實際應解析時間戳
                hour_key = anr.timestamp[:13]  # YYYY-MM-DD HH
                day_key = anr.timestamp[:10]   # YYYY-MM-DD
                hourly_counts[hour_key] += 1
                daily_counts[day_key] += 1
        
        # 計算趨勢
        if len(daily_counts) > 1:
            days = sorted(daily_counts.keys())
            counts = [daily_counts[day] for day in days]
            
            # 簡單的趨勢判斷
            if len(counts) >= 3:
                recent_avg = sum(counts[-3:]) / 3
                earlier_avg = sum(counts[:-3]) / max(1, len(counts) - 3)
                
                if recent_avg > earlier_avg * 1.5:
                    trend = 'increasing'
                    trend_desc = f'上升趨勢 ({earlier_avg:.1f} → {recent_avg:.1f} ANR/天)'
                elif recent_avg < earlier_avg * 0.7:
                    trend = 'decreasing'
                    trend_desc = f'下降趨勢 ({earlier_avg:.1f} → {recent_avg:.1f} ANR/天)'
                else:
                    trend = 'stable'
                    trend_desc = f'穩定 (~{recent_avg:.1f} ANR/天)'
            else:
                trend = 'insufficient_data'
                trend_desc = '數據不足'
        else:
            trend = 'no_trend'
            trend_desc = '無趨勢數據'
        
        return {
            'trend': trend,
            'description': trend_desc,
            'hourly_distribution': dict(hourly_counts),
            'daily_distribution': dict(daily_counts),
            'peak_hours': self._find_peak_hours(hourly_counts),
            'peak_days': self._find_peak_days(daily_counts)
        }
    
    def _identify_recurring_patterns(self, historical_data: List[ANRInfo]) -> List[Dict]:
        """識別重複出現的模式"""
        patterns = []
        
        # 1. 堆疊模式
        stack_patterns = defaultdict(list)
        for anr in historical_data:
            if anr.main_thread and anr.main_thread.backtrace:
                # 生成堆疊簽名（前5幀）
                signature = self._generate_stack_signature(anr.main_thread.backtrace[:5])
                stack_patterns[signature].append(anr)
        
        # 找出重複模式
        for signature, anrs in stack_patterns.items():
            if len(anrs) >= 3:  # 至少出現3次
                patterns.append({
                    'type': 'stack_pattern',
                    'signature': signature,
                    'count': len(anrs),
                    'description': self._describe_stack_pattern(anrs[0]),
                    'examples': [anr.timestamp for anr in anrs[:5]]
                })
        
        # 2. ANR 類型模式
        type_counts = Counter(anr.anr_type for anr in historical_data)
        for anr_type, count in type_counts.most_common():
            if count >= 5:
                patterns.append({
                    'type': 'anr_type_pattern',
                    'anr_type': anr_type.value,
                    'count': count,
                    'percentage': count / len(historical_data) * 100
                })
        
        # 3. 時間模式
        time_patterns = self._find_time_patterns(historical_data)
        patterns.extend(time_patterns)
        
        return sorted(patterns, key=lambda x: x.get('count', 0), reverse=True)
    
    def _find_degradation_signs(self, historical_data: List[ANRInfo]) -> List[Dict]:
        """查找性能退化跡象"""
        signs = []
        
        # 按時間排序
        sorted_data = sorted(historical_data, key=lambda x: x.timestamp or '')
        
        if len(sorted_data) < 10:
            return []
        
        # 1. CPU 使用率趨勢
        cpu_trend = []
        for anr in sorted_data:
            if anr.cpu_usage and 'total' in anr.cpu_usage:
                cpu_trend.append(anr.cpu_usage['total'])
        
        if len(cpu_trend) >= 5:
            recent_cpu = sum(cpu_trend[-5:]) / 5
            earlier_cpu = sum(cpu_trend[:-5]) / max(1, len(cpu_trend) - 5)
            
            if recent_cpu > earlier_cpu * 1.2:
                signs.append({
                    'type': 'cpu_degradation',
                    'severity': 'medium',
                    'description': f'CPU 使用率上升: {earlier_cpu:.1f}% → {recent_cpu:.1f}%',
                    'impact': '系統響應變慢'
                })
        
        # 2. 線程數趨勢
        thread_counts = [len(anr.all_threads) for anr in sorted_data[-10:]]
        if thread_counts:
            avg_threads = sum(thread_counts) / len(thread_counts)
            if avg_threads > 150:
                signs.append({
                    'type': 'thread_leak',
                    'severity': 'high',
                    'description': f'平均線程數過高: {avg_threads:.0f}',
                    'impact': '可能存在線程洩漏'
                })
        
        # 3. 阻塞線程增加
        blocked_trend = []
        for anr in sorted_data[-10:]:
            blocked_count = sum(1 for t in anr.all_threads if t.state == ThreadState.BLOCKED)
            blocked_trend.append(blocked_count)
        
        if blocked_trend and max(blocked_trend) > 10:
            signs.append({
                'type': 'increasing_contention',
                'severity': 'high',
                'description': f'阻塞線程增加: 最高 {max(blocked_trend)} 個',
                'impact': '鎖競爭加劇'
            })
        
        return signs
    
    def _predict_future_issues(self, historical_data: List[ANRInfo]) -> List[Dict]:
        """預測未來可能的問題"""
        predictions = []
        
        # 基於趨勢的簡單預測
        freq_trend = self._calculate_frequency_trend(historical_data)
        
        if freq_trend['trend'] == 'increasing':
            predictions.append({
                'issue': 'ANR 頻率持續上升',
                'probability': 0.8,
                'timeframe': '未來 24 小時',
                'recommendation': '立即進行性能優化'
            })
        
        # 基於模式的預測
        patterns = self._identify_recurring_patterns(historical_data)
        for pattern in patterns[:3]:  # 前3個最常見的模式
            if pattern['count'] >= 5:
                predictions.append({
                    'issue': f'{pattern["description"]} 將再次發生',
                    'probability': 0.7,
                    'timeframe': '基於歷史模式',
                    'recommendation': '針對此模式進行優化'
                })
        
        # 基於退化跡象的預測
        degradation = self._find_degradation_signs(historical_data)
        for sign in degradation:
            if sign['severity'] == 'high':
                predictions.append({
                    'issue': sign['description'],
                    'probability': 0.6,
                    'timeframe': '持續惡化中',
                    'recommendation': sign.get('impact', '需要關注')
                })
        
        return predictions
    
    def _generate_stack_signature(self, frames: List[str]) -> str:
        """生成堆疊簽名"""
        # 提取關鍵方法名
        key_methods = []
        for frame in frames:
            # 簡化提取方法名
            match = re.search(r'\.(\w+)\(', frame)
            if match:
                key_methods.append(match.group(1))
        
        # 生成簽名
        signature = '|'.join(key_methods[:3])
        return hashlib.md5(signature.encode()).hexdigest()[:16]
    
    def _describe_stack_pattern(self, anr: ANRInfo) -> str:
        """描述堆疊模式"""
        if anr.main_thread and anr.main_thread.backtrace:
            # 提取關鍵信息
            for frame in anr.main_thread.backtrace[:3]:
                if 'Binder' in frame:
                    return 'Binder IPC 相關 ANR'
                elif 'SQLite' in frame:
                    return '資料庫操作相關 ANR'
                elif 'File' in frame:
                    return '文件 I/O 相關 ANR'
                elif 'lock' in frame.lower():
                    return '鎖相關 ANR'
        
        return f'{anr.anr_type.value} 類型 ANR'
    
    def _find_time_patterns(self, historical_data: List[ANRInfo]) -> List[Dict]:
        """查找時間模式"""
        patterns = []
        
        # 按小時分組
        hourly_distribution = defaultdict(int)
        for anr in historical_data:
            if anr.timestamp:
                hour = int(anr.timestamp[11:13])
                hourly_distribution[hour] += 1
        
        # 找出高峰時段
        if hourly_distribution:
            avg_count = sum(hourly_distribution.values()) / 24
            peak_hours = [hour for hour, count in hourly_distribution.items() 
                         if count > avg_count * 2]
            
            if peak_hours:
                patterns.append({
                    'type': 'time_pattern',
                    'pattern': 'peak_hours',
                    'hours': peak_hours,
                    'description': f'高峰時段: {", ".join(f"{h}:00" for h in sorted(peak_hours))}'
                })
        
        return patterns
    
    def _find_peak_hours(self, hourly_counts: Dict) -> List[str]:
        """找出高峰小時"""
        if not hourly_counts:
            return []
        
        sorted_hours = sorted(hourly_counts.items(), key=lambda x: x[1], reverse=True)
        return [hour for hour, count in sorted_hours[:3]]
    
    def _find_peak_days(self, daily_counts: Dict) -> List[str]:
        """找出高峰日期"""
        if not daily_counts:
            return []
        
        sorted_days = sorted(daily_counts.items(), key=lambda x: x[1], reverse=True)
        return [day for day, count in sorted_days[:3]]
    
    def _generate_trend_recommendations(self, trends: Dict) -> List[str]:
        """生成趨勢相關建議"""
        recommendations = []
        
        # 基於頻率趨勢
        if trends['anr_frequency']['trend'] == 'increasing':
            recommendations.append('ANR 頻率上升，建議進行全面性能審查')
        
        # 基於常見模式
        if trends['common_patterns']:
            top_pattern = trends['common_patterns'][0]
            recommendations.append(
                f'最常見的 ANR 模式 ({top_pattern.get("description", "未知")}) '
                f'出現了 {top_pattern.get("count", 0)} 次，應優先解決'
            )
        
        # 基於退化跡象
        for sign in trends['degradation_indicators']:
            if sign['severity'] == 'high':
                recommendations.append(f'檢測到{sign["type"]}，需要立即處理')
        
        # 基於預測
        for prediction in trends['predictions']:
            if prediction['probability'] > 0.7:
                recommendations.append(
                    f'高概率預測: {prediction["issue"]} ({prediction["timeframe"]})'
                )
        
        return recommendations


## 5. 整合外部數據模塊
class SystemMetricsIntegrator:
    """系統指標整合器"""
    
    def __init__(self):
        # 延遲初始化 metric_parsers，避免引用還未定義的方法
        self.metric_parsers = {}
        self._init_parsers()
    
    def _init_parsers(self):
        """初始化解析器"""
        self.metric_parsers = {
            'dumpsys': self._parse_dumpsys,
            'systrace': self._parse_systrace,
            'battery': self._parse_battery_stats,
            'network': self._parse_network_stats
        }
    
    # 添加缺失的方法
    def _parse_dumpsys(self, content: str) -> Dict:
        """解析 dumpsys 內容"""
        dumpsys_data = {
            'meminfo': {},
            'cpuinfo': {},
            'activity': {},
            'window': {},
            'power': {}
        }
        
        try:
            # 解析各個部分
            dumpsys_data['meminfo'] = self._parse_meminfo(content)
            dumpsys_data['cpuinfo'] = self._parse_cpuinfo(content)
            dumpsys_data['activity'] = self._parse_activity_manager(content)
            dumpsys_data['window'] = self._parse_window_manager(content)
            dumpsys_data['power'] = self._parse_power_manager(content)
        except Exception as e:
            print(f"Error parsing dumpsys: {e}")
        
        return dumpsys_data
    
    def _parse_systrace(self, content: str) -> Dict:
        """解析 systrace 內容"""
        systrace_data = {
            'cpu_frequency': {},
            'scheduler_latency': {},
            'binder_transactions': [],
            'frame_drops': 0
        }
        
        try:
            # CPU 頻率信息
            cpu_freq_matches = re.findall(r'cpu_frequency:\s*(\d+)\s+cpu_id=(\d+)', content)
            for freq, cpu_id in cpu_freq_matches:
                if cpu_id not in systrace_data['cpu_frequency']:
                    systrace_data['cpu_frequency'][cpu_id] = []
                systrace_data['cpu_frequency'][cpu_id].append(int(freq))
            
            # Binder 事務
            binder_matches = re.findall(r'binder_transaction:.*?from\s+(\d+):(\d+)\s+to\s+(\d+):(\d+)', content)
            for match in binder_matches:
                systrace_data['binder_transactions'].append({
                    'from_pid': match[0],
                    'from_tid': match[1],
                    'to_pid': match[2],
                    'to_tid': match[3]
                })
            
            # 幀丟失
            frame_drop_match = re.search(r'Dropped\s+(\d+)\s+frames', content)
            if frame_drop_match:
                systrace_data['frame_drops'] = int(frame_drop_match.group(1))
                
        except Exception as e:
            print(f"Error parsing systrace: {e}")
        
        return systrace_data
    
    def _parse_battery_stats(self, content: str) -> Dict:
        """解析電池統計"""
        battery_data = {
            'level': 0,
            'temperature': 0,
            'voltage': 0,
            'charging': False,
            'screen_on_time': 0,
            'wake_locks': []
        }
        
        try:
            # 電池電量
            level_match = re.search(r'Battery\s+level:\s*(\d+)', content)
            if level_match:
                battery_data['level'] = int(level_match.group(1))
            
            # 溫度
            temp_match = re.search(r'temperature:\s*(\d+)', content)
            if temp_match:
                battery_data['temperature'] = int(temp_match.group(1)) / 10  # 通常是十分之一度
            
            # 電壓
            voltage_match = re.search(r'voltage:\s*(\d+)', content)
            if voltage_match:
                battery_data['voltage'] = int(voltage_match.group(1))
            
            # 充電狀態
            if 'status=charging' in content.lower() or 'plugged=' in content:
                battery_data['charging'] = True
            
            # Wake locks
            wake_lock_matches = re.findall(r'Wake lock\s+([^:]+):\s+(\d+)ms', content)
            for name, duration in wake_lock_matches:
                battery_data['wake_locks'].append({
                    'name': name.strip(),
                    'duration_ms': int(duration)
                })
                
        except Exception as e:
            print(f"Error parsing battery stats: {e}")
        
        return battery_data
    
    def _parse_network_stats(self, content: str) -> Dict:
        """解析網路統計"""
        network_data = {
            'type': 'unknown',
            'connected': False,
            'signal_strength': 0,
            'mobile_data': {},
            'wifi_data': {}
        }
        
        try:
            # 網路類型
            if 'WIFI' in content or 'wifi' in content:
                network_data['type'] = 'wifi'
            elif 'MOBILE' in content or 'mobile' in content:
                network_data['type'] = 'mobile'
            
            # 連接狀態
            if 'CONNECTED' in content or 'connected=true' in content:
                network_data['connected'] = True
            
            # 信號強度
            signal_match = re.search(r'(?:rssi|signal)[=:\s]+(-?\d+)', content)
            if signal_match:
                network_data['signal_strength'] = int(signal_match.group(1))
            
            # 移動數據使用
            mobile_rx_match = re.search(r'Mobile\s+RX\s+bytes:\s*(\d+)', content)
            mobile_tx_match = re.search(r'Mobile\s+TX\s+bytes:\s*(\d+)', content)
            if mobile_rx_match:
                network_data['mobile_data']['rx_bytes'] = int(mobile_rx_match.group(1))
            if mobile_tx_match:
                network_data['mobile_data']['tx_bytes'] = int(mobile_tx_match.group(1))
            
            # WiFi 數據使用
            wifi_rx_match = re.search(r'(?:Wifi|WIFI)\s+RX\s+bytes:\s*(\d+)', content)
            wifi_tx_match = re.search(r'(?:Wifi|WIFI)\s+TX\s+bytes:\s*(\d+)', content)
            if wifi_rx_match:
                network_data['wifi_data']['rx_bytes'] = int(wifi_rx_match.group(1))
            if wifi_tx_match:
                network_data['wifi_data']['tx_bytes'] = int(wifi_tx_match.group(1))
                
        except Exception as e:
            print(f"Error parsing network stats: {e}")
        
        return network_data
    
    def integrate_metrics(self, anr_timestamp: str, log_directory: str) -> Dict:
        """整合 ANR 發生時的系統指標"""
        metrics = {
            'timestamp': anr_timestamp,
            'dumpsys': {},
            'systrace': {},
            'battery': {},
            'network': {},
            'correlation': {}
        }
        
        # 嘗試載入各種系統日誌
        dumpsys_file = self._find_closest_file(log_directory, 'dumpsys', anr_timestamp)
        if dumpsys_file:
            metrics['dumpsys'] = self._parse_dumpsys_at_time(dumpsys_file, anr_timestamp)
        
        # 解析 systrace（如果存在）
        systrace_file = self._find_closest_file(log_directory, 'systrace', anr_timestamp)
        if systrace_file:
            metrics['systrace'] = self._correlate_systrace_data(systrace_file, anr_timestamp)
        
        # 電池統計
        battery_file = self._find_closest_file(log_directory, 'batterystats', anr_timestamp)
        if battery_file:
            metrics['battery'] = self._get_battery_stats(battery_file, anr_timestamp)
        
        # 網路狀態
        metrics['network'] = self._get_network_state(metrics['dumpsys'])
        
        # 分析相關性
        metrics['correlation'] = self._analyze_metric_correlation(metrics)
        
        return metrics
    
    def _find_closest_file(self, directory: str, file_type: str, timestamp: str) -> Optional[str]:
        """找到最接近時間戳的檔案"""
        import glob
        
        pattern = os.path.join(directory, f'*{file_type}*')
        files = glob.glob(pattern)
        
        if not files:
            return None
        
        # 簡化：返回最新的檔案
        return max(files, key=os.path.getmtime)
    
    def _parse_dumpsys_at_time(self, file_path: str, target_time: str) -> Dict:
        """解析特定時間的 dumpsys"""
        dumpsys_data = {
            'meminfo': {},
            'cpuinfo': {},
            'activity': {},
            'window': {},
            'power': {}
        }
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 解析各個部分
            dumpsys_data['meminfo'] = self._parse_meminfo(content)
            dumpsys_data['cpuinfo'] = self._parse_cpuinfo(content)
            dumpsys_data['activity'] = self._parse_activity_manager(content)
            dumpsys_data['window'] = self._parse_window_manager(content)
            dumpsys_data['power'] = self._parse_power_manager(content)
            
        except Exception as e:
            print(f"Error parsing dumpsys: {e}")
        
        return dumpsys_data
    
    def _parse_meminfo(self, content: str) -> Dict:
        """解析 meminfo"""
        meminfo = {}
        
        # 查找 meminfo 部分
        meminfo_match = re.search(r'MEMINFO.*?Total RAM:(.*?)Total PSS', content, re.DOTALL)
        if meminfo_match:
            meminfo_text = meminfo_match.group(1)
            
            # 提取關鍵數據
            patterns = {
                'total_ram': r'Total RAM:\s*([\d,]+)K',
                'free_ram': r'Free RAM:\s*([\d,]+)K',
                'used_ram': r'Used RAM:\s*([\d,]+)K',
                'lost_ram': r'Lost RAM:\s*([\d,]+)K'
            }
            
            for key, pattern in patterns.items():
                match = re.search(pattern, meminfo_text)
                if match:
                    meminfo[key] = int(match.group(1).replace(',', ''))
        
        return meminfo
    
    def _parse_cpuinfo(self, content: str) -> Dict:
        """解析 cpuinfo"""
        cpuinfo = {}
        
        # 查找 CPU 使用率
        cpu_match = re.search(r'CPU usage from.*?(\d+)% user \+ (\d+)% kernel', content)
        if cpu_match:
            cpuinfo['user_percent'] = int(cpu_match.group(1))
            cpuinfo['kernel_percent'] = int(cpu_match.group(2))
            cpuinfo['total_percent'] = cpuinfo['user_percent'] + cpuinfo['kernel_percent']
        
        # 查找各進程 CPU 使用
        process_cpu = []
        process_pattern = r'(\d+)%\s+(\d+)/([^:]+):\s+(\d+)% user \+ (\d+)% kernel'
        for match in re.finditer(process_pattern, content):
            process_cpu.append({
                'total': int(match.group(1)),
                'pid': match.group(2),
                'name': match.group(3),
                'user': int(match.group(4)),
                'kernel': int(match.group(5))
            })
        
        cpuinfo['top_processes'] = sorted(process_cpu, key=lambda x: x['total'], reverse=True)[:10]
        
        return cpuinfo
    
    def _parse_activity_manager(self, content: str) -> Dict:
        """解析 Activity Manager 狀態"""
        activity_info = {
            'focused_activity': None,
            'focused_package': None,
            'running_services': [],
            'recent_tasks': []
        }
        
        # 查找當前焦點
        focus_match = re.search(r'mFocusedActivity: .* ([^/]+)/([^ ]+)', content)
        if focus_match:
            activity_info['focused_package'] = focus_match.group(1)
            activity_info['focused_activity'] = focus_match.group(2)
        
        # 查找運行的服務
        services_section = re.search(r'ACTIVITY MANAGER SERVICES.*?Active services:(.*?)' + 
                                   r'(?:ACTIVITY MANAGER|$)', content, re.DOTALL)
        if services_section:
            service_pattern = r'\* ServiceRecord\{[^}]+\s+([^}]+)\}'
            services = re.findall(service_pattern, services_section.group(1))
            activity_info['running_services'] = services[:20]  # 限制數量
        
        return activity_info
    
    def _parse_window_manager(self, content: str) -> Dict:
        """解析 Window Manager 狀態"""
        window_info = {
            'focused_window': None,
            'orientation': None,
            'frozen_windows': []
        }
        
        # 當前焦點窗口
        window_match = re.search(r'mCurrentFocus=Window\{[^}]+ ([^}]+)\}', content)
        if window_match:
            window_info['focused_window'] = window_match.group(1)
        
        # 螢幕方向
        orientation_match = re.search(r'mRotation=(\d+)', content)
        if orientation_match:
            rotation = int(orientation_match.group(1))
            window_info['orientation'] = {0: 'portrait', 1: 'landscape', 
                                        2: 'reverse_portrait', 3: 'reverse_landscape'}.get(rotation)
        
        return window_info
    
    def _parse_power_manager(self, content: str) -> Dict:
        """解析 Power Manager 狀態"""
        power_info = {
            'screen_state': 'unknown',
            'battery_level': None,
            'power_save_mode': False
        }
        
        # 螢幕狀態
        if 'mWakefulness=Awake' in content:
            power_info['screen_state'] = 'on'
        elif 'mWakefulness=Asleep' in content:
            power_info['screen_state'] = 'off'
        
        # 省電模式
        if 'mBatterySaverEnabled=true' in content:
            power_info['power_save_mode'] = True
        
        return power_info
    
    def _correlate_systrace_data(self, file_path: str, target_time: str) -> Dict:
        """關聯 systrace 數據"""
        # 簡化實現
        return {
            'cpu_frequency': {},
            'scheduler_latency': {},
            'binder_transactions': {},
            'frame_drops': 0
        }
    
    def _get_battery_stats(self, file_path: str, target_time: str) -> Dict:
        """獲取電池統計"""
        return {
            'level': 50,
            'temperature': 35,
            'voltage': 3800,
            'charging': False
        }
    
    def _get_network_state(self, dumpsys_data: Dict) -> Dict:
        """獲取網路狀態"""
        return {
            'type': 'wifi',
            'connected': True,
            'signal_strength': -65
        }
    
    def _analyze_metric_correlation(self, metrics: Dict) -> Dict:
        """分析指標相關性"""
        correlations = []
        
        # 檢查記憶體壓力與 GC
        if metrics.get('dumpsys', {}).get('meminfo', {}).get('free_ram', float('inf')) < 100000:
            correlations.append({
                'type': 'memory_pressure',
                'description': '低記憶體可能導致頻繁 GC',
                'severity': 'high'
            })
        
        # 檢查 CPU 與電池
        if metrics.get('dumpsys', {}).get('cpuinfo', {}).get('total_percent', 0) > 80:
            if metrics.get('battery', {}).get('temperature', 0) > 40:
                correlations.append({
                    'type': 'thermal_throttling',
                    'description': '高 CPU 使用率導致設備發熱',
                    'severity': 'medium'
                })
        
        return {'findings': correlations}


class SourceCodeAnalyzer:
    """源代碼分析器"""
    
    def __init__(self, source_root: str = None):
        self.source_root = source_root
        self.complexity_threshold = 10
        self.issue_patterns = self._init_issue_patterns()
    
    def _init_issue_patterns(self) -> Dict:
        """初始化問題模式"""
        return {
            'synchronization': [
                r'synchronized\s*\([^)]*\)\s*\{[^}]*synchronized',  # 嵌套同步
                r'wait\(\)(?!.*?catch.*?InterruptedException)',    # 未捕獲中斷
                r'Thread\.sleep\(\d+\)',                           # 主線程休眠
            ],
            'io_operations': [
                r'new\s+File\s*\([^)]+\)\.(?:read|write)',        # 直接文件操作
                r'SharedPreferences.*\.commit\(\)',                 # 同步提交
                r'(?:FileInputStream|FileOutputStream).*?close',   # 資源管理
            ],
            'memory_issues': [
                r'static\s+(?:final\s+)?(?:HashMap|ArrayList)',    # 靜態集合
                r'Bitmap\.createBitmap',                           # Bitmap 創建
                r'new\s+byte\[\d{7,}\]',                          # 大數組分配
            ]
        }
    
    def analyze_related_code(self, stack_trace: List[str]) -> Dict:
        """分析相關源代碼"""
        analysis = {
            'complexity': {},
            'recent_changes': {},
            'known_issues': {},
            'optimization_suggestions': {}
        }
        
        # 提取源文件
        source_files = self._extract_source_files(stack_trace)
        
        for file_path in source_files:
            if self._is_app_code(file_path):
                # 分析代碼複雜度
                analysis['complexity'][file_path] = self._analyze_complexity(file_path)
                
                # 查找最近變更
                analysis['recent_changes'][file_path] = self._get_git_history(file_path)
                
                # 查找已知問題
                analysis['known_issues'][file_path] = self._search_issue_tracker(file_path)
                
                # 生成優化建議
                analysis['optimization_suggestions'][file_path] = self._generate_optimization_suggestions(file_path)
        
        return analysis
    
    def _extract_source_files(self, stack_trace: List[str]) -> List[str]:
        """從堆疊追蹤提取源文件"""
        source_files = []
        
        for frame in stack_trace:
            # 匹配 Java/Kotlin 文件
            match = re.search(r'\(([^:]+\.(java|kt)):(\d+)\)', frame)
            if match:
                source_files.append(match.group(1))
        
        return list(set(source_files))
    
    def _is_app_code(self, file_path: str) -> bool:
        """判斷是否為應用代碼"""
        # 排除系統和第三方庫
        excluded_packages = ['android.', 'java.', 'kotlin.', 'androidx.', 'com.google.']
        return not any(file_path.startswith(pkg) for pkg in excluded_packages)
    
    def _analyze_complexity(self, file_path: str) -> Dict:
        """分析代碼複雜度"""
        complexity = {
            'cyclomatic': 0,
            'lines_of_code': 0,
            'method_count': 0,
            'max_method_length': 0,
            'issues': []
        }
        
        if self.source_root and os.path.exists(os.path.join(self.source_root, file_path)):
            try:
                with open(os.path.join(self.source_root, file_path), 'r') as f:
                    content = f.read()
                
                # 簡單的複雜度計算
                complexity['lines_of_code'] = len(content.splitlines())
                complexity['method_count'] = len(re.findall(r'(?:public|private|protected).*?\(', content))
                
                # 檢查問題模式
                for category, patterns in self.issue_patterns.items():
                    for pattern in patterns:
                        if re.search(pattern, content):
                            complexity['issues'].append({
                                'category': category,
                                'pattern': pattern,
                                'severity': 'medium'
                            })
                
            except Exception as e:
                print(f"Error analyzing {file_path}: {e}")
        
        return complexity
    
    def _get_git_history(self, file_path: str) -> List[Dict]:
        """獲取 Git 歷史"""
        # 簡化實現 - 實際應調用 git 命令
        return [{
            'commit': 'abc123',
            'date': '2024-01-01',
            'author': 'developer',
            'message': 'Fix ANR issue'
        }]
    
    def _search_issue_tracker(self, file_path: str) -> List[Dict]:
        """搜尋問題追蹤器"""
        # 簡化實現 - 實際應調用 JIRA/GitHub API
        return [{
            'issue_id': 'ANR-123',
            'title': 'ANR in MainActivity',
            'status': 'open',
            'priority': 'high'
        }]
    
    def _generate_optimization_suggestions(self, file_path: str) -> List[Dict]:
        """生成優化建議"""
        suggestions = []
        
        # 基於文件名和路徑
        if 'Activity' in file_path:
            suggestions.append({
                'type': 'lifecycle',
                'suggestion': '確保在 onCreate/onResume 中避免耗時操作',
                'priority': 'high'
            })
        elif 'Service' in file_path:
            suggestions.append({
                'type': 'threading',
                'suggestion': '使用 IntentService 或 JobIntentService 處理背景任務',
                'priority': 'medium'
            })
        
        return suggestions


## 6. 自動化建議模塊
class CodeFixGenerator:
    """代碼修復建議生成器"""
    
    def __init__(self):
        self.fix_templates = self._init_fix_templates()
    
    def _init_fix_templates(self) -> Dict:
        """初始化修復模板"""
        return {
            'main_thread_io': {
                'kotlin_coroutine': '''
// 使用 Kotlin Coroutines 進行異步 I/O
lifecycleScope.launch(Dispatchers.IO) {
    val result = performIOOperation()
    withContext(Dispatchers.Main) {
        updateUI(result)
    }
}''',
                'executor_service': '''
// 使用 ExecutorService
private val executor = Executors.newSingleThreadExecutor()

executor.execute {
    val result = performIOOperation()
    runOnUiThread {
        updateUI(result)
    }
}''',
                'async_task': '''
// 使用 AsyncTask (已廢棄，建議使用上述方法)
private class IOTask : AsyncTask<Void, Void, Result>() {
    override fun doInBackground(vararg params: Void?): Result {
        return performIOOperation()
    }
    
    override fun onPostExecute(result: Result) {
        updateUI(result)
    }
}'''
            },
            'shared_preferences': {
                'apply_instead_commit': '''
// 使用 apply() 而非 commit()
sharedPreferences.edit()
    .putString("key", value)
    .apply()  // 異步寫入，不會阻塞主線程
    
// 如果需要確認寫入完成，使用:
sharedPreferences.edit()
    .putString("key", value)
    .commit()  // 同步寫入，會阻塞，應在背景線程使用''',
                'datastore': '''
// 考慮遷移到 DataStore
private val dataStore: DataStore<Preferences> = context.createDataStore("settings")

// 寫入數據
lifecycleScope.launch {
    dataStore.edit { preferences ->
        preferences[KEY] = value
    }
}

// 讀取數據
val value = dataStore.data
    .map { preferences -> preferences[KEY] }
    .first()'''
            },
            'database_operations': {
                'room_async': '''
// Room 異步查詢
@Dao
interface UserDao {
    @Query("SELECT * FROM users")
    suspend fun getAllUsers(): List<User>  // 協程支援
    
    @Query("SELECT * FROM users")
    fun getAllUsersLiveData(): LiveData<List<User>>  // LiveData
    
    @Query("SELECT * FROM users")
    fun getAllUsersFlow(): Flow<List<User>>  // Flow
}''',
                'cursor_background': '''
// 在背景線程查詢資料庫
viewModelScope.launch(Dispatchers.IO) {
    val cursor = database.query(...)
    try {
        val results = parseCursor(cursor)
        withContext(Dispatchers.Main) {
            updateUI(results)
        }
    } finally {
        cursor.close()
    }
}'''
            },
            'synchronization': {
                'concurrent_collections': '''
// 使用併發集合替代同步
// 替換 synchronized HashMap
private val map = ConcurrentHashMap<String, String>()

// 替換 synchronized ArrayList
private val list = CopyOnWriteArrayList<String>()

// 使用原子變量
private val counter = AtomicInteger(0)
counter.incrementAndGet()  // 線程安全''',
                'lock_ordering': '''
// 使用一致的鎖順序避免死鎖
class ResourceManager {
    private val lock1 = Any()
    private val lock2 = Any()
    
    // 始終以相同順序獲取鎖
    fun method1() {
        synchronized(lock1) {
            synchronized(lock2) {
                // 操作
            }
        }
    }
    
    fun method2() {
        synchronized(lock1) {  // 相同順序
            synchronized(lock2) {
                // 操作
            }
        }
    }
}''',
                'lock_free': '''
// 使用無鎖數據結構
class LockFreeQueue<T> {
    private val queue = ConcurrentLinkedQueue<T>()
    
    fun enqueue(item: T) {
        queue.offer(item)  // 無鎖操作
    }
    
    fun dequeue(): T? {
        return queue.poll()  // 無鎖操作
    }
}'''
            },
            'binder_optimization': {
                'oneway': '''
// 使用 oneway 異步 Binder 調用
interface IMyService {
    void normalCall();  // 同步調用，會等待返回
    
    oneway void asyncCall();  // 異步調用，立即返回
}''',
                'batch_operations': '''
// 批量處理 Binder 調用
class BatchedOperations {
    private val pendingOps = mutableListOf<Operation>()
    
    fun addOperation(op: Operation) {
        pendingOps.add(op)
        if (pendingOps.size >= BATCH_SIZE) {
            flushOperations()
        }
    }
    
    private fun flushOperations() {
        service.batchProcess(pendingOps)
        pendingOps.clear()
    }
}'''
            }
        }
    
    def generate_fix_suggestions(self, issue_type: str, context: Dict) -> List[Dict]:
        """生成具體的代碼修復建議"""
        suggestions = []
        
        if issue_type == 'main_thread_io':
            problematic_code = self._extract_problematic_code(context)
            
            for fix_name, fix_template in self.fix_templates['main_thread_io'].items():
                suggestions.append({
                    'title': f'使用 {fix_name.replace("_", " ").title()}',
                    'before': problematic_code,
                    'after': fix_template,
                    'explanation': self._get_fix_explanation(issue_type, fix_name),
                    'difficulty': self._assess_fix_difficulty(fix_name),
                    'impact': 'high'
                })
        
        elif issue_type == 'shared_preferences_commit':
            for fix_name, fix_template in self.fix_templates['shared_preferences'].items():
                suggestions.append({
                    'title': f'SharedPreferences 優化: {fix_name}',
                    'before': 'sharedPreferences.edit().putString("key", value).commit()',
                    'after': fix_template,
                    'explanation': self._get_fix_explanation('shared_preferences', fix_name),
                    'difficulty': 'easy' if fix_name == 'apply_instead_commit' else 'medium',
                    'impact': 'medium'
                })
        
        elif issue_type == 'synchronization_issue':
            for fix_name, fix_template in self.fix_templates['synchronization'].items():
                suggestions.append({
                    'title': f'同步優化: {fix_name.replace("_", " ").title()}',
                    'before': self._extract_problematic_code(context),
                    'after': fix_template,
                    'explanation': self._get_fix_explanation('synchronization', fix_name),
                    'difficulty': self._assess_fix_difficulty(fix_name),
                    'impact': 'high'
                })
        
        return suggestions
    
    def _extract_problematic_code(self, context: Dict) -> str:
        """提取有問題的代碼"""
        # 從堆疊或上下文中提取
        if 'stack_frame' in context:
            return context['stack_frame']
        elif 'code_snippet' in context:
            return context['code_snippet']
        else:
            return "// 原始代碼"
    
    def _get_fix_explanation(self, category: str, fix_type: str) -> str:
        """獲取修復說明"""
        explanations = {
            ('main_thread_io', 'kotlin_coroutine'): 
                'Kotlin Coroutines 提供結構化併發，自動處理線程切換和生命週期',
            ('main_thread_io', 'executor_service'): 
                'ExecutorService 提供靈活的線程池管理，適合 Java 項目',
            ('shared_preferences', 'apply_instead_commit'): 
                'apply() 異步寫入磁碟，不會阻塞主線程，適合大多數場景',
            ('shared_preferences', 'datastore'): 
                'DataStore 是新一代數據存儲方案，提供類型安全和協程支援',
            ('synchronization', 'concurrent_collections'): 
                '併發集合內建線程安全，性能優於外部同步',
            ('synchronization', 'lock_ordering'): 
                '統一的鎖獲取順序可以完全避免死鎖',
            ('synchronization', 'lock_free'): 
                '無鎖數據結構提供最佳併發性能，但實現複雜'
        }
        
        return explanations.get((category, fix_type), '優化代碼以提升性能')
    
    def _assess_fix_difficulty(self, fix_type: str) -> str:
        """評估修復難度"""
        difficulty_map = {
            'apply_instead_commit': 'easy',
            'kotlin_coroutine': 'medium',
            'executor_service': 'medium',
            'async_task': 'easy',
            'concurrent_collections': 'easy',
            'lock_ordering': 'medium',
            'lock_free': 'hard',
            'datastore': 'medium'
        }
        
        return difficulty_map.get(fix_type, 'medium')


class ConfigurationOptimizer:
    """配置優化器"""
    
    def __init__(self):
        self.optimization_rules = self._init_optimization_rules()
    
    def _init_optimization_rules(self) -> Dict:
        """初始化優化規則"""
        return {
            'thread_pool': {
                'cpu_bound': lambda cores: cores * 2,
                'io_bound': lambda cores: cores * 4,
                'mixed': lambda cores: cores * 3
            },
            'memory': {
                'heap_size': {
                    'small': 64,   # MB
                    'normal': 128,
                    'large': 256,
                    'xlarge': 512
                },
                'gc_threshold': {
                    'aggressive': 0.7,  # 70% 時觸發 GC
                    'balanced': 0.8,
                    'relaxed': 0.9
                }
            },
            'system_properties': {
                'dalvik.vm.heapgrowthlimit': '256m',
                'dalvik.vm.heapsize': '512m',
                'dalvik.vm.heapminfree': '2m',
                'dalvik.vm.heapmaxfree': '8m'
            }
        }
    
    def optimize_configuration(self, performance_data: Dict) -> Dict:
        """生成配置優化建議"""
        optimizations = {
            'thread_pool_size': self._calculate_optimal_thread_pool_size(performance_data),
            'memory_settings': self._optimize_memory_settings(performance_data),
            'gc_parameters': self._tune_gc_parameters(performance_data),
            'system_properties': self._recommend_system_props(performance_data),
            'gradle_config': self._optimize_gradle_config(performance_data),
            'proguard_rules': self._optimize_proguard(performance_data)
        }
        
        return optimizations
    
    def _calculate_optimal_thread_pool_size(self, performance_data: Dict) -> Dict:
        """計算最佳線程池大小"""
        cpu_cores = performance_data.get('cpu_cores', 4)
        workload_type = self._determine_workload_type(performance_data)
        
        optimal_size = self.optimization_rules['thread_pool'][workload_type](cpu_cores)
        
        return {
            'recommended_size': optimal_size,
            'current_size': performance_data.get('current_thread_pool_size', 'unknown'),
            'workload_type': workload_type,
            'configuration': f'''
// 在 Application 類中配置
class MyApplication : Application() {{
    companion object {{
        val THREAD_POOL_SIZE = {optimal_size}
        val executor = ThreadPoolExecutor(
            THREAD_POOL_SIZE / 2,  // 核心線程數
            THREAD_POOL_SIZE,      // 最大線程數
            60L,                   // 空閒線程存活時間
            TimeUnit.SECONDS,
            LinkedBlockingQueue<Runnable>(),
            ThreadPoolExecutor.CallerRunsPolicy()
        )
    }}
}}'''
        }
    
    def _determine_workload_type(self, performance_data: Dict) -> str:
        """判斷工作負載類型"""
        io_operations = performance_data.get('io_operation_count', 0)
        cpu_usage = performance_data.get('avg_cpu_usage', 0)
        
        if io_operations > 100 and cpu_usage < 50:
            return 'io_bound'
        elif cpu_usage > 70 and io_operations < 50:
            return 'cpu_bound'
        else:
            return 'mixed'
    
    def _optimize_memory_settings(self, performance_data: Dict) -> Dict:
        """優化記憶體設置"""
        available_memory = performance_data.get('total_memory_mb', 2048)
        gc_frequency = performance_data.get('gc_frequency', 10)
        
        # 根據可用記憶體推薦堆大小
        if available_memory < 1024:
            heap_category = 'small'
        elif available_memory < 2048:
            heap_category = 'normal'
        elif available_memory < 4096:
            heap_category = 'large'
        else:
            heap_category = 'xlarge'
        
        recommended_heap = self.optimization_rules['memory']['heap_size'][heap_category]
        
        # 根據 GC 頻率推薦閾值
        if gc_frequency > 30:
            gc_strategy = 'relaxed'
        elif gc_frequency > 15:
            gc_strategy = 'balanced'
        else:
            gc_strategy = 'aggressive'
        
        return {
            'heap_size_mb': recommended_heap,
            'gc_strategy': gc_strategy,
            'large_heap_enabled': heap_category in ['large', 'xlarge'],
            'manifest_config': f'''
<!-- 在 AndroidManifest.xml 中 -->
<application
    android:largeHeap="{heap_category in ['large', 'xlarge']}"
    android:hardwareAccelerated="true"
    ... >''',
            'runtime_config': f'''
// 在代碼中動態調整
if (BuildConfig.DEBUG) {{
    // 調試模式下監控記憶體
    StrictMode.setVmPolicy(StrictMode.VmPolicy.Builder()
        .detectLeakedSqlLiteObjects()
        .detectLeakedClosableObjects()
        .penaltyLog()
        .build())
}}'''
        }
    
    def _tune_gc_parameters(self, performance_data: Dict) -> Dict:
        """調整 GC 參數"""
        gc_pause_time = performance_data.get('avg_gc_pause_ms', 50)
        memory_pressure = performance_data.get('memory_pressure', 'normal')
        
        recommendations = {
            'gc_type': 'concurrent' if gc_pause_time > 100 else 'generational',
            'suggestions': []
        }
        
        if gc_pause_time > 100:
            recommendations['suggestions'].append('使用併發 GC 減少暫停時間')
            recommendations['suggestions'].append('考慮使用 G1GC (Android 10+)')
        
        if memory_pressure == 'high':
            recommendations['suggestions'].append('增加堆內存大小')
            recommendations['suggestions'].append('優化對象分配策略')
            recommendations['suggestions'].append('使用對象池減少 GC 壓力')
        
        recommendations['code_optimization'] = '''
// 減少 GC 壓力的最佳實踐
class ObjectPool<T>(
    private val factory: () -> T,
    private val reset: (T) -> Unit,
    private val maxSize: Int = 10
) {
    private val pool = mutableListOf<T>()
    
    fun acquire(): T {
        return pool.removeLastOrNull() ?: factory()
    }
    
    fun release(obj: T) {
        reset(obj)
        if (pool.size < maxSize) {
            pool.add(obj)
        }
    }
}'''
        
        return recommendations
    
    def _recommend_system_props(self, performance_data: Dict) -> Dict:
        """推薦系統屬性"""
        props = dict(self.optimization_rules['system_properties'])
        
        # 根據性能數據調整
        if performance_data.get('total_memory_mb', 0) > 4096:
            props['dalvik.vm.heapsize'] = '1024m'
            props['dalvik.vm.heapgrowthlimit'] = '512m'
        
        return {
            'properties': props,
            'apply_method': '''
# 在 build.prop 或通過 adb 設置
adb shell setprop dalvik.vm.heapsize 512m
adb shell setprop dalvik.vm.heapgrowthlimit 256m

# 或在自定義 ROM 中修改 build.prop''',
            'warning': '修改系統屬性需要 root 權限或自定義 ROM'
        }
    
    def _optimize_gradle_config(self, performance_data: Dict) -> Dict:
        """優化 Gradle 配置"""
        return {
            'build_optimization': '''
// app/build.gradle
android {
    buildTypes {
        release {
            minifyEnabled true
            shrinkResources true
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
            
            // 優化 APK 大小和性能
            ndk {
                debugSymbolLevel 'SYMBOL_TABLE'
            }
        }
    }
    
    // 啟用增量編譯
    compileOptions {
        incremental true
        sourceCompatibility JavaVersion.VERSION_11
        targetCompatibility JavaVersion.VERSION_11
    }
    
    // 優化 DEX
    dexOptions {
        preDexLibraries true
        maxProcessCount 8
        javaMaxHeapSize "4g"
    }
}''',
            'dependency_optimization': '''
// 移除未使用的依賴，使用特定模塊
implementation 'com.google.android.gms:play-services-maps:18.1.0'
// 而非
implementation 'com.google.android.gms:play-services:18.1.0'''
        }
    
    def _optimize_proguard(self, performance_data: Dict) -> Dict:
        """優化 ProGuard/R8 規則"""
        return {
            'performance_rules': '''
# ProGuard/R8 性能優化規則

# 優化選項
-optimizationpasses 5
-allowaccessmodification
-repackageclasses ''

# 保留性能關鍵的類
-keep class androidx.recyclerview.widget.RecyclerView { *; }
-keep class androidx.viewpager2.widget.ViewPager2 { *; }

# 內聯簡單方法
-optimizations !code/simplification/arithmetic,!field/*,!class/merging/*,code/removal/advanced

# 移除日誌
-assumenosideeffects class android.util.Log {
    public static *** d(...);
    public static *** v(...);
    public static *** i(...);
}''',
            'size_optimization': '''
# 減少 APK 大小
-repackageclasses
-allowaccessmodification
-overloadaggressively''',
            'startup_optimization': '''
# 優化啟動時間
-keep class com.myapp.startup.* { *; }
-keepclassmembers class * {
    @com.myapp.startup.StartupOptimized *;
}'''
        }


## 7. 報告增強模塊
class ExecutiveSummaryGenerator:
    """執行摘要生成器"""
    
    def __init__(self):
        self.impact_levels = {
            'critical': {'score': 10, 'color': 'red', 'action': 'immediate'},
            'high': {'score': 7, 'color': 'orange', 'action': 'urgent'},
            'medium': {'score': 4, 'color': 'yellow', 'action': 'planned'},
            'low': {'score': 1, 'color': 'green', 'action': 'monitor'}
        }
    
    def generate_summary(self, analysis_results: Dict) -> str:
        """生成管理層摘要"""
        summary_data = {
            'impact': self._assess_business_impact(analysis_results),
            'root_cause': self._simplify_technical_cause(analysis_results),
            'action_items': self._prioritize_actions(analysis_results),
            'timeline': self._estimate_fix_timeline(analysis_results),
            'resources_needed': self._estimate_resources(analysis_results),
            'risk_assessment': self._assess_risks(analysis_results)
        }
        
        return self._format_executive_summary(summary_data)
    
    def _assess_business_impact(self, analysis_results: Dict) -> Dict:
        """評估業務影響"""
        impact = {
            'user_experience': 'severe',
            'revenue_impact': 'high',
            'brand_reputation': 'medium',
            'affected_users': 0,
            'estimated_loss': 0
        }
        
        # 基於 ANR 類型評估
        anr_type = analysis_results.get('anr_type', 'unknown')
        if anr_type == 'INPUT_DISPATCHING':
            impact['user_experience'] = 'severe'
            impact['affected_users'] = '所有使用該功能的用戶'
        elif anr_type == 'SERVICE':
            impact['user_experience'] = 'moderate'
            impact['affected_users'] = '背景服務用戶'
        
        # 基於頻率評估
        frequency = analysis_results.get('frequency', 0)
        if frequency > 100:
            impact['revenue_impact'] = 'critical'
            impact['estimated_loss'] = frequency * 0.1  # 假設每次 ANR 損失 0.1 元
        
        return impact
    
    def _simplify_technical_cause(self, analysis_results: Dict) -> str:
        """簡化技術原因為管理層可理解的語言"""
        technical_cause = analysis_results.get('root_cause', 'unknown')
        
        simplifications = {
            'main_thread_io': '應用在處理用戶操作時進行了耗時的文件讀寫',
            'deadlock': '應用內部的資源競爭導致相互等待',
            'memory_pressure': '設備記憶體不足影響應用運行',
            'binder_timeout': '與系統服務通信超時',
            'cpu_contention': '設備處理器負載過高'
        }
        
        return simplifications.get(technical_cause, '應用響應時間超過系統限制')
    
    def _prioritize_actions(self, analysis_results: Dict) -> List[Dict]:
        """優先級排序行動項"""
        actions = []
        
        # 基於分析結果生成行動項
        if analysis_results.get('severity') == 'critical':
            actions.append({
                'priority': 1,
                'action': '立即熱修復受影響功能',
                'owner': '技術負責人',
                'deadline': '24小時內'
            })
        
        actions.append({
            'priority': 2,
            'action': '全面代碼審查和性能測試',
            'owner': '開發團隊',
            'deadline': '本週內'
        })
        
        actions.append({
            'priority': 3,
            'action': '建立 ANR 監控和預警機制',
            'owner': 'DevOps 團隊',
            'deadline': '本月內'
        })
        
        return sorted(actions, key=lambda x: x['priority'])
    
    def _estimate_fix_timeline(self, analysis_results: Dict) -> Dict:
        """估算修復時間線"""
        complexity = analysis_results.get('fix_complexity', 'medium')
        
        timelines = {
            'low': {'hotfix': '2-4 小時', 'complete': '1-2 天'},
            'medium': {'hotfix': '1-2 天', 'complete': '3-5 天'},
            'high': {'hotfix': '2-3 天', 'complete': '1-2 週'}
        }
        
        return timelines.get(complexity, timelines['medium'])
    
    def _estimate_resources(self, analysis_results: Dict) -> Dict:
        """估算所需資源"""
        return {
            'developers': 2,
            'testers': 1,
            'hours': 40,
            'additional_tools': ['性能分析工具', 'APM 系統'],
            'budget': '視具體工具而定'
        }
    
    def _assess_risks(self, analysis_results: Dict) -> List[Dict]:
        """風險評估"""
        risks = []
        
        if analysis_results.get('anr_frequency', 0) > 50:
            risks.append({
                'risk': '用戶流失',
                'probability': 'high',
                'impact': 'critical',
                'mitigation': '提供臨時解決方案和用戶溝通'
            })
        
        risks.append({
            'risk': '應用商店評分下降',
            'probability': 'medium',
            'impact': 'high',
            'mitigation': '主動回應用戶評論，快速迭代修復'
        })
        
        return risks
    
    def _format_executive_summary(self, summary_data: Dict) -> str:
        """格式化執行摘要"""
        # 使用 get 方法提供預設值，避免 KeyError
        root_cause = summary_data.get('root_cause', '未知原因')
        timeline = summary_data.get('timeline', {'hotfix': '未知', 'complete': '未知'})
        action_items = summary_data.get('action_items', [])
        resources_needed = summary_data.get('resources_needed', {
            'developers': 0,
            'testers': 0, 
            'hours': 0,
            'additional_tools': [],
            'budget': '未定'
        })
        risk_assessment = summary_data.get('risk_assessment', [])
        impact = summary_data.get('impact', {
            'user_experience': 'unknown',
            'revenue_impact': 'unknown',
            'affected_users': '未知',
            'estimated_loss': 0,
            'brand_reputation': 'unknown'
        })
        
        html = f'''
        <div class="executive-summary">
            <h1>ANR 問題執行摘要</h1>
            
            <div class="summary-section impact">
                <h2>業務影響</h2>
                <div class="impact-grid">
                    <div class="impact-item">
                        <span class="label">用戶體驗影響</span>
                        <span class="value {impact.get('user_experience', 'unknown')}">{impact.get('user_experience', 'unknown').upper()}</span>
                    </div>
                    <div class="impact-item">
                        <span class="label">收入影響</span>
                        <span class="value {impact.get('revenue_impact', 'unknown')}">{impact.get('revenue_impact', 'unknown').upper()}</span>
                    </div>
                    <div class="impact-item">
                        <span class="label">受影響用戶</span>
                        <span class="value">{impact.get('affected_users', '未知')}</span>
                    </div>
                </div>
            </div>
            
            <div class="summary-section root-cause">
                <h2>問題原因（簡化版）</h2>
                <p>{root_cause}</p>
            </div>
            
            <div class="summary-section timeline">
                <h2>修復時間線</h2>
                <ul>
                    <li>緊急修復: {timeline.get('hotfix', '未知')}</li>
                    <li>完整解決: {timeline.get('complete', '未知')}</li>
                </ul>
            </div>
        '''
        
        # 處理 action_items
        if action_items:
            html += '''
            <div class="summary-section actions">
                <h2>行動計劃</h2>
                <table class="action-table">
                    <thead>
                        <tr>
                            <th>優先級</th>
                            <th>行動項</th>
                            <th>負責人</th>
                            <th>期限</th>
                        </tr>
                    </thead>
                    <tbody>
            '''
            
            for action in action_items:
                html += f'''
                    <tr>
                        <td class="priority-{action.get('priority', 0)}">{action.get('priority', 0)}</td>
                        <td>{action.get('action', '')}</td>
                        <td>{action.get('owner', '')}</td>
                        <td>{action.get('deadline', '')}</td>
                    </tr>
                '''
            
            html += '''
                    </tbody>
                </table>
            </div>
            '''
        
        html += f'''
            <div class="summary-section resources">
                <h2>所需資源</h2>
                <ul>
                    <li>開發人員: {resources_needed.get('developers', 0)} 人</li>
                    <li>測試人員: {resources_needed.get('testers', 0)} 人</li>
                    <li>預估工時: {resources_needed.get('hours', 0)} 小時</li>
                    <li>額外工具: {', '.join(resources_needed.get('additional_tools', []))}</li>
                    <li>預算: {resources_needed.get('budget', '視具體工具而定')}</li>
                </ul>
            </div>
        '''
        
        # 風險評估部分
        if risk_assessment:
            html += '''
            <div class="summary-section risks">
                <h2>風險評估</h2>
                <div class="risk-matrix">
            '''
            html += self._generate_risk_matrix(risk_assessment)
            html += '''
                </div>
            </div>
            '''
        
        html += '''
            <style>
                .executive-summary {
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }
                
                .summary-section {
                    margin-bottom: 30px;
                    padding: 20px;
                    background: #f5f5f5;
                    border-radius: 8px;
                }
                
                .impact-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                }
                
                .impact-item {
                    text-align: center;
                }
                
                .value.severe, .value.critical {
                    color: #ff0000;
                    font-weight: bold;
                }
                
                .value.high {
                    color: #ff8800;
                    font-weight: bold;
                }
                
                .value.medium {
                    color: #ffaa00;
                }
                
                .value.unknown {
                    color: #999999;
                }
                
                .action-table {
                    width: 100%;
                    border-collapse: collapse;
                }
                
                .action-table th, .action-table td {
                    padding: 10px;
                    border: 1px solid #ddd;
                    text-align: left;
                }
                
                .priority-1 {
                    background-color: #ffcccc;
                    font-weight: bold;
                }
                
                .priority-2 {
                    background-color: #ffe6cc;
                }
                
                .priority-3 {
                    background-color: #fff9cc;
                }
                
                .risk-matrix {
                    display: grid;
                    grid-template-columns: 100px repeat(3, 1fr);
                    gap: 5px;
                    margin-top: 15px;
                }
                
                .risk-header {
                    font-weight: bold;
                    padding: 5px;
                    background: #e0e0e0;
                    text-align: center;
                }
                
                .risk-cell {
                    padding: 10px;
                    border: 1px solid #ddd;
                    text-align: center;
                    font-size: 14px;
                }
                
                .risk-high-high {
                    background-color: #ff4444;
                    color: white;
                }
                
                .risk-high-medium {
                    background-color: #ff8844;
                    color: white;
                }
                
                .risk-high-low {
                    background-color: #ffaa44;
                }
                
                .risk-medium-high {
                    background-color: #ff8844;
                    color: white;
                }
                
                .risk-medium-medium {
                    background-color: #ffaa44;
                }
                
                .risk-medium-low {
                    background-color: #ffdd44;
                }
                
                .risk-low-high {
                    background-color: #ffaa44;
                }
                
                .risk-low-medium {
                    background-color: #ffdd44;
                }
                
                .risk-low-low {
                    background-color: #44ff44;
                }
            </style>
        </div>
        '''
        
        return html
    
    def _generate_risk_matrix(self, risks: List[Dict]) -> str:
        """生成風險矩陣"""
        matrix_html = '<div class="risk-header"></div>'
        matrix_html += '<div class="risk-header">低影響</div>'
        matrix_html += '<div class="risk-header">中影響</div>'
        matrix_html += '<div class="risk-header">高影響</div>'
        
        for probability in ['high', 'medium', 'low']:
            matrix_html += f'<div class="risk-header">{probability}概率</div>'
            for impact in ['low', 'medium', 'high']:
                risks_in_cell = [r for r in risks 
                               if r['probability'] == probability and r['impact'] == impact]
                cell_content = '<br>'.join(r['risk'] for r in risks_in_cell) if risks_in_cell else '-'
                cell_class = f'risk-cell risk-{probability}-{impact}'
                matrix_html += f'<div class="{cell_class}">{cell_content}</div>'
        
        return matrix_html


class ComparativeAnalyzer:
    """比較分析器"""
    
    def __init__(self):
        self.similarity_threshold = 0.7
    
    def compare_anrs(self, anr_list: List[ANRInfo]) -> Dict:
        """比較多個 ANR 找出共同點"""
        if len(anr_list) < 2:
            return {'error': '需要至少 2 個 ANR 進行比較'}
        
        comparison = {
            'total_anrs': len(anr_list),
            'common_threads': self._find_common_threads(anr_list),
            'common_stack_patterns': self._find_stack_patterns(anr_list),
            'timing_correlation': self._analyze_timing_correlation(anr_list),
            'environmental_factors': self._compare_environments(anr_list),
            'clustering_result': self._cluster_anrs(anr_list),
            'recommendations': []
        }
        
        # 生成比較建議
        comparison['recommendations'] = self._generate_comparison_recommendations(comparison)
        
        return comparison
    
    def _find_common_threads(self, anr_list: List[ANRInfo]) -> Dict:
        """找出共同的線程問題"""
        thread_issues = defaultdict(int)
        thread_states = defaultdict(lambda: defaultdict(int))
        
        for anr in anr_list:
            # 統計線程狀態
            for thread in anr.all_threads:
                thread_states[thread.name][thread.state.value] += 1
                
                # 記錄問題線程
                if thread.state == ThreadState.BLOCKED:
                    thread_issues[f"{thread.name} - BLOCKED"] += 1
                elif thread.waiting_locks:
                    thread_issues[f"{thread.name} - WAITING_LOCK"] += 1
        
        # 找出在多個 ANR 中都有問題的線程
        common_issues = {
            thread: count for thread, count in thread_issues.items()
            if count >= len(anr_list) * 0.5  # 至少一半的 ANR 中出現
        }
        
        return {
            'problematic_threads': common_issues,
            'thread_state_distribution': dict(thread_states),
            'most_blocked_thread': max(thread_issues.items(), key=lambda x: x[1])[0] if thread_issues else None
        }
    
    def _find_stack_patterns(self, anr_list: List[ANRInfo]) -> List[Dict]:
        """找出共同的堆疊模式"""
        stack_signatures = defaultdict(list)
        
        for i, anr in enumerate(anr_list):
            if anr.main_thread and anr.main_thread.backtrace:
                # 為每個 ANR 的主線程堆疊生成簽名
                signature = self._generate_stack_signature(anr.main_thread.backtrace[:10])
                stack_signatures[signature].append({
                    'anr_index': i,
                    'timestamp': anr.timestamp,
                    'top_frames': anr.main_thread.backtrace[:5]
                })
        
        # 找出重複的模式
        patterns = []
        for signature, occurrences in stack_signatures.items():
            if len(occurrences) >= 2:
                patterns.append({
                    'signature': signature,
                    'count': len(occurrences),
                    'percentage': len(occurrences) / len(anr_list) * 100,
                    'common_frames': self._extract_common_frames(occurrences),
                    'occurrences': occurrences
                })
        
        return sorted(patterns, key=lambda x: x['count'], reverse=True)
    
    def _analyze_timing_correlation(self, anr_list: List[ANRInfo]) -> Dict:
        """分析時間相關性"""
        if not all(anr.timestamp for anr in anr_list):
            return {'error': '缺少時間戳資訊'}
        
        # 按時間排序
        sorted_anrs = sorted(anr_list, key=lambda x: x.timestamp or '')
        
        # 計算時間間隔
        intervals = []
        for i in range(1, len(sorted_anrs)):
            # 簡化的時間差計算
            intervals.append({
                'from': sorted_anrs[i-1].timestamp,
                'to': sorted_anrs[i].timestamp,
                'interval': 'calculated_interval'  # 實際應計算時間差
            })
        
        # 分析模式
        timing_analysis = {
            'intervals': intervals,
            'pattern': 'unknown',
            'description': ''
        }
        
        # 簡單的模式判斷
        if len(intervals) > 2:
            # 檢查是否為週期性
            timing_analysis['pattern'] = 'periodic' if len(set(i['interval'] for i in intervals)) < 3 else 'random'
            timing_analysis['description'] = '週期性發生' if timing_analysis['pattern'] == 'periodic' else '隨機發生'
        
        return timing_analysis
    
    def _compare_environments(self, anr_list: List[ANRInfo]) -> Dict:
        """比較環境因素"""
        env_factors = {
            'cpu_usage': [],
            'memory_available': [],
            'thread_counts': [],
            'anr_types': Counter()
        }
        
        for anr in anr_list:
            # CPU 使用率
            if anr.cpu_usage:
                env_factors['cpu_usage'].append(anr.cpu_usage.get('total', 0))
            
            # 記憶體
            if anr.memory_info:
                env_factors['memory_available'].append(
                    anr.memory_info.get('available', 0) / 1024  # MB
                )
            
            # 線程數
            env_factors['thread_counts'].append(len(anr.all_threads))
            
            # ANR 類型
            env_factors['anr_types'][anr.anr_type.value] += 1
        
        # 計算統計
        return {
            'avg_cpu_usage': sum(env_factors['cpu_usage']) / len(env_factors['cpu_usage']) if env_factors['cpu_usage'] else 0,
            'avg_memory_available': sum(env_factors['memory_available']) / len(env_factors['memory_available']) if env_factors['memory_available'] else 0,
            'avg_thread_count': sum(env_factors['thread_counts']) / len(env_factors['thread_counts']),
            'anr_type_distribution': dict(env_factors['anr_types']),
            'correlation': self._calculate_env_correlation(env_factors)
        }
    
    def _cluster_anrs(self, anr_list: List[ANRInfo]) -> List[Dict]:
        """將相似的 ANR 聚類"""
        clusters = []
        clustered = set()
        
        for i, anr1 in enumerate(anr_list):
            if i in clustered:
                continue
            
            cluster = {
                'members': [i],
                'representative': i,
                'common_features': []
            }
            
            # 找出相似的 ANR
            for j, anr2 in enumerate(anr_list[i+1:], i+1):
                if j not in clustered:
                    similarity = self._calculate_anr_similarity(anr1, anr2)
                    if similarity > self.similarity_threshold:
                        cluster['members'].append(j)
                        clustered.add(j)
            
            clustered.add(i)
            
            # 提取共同特徵
            cluster['common_features'] = self._extract_cluster_features(
                [anr_list[idx] for idx in cluster['members']]
            )
            
            clusters.append(cluster)
        
        return clusters
    
    def _generate_stack_signature(self, frames: List[str]) -> str:
        """生成堆疊簽名"""
        # 提取關鍵方法名和類名
        key_elements = []
        for frame in frames[:5]:  # 只用前5幀
            # 簡化提取類名和方法名
            match = re.search(r'([a-zA-Z0-9._$]+)\.([a-zA-Z0-9_$]+)\(', frame)
            if match:
                class_name = match.group(1).split('.')[-1]  # 只取最後一部分
                method_name = match.group(2)
                key_elements.append(f"{class_name}.{method_name}")
        
        # 生成簽名
        signature_str = '|'.join(key_elements)
        return hashlib.md5(signature_str.encode()).hexdigest()[:16]
    
    def _extract_common_frames(self, occurrences: List[Dict]) -> List[str]:
        """提取共同的堆疊幀"""
        if not occurrences:
            return []
        
        # 取第一個作為參考
        reference_frames = occurrences[0]['top_frames']
        common_frames = []
        
        # 檢查每一幀是否在所有 occurrence 中都存在
        for frame in reference_frames:
            if all(frame in occ['top_frames'] for occ in occurrences[1:]):
                common_frames.append(frame)
        
        return common_frames
    
    def _calculate_env_correlation(self, env_factors: Dict) -> Dict:
        """計算環境因素相關性"""
        correlations = {}
        
        # 簡單的相關性分析
        if env_factors['cpu_usage'] and env_factors['memory_available']:
            # 檢查 CPU 高時記憶體是否也低
            high_cpu_low_mem = sum(
                1 for cpu, mem in zip(env_factors['cpu_usage'], env_factors['memory_available'])
                if cpu > 80 and mem < 100
            )
            
            if high_cpu_low_mem > len(env_factors['cpu_usage']) * 0.5:
                correlations['cpu_memory'] = 'negative_correlation'
                correlations['description'] = 'CPU 使用率高時通常伴隨記憶體不足'
        
        return correlations
    
    def _calculate_anr_similarity(self, anr1: ANRInfo, anr2: ANRInfo) -> float:
        """計算兩個 ANR 的相似度"""
        similarity_score = 0.0
        weight_sum = 0.0
        
        # ANR 類型相似度
        if anr1.anr_type == anr2.anr_type:
            similarity_score += 0.3
        weight_sum += 0.3
        
        # 主線程堆疊相似度
        if anr1.main_thread and anr2.main_thread:
            stack_sim = self._calculate_stack_similarity(
                anr1.main_thread.backtrace[:10],
                anr2.main_thread.backtrace[:10]
            )
            similarity_score += stack_sim * 0.5
        weight_sum += 0.5
        
        # 線程狀態相似度
        thread_sim = self._calculate_thread_state_similarity(anr1.all_threads, anr2.all_threads)
        similarity_score += thread_sim * 0.2
        weight_sum += 0.2
        
        return similarity_score / weight_sum if weight_sum > 0 else 0
    
    def _calculate_stack_similarity(self, stack1: List[str], stack2: List[str]) -> float:
        """計算堆疊相似度"""
        if not stack1 or not stack2:
            return 0.0
        
        # 計算共同幀的比例
        common_frames = 0
        for i, (frame1, frame2) in enumerate(zip(stack1, stack2)):
            if frame1 == frame2:
                common_frames += 1
            elif i < 3 and self._is_similar_frame(frame1, frame2):
                common_frames += 0.5  # 部分匹配
        
        return common_frames / max(len(stack1), len(stack2))
    
    def _is_similar_frame(self, frame1: str, frame2: str) -> bool:
        """判斷兩個堆疊幀是否相似"""
        # 提取類名和方法名進行比較
        pattern = r'([a-zA-Z0-9._$]+)\.([a-zA-Z0-9_$]+)\('
        
        match1 = re.search(pattern, frame1)
        match2 = re.search(pattern, frame2)
        
        if match1 and match2:
            return (match1.group(1) == match2.group(1) and 
                   match1.group(2) == match2.group(2))
        
        return False
    
    def _calculate_thread_state_similarity(self, threads1: List[ThreadInfo], 
                                         threads2: List[ThreadInfo]) -> float:
        """計算線程狀態相似度"""
        # 統計線程狀態分布
        states1 = Counter(t.state.value for t in threads1)
        states2 = Counter(t.state.value for t in threads2)
        
        # 計算分布相似度
        all_states = set(states1.keys()) | set(states2.keys())
        
        if not all_states:
            return 0.0
        
        similarity = 0.0
        for state in all_states:
            count1 = states1.get(state, 0)
            count2 = states2.get(state, 0)
            
            # 使用最小值除以最大值計算相似度
            if count1 > 0 or count2 > 0:
                similarity += min(count1, count2) / max(count1, count2)
        
        return similarity / len(all_states)
    
    def _extract_cluster_features(self, cluster_anrs: List[ANRInfo]) -> List[str]:
        """提取聚類的共同特徵"""
        features = []
        
        # ANR 類型
        anr_types = Counter(anr.anr_type.value for anr in cluster_anrs)
        if len(anr_types) == 1:
            features.append(f"相同 ANR 類型: {list(anr_types.keys())[0]}")
        
        # 共同的問題線程
        common_blocked = set()
        for anr in cluster_anrs:
            blocked = {t.name for t in anr.all_threads if t.state == ThreadState.BLOCKED}
            if not common_blocked:
                common_blocked = blocked
            else:
                common_blocked &= blocked
        
        if common_blocked:
            features.append(f"共同阻塞線程: {', '.join(list(common_blocked)[:3])}")
        
        # 環境特徵
        avg_cpu = sum(anr.cpu_usage.get('total', 0) for anr in cluster_anrs 
                     if anr.cpu_usage) / len(cluster_anrs)
        if avg_cpu > 80:
            features.append(f"高 CPU 使用率: 平均 {avg_cpu:.1f}%")
        
        return features
    
    def _generate_comparison_recommendations(self, comparison: Dict) -> List[str]:
        """生成比較分析建議"""
        recommendations = []
        
        # 基於共同線程問題
        if comparison['common_threads']['problematic_threads']:
            most_common = max(comparison['common_threads']['problematic_threads'].items(), 
                            key=lambda x: x[1])
            recommendations.append(
                f"優先解決 {most_common[0]} 的問題，它在 {most_common[1]} 個 ANR 中出現"
            )
        
        # 基於堆疊模式
        if comparison['common_stack_patterns']:
            top_pattern = comparison['common_stack_patterns'][0]
            recommendations.append(
                f"發現重複堆疊模式 (出現 {top_pattern['count']} 次)，"
                f"表明存在系統性問題"
            )
        
        # 基於時間相關性
        if comparison['timing_correlation'].get('pattern') == 'periodic':
            recommendations.append("ANR 呈週期性發生，可能與定時任務或系統事件相關")
        
        # 基於環境因素
        env = comparison['environmental_factors']
        if env['avg_cpu_usage'] > 80:
            recommendations.append(f"平均 CPU 使用率高達 {env['avg_cpu_usage']:.1f}%，需要優化計算密集型操作")
        
        if env['avg_memory_available'] < 100:
            recommendations.append(f"平均可用記憶體僅 {env['avg_memory_available']:.1f}MB，需要優化記憶體使用")
        
        # 基於聚類結果
        if comparison['clustering_result']:
            recommendations.append(
                f"發現 {len(comparison['clustering_result'])} 個不同的 ANR 模式，"
                f"建議分別針對每個模式制定解決方案"
            )
        
        return recommendations


## 8. 性能優化模塊
class ParallelAnalyzer:
    """並行分析器"""
    
    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers or os.cpu_count()
        self.executor = None
    
    async def analyze_parallel(self, files: List[str]) -> List[Dict]:
        """並行分析多個檔案"""
        import concurrent.futures
        
        results = []
        
        # 使用 ThreadPoolExecutor 進行並行處理
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任務
            future_to_file = {
                executor.submit(self._analyze_file_async, file): file 
                for file in files
            }
            
            # 收集結果
            for future in concurrent.futures.as_completed(future_to_file):
                file = future_to_file[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    print(f"Error analyzing {file}: {e}")
                    results.append({
                        'file': file,
                        'error': str(e),
                        'status': 'failed'
                    })
        
        # 合併結果
        return self._merge_results(results)
    
    def _analyze_file_async(self, file_path: str) -> Dict:
        """異步分析單個檔案"""
        try:
            # 執行完整分析
            print(f"執行完整分析: {file_path}")
            file_type = self._determine_file_type(file_path)
            
            # 延遲導入
            from vp_analyze_logs_factory import AnalyzerFactory
            analyzer = AnalyzerFactory.create_analyzer(file_type)

            # 執行分析
            result = analyzer.analyze(file_path)
            
            return {
                'file': file_path,
                'type': file_type,
                'result': result,
                'status': 'success'
            }
        except Exception as e:
            return {
                'file': file_path,
                'error': str(e),
                'status': 'failed'
            }
    
    def _determine_file_type(self, file_path: str) -> str:
        """判斷檔案類型"""
        file_name = os.path.basename(file_path).lower()
        
        if 'anr' in file_name:
            return 'anr'
        elif 'tombstone' in file_name:
            return 'tombstone'
        else:
            # 讀取檔案內容判斷
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(1000)  # 只讀前1000字符
                
            if 'ANR in' in content or 'Input dispatching timed out' in content:
                return 'anr'
            elif 'signal' in content and 'fault addr' in content:
                return 'tombstone'
            else:
                raise ValueError(f"無法判斷檔案類型: {file_path}")
    
    def _merge_results(self, results: List[Dict]) -> List[Dict]:
        """合併分析結果"""
        merged = {
            'total_files': len(results),
            'successful': sum(1 for r in results if r['status'] == 'success'),
            'failed': sum(1 for r in results if r['status'] == 'failed'),
            'anr_files': [],
            'tombstone_files': [],
            'common_issues': [],
            'summary': {}
        }
        
        # 分類結果
        for result in results:
            if result['status'] == 'success':
                if result['type'] == 'anr':
                    merged['anr_files'].append(result)
                else:
                    merged['tombstone_files'].append(result)
        
        # 提取共同問題
        if merged['anr_files']:
            # 這裡可以調用 ComparativeAnalyzer
            pass
        
        return merged

    def _analyze_file_async(self, file_path: str) -> Dict:
        """異步分析單個檔案"""
        try:
            # 判斷檔案類型
            file_type = self._determine_file_type(file_path)
            
            # 延遲導入避免循環引入
            from vp_analyze_logs_factory import AnalyzerFactory
            
            # 創建分析器
            analyzer = AnalyzerFactory.create_analyzer(file_type)
            
            # 執行分析
            result = analyzer.analyze(file_path)
            
            return {
                'file': file_path,
                'type': file_type,
                'result': result,
                'status': 'success'
            }
        except Exception as e:
            return {
                'file': file_path,
                'error': str(e),
                'status': 'failed'
            }

class IncrementalAnalyzer:
    """增量分析器"""
    
    def __init__(self, cache_dir: str = '.anr_cache'):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict:
        """載入快取"""
        cache_file = os.path.join(self.cache_dir, 'analysis_cache.json')
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_cache(self):
        """保存快取"""
        cache_file = os.path.join(self.cache_dir, 'analysis_cache.json')
        with open(cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)
    
    def analyze_incremental(self, file_path: str, force: bool = False) -> Dict:
        """增量分析 - 只分析變更的部分"""
        file_hash = self._calculate_file_hash(file_path)
        cache_key = os.path.basename(file_path)
        
        # 檢查快取
        if not force and cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if cached_data['hash'] == file_hash:
                print(f"使用快取結果: {file_path}")
                return cached_data['analysis']
        
        # 如果有舊的分析結果，進行增量分析
        if cache_key in self.cache and not force:
            old_analysis = self.cache[cache_key]['analysis']
            new_content = self._read_file(file_path)
            old_content = self.cache[cache_key].get('content', '')
            
            # 計算差異
            diff = self._calculate_diff(new_content, old_content)
            
            if diff['added_lines'] < 100:  # 如果新增內容不多，使用增量分析
                print(f"執行增量分析: {file_path}")
                incremental_result = self._analyze_diff(diff, old_analysis)
                
                # 合併結果
                merged_result = self._merge_with_previous(incremental_result, old_analysis)
                
                # 更新快取
                self.cache[cache_key] = {
                    'hash': file_hash,
                    'analysis': merged_result,
                    'content': new_content,
                    'timestamp': time.time()
                }
                self._save_cache()
                
                return merged_result
        
        # 執行完整分析
        print(f"執行完整分析: {file_path}")
        file_type = self._determine_file_type(file_path)
        
        # 延遲導入
        from vp_analyze_logs_factory import AnalyzerFactory
        analyzer = AnalyzerFactory.create_analyzer(file_type)
        
        # 分析並解析結果
        result_text = analyzer.analyze(file_path)
        
        # 簡化的結果結構
        analysis_result = {
            'file': file_path,
            'type': file_type,
            'result': result_text,
            'timestamp': time.time()
        }
        
        # 更新快取
        self.cache[cache_key] = {
            'hash': file_hash,
            'analysis': analysis_result,
            'content': self._read_file(file_path),
            'timestamp': time.time()
        }
        self._save_cache()
        
        return analysis_result
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """計算檔案雜湊值"""
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def _read_file(self, file_path: str) -> str:
        """讀取檔案內容"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    
    def _determine_file_type(self, file_path: str) -> str:
        """判斷檔案類型"""
        content = self._read_file(file_path)[:1000]
        
        if 'ANR in' in content or 'Input dispatching timed out' in content:
            return 'anr'
        elif 'signal' in content and 'fault addr' in content:
            return 'tombstone'
        else:
            return 'unknown'
    
    def _calculate_diff(self, new_content: str, old_content: str) -> Dict:
        """計算內容差異"""
        new_lines = new_content.splitlines()
        old_lines = old_content.splitlines()
        
        # 簡單的差異計算
        added_lines = len(new_lines) - len(old_lines)
        
        # 找出新增的部分
        new_section = []
        if added_lines > 0:
            new_section = new_lines[len(old_lines):]
        
        return {
            'added_lines': added_lines,
            'new_section': '\n'.join(new_section),
            'total_lines': len(new_lines)
        }
    
    def _analyze_diff(self, diff: Dict, old_analysis: Dict) -> Dict:
        """分析差異部分"""
        # 只分析新增的部分
        if diff['new_section']:
            # 簡化的增量分析
            return {
                'incremental': True,
                'new_findings': f"新增 {diff['added_lines']} 行內容",
                'diff_analysis': self._quick_analyze(diff['new_section'])
            }
        
        return {'incremental': True, 'new_findings': '無新增內容'}
    
    def _quick_analyze(self, content: str) -> Dict:
        """快速分析內容片段"""
        findings = {
            'new_errors': [],
            'new_warnings': [],
            'new_threads': []
        }
        
        # 簡單的模式匹配
        if 'ERROR' in content or 'FATAL' in content:
            findings['new_errors'].append('發現新的錯誤日誌')
        
        if 'WARNING' in content:
            findings['new_warnings'].append('發現新的警告')
        
        thread_matches = re.findall(r'"([^"]+)".*?tid=(\d+)', content)
        if thread_matches:
            findings['new_threads'] = [f"{name} (tid={tid})" for name, tid in thread_matches[:5]]
        
        return findings
    
    def _merge_with_previous(self, incremental_result: Dict, previous_analysis: Dict) -> Dict:
        """合併增量結果與之前的分析"""
        merged = previous_analysis.copy()
        
        # 添加增量分析標記
        merged['last_incremental_update'] = time.time()
        merged['incremental_findings'] = incremental_result
        
        return merged
    
    def clear_cache(self):
        """清除快取"""
        self.cache = {}
        self._save_cache()
        print("快取已清除")

class BinderCallChainAnalyzer:
    """Binder 調用鏈分析器"""
    
    def __init__(self):
        self.binder_services = {
            'WindowManagerService': {
                'methods': ['getWindowInsets', 'addWindow', 'removeWindow', 'relayoutWindow'],
                'avg_latency_ms': 50,
                'timeout_ms': 5000
            },
            'ActivityManagerService': {
                'methods': ['startActivity', 'bindService', 'getRunningTasks', 'broadcastIntent'],
                'avg_latency_ms': 100,
                'timeout_ms': 10000
            },
            'PackageManagerService': {
                'methods': ['getPackageInfo', 'queryIntentActivities', 'getApplicationInfo'],
                'avg_latency_ms': 200,
                'timeout_ms': 20000
            }
        }
    
    def analyze_binder_chain(self, backtrace: List[str]) -> Dict:
        """分析 Binder 調用鏈"""
        chain_info = {
            'call_sequence': [],
            'total_latency': 0,
            'bottlenecks': [],
            'cross_process_calls': 0,
            'recommendation': ''
        }
        
        # 解析調用序列
        for i, frame in enumerate(backtrace):
            if self._is_binder_call(frame):
                # 調試輸出
                print(f"發現 Binder 調用: {frame}")
                
                call_detail = self._extract_binder_detail(frame, backtrace[i:i+5])
                
                # 調試輸出
                print(f"解析結果: Service={call_detail['service']}, Method={call_detail['method']}")
                
                chain_info['call_sequence'].append(call_detail)
                chain_info['cross_process_calls'] += 1
                
                # 檢測瓶頸
                if call_detail.get('estimated_latency', 0) > 1000:  # 超過1秒
                    chain_info['bottlenecks'].append({
                        'service': call_detail['service'],
                        'method': call_detail['method'],
                        'latency': call_detail['estimated_latency'],
                        'reason': self._analyze_bottleneck_reason(call_detail)
                    })
        
        # 計算總延遲
        chain_info['total_latency'] = sum(
            call.get('estimated_latency', 0) for call in chain_info['call_sequence']
        )
        
        # 生成建議
        chain_info['recommendation'] = self._generate_binder_recommendation(chain_info)
        
        return chain_info
    
    def _is_binder_call(self, frame: str) -> bool:
        """檢查是否為 Binder 調用"""
        binder_indicators = [
            'BinderProxy', 'Binder.transact', 'IPCThreadState',
            'IInterface', 'AIDL', 'onTransact', 
            '$Stub$Proxy',  # 新增：AIDL 生成的 Proxy 類
            'android.os.Binder',  # 新增：Binder 基類
            'execTransact',  # 新增：Binder 執行事務
            'transactNative',  # 新增：Native 事務方法
        ]
        return any(indicator in frame for indicator in binder_indicators)
    
    def _extract_binder_detail(self, frame: str, context: List[str]) -> Dict:
        """提取 Binder 調用詳情"""
        detail = {
            'frame': frame,
            'service': 'Unknown',
            'method': 'Unknown',
            'transaction_code': None,
            'estimated_latency': 100  # 預設 100ms
        }
        
        # 將 context 合併為一個字串，方便搜尋
        context_str = '\n'.join(context)
        
        # 1. 從介面類別名稱識別服務
        interface_patterns = [
            (r'android\.view\.IWindowManager', 'WindowManagerService'),
            (r'android\.app\.IActivityManager', 'ActivityManagerService'),
            (r'android\.content\.pm\.IPackageManager', 'PackageManagerService'),
            (r'com\.android\.internal\.view\.IInputMethodManager', 'InputMethodManagerService'),
            (r'android\.os\.IPowerManager', 'PowerManagerService'),
            (r'android\.media\.IAudioService', 'AudioService'),
            (r'android\.app\.INotificationManager', 'NotificationManagerService'),
            (r'android\.net\.IConnectivityManager', 'ConnectivityService'),
            (r'android\.content\.IContentProvider', 'ContentProviderService'),
            (r'android\.view\.IWindowSession', 'WindowManagerService'),
            (r'android\.view\.accessibility\.IAccessibilityManager', 'AccessibilityManagerService'),
        ]
        
        for pattern, service_name in interface_patterns:
            if re.search(pattern, context_str):
                detail['service'] = service_name
                # 設定預估延遲
                if service_name in self.binder_services:
                    detail['estimated_latency'] = self.binder_services[service_name]['avg_latency_ms']
                break
        
        # 2. 提取方法名稱
        # 從多種格式中提取方法名
        method_patterns = [
            # IInterface$Stub$Proxy.methodName 格式
            r'(?:I\w+)\$Stub\$Proxy\.(\w+)',
            # 標準方法調用格式
            r'\.(\w+)\([^)]*\)\s*$',
            # 簡單方法名
            r'\.(\w+)$',
        ]
        
        # 首先從當前 frame 提取
        for pattern in method_patterns:
            match = re.search(pattern, frame)
            if match:
                method_name = match.group(1)
                # 過濾掉一些通用方法
                if method_name not in ['transact', 'onTransact', 'transactNative', 'invoke', 'run']:
                    detail['method'] = method_name
                    break
        
        # 如果沒找到，從 context 中查找
        if detail['method'] == 'Unknown':
            for ctx_frame in context:
                for pattern in method_patterns:
                    match = re.search(pattern, ctx_frame)
                    if match:
                        method_name = match.group(1)
                        if method_name not in ['transact', 'onTransact', 'transactNative', 'invoke', 'run']:
                            detail['method'] = method_name
                            break
                if detail['method'] != 'Unknown':
                    break
        
        # 3. 特殊處理某些已知的方法模式
        if detail['service'] == 'Unknown' or detail['method'] == 'Unknown':
            # WindowManager 相關
            if 'getWindowInsets' in context_str:
                detail['service'] = 'WindowManagerService'
                detail['method'] = 'getWindowInsets'
                detail['estimated_latency'] = 50
            elif 'addWindow' in context_str:
                detail['service'] = 'WindowManagerService'
                detail['method'] = 'addWindow'
                detail['estimated_latency'] = 100
            elif 'removeWindow' in context_str:
                detail['service'] = 'WindowManagerService'
                detail['method'] = 'removeWindow'
                detail['estimated_latency'] = 80
            elif 'relayoutWindow' in context_str:
                detail['service'] = 'WindowManagerService'
                detail['method'] = 'relayoutWindow'
                detail['estimated_latency'] = 60
            # ActivityManager 相關
            elif 'startActivity' in context_str:
                detail['service'] = 'ActivityManagerService'
                detail['method'] = 'startActivity'
                detail['estimated_latency'] = 200
            elif 'bindService' in context_str:
                detail['service'] = 'ActivityManagerService'
                detail['method'] = 'bindService'
                detail['estimated_latency'] = 150
            elif 'broadcastIntent' in context_str:
                detail['service'] = 'ActivityManagerService'
                detail['method'] = 'broadcastIntent'
                detail['estimated_latency'] = 100
            # PackageManager 相關
            elif 'getPackageInfo' in context_str:
                detail['service'] = 'PackageManagerService'
                detail['method'] = 'getPackageInfo'
                detail['estimated_latency'] = 200
            elif 'queryIntentActivities' in context_str:
                detail['service'] = 'PackageManagerService'
                detail['method'] = 'queryIntentActivities'
                detail['estimated_latency'] = 300
        
        # 4. 提取事務碼（如果有）
        transaction_match = re.search(r'code[=:\s]+(\d+)', context_str)
        if transaction_match:
            detail['transaction_code'] = int(transaction_match.group(1))
        
        # 5. 如果還是 Unknown，嘗試從類名推測
        if detail['service'] == 'Unknown':
            # 從類路徑推測服務
            class_patterns = [
                (r'com\.android\.server\.wm\.', 'WindowManagerService'),
                (r'com\.android\.server\.am\.', 'ActivityManagerService'),
                (r'com\.android\.server\.pm\.', 'PackageManagerService'),
                (r'com\.android\.server\.input\.', 'InputManagerService'),
                (r'com\.android\.server\.power\.', 'PowerManagerService'),
            ]
            
            for pattern, service_name in class_patterns:
                if re.search(pattern, context_str):
                    detail['service'] = service_name
                    break
        
        return detail
    
    def _analyze_bottleneck_reason(self, call_detail: Dict) -> str:
        """分析瓶頸原因"""
        service = call_detail.get('service', 'Unknown')
        
        if service == 'WindowManagerService':
            return 'WindowManager 可能因為大量窗口操作或動畫導致延遲'
        elif service == 'ActivityManagerService':
            return 'ActivityManager 可能因為進程啟動或服務綁定導致延遲'
        elif service == 'PackageManagerService':
            return 'PackageManager 可能因為包掃描或權限檢查導致延遲'
        
        return '跨進程通信延遲'
    
    def _generate_binder_recommendation(self, chain_info: Dict) -> str:
        """生成 Binder 優化建議"""
        recommendations = []
        
        if chain_info['cross_process_calls'] > 5:
            recommendations.append('減少跨進程調用次數，考慮批量操作')
        
        if chain_info['total_latency'] > 3000:
            recommendations.append('總延遲超過 3 秒，建議使用異步調用')
        
        for bottleneck in chain_info['bottlenecks']:
            if bottleneck['service'] == 'WindowManagerService':
                recommendations.append('優化 UI 更新邏輯，避免頻繁的窗口操作')
            elif bottleneck['service'] == 'PackageManagerService':
                recommendations.append('快取包資訊，避免重複查詢')
        
        return ' | '.join(recommendations) if recommendations else '無特殊優化建議'

class ThreadDependencyAnalyzer:
    """線程依賴關係分析器"""
    
    def __init__(self):
        self.dependency_graph = {}
        self.thread_states = {}
        self.deadlock_cycles = []  # 儲存死鎖循環
    
    def analyze_thread_dependencies(self, threads: List[ThreadInfo]) -> Dict:
        """分析線程間的依賴關係"""
        analysis = {
            'dependency_graph': {},
            'deadlock_cycles': [],
            'blocking_chains': [],
            'critical_paths': [],
            'visualization': ''
        }
        
        # 重置狀態
        self.dependency_graph = {}
        self.thread_states = {}
        self.deadlock_cycles = []
        
        # 建立依賴圖
        for thread in threads:
            self._build_dependency_graph(thread)
        
        # 檢測死鎖循環
        self.deadlock_cycles = self._detect_deadlock_cycles()
        analysis['deadlock_cycles'] = self.deadlock_cycles
        
        # 找出阻塞鏈
        analysis['blocking_chains'] = self._find_blocking_chains()
        
        # 識別關鍵路徑
        analysis['critical_paths'] = self._identify_critical_paths()
        
        # 生成視覺化
        analysis['visualization'] = self._generate_ascii_graph()
        
        analysis['dependency_graph'] = self.dependency_graph
        
        return analysis
    
    def _build_dependency_graph(self, thread: ThreadInfo):
        """建立線程依賴圖"""
        thread_id = thread.tid
        self.thread_states[thread_id] = {
            'name': thread.name,
            'state': thread.state,
            'priority': thread.prio,
            'waiting_on': [],
            'holding': thread.held_locks.copy(),
            'waiting_locks': thread.waiting_locks.copy()
        }
        
        # 解析等待關係
        if thread.waiting_info:
            # 嘗試多種模式提取等待的線程ID
            patterns = [
                r'held by (?:thread\s+)?(\d+)',
                r'held by tid=(\d+)',
                r'heldby=(\d+)',
                r'owner tid=(\d+)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, thread.waiting_info)
                if match:
                    holder_tid = match.group(1)
                    self.thread_states[thread_id]['waiting_on'].append(holder_tid)
                    
                    if holder_tid not in self.dependency_graph:
                        self.dependency_graph[holder_tid] = []
                    self.dependency_graph[holder_tid].append(thread_id)
                    break
        
        # 如果有等待的鎖但沒有明確的持有者信息，嘗試從其他線程找出持有者
        if thread.waiting_locks and not self.thread_states[thread_id]['waiting_on']:
            # 這個線程在等待鎖，標記它
            self.thread_states[thread_id]['is_waiting'] = True
    
    def _detect_deadlock_cycles(self) -> List[List[Dict]]:
        """使用 DFS 檢測死鎖循環"""
        visited = set()
        rec_stack = set()
        cycles = []
        
        def dfs(node, path):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            if node in self.dependency_graph:
                for neighbor in self.dependency_graph[node]:
                    if neighbor not in visited:
                        result = dfs(neighbor, path.copy())
                        if result:
                            cycles.extend(result)
                    elif neighbor in rec_stack:
                        # 找到循環
                        cycle_start = path.index(neighbor)
                        cycle = path[cycle_start:]
                        
                        # 轉換為詳細信息
                        cycle_info = []
                        for tid in cycle:
                            if tid in self.thread_states:
                                info = {
                                    'tid': tid,
                                    'name': self.thread_states[tid]['name'],
                                    'state': self.thread_states[tid]['state'].value,
                                    'waiting_on': self.thread_states[tid]['waiting_on']
                                }
                                cycle_info.append(info)
                        
                        if cycle_info:
                            cycles.append(cycle_info)
            
            rec_stack.remove(node)
            return cycles
        
        for node in self.dependency_graph:
            if node not in visited:
                dfs(node, [])
        
        # 去重
        unique_cycles = []
        for cycle in cycles:
            # 將循環標準化（從最小的tid開始）
            if cycle:
                min_idx = min(range(len(cycle)), key=lambda i: cycle[i]['tid'])
                normalized = cycle[min_idx:] + cycle[:min_idx]
                
                # 檢查是否已存在
                is_duplicate = False
                for existing in unique_cycles:
                    if len(existing) == len(normalized):
                        if all(existing[i]['tid'] == normalized[i]['tid'] for i in range(len(existing))):
                            is_duplicate = True
                            break
                
                if not is_duplicate:
                    unique_cycles.append(normalized)
        
        return unique_cycles
    
    def _find_blocking_chains(self) -> List[Dict]:
        """找出阻塞鏈"""
        chains = []
        
        # 找出所有被阻塞的線程
        blocked_threads = {}
        for tid, deps in self.dependency_graph.items():
            if len(deps) > 0:  # 這個線程阻塞了其他線程
                blocked_threads[tid] = deps
        
        # 分析每個阻塞者
        for blocker_tid, blocked_list in blocked_threads.items():
            if blocker_tid in self.thread_states:
                # 計算被阻塞線程的總優先級
                total_priority = 0
                high_priority_count = 0
                
                for blocked_tid in blocked_list:
                    if blocked_tid in self.thread_states:
                        prio = self.thread_states[blocked_tid].get('priority', 'N/A')
                        if prio != 'N/A' and prio.isdigit():
                            prio_int = int(prio)
                            total_priority += prio_int
                            if prio_int <= 5:  # 高優先級
                                high_priority_count += 1
                
                severity = 'critical' if high_priority_count > 0 else 'high' if len(blocked_list) > 3 else 'medium'
                
                chain = {
                    'blocker': blocker_tid,
                    'blocker_name': self.thread_states[blocker_tid]['name'],
                    'blocked_threads': blocked_list,
                    'impact': len(blocked_list),
                    'severity': severity,
                    'high_priority_blocked': high_priority_count
                }
                chains.append(chain)
        
        return sorted(chains, key=lambda x: (x['high_priority_blocked'], x['impact']), reverse=True)
    
    def _identify_critical_paths(self) -> List[Dict]:
        """識別關鍵路徑"""
        critical_paths = []
        
        # 找出主線程相關的路徑
        main_tid = '1'
        if main_tid in self.thread_states and self.thread_states[main_tid]['waiting_on']:
            path = self._trace_dependency_path(main_tid)
            if len(path) > 1:
                critical_paths.append({
                    'type': 'main_thread_blocked',
                    'path': path,
                    'severity': 'critical',
                    'description': '主線程被阻塞'
                })
        
        # 找出高優先級線程的阻塞路徑
        for tid, state in self.thread_states.items():
            if tid != main_tid and state.get('priority') and state['priority'].isdigit():
                if int(state['priority']) <= 5 and state['waiting_on']:
                    path = self._trace_dependency_path(tid)
                    if len(path) > 1:
                        critical_paths.append({
                            'type': 'high_priority_blocked',
                            'path': path,
                            'severity': 'high',
                            'description': f"高優先級線程 {state['name']} 被阻塞"
                        })
        
        # 找出最長的依賴鏈
        longest_path = []
        for tid in self.thread_states:
            path = self._trace_dependency_path(tid)
            if len(path) > len(longest_path):
                longest_path = path
        
        if len(longest_path) > 3:
            critical_paths.append({
                'type': 'long_dependency_chain',
                'path': longest_path,
                'severity': 'medium',
                'description': f"長依賴鏈 ({len(longest_path)} 層)"
            })
        
        return critical_paths
    
    def _trace_dependency_path(self, start_tid: str) -> List[str]:
        """追蹤依賴路徑"""
        path = []
        current = start_tid
        visited = set()
        
        while current and current not in visited:
            visited.add(current)
            
            if current in self.thread_states:
                thread_info = f"{current}({self.thread_states[current]['name']})"
                path.append(thread_info)
                
                waiting_on = self.thread_states[current]['waiting_on']
                if waiting_on:
                    current = waiting_on[0]
                else:
                    break
            else:
                break
        
        return path
    
    def _generate_ascii_graph(self) -> str:
        """生成 ASCII 依賴關係圖"""
        lines = ["線程依賴關係圖:", "=" * 60]
        
        # 顯示死鎖
        if self.deadlock_cycles:
            lines.append("\n🔴 死鎖檢測:")
            for i, cycle in enumerate(self.deadlock_cycles, 1):
                lines.append(f"\n  死鎖循環 {i}:")
                
                # 顯示循環
                cycle_str = ""
                for j, thread_info in enumerate(cycle):
                    cycle_str += f"{thread_info['tid']}({thread_info['name']})"
                    if j < len(cycle) - 1:
                        cycle_str += " → "
                    else:
                        cycle_str += f" → {cycle[0]['tid']}({cycle[0]['name']})"
                
                lines.append(f"    {cycle_str}")
                
                # 顯示詳細信息
                for thread_info in cycle:
                    lines.append(f"    • 線程 {thread_info['tid']} ({thread_info['name']}) - {thread_info['state']}")
        else:
            lines.append("\n✅ 未檢測到死鎖")
        
        # 顯示阻塞鏈
        blocking_chains = self._find_blocking_chains()
        if blocking_chains:
            lines.append("\n🟡 主要阻塞鏈:")
            for chain in blocking_chains[:5]:  # 只顯示前5個
                lines.append(f"\n  • {chain['blocker']}({chain['blocker_name']}) 阻塞了 {chain['impact']} 個線程")
                if chain['high_priority_blocked'] > 0:
                    lines.append(f"    ⚠️ 包含 {chain['high_priority_blocked']} 個高優先級線程")
                
                # 顯示被阻塞的線程
                blocked_names = []
                for blocked_tid in chain['blocked_threads'][:3]:  # 只顯示前3個
                    if blocked_tid in self.thread_states:
                        blocked_names.append(f"{blocked_tid}({self.thread_states[blocked_tid]['name']})")
                
                if blocked_names:
                    lines.append(f"    被阻塞: {', '.join(blocked_names)}")
                    if len(chain['blocked_threads']) > 3:
                        lines.append(f"    ... 還有 {len(chain['blocked_threads']) - 3} 個線程")
        
        # 顯示關鍵路徑
        critical_paths = self._identify_critical_paths()
        if critical_paths:
            lines.append("\n🔵 關鍵路徑:")
            for path_info in critical_paths[:3]:
                lines.append(f"\n  • {path_info['description']}:")
                path_str = " → ".join(path_info['path'][:5])
                if len(path_info['path']) > 5:
                    path_str += f" → ... ({len(path_info['path'])-5} more)"
                lines.append(f"    {path_str}")
                lines.append(f"    嚴重性: {path_info['severity']}")
        
        # 如果什麼都沒有，顯示基本統計
        if not self.deadlock_cycles and not blocking_chains and not critical_paths:
            lines.append("\n📊 線程統計:")
            
            # 統計等待中的線程
            waiting_count = sum(1 for state in self.thread_states.values() 
                              if state['waiting_on'] or state.get('is_waiting'))
            
            lines.append(f"  • 總線程數: {len(self.thread_states)}")
            lines.append(f"  • 等待中的線程: {waiting_count}")
            
            if self.dependency_graph:
                lines.append(f"  • 存在依賴關係的線程: {len(self.dependency_graph)}")
        
        return "\n".join(lines)
    
class PerformanceBottleneckDetector:
    """性能瓶頸檢測器"""
    
    def __init__(self):
        self.bottleneck_thresholds = {
            'cpu_usage': 80,  # CPU 使用率閾值
            'memory_available_mb': 100,  # 可用記憶體閾值
            'thread_count': 150,  # 線程數閾值
            'blocked_threads': 5,  # 阻塞線程數閾值
            'gc_pause_ms': 500,  # GC 暫停時間閾值
            'binder_calls': 10,  # Binder 調用數閾值
            'lock_contention': 3,  # 鎖競爭閾值
        }
        
        self.bottleneck_scores = {
            'critical': 90,
            'high': 70,
            'medium': 50,
            'low': 30
        }
    
    def detect_bottlenecks(self, anr_info: ANRInfo, content: str) -> Dict:
        """檢測性能瓶頸"""
        bottlenecks = {
            'cpu_bottlenecks': self._detect_cpu_bottlenecks(anr_info),
            'memory_bottlenecks': self._detect_memory_bottlenecks(anr_info),
            'thread_bottlenecks': self._detect_thread_bottlenecks(anr_info),
            'io_bottlenecks': self._detect_io_bottlenecks(anr_info, content),
            'lock_bottlenecks': self._detect_lock_bottlenecks(anr_info),
            'gc_bottlenecks': self._detect_gc_bottlenecks(content),
            'overall_score': 0,
            'top_issues': [],
            'recommendations': []
        }
        
        # 計算整體分數
        bottlenecks['overall_score'] = self._calculate_overall_score(bottlenecks)
        
        # 識別主要問題
        bottlenecks['top_issues'] = self._identify_top_issues(bottlenecks)
        
        # 生成建議
        bottlenecks['recommendations'] = self._generate_recommendations(bottlenecks)
        
        return bottlenecks
    
    def _detect_cpu_bottlenecks(self, anr_info: ANRInfo) -> List[Dict]:
        """檢測 CPU 瓶頸"""
        bottlenecks = []
        
        if anr_info.cpu_usage:
            total_cpu = anr_info.cpu_usage.get('total', 0)
            
            if total_cpu > self.bottleneck_thresholds['cpu_usage']:
                bottlenecks.append({
                    'type': 'high_cpu_usage',
                    'severity': 'critical' if total_cpu > 95 else 'high',
                    'value': total_cpu,
                    'description': f'CPU 使用率過高: {total_cpu:.1f}%',
                    'impact': '系統響應緩慢，可能導致 ANR',
                    'solutions': [
                        '檢查是否有無限循環或過度計算',
                        '使用 CPU Profiler 分析熱點函數',
                        '考慮將計算密集型任務移至背景線程',
                        '優化算法複雜度'
                    ]
                })
            
            # 檢查 load average
            load_1min = anr_info.cpu_usage.get('load_1min', 0)
            if load_1min > 4.0:
                bottlenecks.append({
                    'type': 'high_load_average',
                    'severity': 'high',
                    'value': load_1min,
                    'description': f'系統負載過高: {load_1min}',
                    'impact': '系統調度延遲增加',
                    'solutions': [
                        '減少並發任務數量',
                        '優化線程池大小',
                        '檢查是否有失控的進程'
                    ]
                })
        
        return bottlenecks
    
    def _detect_memory_bottlenecks(self, anr_info: ANRInfo) -> List[Dict]:
        """檢測記憶體瓶頸"""
        bottlenecks = []
        
        if anr_info.memory_info:
            available_mb = anr_info.memory_info.get('available', float('inf')) / 1024
            
            if available_mb < self.bottleneck_thresholds['memory_available_mb']:
                severity = 'critical' if available_mb < 50 else 'high'
                bottlenecks.append({
                    'type': 'low_memory',
                    'severity': severity,
                    'value': available_mb,
                    'description': f'可用記憶體不足: {available_mb:.1f} MB',
                    'impact': '頻繁 GC，應用可能被系統殺死',
                    'solutions': [
                        '優化記憶體使用，釋放不必要的資源',
                        '使用 Memory Profiler 查找記憶體洩漏',
                        '實施圖片和資源的快取策略',
                        '考慮使用 largeHeap 選項'
                    ]
                })
            
            # 檢查記憶體使用率
            used_percent = anr_info.memory_info.get('used_percent', 0)
            if used_percent > 85:
                bottlenecks.append({
                    'type': 'high_memory_usage',
                    'severity': 'medium',
                    'value': used_percent,
                    'description': f'記憶體使用率高: {used_percent:.1f}%',
                    'impact': '系統可能開始回收背景應用',
                    'solutions': [
                        '檢查大對象分配',
                        '優化數據結構',
                        '使用弱引用或軟引用'
                    ]
                })
        
        return bottlenecks
    
    def _detect_thread_bottlenecks(self, anr_info: ANRInfo) -> List[Dict]:
        """檢測線程瓶頸"""
        bottlenecks = []
        
        thread_count = len(anr_info.all_threads)
        if thread_count > self.bottleneck_thresholds['thread_count']:
            bottlenecks.append({
                'type': 'excessive_threads',
                'severity': 'high' if thread_count > 200 else 'medium',
                'value': thread_count,
                'description': f'線程數過多: {thread_count} 個',
                'impact': '線程調度開銷大，記憶體消耗高',
                'solutions': [
                    '使用線程池而非創建新線程',
                    '檢查是否有線程洩漏',
                    '合併相似任務到同一線程',
                    '使用 Kotlin 協程減少線程使用'
                ]
            })
        
        # 檢測阻塞線程
        blocked_threads = [t for t in anr_info.all_threads if t.state == ThreadState.BLOCKED]
        if len(blocked_threads) > self.bottleneck_thresholds['blocked_threads']:
            bottlenecks.append({
                'type': 'thread_contention',
                'severity': 'critical' if len(blocked_threads) > 10 else 'high',
                'value': len(blocked_threads),
                'description': f'{len(blocked_threads)} 個線程處於阻塞狀態',
                'impact': '嚴重的線程競爭，可能存在死鎖',
                'solutions': [
                    '優化鎖的粒度',
                    '使用無鎖數據結構',
                    '避免嵌套鎖',
                    '使用讀寫鎖替代互斥鎖'
                ]
            })
        
        # 檢測主線程問題
        if anr_info.main_thread and anr_info.main_thread.state == ThreadState.BLOCKED:
            bottlenecks.append({
                'type': 'main_thread_blocked',
                'severity': 'critical',
                'value': 1,
                'description': '主線程被阻塞',
                'impact': '直接導致 ANR',
                'solutions': [
                    '立即將阻塞操作移至背景線程',
                    '使用 Handler 或 AsyncTask',
                    '檢查主線程的同步操作'
                ]
            })
        
        return bottlenecks
    
    def _detect_io_bottlenecks(self, anr_info: ANRInfo, content: str) -> List[Dict]:
        """檢測 I/O 瓶頸"""
        bottlenecks = []
        
        # 檢查主線程 I/O
        if anr_info.main_thread:
            io_operations = []
            for frame in anr_info.main_thread.backtrace[:10]:
                if any(io in frame for io in ['File', 'SQLite', 'SharedPreferences', 'Socket']):
                    io_operations.append(frame)
            
            if io_operations:
                bottlenecks.append({
                    'type': 'main_thread_io',
                    'severity': 'critical',
                    'value': len(io_operations),
                    'description': f'主線程執行 I/O 操作',
                    'impact': '阻塞 UI 響應',
                    'operations': io_operations[:3],  # 顯示前3個
                    'solutions': [
                        '使用異步 I/O API',
                        '將檔案操作移至 WorkManager',
                        'SharedPreferences 使用 apply() 而非 commit()',
                        '使用 Room 的異步查詢'
                    ]
                })
        
        # 檢查過多的 Binder IPC
        binder_count = content.count('BinderProxy')
        if binder_count > self.bottleneck_thresholds['binder_calls']:
            bottlenecks.append({
                'type': 'excessive_binder_calls',
                'severity': 'high',
                'value': binder_count,
                'description': f'過多的 Binder IPC 調用: {binder_count} 次',
                'impact': '跨進程通信開銷大',
                'solutions': [
                    '批量處理系統服務調用',
                    '快取服務查詢結果',
                    '使用本地廣播替代系統廣播',
                    '減少跨進程通信頻率'
                ]
            })
        
        return bottlenecks
    
    def _detect_lock_bottlenecks(self, anr_info: ANRInfo) -> List[Dict]:
        """檢測鎖瓶頸"""
        bottlenecks = []
        
        # 統計等待鎖的線程
        waiting_threads = [t for t in anr_info.all_threads if t.waiting_locks]
        
        if len(waiting_threads) > self.bottleneck_thresholds['lock_contention']:
            # 分析鎖的持有情況
            lock_holders = {}
            for thread in anr_info.all_threads:
                for lock in thread.held_locks:
                    if lock not in lock_holders:
                        lock_holders[lock] = []
                    lock_holders[lock].append(thread)
            
            bottlenecks.append({
                'type': 'lock_contention',
                'severity': 'high',
                'value': len(waiting_threads),
                'description': f'{len(waiting_threads)} 個線程在等待鎖',
                'impact': '並發性能差，可能導致死鎖',
                'lock_analysis': {
                    'total_waiting': len(waiting_threads),
                    'unique_locks': len(lock_holders),
                    'hot_locks': [lock for lock, holders in lock_holders.items() if len(holders) > 1]
                },
                'solutions': [
                    '減小同步塊的範圍',
                    '使用細粒度鎖',
                    '考慮使用 ConcurrentHashMap 等併發集合',
                    '使用讀寫鎖分離讀寫操作'
                ]
            })
        
        return bottlenecks
    
    def _detect_gc_bottlenecks(self, content: str) -> List[Dict]:
        """檢測 GC 瓶頸"""
        bottlenecks = []
        
        # 解析 GC 暫停時間
        gc_pauses = re.findall(r'paused\s+(\d+)ms', content)
        if gc_pauses:
            total_pause = sum(int(pause) for pause in gc_pauses)
            max_pause = max(int(pause) for pause in gc_pauses)
            
            if total_pause > self.bottleneck_thresholds['gc_pause_ms']:
                bottlenecks.append({
                    'type': 'excessive_gc',
                    'severity': 'high' if total_pause > 1000 else 'medium',
                    'value': total_pause,
                    'description': f'GC 暫停時間過長: 總計 {total_pause}ms, 最大 {max_pause}ms',
                    'impact': 'UI 卡頓，響應延遲',
                    'gc_stats': {
                        'count': len(gc_pauses),
                        'total_pause': total_pause,
                        'max_pause': max_pause,
                        'avg_pause': total_pause // len(gc_pauses) if gc_pauses else 0
                    },
                    'solutions': [
                        '減少對象分配，特別是大對象',
                        '使用對象池重用對象',
                        '避免在循環中創建對象',
                        '優化 Bitmap 使用和回收'
                    ]
                })
        
        return bottlenecks
    
    def _calculate_overall_score(self, bottlenecks: Dict) -> int:
        """計算整體瓶頸分數"""
        score = 100
        
        # 根據各類瓶頸扣分
        for category, issues in bottlenecks.items():
            if isinstance(issues, list):
                for issue in issues:
                    severity = issue.get('severity', 'low')
                    if severity == 'critical':
                        score -= 30
                    elif severity == 'high':
                        score -= 20
                    elif severity == 'medium':
                        score -= 10
                    else:
                        score -= 5
        
        return max(0, score)
    
    def _identify_top_issues(self, bottlenecks: Dict) -> List[Dict]:
        """識別最主要的問題"""
        all_issues = []
        
        for category, issues in bottlenecks.items():
            if isinstance(issues, list):
                for issue in issues:
                    issue['category'] = category
                    all_issues.append(issue)
        
        # 按嚴重性排序
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        all_issues.sort(key=lambda x: severity_order.get(x.get('severity', 'low'), 3))
        
        return all_issues[:5]  # 返回前5個最嚴重的問題
    
    def _generate_recommendations(self, bottlenecks: Dict) -> List[str]:
        """生成優化建議"""
        recommendations = []
        
        # 基於整體分數
        score = bottlenecks['overall_score']
        if score < 30:
            recommendations.append('🚨 系統存在嚴重性能問題，需要立即優化')
        elif score < 60:
            recommendations.append('⚠️ 系統性能不佳，建議進行全面優化')
        elif score < 80:
            recommendations.append('💡 系統有優化空間，建議針對性改進')
        else:
            recommendations.append('✅ 系統性能良好，繼續保持')
        
        # 基於具體問題
        top_issues = bottlenecks.get('top_issues', [])
        if any(issue['type'] == 'main_thread_blocked' for issue in top_issues):
            recommendations.insert(0, '🔴 首要任務：解決主線程阻塞問題')
        
        if any(issue['type'] == 'excessive_gc' for issue in top_issues):
            recommendations.append('♻️ 優先優化記憶體分配策略')
        
        if any(issue['type'] == 'thread_contention' for issue in top_issues):
            recommendations.append('🔒 重點關注多線程同步問題')
        
        return recommendations
    