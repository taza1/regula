"""Configuration management for the research system."""

from typing import Optional, List
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class AzureConfig(BaseSettings):
    """Azure service configuration."""
    
    # Authentication
    tenant_id: str = Field(default="", description="Azure AD tenant ID")
    subscription_id: str = Field(default="", description="Azure subscription ID")
    
    # Cosmos DB
    cosmos_endpoint: str = Field(default="https://research-cosmos.documents.azure.com:443/", 
                                  description="Cosmos DB endpoint")
    cosmos_db_name: str = Field(default="research_db", description="Cosmos DB database name")
    cosmos_container_name: str = Field(default="documents", description="Cosmos DB container name")
    cosmos_key: Optional[str] = Field(default=None, description="Cosmos DB account key (if not using MSI)")
    
    # Blob Storage
    blob_storage_account: str = Field(default="researchstorage", description="Blob storage account name")
    blob_container_evidence: str = Field(default="evidence", description="Evidence container name")
    blob_container_artifacts: str = Field(default="artifacts", description="Artifacts container name")
    
    # Azure AI Search
    search_service_name: str = Field(default="research-search", description="AI Search service name")
    search_index_name: str = Field(default="evidence-index", description="Search index name")
    
    # Service Bus
    service_bus_namespace: str = Field(default="research-bus", description="Service Bus namespace")
    service_bus_queue: str = Field(default="research-tasks", description="Service Bus queue name")
    
    # Application Insights
    app_insights_key: Optional[str] = Field(default=None, description="Application Insights key")
    
    # Key Vault
    key_vault_url: str = Field(default="https://research-vault.vault.azure.net/", 
                               description="Key Vault URL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


class ModelConfig(BaseSettings):
    """LLM and model configuration."""
    
    # OpenAI configuration
    openai_api_version: str = Field(default="2023-12-01-preview", description="OpenAI API version")
    openai_deployment_id: str = Field(default="research-gpt4", description="OpenAI deployment ID")
    openai_model: str = Field(default="gpt-4-turbo", description="OpenAI model name")
    openai_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    openai_max_tokens: int = Field(default=4096, ge=1, le=8192)
    
    # Embedding configuration
    embedding_model: str = Field(default="text-embedding-3-small", description="Embedding model name")
    embedding_dimensions: int = Field(default=1536, description="Embedding dimensions")
    embedding_batch_size: int = Field(default=16, description="Batch size for embeddings")
    
    # Search configuration
    search_result_limit: int = Field(default=20, description="Max search results per query")
    search_min_score: float = Field(default=0.5, description="Minimum relevance score")
    hybrid_search_weight_keyword: float = Field(default=0.6, description="Keyword search weight")
    hybrid_search_weight_semantic: float = Field(default=0.4, description="Semantic search weight")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


class ResearchConfig(BaseSettings):
    """Research system configuration."""
    
    # Project settings
    max_concurrent_runs: int = Field(default=5, description="Max concurrent research runs")
    max_run_duration_seconds: int = Field(default=3600, description="Max run duration")
    max_budget_usd: float = Field(default=100.0, description="Default max budget in USD")
    
    # Source discovery limits
    max_sources_per_query: int = Field(default=50, description="Max sources per search query")
    max_total_sources: int = Field(default=100, description="Max total sources per run")
    max_crawl_depth: int = Field(default=3, description="Max crawl depth for web pages")
    crawl_rate_limit_per_domain: int = Field(default=5, description="Requests per domain per minute")
    
    # Revision limits
    max_revisions: int = Field(default=3, description="Max synthesis revisions")
    max_review_iterations: int = Field(default=2, description="Max review iterations")
    
    # Evidence requirements
    require_peer_review: bool = Field(default=True, description="Require peer-reviewed sources")
    min_independence_groups: int = Field(default=2, description="Min independent source origins")
    require_publication_date: bool = Field(default=True, description="Require published date")
    
    # Approval settings
    require_human_approval: bool = Field(default=True, description="Require human approval before release")
    require_separate_publisher: bool = Field(default=True, description="Require different user as publisher")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


class APIConfig(BaseSettings):
    """API server configuration."""
    
    host: str = Field(default="0.0.0.0", description="API server host")
    port: int = Field(default=8000, description="API server port")
    api_version: str = Field(default="1.0", description="API version")
    enable_docs: bool = Field(default=True, description="Enable OpenAPI docs")
    
    # CORS
    cors_origins: List[str] = Field(default=["http://localhost:3000"], description="CORS allowed origins")
    cors_credentials: bool = Field(default=True, description="Allow credentials in CORS")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_azure_config() -> AzureConfig:
    """Get cached Azure configuration."""
    return AzureConfig()


@lru_cache()
def get_model_config() -> ModelConfig:
    """Get cached model configuration."""
    return ModelConfig()


@lru_cache()
def get_research_config() -> ResearchConfig:
    """Get cached research configuration."""
    return ResearchConfig()


@lru_cache()
def get_api_config() -> APIConfig:
    """Get cached API configuration."""
    return APIConfig()
