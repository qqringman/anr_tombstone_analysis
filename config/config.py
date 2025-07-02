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
    'RETRY_DELAY': 30,  # 減少重試延遲
    'MAX_RETRIES': 3,
    'PARALLEL_SEGMENTS': 2,  # 新增：並行處理段數
}

# 更新 MODEL_LIMITS 以包含正確的速率限制
MODEL_LIMITS = {
    # Claude 4 系列（新增）
    'claude-opus-4': {
        'max_tokens': 200000,
        'max_output_tokens': 16000,  # 根據 OTPM 限制
        'chars_per_token': 4,
        'name': 'Claude Opus 4',
        'description': '最新最強大的模型'
    },
    'claude-sonnet-4': {
        'max_tokens': 200000,
        'max_output_tokens': 16000,
        'chars_per_token': 4,
        'name': 'Claude Sonnet 4',
        'description': '新一代平衡型模型'
    },
    
    # Claude 3.5 系列
    'claude-3-5-sonnet-20241022': {
        'max_tokens': 200000,
        'max_output_tokens': 16000,  # 根據表格
        'chars_per_token': 4,
        'name': 'Claude Sonnet 3.5',
        'description': '最新版本，智能度高'
    },
    'claude-3-5-haiku-20241022': {
        'max_tokens': 200000,
        'max_output_tokens': 16000,
        'chars_per_token': 4,
        'name': 'Claude Haiku 3.5',
        'description': '快速且成本效益高'
    },
    
    # Claude 3 系列
    'claude-3-opus-20240229': {
        'max_tokens': 200000,
        'max_output_tokens': 16000,  # 更新為 16K
        'chars_per_token': 4,
        'name': 'Claude 3 Opus',
        'description': '強大的推理能力'
    },
    'claude-3-sonnet-20240229': {
        'max_tokens': 200000,
        'max_output_tokens': 16000,
        'chars_per_token': 4,
        'name': 'Claude 3 Sonnet',
        'description': '平衡的性能'
    },
    'claude-3-haiku-20240307': {
        'max_tokens': 200000,
        'max_output_tokens': 20000,  # Tier 4 為 20K
        'chars_per_token': 4,
        'name': 'Claude 3 Haiku',
        'description': '即時回應，成本最低'
    }
}

# 更新默認模型為 Claude 4 Sonnet
DEFAULT_MODEL = 'claude-sonnet-4-20250514'

# AI Provider 配置
AI_PROVIDERS = {
    'anthropic': {
        'api_key': os.environ.get('ANTHROPIC_API_KEY', CLAUDE_API_KEY),
        'models': MODEL_LIMITS,  # 使用現有的 MODEL_LIMITS
        'default_model': DEFAULT_MODEL
    },
    'openai': {
        'api_key': os.environ.get('OPENAI_API_KEY', ''),
        'models': {
            'gpt-4-turbo-preview': {
                'max_tokens': 128000,
                'max_output_tokens': 4096,
                'chars_per_token': 2.5,
                'name': 'GPT-4 Turbo',
                'description': '最新的 GPT-4 模型，支援 128K context'
            },
            'gpt-4': {
                'max_tokens': 8192,
                'max_output_tokens': 4096,
                'chars_per_token': 2.5,
                'name': 'GPT-4',
                'description': '強大的推理能力'
            },
            'gpt-3.5-turbo': {
                'max_tokens': 16384,
                'max_output_tokens': 4096,
                'chars_per_token': 2.5,
                'name': 'GPT-3.5 Turbo',
                'description': '快速且經濟的選擇'
            }
        },
        'default_model': 'gpt-4-turbo-preview'
    }
}

# 分析模式配置
ANALYSIS_MODES = {
    'smart': {
        'name': '智能分析',
        'description': '自動選擇最佳策略',
        'max_wait_time': 60,  # 秒
        'priority': 'balanced'
    },
    'quick': {
        'name': '快速分析',
        'description': '30秒內獲得結果',
        'max_wait_time': 30,
        'priority': 'speed'
    },
    'deep': {
        'name': '深度分析',
        'description': '詳細深入的分析',
        'max_wait_time': 180,
        'priority': 'quality'
    }
}

# Token 計費配置（參考官網）
TOKEN_PRICING = {
    'anthropic': {
        'claude-opus-4-20250514': {'input': 0.015, 'output': 0.075},  # per 1K tokens
        'claude-sonnet-4-20250514': {'input': 0.003, 'output': 0.015},
        'claude-3-5-sonnet-20241022': {'input': 0.003, 'output': 0.015},
        'claude-3-5-haiku-20241022': {'input': 0.0008, 'output': 0.004},
        'claude-3-opus-20240229': {'input': 0.015, 'output': 0.075},
        'claude-3-haiku-20240307': {'input': 0.00025, 'output': 0.00125}
    },
    'openai': {
        'gpt-4-turbo-preview': {'input': 0.01, 'output': 0.03},
        'gpt-4': {'input': 0.03, 'output': 0.06},
        'gpt-3.5-turbo': {'input': 0.001, 'output': 0.002}
    }
}

# Rate Limits 配置
RATE_LIMITS = {
    'anthropic': {
        'tier1': {'rpm': 50, 'tpm': 50000, 'tpd': 1000000},
        'tier2': {'rpm': 1000, 'tpm': 100000, 'tpd': 2500000},
        'tier3': {'rpm': 2000, 'tpm': 200000, 'tpd': 5000000},
        'tier4': {'rpm': 4000, 'tpm': 400000, 'tpd': 10000000}
    },
    'openai': {
        'tier1': {'rpm': 500, 'tpm': 60000, 'tpd': 1000000},
        'tier2': {'rpm': 5000, 'tpm': 80000, 'tpd': 2000000}
    }
}