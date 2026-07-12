import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import { Construct } from 'constructs';
import {
  APP_PREFIX,
  BEDROCK_REGION,
  EMBEDDING_MODEL_ID,
  EMBEDDING_DIMENSION,
  VECTOR_INDEX_NAME,
} from './config';

/**
 * RAG storage + retrieval layer. Owns the corpus S3 bucket, the S3 Vectors
 * index, and the Bedrock Knowledge Base that embeds (Cohere Multilingual v3)
 * and indexes the Quran + Bukhari corpus. Stateless compute (Api stack)
 * queries this via the bedrock-agent-runtime Retrieve API.
 */
export class KnowledgeBaseStack extends cdk.Stack {
  /** Knowledge Base ID — consumed by the Api Lambda (Retrieve) and sync.py. */
  public readonly knowledgeBaseId: string;
  /** Data source ID — consumed by sync.py to trigger ingestion jobs. */
  public readonly dataSourceId: string;
  /** Corpus bucket — sync.py uploads ingest/data/corpus/ here. */
  public readonly corpusBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ─── Corpus data-source bucket (empty; sync.py populates it) ───────────
    // Not using BucketDeployment: 27k files is too many for the Lambda-based
    // asset uploader. sync.py does a bulk aws s3 sync instead.
    this.corpusBucket = new s3.Bucket(this, 'CorpusBucket', {
      bucketName: `${APP_PREFIX.toLowerCase()}-corpus-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY, // portfolio project; recreate freely
      autoDeleteObjects: true,
    });

    // ─── S3 Vectors: vector bucket + index ─────────────────────────────────
    // Cohere Embed Multilingual v3 => 1024 dims, cosine distance.
    const vectorBucket = new s3vectors.CfnVectorBucket(this, 'VectorBucket', {
      vectorBucketName: `${APP_PREFIX.toLowerCase()}-vectors-${this.account}`,
    });

    const vectorIndex = new s3vectors.CfnIndex(this, 'VectorIndex', {
      vectorBucketName: vectorBucket.vectorBucketName!,
      indexName: VECTOR_INDEX_NAME,
      dataType: 'float32',
      dimension: EMBEDDING_DIMENSION,
      distanceMetric: 'cosine',
      // Bedrock stores chunk text + source metadata as vector metadata; these
      // exceed the S3 Vectors filterable-metadata size cap, so mark them
      // non-filterable. Our own filter keys (source_type, etc.) stay filterable.
      metadataConfiguration: {
        nonFilterableMetadataKeys: ['AMAZON_BEDROCK_TEXT', 'AMAZON_BEDROCK_METADATA'],
      },
    });
    vectorIndex.addDependency(vectorBucket);

    // ─── IAM role the Bedrock KB assumes ───────────────────────────────────
    const kbRole = new iam.Role(this, 'KnowledgeBaseRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com', {
        conditions: { StringEquals: { 'aws:SourceAccount': this.account } },
      }),
    });

    // Invoke the embedding model.
    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel'],
        resources: [
          `arn:aws:bedrock:${BEDROCK_REGION}::foundation-model/${EMBEDDING_MODEL_ID}`,
        ],
      })
    );
    // Read the corpus bucket.
    this.corpusBucket.grantRead(kbRole);
    // Read/write the S3 Vectors index.
    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          's3vectors:GetIndex',
          's3vectors:PutVectors',
          's3vectors:GetVectors',
          's3vectors:QueryVectors',
          's3vectors:DeleteVectors',
          's3vectors:ListVectors',
        ],
        resources: [vectorBucket.attrVectorBucketArn, vectorIndex.attrIndexArn],
      })
    );

    // ─── Bedrock Knowledge Base ────────────────────────────────────────────
    const kb = new bedrock.CfnKnowledgeBase(this, 'KnowledgeBase', {
      name: `${APP_PREFIX}-KB`,
      roleArn: kbRole.roleArn,
      knowledgeBaseConfiguration: {
        type: 'VECTOR',
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: `arn:aws:bedrock:${BEDROCK_REGION}::foundation-model/${EMBEDDING_MODEL_ID}`,
        },
      },
      storageConfiguration: {
        type: 'S3_VECTORS',
        s3VectorsConfiguration: {
          vectorBucketArn: vectorBucket.attrVectorBucketArn,
          indexArn: vectorIndex.attrIndexArn,
        },
      },
    });
    kb.addDependency(vectorIndex);
    kb.node.addDependency(kbRole);

    // ─── Data source: the corpus bucket, one-file-per-item (no chunking) ────
    const dataSource = new bedrock.CfnDataSource(this, 'CorpusDataSource', {
      knowledgeBaseId: kb.attrKnowledgeBaseId,
      name: `${APP_PREFIX}-Corpus`,
      dataSourceConfiguration: {
        type: 'S3',
        s3Configuration: { bucketArn: this.corpusBucket.bucketArn },
      },
      // build_corpus.py already split into one verse/hadith per file, so the
      // KB must use fixed size chunking to be within the limit of the embedding model.
      vectorIngestionConfiguration: {
        chunkingConfiguration: {
          chunkingStrategy: 'FIXED_SIZE',
          fixedSizeChunkingConfiguration: {
            maxTokens: 400,          // under Cohere's 512 hard limit
            overlapPercentage: 15,   // keeps context across split boundaries
          },
        },
      },
    });
    dataSource.addDependency(kb);

    this.knowledgeBaseId = kb.attrKnowledgeBaseId;
    this.dataSourceId = dataSource.attrDataSourceId;

    new cdk.CfnOutput(this, 'KnowledgeBaseId', { value: this.knowledgeBaseId });
    new cdk.CfnOutput(this, 'DataSourceId', { value: this.dataSourceId });
    new cdk.CfnOutput(this, 'CorpusBucketName', { value: this.corpusBucket.bucketName });
  }
}