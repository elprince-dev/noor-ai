/**
 * Shared configuration constants for the Noor AI infrastructure.
 * Centralised here so values are defined once and reused across stacks.
 */

/** Prefix for all stack IDs / CloudFormation stack names. */
export const APP_PREFIX = 'NoorAi';

/**
 * Bedrock model used by the API Lambda.
 * Cross-region inference profile (current Claude models require a profile,
 * not an on-demand foundation-model ID).
 */
export const BEDROCK_MODEL_ID = 'us.anthropic.claude-haiku-4-5-20251001-v1:0';

/** Region where Bedrock is invoked (Claude availability). */
export const BEDROCK_REGION = 'us-east-1';

/** DynamoDB chat history table name. */
export const CHAT_TABLE_NAME = 'noor-ai-chat-history';

/** Embedding model for the Knowledge Base (multilingual: Arabic + English). */
export const EMBEDDING_MODEL_ID = 'cohere.embed-multilingual-v3';

/** Cohere Embed Multilingual v3 output dimensionality. */
export const EMBEDDING_DIMENSION = 1024;

/** S3 Vectors index name. */
export const VECTOR_INDEX_NAME = 'noor-ai-corpus-index';
