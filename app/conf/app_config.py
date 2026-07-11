# 日志配置
from dataclasses import dataclass
import os
from pathlib import Path

from omegaconf import OmegaConf

@dataclass
class File:
    enable: bool
    level: str
    path: str
    rotation: str
    retention: str

@dataclass
class Console:
    enable: bool
    level: str

@dataclass
class LoggingConfig:
    file: File
    console: Console

# 数据库配置
@dataclass
class DBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

@dataclass
class QdrantConfig:
    host: str
    port: int
    embedding_size: int

@dataclass
class EmbeddingConfig:
    host: str
    port: int
    model: str

@dataclass
class ESConfig:
    host: str
    port: int
    index_name: str

@dataclass
class LLMConfig:
    model_name: str
    base_url: str
    api_key: str = ""

@dataclass
class AppConfig:
    logging: LoggingConfig
    db_meta: DBConfig
    db_dw: DBConfig
    qdrant: QdrantConfig
    embedding: EmbeddingConfig
    es: ESConfig
    llm: LLMConfig
# 1. 构建配置文件路径：向上两级目录 + 'conf/app_config.yaml
config_file = Path(__file__).parents[2] / 'conf' / 'app_config.yaml'
# 2. 加载 yml 文件内容
context = OmegaConf.load(config_file)
# 3. 根据 dataclass 生成结构化 schema （带类型约束）
schema = OmegaConf.structured(AppConfig)
# 4. 合并 schema 和配置内容，转为 python 对象
app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))
app_config.llm.api_key = os.getenv("OPENAI_API_KEY", "").strip()
