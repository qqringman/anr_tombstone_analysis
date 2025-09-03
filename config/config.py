import os

# Claude API 配置 - 請設置環境變數或直接填入
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')  # 從環境變數讀取

# 新增 Realtek API 配置
REALTEK_API_KEY = os.environ.get('REALTEK_API_KEY', '')  # 從環境變數讀取
REALTEK_BASE_URL = os.environ.get('REALTEK_BASE_URL', 'https://devops.realtek.com/realgpt-api/openai-compatible/v1')

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

# 更新 MODEL_LIMITS 以包含 Realtek 模型
MODEL_LIMITS = {
    # Claude 4 系列（新增）
    'claude-opus-4': {
        'max_tokens': 200000,
        'max_output_tokens': 16000,
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
        'max_output_tokens': 16000,
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
        'max_output_tokens': 16000,
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
        'max_output_tokens': 20000,
        'chars_per_token': 4,
        'name': 'Claude 3 Haiku',
        'description': '即時回應，成本最低'
    },
    
    # Realtek 模型系列（只保留 2 個）
    'chat-chattek-qwen': {
        'max_tokens': 256000,  # 256K 模型
        'max_output_tokens': 8000,
        'chars_per_token': 2.5,  # 中文模型，調整比率
        'name': 'Chattek Qwen',
        'description': 'Realtek 內部 Qwen 模型，適合中文對話分析'
    },
    'chat-chattek-gpt': {
        'max_tokens': 128000,  # 128K 模型
        'max_output_tokens': 8000,
        'chars_per_token': 3,
        'name': 'Chattek GPT',
        'description': 'Realtek 內部 GPT 模型，適合程式碼分析'
    }
}

# 更新系統預設為 Realtek Chattek Qwen
DEFAULT_PROVIDER = 'realtek'
DEFAULT_MODEL = 'chat-chattek-qwen'

# AI Provider 配置 - 新增 Realtek
AI_PROVIDERS = {
    'anthropic': {
        'api_key': os.environ.get('ANTHROPIC_API_KEY', CLAUDE_API_KEY),
        'models': {k: v for k, v in MODEL_LIMITS.items() if k.startswith('claude')},
        'default_model': 'claude-sonnet-4-20250514'
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
    },
    'realtek': {
        'api_key': REALTEK_API_KEY,
        'base_url': REALTEK_BASE_URL,
        'models': {k: v for k, v in MODEL_LIMITS.items() if k.startswith('chat-chattek')},  # 只包含 chattek 模型
        'default_model': 'chat-chattek-qwen'  # 預設為 qwen 模型
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

# Token 計費配置（參考官網）- 新增 Realtek 定價
TOKEN_PRICING = {
    'anthropic': {
        'claude-opus-4-20250514': {'input': 0.015, 'output': 0.075},
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
    },
    'realtek': {
        'chat-chattek-qwen': {'input': 0.001, 'output': 0.002},  # 256K 模型，稍高定價
        'chat-chattek-gpt': {'input': 0.0015, 'output': 0.003}   # 128K GPT 模型
    }
}

# Rate Limits 配置 - 新增 Realtek 限制
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
    },
    'realtek': {
        'default': {'rpm': 1000, 'tpm': 100000, 'tpd': 2000000}  # 內部 API，假設較寬鬆限制
    }
}