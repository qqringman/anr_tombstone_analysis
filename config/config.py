import os

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

# 更新 MODEL_LIMITS 以包含正確的速率限制
MODEL_LIMITS = {
    # Claude 4 系列
    'claude-opus-4-20250514': {
        'max_tokens': 200000,  # 200K context window
        'max_output_tokens': 16000,  # 根據 OTPM 限制設置
        'chars_per_token': 2.5,
        'rate_limits': {
            'rpm': 1000,      # 每分鐘請求數
            'itpm': 40000,    # 每分鐘輸入 tokens
            'otpm': 16000     # 每分鐘輸出 tokens
        },
        'name': 'Claude 4 Opus',
        'description': '最強大的模型，適合複雜分析'
    },
    'claude-sonnet-4-20250514': {
        'max_tokens': 200000,
        'max_output_tokens': 16000,
        'chars_per_token': 2.5,
        'rate_limits': {
            'rpm': 1000,
            'itpm': 40000,
            'otpm': 16000
        },
        'name': 'Claude 4 Sonnet',
        'description': '平衡效能與成本，推薦使用'
    },
    
    # Claude 3.5 系列
    'claude-3-5-sonnet-20241022': {
        'max_tokens': 200000,
        'max_output_tokens': 8192,  # 實際限制可能更低，根據 OTPM
        'chars_per_token': 2.5,
        'rate_limits': {
            'rpm': 1000,
            'itpm': 80000,    # 帶星號，可能變動
            'otpm': 16000
        },
        'name': 'Claude 3.5 Sonnet',
        'description': '快速準確，適合大部分場景'
    },
    'claude-3-5-haiku-20241022': {
        'max_tokens': 200000,
        'max_output_tokens': 8192,
        'chars_per_token': 2.5,
        'rate_limits': {
            'rpm': 1000,
            'itpm': 100000,   # 帶星號，可能變動
            'otpm': 20000
        },
        'name': 'Claude 3.5 Haiku',
        'description': '輕量快速，簡單分析'
    },
    
    # Claude 3 系列
    'claude-3-opus-20240229': {
        'max_tokens': 200000,
        'max_output_tokens': 4096,
        'chars_per_token': 2.5,
        'rate_limits': {
            'rpm': 1000,
            'itpm': 40000,    # 帶星號，可能變動
            'otpm': 8000
        },
        'name': 'Claude 3 Opus',
        'description': '深度分析，較慢但詳細'
    },
    'claude-3-haiku-20240307': {
        'max_tokens': 200000,
        'max_output_tokens': 4096,
        'chars_per_token': 2.5,
        'rate_limits': {
            'rpm': 1000,
            'itpm': 100000,   # 帶星號，可能變動
            'otpm': 20000
        },
        'name': 'Claude 3 Haiku',
        'description': '經濟實惠，基本分析'
    }
}

# 更新默認模型為 Claude 4 Sonnet
DEFAULT_MODEL = 'claude-sonnet-4-20250514'